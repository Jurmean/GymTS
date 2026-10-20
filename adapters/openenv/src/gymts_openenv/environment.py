"""Attach to an OpenEnv host while owning exactly one new WS session."""
import copy
from urllib.parse import urlsplit

from gymts.contracts import GymTSError, utc_now
from gymts.plugin_support import fail, identifier, payload
from gymts_interaction.contracts import RECEIPT
from gymts_interaction.environment import CachedInteractionEnvironment
from .transport import RemoteRequestUncertain

AUDIT = 'gymts.openenv/exchange/1'


def check_source(spec):
    connection = spec['source']['connection']
    url = urlsplit(connection['base_url'])
    if url.scheme not in ('http', 'https', 'ws', 'wss') or not url.hostname:
        fail('invalid_config', 'OpenEnv requires an HTTP(S) or WS(S) base URL')
    if url.username or url.password or url.query or url.fragment:
        fail('invalid_config', 'OpenEnv URL must not contain userinfo, query, or fragment credentials')
    if 'seed' in spec['options']['reset_options']:
        fail('unsupported_capability', 'Generic OpenEnv cannot attest native seed enforcement')
    if spec['source']['credential_ref'] is not None:
        fail('unsupported_capability', 'No OpenEnv credential provider is configured')


class OpenEnvEnvironment(CachedInteractionEnvironment):
    ADAPTER = 'openenv-websocket'

    @classmethod
    def describe_spec(cls, spec):
        check_source(spec)
        result = super().describe_spec(spec)
        # OpenEnv accepts a seed argument, but individual servers may ignore it
        # (official Echo explicitly does). Receiving it is not honoring it.
        result['capabilities']['seed'] = False
        return result

    def __init__(self, spec, services):
        super().__init__(spec, services)
        self.transport = None
        self._evidence = []
        self._saved_frames = 0
        self._uncertain = []
        check_source(spec)

    def _record_exchanges(self):
        if self.transport is None:
            return
        while self._saved_frames < len(self.transport.frames):
            index = self._saved_frames
            frame = self.transport.frames[index]
            try:
                ref = self.services.save_json({
                    'protocol_version': AUDIT, 'sequence': index,
                    'transport': 'official-openenv-sdk-websocket',
                    'sdk_version': self.transport.sdk_version,
                    'source_revision': self.spec['source']['revision'],
                    'deployment_identity': self.spec['source']['connection']['deployment_identity'],
                    'identity_verification': 'caller-declared-not-remotely-attested',
                    'request': frame['request'], 'response': frame['response'],
                    'error': frame['error'], 'duration_s': frame['duration_s'],
                }, AUDIT)
            except Exception as error:
                method = frame['request']['type']
                raise GymTSError('recording_failure', 'OpenEnv exchange could not be committed',
                    stage='environment', method=method, retryable=False,
                    links={'exchange_sequence': index, 'error_class': type(error).__name__},
                    side_effect='possible' if method in ('reset', 'step') else 'none') from error
            self._evidence.append(ref)
            self._saved_frames += 1

    def _call(self, name, value=None):
        try:
            return self.transport.call(name, value)
        finally:
            self._record_exchanges()

    def _reset(self, seed):
        if seed is not None:
            fail('unsupported_capability', 'Generic OpenEnv cannot attest seed enforcement')
        from .transport import SDKSession
        self.transport = SDKSession(self.spec['source']['connection'])
        result = self._call('reset', copy.deepcopy(self.spec['options']['reset_options']))
        if result['done']:
            fail('unsupported_capability', 'This adapter requires a nonterminal initial OpenEnv reset')
        state = self._call('state')
        return {'observation': result['observation'],
            'info': {'openenv': {'reward': result['reward'], 'metadata': result['metadata'],
                               'server_state': state, 'exchange_refs': copy.deepcopy(self._evidence)}},
            'source_identity': {'project': 'OpenEnv',
                'deployment_identity': self.spec['source']['connection']['deployment_identity'],
                'source_revision': self.spec['source']['revision'],
                'sdk_version': self.transport.sdk_version,
                'identity_verification': 'caller-declared-not-remotely-attested',
                'session': 'dedicated-websocket', 'host_ownership': 'attached',
                'seed_enforcement': 'unsupported'},
            'observation_space': copy.deepcopy(self.spec['options']['observation_space']),
            'action_space': copy.deepcopy(self.spec['options']['action_space'])}

    def _step(self, action):
        result = self._call('step', action)
        # OpenEnv has a single done flag, not Gymnasium's two flags. Closing
        # the episode does not establish which termination cause occurred.
        return {'observation': result['observation'], 'reward': result['reward'],
            'terminated': False, 'truncated': False, 'backend_done': result['done'],
            'end_cause': 'unclassified' if result['done'] else None,
            'info': {'openenv': {'done': result['done'],
                'done_projection': 'backend-episode-end-without-cause-classification',
                'metadata': result['metadata'], 'exchange_ref': copy.deepcopy(self._evidence[-1])}}}

    def act(self, command):
        try:
            return super().act(command)
        except RemoteRequestUncertain:
            self._uncertain.append(command['operation_id'])
            return {'receipt_id': identifier('receipt'), 'operation_id': command['operation_id'],
                'request_id': command['request_id'], 'status': 'unknown', 'received_at': utc_now(),
                'payload': payload(RECEIPT, {'step': self.step, 'transition_available': False}), 'feedback': []}

    def _close(self):
        if self.transport is not None:
            self.transport.close()

    def finish(self):
        result = super().finish()
        result['artifact_refs'].extend(copy.deepcopy(self._evidence))
        result['pending_operations'] = list(dict.fromkeys(
            result['pending_operations'] + self._uncertain))
        if self.transport is not None:
            # The Run owns the new WS session, so the formal disposition is
            # closed. Host ownership remains attached in source_identity.
            result['backend_disposition'] = 'closed'
        return result
