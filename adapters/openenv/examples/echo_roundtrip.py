"""Real official server/SDK -> EnvironmentTS -> independent score -> rescore.

This launcher owns only the optional local child process. The adapter itself
always attaches to an existing host and releases only its own WS session.
"""
import argparse
import copy
import importlib.metadata
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
from unittest.mock import patch

from gymts import GymTS
from gymts_interaction.experiments import rescore_spec
from gymts_openenv.experiments import UPSTREAM_COMMIT, connect4_evaluation, echo_evaluation


def healthy(base_url):
    with urllib.request.urlopen(base_url + '/health', timeout=2) as response:
        return response.status == 200


def run(args):
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    server = None
    log = None
    base_url = args.base_url
    try:
        if args.owned_local_server:
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            base_url = 'http://127.0.0.1:' + str(port)
            log = (root / 'official-server.log').open('w')
            server = subprocess.Popen([sys.executable, '-m', 'uvicorn', args.environment + '_env.server.app:app',
                '--host', '127.0.0.1', '--port', str(port)], stdout=log, stderr=subprocess.STDOUT)
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError('Official server exited; inspect official-server.log')
                try:
                    if healthy(base_url):
                        break
                except (OSError, ValueError):
                    time.sleep(0.1)
            else:
                raise RuntimeError('Official server did not become healthy')
        builder = echo_evaluation if args.environment == 'echo' else connect4_evaluation
        spec = builder(base_url, sdk_version=importlib.metadata.version('openenv'))
        with GymTS(str(root / 'records'), integrations=('interaction', 'openenv')) as gym:
            # A plan on an unreachable endpoint must remain pure. The actual
            # backend is opened only by the following evaluate call.
            case = spec['cases'][0]
            validation = gym.validate({'protocol_version': 'gymts.experiment/1',
                'name': spec['name'], 'purpose': spec['purpose'],
                'scene': case['scene'], 'candidate': spec['candidates'][0]['spec'],
                'execution': case['execution'], 'recording': case['recording'], 'extensions': {}})
            if not validation['valid']:
                raise AssertionError('Pure planning failed: ' + json.dumps(validation['issues']))
            report = gym.autobench.evaluate(spec)
            executions = gym.artifacts.read_json(report['run_manifest_ref'])['entries']
            run_ids = [row['run_id'] for row in executions]
            before = {run_id: gym.records.get_run(run_id) for run_id in run_ids}
            with patch('gymts_openenv.transport.SDKSession',
                    side_effect=AssertionError('Rescoring must not open a server session')):
                rescored = gym.autobench.score(rescore_spec(gym, report, spec))
            after = {run_id: gym.records.get_run(run_id) for run_id in run_ids}
            if before != after:
                raise AssertionError('Rescoring changed sealed Run evidence')
            exchanges = []
            for run_id in run_ids:
                record = after[run_id]
                result = record['result']
                if result['status'] != 'succeeded':
                    raise AssertionError('Native Run failed: ' + json.dumps(result['errors']))
                for ref in result['artifact_refs']:
                    if ref['schema_ref'] == 'gymts.openenv/exchange/1':
                        exchanges.append(gym.artifacts.read_json(ref))
            types = [row['request']['type'] for row in exchanges]
            expected_steps = 3 if args.environment == 'echo' else 7
            if types != ['reset', 'state'] + ['step'] * expected_steps:
                raise AssertionError('Unexpected native calls: ' + repr(types))
            responses = [row['response']['data']['observation'] for row in exchanges
                if row['request']['type'] == 'step']
            if args.environment == 'echo':
                for i, observation in enumerate(responses):
                    if observation.get('error') is not None:
                        raise AssertionError('Official tool call reported an error')
                    expected = 'GymTS remote step ' + str(i + 1)
                    if expected not in json.dumps(observation['result'], ensure_ascii=False):
                        raise AssertionError('Echo observation did not contain the sent message')
            elif exchanges[-1]['response']['data']['reward'] != 1.0 or not exchanges[-1]['response']['data']['done']:
                raise AssertionError('Official Connect4 did not reach the expected native terminal reward')
            if report['verdict'] != 'pass' or rescored['verdict'] != 'pass':
                raise AssertionError('Independent evaluation did not pass: ' + json.dumps(report['metrics']))
            aggregate = {row['metric_id']: row['result']['value'] for row in report['metrics']
                if row['level'] == 'aggregate'}
            assert aggregate['episode_length'] == expected_steps
            if args.environment == 'echo':
                assert aggregate['scope_limited'] == 1.0
                for record in after.values():
                    end = record['result']['summary']['environment_end']
                    assert end['reason'] == 'read_scope_end'
                    assert end['terminated'] is False and end['truncated'] is False
            else:
                assert aggregate['episode_return'] == 1.0
            cause_report = None
            if args.environment == 'connect4':
                states = [event['payload']['value']['data']['native']['value']
                    for run_id in run_ids for event in after[run_id]['events']
                    if event['kind'] == 'observation' and event['payload']['value'].get('data')]
                assert states[-1]['backend_done'] is True
                assert states[-1]['end_cause'] == 'unclassified'
                assert states[-1]['terminated'] is False and states[-1]['truncated'] is False
                for record in after.values():
                    end = record['result']['summary']['environment_end']
                    assert end['reason'] == 'source_exhausted'
                    assert end['detail']['reason'] == 'native_done_unclassified'
                    assert end['terminated'] is False and end['truncated'] is False
                cause_spec = copy.deepcopy(spec)
                cause_spec['scoring']['metrics'] = ['terminated', 'truncated']
                cause_spec['comparison']['gates'] = []
                with patch('gymts_openenv.transport.SDKSession',
                        side_effect=AssertionError('Rescoring must not open a server session')):
                    cause_report = gym.autobench.score(rescore_spec(gym, report, cause_spec))
                assert cause_report['verdict'] == 'insufficient_evidence'
                assert all(metric['result']['reason'] == 'termination_cause_unavailable'
                    for metric in cause_report['metrics'] if metric['level'] == 'unit')
                assert {run_id: gym.records.get_run(run_id) for run_id in run_ids} == before
            result = {'protocol_version': 'gymts.openenv-acceptance/1',
                'upstream_commit': UPSTREAM_COMMIT, 'sdk_version': importlib.metadata.version('openenv'),
                'core_version': importlib.metadata.version('gymts'),
                'environment': args.environment,
                'server_kind': 'official-local-process' if server else 'caller-provided-endpoint',
                'server_alive_after_adapter_finish': healthy(base_url),
                'validation': validation, 'evaluation': report, 'rescored': rescored,
                'unknown_end_cause_check': cause_report,
                'sealed_runs_unchanged': before == after,
                'native_request_types': types, 'exchanges': exchanges,
                'run_records': after,
                'limitations': ['Local integration acceptance; no production testbed endpoint verified',
                    'OpenEnv seed enforcement unsupported; no seed passed',
                    'Echo rewards stay null and its execution scope truncates after three actions; Connect4 has a native terminal reward',
                    'Deployment identity declared by caller, not remotely attested']}
            (root / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
            print(json.dumps({'result': str(root / 'result.json'), 'runs': run_ids,
                'request_types': types, 'sealed_runs_unchanged': before == after}, indent=2))
            return result
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
        if log is not None:
            log.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--owned-local-server', '--owned-local-echo', action='store_true')
    group.add_argument('--base-url')
    parser.add_argument('--environment', choices=('echo', 'connect4'), default='echo')
    parser.add_argument('--root', default='/tmp/gymts-openenv-native')
    run(parser.parse_args())
