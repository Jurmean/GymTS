"""Adapter contract checks; real official server acceptance is separate."""
import copy
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS, GymTSError
from gymts.plugin_support import payload
from gymts_interaction import register_interaction_plugins
from gymts_interaction.contracts import ACTION
from gymts_openenv import register_openenv_plugins
from gymts_openenv.environment import OpenEnvEnvironment
from gymts_openenv.experiments import echo_evaluation
from gymts_openenv.transport import RemoteRequestUncertain, SDKSession


def experiment():
    evaluation = echo_evaluation('http://127.0.0.1:1')
    case = evaluation['cases'][0]
    return {'protocol_version': 'gymts.experiment/1', 'name': 'OpenEnv contract',
        'purpose': 'acceptance', 'scene': case['scene'],
        'candidate': evaluation['candidates'][0]['spec'],
        'execution': case['execution'], 'recording': case['recording'], 'extensions': {}}


class FakeSession:
    """Fault injection only; no claim this is an actual OpenEnv environment."""
    def __init__(self, connection):
        self.sdk_version = connection['sdk_version']
        self.calls = []
        self.frames = []
        self.closed = False
        self.poisoned = False
        self.fail_step = False

    def call(self, name, value=None):
        self.calls.append((name, copy.deepcopy(value)))
        request = {'type': name}
        if value is not None:
            request['data'] = copy.deepcopy(value)
        result = {'observation': {'echo': value}, 'reward': 0.0, 'done': False, 'metadata': {}}
        if name == 'state':
            result = {'episode_id': 'fake-fault-test', 'step_count': 0}
        frame = {'request': request, 'response': {'type': 'state' if name == 'state' else 'observation',
            'data': copy.deepcopy(result)}, 'duration_s': 0.01, 'error': None}
        self.frames.append(frame)
        if name == 'step' and self.fail_step:
            self.poisoned = True
            frame['response'] = None
            frame['error'] = 'TimeoutError'
            raise RemoteRequestUncertain(name, TimeoutError())
        return result

    def close(self):
        self.closed = True


class OpenEnvTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.gym = GymTS(self.tmp.name)
        register_interaction_plugins(self.gym.registries, self.gym.schemas)
        register_openenv_plugins(self.gym.registries, self.gym.schemas)

    def tearDown(self):
        self.gym.close()
        self.tmp.cleanup()

    def test_pure_plan_never_constructs_sdk_or_contacts_endpoint(self):
        with patch('gymts_openenv.transport.SDKSession', side_effect=AssertionError('native I/O')):
            plan = self.gym.plan(experiment())
        self.assertEqual(plan['resource_checks'], 'deferred_to_open')
        self.assertFalse(plan['descriptions']['environment']['capabilities']['seed'])

    def test_seed_credentials_and_secret_urls_fail_before_open(self):
        for mutation in ('seed', 'query', 'credential', 'reset_seed'):
            spec = experiment()
            source = spec['scene']['environment']['source']
            if mutation == 'seed':
                spec['execution']['seed'] = 1
            elif mutation == 'query':
                source['connection']['base_url'] += '?token=private'
            elif mutation == 'credential':
                source['credential_ref'] = 'credential:private'
            else:
                spec['scene']['environment']['options']['reset_options']['seed'] = 1
            with self.subTest(mutation=mutation), patch('gymts_openenv.transport.SDKSession',
                    side_effect=AssertionError('native I/O')):
                self.assertFalse(self.gym.validate(spec)['valid'])

    def test_explicit_sdk_version_checked_before_import_or_request(self):
        connection = experiment()['scene']['environment']['source']['connection']
        with patch('gymts_openenv.transport.importlib.metadata.version', return_value='different'):
            with self.assertRaises(GymTSError) as error:
                SDKSession(connection)
        self.assertEqual(error.exception.code, 'conflict')

    def test_native_done_never_invents_termination_cause(self):
        from gymts.environment_ts.services import RestrictedServices
        services = RestrictedServices(self.gym.artifacts, schemas=self.gym.schemas)
        env = OpenEnvEnvironment(experiment()['scene']['environment'], services)
        session = FakeSession(env.spec['source']['connection'])
        original = session.call
        def terminal(name, value=None):
            result = original(name, value)
            result['done'] = True
            return result
        session.call = terminal
        env.transport = session
        transition = env._step({'message': 'done'})
        self.assertTrue(transition['backend_done'])
        self.assertEqual(transition['end_cause'], 'unclassified')
        self.assertFalse(transition['terminated'])
        self.assertFalse(transition['truncated'])

    def test_cached_observation_and_unknown_operation_never_resend(self):
        from gymts.environment_ts.services import RestrictedServices
        spec = experiment()
        environment_spec = spec['scene']['environment']
        services = RestrictedServices(self.gym.artifacts, schemas=self.gym.schemas)
        env = OpenEnvEnvironment(environment_spec, services)
        start = {'run_id': 'test-run', 'mode': 'reinitialize', 'scope': {'start': 0, 'end': 3},
            'read_scope': {'start': 0, 'end': 3}, 'feedback_until': None, 'seed': None,
            'permitted_variables': ['state'], 'permitted_operations': ['act']}
        with patch('gymts_openenv.transport.SDKSession', FakeSession):
            session = env.start(start)
        request = {'request_id': 'r0', 'kind': 'next', 'entities': ['episode'],
            'variables': ['state'], 'cursor': session['initial_cursor'], 'max_wait_ms': 0}
        initial = env.observe(request)
        self.assertEqual([call[0] for call in env.transport.calls], ['reset', 'state'])
        request.update(cursor=initial['cursor'], request_id='r1')
        self.assertEqual(env.observe(request)['status'], 'waiting')
        env.transport.fail_step = True
        command = {'operation_id': 'op1', 'request_id': 'command1', 'name': 'act',
            'arguments': payload(ACTION, {'message': 'hello'}), 'idempotency_key': None,
            'output_id': 'output1', 'origin': 'task', 'trigger_batch_id': None}
        self.assertEqual(env.act(command)['status'], 'unknown')
        for op, request_id in [('op1', 'command1'), ('op2', 'command2')]:
            command.update(operation_id=op, request_id=request_id)
            with self.assertRaises(GymTSError):
                env.act(command)
        self.assertEqual([call[0] for call in env.transport.calls], ['reset', 'state', 'step'])
        summary = env.finish()
        self.assertEqual(summary['pending_operations'], ['op1'])
        self.assertTrue(env.transport.closed)
        self.assertEqual(len(summary['artifact_refs']), 3)
        self.assertEqual(summary['backend_disposition'], 'closed')

    def test_failed_remote_request_sealed_as_possible_side_effect(self):
        original = FakeSession.call
        def fail_step(instance, name, value=None):
            instance.fail_step = True
            return original(instance, name, value)
        with patch('gymts_openenv.transport.SDKSession', FakeSession), patch.object(FakeSession, 'call', fail_step):
            result = self.gym.run(experiment())
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['errors'][0]['side_effect'], 'possible')
        record = self.gym.records.get_run(result['run_id'])
        receipt_events = [event for event in record['events'] if event['kind'] == 'environment_receipt']
        self.assertEqual(len(receipt_events), 1)
        self.assertEqual(receipt_events[0]['payload']['value']['status'], 'unknown')
        self.assertEqual(len([ref for ref in result['artifact_refs']
            if ref['schema_ref'] == 'gymts.openenv/exchange/1']), 3)

    def test_invalid_native_transition_retains_possible_side_effect_and_operation(self):
        original = FakeSession.call
        def invalid_reward(instance, name, value=None):
            value = original(instance, name, value)
            if name == 'step':
                value['reward'] = 'invalid-native-reward'
            return value
        with patch('gymts_openenv.transport.SDKSession', FakeSession), patch.object(FakeSession, 'call', invalid_reward):
            result = self.gym.run(experiment())
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['errors'][0]['side_effect'], 'possible')
        summary = result['summary']['cleanup']['environment']['summary']
        self.assertEqual(len(summary['pending_operations']), 1)

    def test_capture_failure_after_native_step_retains_possible_side_effect(self):
        original = self.gym.artifacts.save_json
        def fail_step_capture(value, schema_ref='gymts.json/1'):
            if schema_ref == 'gymts.openenv/exchange/1' and value['request']['type'] == 'step':
                raise OSError('injected exchange capture failure')
            return original(value, schema_ref)
        with patch('gymts_openenv.transport.SDKSession', FakeSession), patch.object(
                self.gym.artifacts, 'save_json', side_effect=fail_step_capture):
            result = self.gym.run(experiment())
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['errors'][0]['side_effect'], 'possible')
        self.assertEqual(result['errors'][0]['code'], 'recording_failure')
        self.assertEqual(len(result['summary']['cleanup']['environment']['summary']['pending_operations']), 1)


if __name__ == '__main__':
    unittest.main()
