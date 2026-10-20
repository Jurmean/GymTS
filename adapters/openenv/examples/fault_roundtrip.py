"""Real official Echo server: timeout side effects and lost-session safeguards."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
from unittest.mock import patch

from gymts import GymTS, GymTSError
from gymts_openenv.experiments import echo_evaluation
from gymts_openenv.transport import RemoteRequestUncertain, SDKSession


class StepTimeoutSession(SDKSession):
    def call(self, name, value=None):
        if name == 'step':
            # Fault injection changes only the official SDK receive deadline;
            # the server and WebSocket implementation remain unmodified.
            self.client._async._message_timeout = 1e-12
        return super().call(name, value)


def run(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    url = 'http://127.0.0.1:' + str(port)
    log = (root / 'official-server.log').open('w')
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'echo_env.server.app:app',
        '--host', '127.0.0.1', '--port', str(port)], stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen(url + '/health', timeout=2):
                    break
            except OSError:
                if process.poll() is not None:
                    raise RuntimeError('Official Echo server exited')
                time.sleep(.1)
        else:
            raise RuntimeError('Official Echo server was not ready')
        evaluation = echo_evaluation(url, sdk_version=importlib.metadata.version('openenv'))
        case = evaluation['cases'][0]
        experiment = {'protocol_version': 'gymts.experiment/1', 'name': 'Actual WS timeout fault',
            'purpose': 'acceptance', 'scene': case['scene'],
            'candidate': evaluation['candidates'][0]['spec'],
            'execution': case['execution'], 'recording': case['recording'], 'extensions': {}}
        with GymTS(str(root / 'records'), integrations=('interaction', 'openenv')) as gym:
            with patch('gymts_openenv.transport.SDKSession', StepTimeoutSession):
                result = gym.run(experiment)
            record = gym.records.get_run(result['run_id'])
            assert result['status'] == 'failed'
            assert result['errors'][0]['side_effect'] == 'possible'
            receipts = [event['payload']['value'] for event in record['events']
                if event['kind'] == 'environment_receipt']
            assert len(receipts) == 1 and receipts[0]['status'] == 'unknown'
            exchanges = [gym.artifacts.read_json(ref) for ref in result['artifact_refs']
                if ref['schema_ref'] == 'gymts.openenv/exchange/1']
            assert [row['request']['type'] for row in exchanges] == ['reset', 'state', 'step']
            assert exchanges[-1]['error'] == 'TimeoutError'
            assert len(result['summary']['cleanup']['environment']['summary']['pending_operations']) == 1
            assert process.poll() is None
            # A real SDK socket is explicitly closed to simulate session loss.
            # The next attempted operation must fail instead of opening a new
            # server-side environment behind the caller's back.
            session = SDKSession(experiment['scene']['environment']['source']['connection'])
            try:
                session.call('reset', {})
                session.client.close()
                try:
                    session.call('step', {'type': 'call_tool', 'tool_name': 'echo_message',
                        'arguments': {'message': 'must not run in a new session'}})
                    raise AssertionError('Lost session unexpectedly reconnected')
                except RemoteRequestUncertain as error:
                    assert error.info['links']['error_class'] == 'ConnectionError'
                frame_count = len(session.frames)
                try:
                    session.call('reset', {})
                    raise AssertionError('Uncertain session unexpectedly allowed a new request')
                except GymTSError as error:
                    assert error.code == 'invalid_state'
                assert len(session.frames) == frame_count
                lost_session_frames = session.frames
            finally:
                session.close()
            report = {'protocol_version': 'gymts.openenv-fault-acceptance/1',
                'timeout_run': record, 'timeout_exchanges': exchanges,
                'lost_session_frames': lost_session_frames,
                'unknown_side_effect_not_retried': True,
                'lost_session_does_not_reconnect': True,
                'attached_host_survived_both': process.poll() is None,
                'fault_injection': 'official SDK deadline only; explicit close of real WS socket',
                'production_endpoint_verified': False}
            path = root / 'result.json'
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps({'result': str(path), 'run_id': result['run_id'],
                'unknown_side_effect_not_retried': True, 'lost_session_does_not_reconnect': True}))
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        log.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='/tmp/gymts-openenv-faults')
    run(parser.parse_args().root)
