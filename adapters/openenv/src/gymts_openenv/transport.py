"""The official OpenEnv SDK owns the WebSocket protocol, never HTTP replay.

No retry is performed here. Once a connection/request fails, the session is
poisoned; a new SDK connection would create a different remote environment.
"""
import copy
import importlib.metadata
import threading
import time

from gymts.contracts import GymTSError, canonical_json
from gymts.plugin_support import fail


class RemoteRequestUncertain(GymTSError):
    def __init__(self, method, exception):
        super().__init__('backend_failure', 'OpenEnv request failed; automatic resend is forbidden',
            stage='environment', method=method, links={'error_class': type(exception).__name__},
            retryable=False, side_effect='possible' if method in ('reset', 'step') else 'none')


class SDKSession:
    def __init__(self, connection):
        expected = connection['sdk_version']
        actual = importlib.metadata.version('openenv')
        if actual != expected:
            fail('conflict', 'Installed OpenEnv SDK version differs from the fixed connection configuration')
        from openenv.core.generic_client import GenericEnvClient
        self.frames = []
        self.poisoned = False
        self.closed = False
        self._lock = threading.Lock()
        owner = self

        class SessionBoundClient(GenericEnvClient):
            _session_socket = None

            async def _connect_async(self):
                # EnvClient may reconnect automatically. That creates a fresh
                # server environment, so forbid it once this session exists.
                if self._session_socket is not None:
                    from websockets.protocol import State
                    if self._ws is not self._session_socket or self._ws.state != State.OPEN:
                        raise ConnectionError('OpenEnv session was lost; reconnection is forbidden')
                await super()._connect_async()
                if self._session_socket is None:
                    self._session_socket = self._ws

            async def _send_and_receive(self, message):
                frame = {'request': copy.deepcopy(message), 'response': None,
                         'error': None, 'duration_s': None}
                owner.frames.append(frame)
                started = time.monotonic()
                try:
                    response = await super()._send_and_receive(message)
                    frame['response'] = copy.deepcopy(response)
                    return response
                except BaseException as exc:
                    # Error classes suffice for diagnostics; remote error text
                    # can contain credentials or arbitrary server content.
                    frame['error'] = type(exc).__name__
                    raise
                finally:
                    frame['duration_s'] = time.monotonic() - started

            async def _receive(self):
                response = await super()._receive()
                # Capture the error envelope too, before the SDK converts it
                # into an exception in _send_and_receive.
                owner.frames[-1]['response'] = copy.deepcopy(response)
                return response

        self.sdk_version = actual
        self.client = SessionBoundClient(
            base_url=connection['base_url'], mode='simulation',
            connect_timeout_s=connection['connect_timeout_s'],
            message_timeout_s=connection['message_timeout_s'],
            max_message_size_mb=connection['max_message_size_mb'],
        ).sync()

    def call(self, name, value=None):
        with self._lock:
            if self.closed or self.poisoned:
                fail('invalid_state', 'OpenEnv session is closed or uncertain; automatic resend is forbidden')
            try:
                if name == 'reset':
                    result = self.client.reset(**value)
                    response = {'observation': result.observation, 'reward': result.reward,
                                'done': result.done, 'metadata': result.metadata}
                elif name == 'step':
                    result = self.client.step(value)
                    response = {'observation': result.observation, 'reward': result.reward,
                                'done': result.done, 'metadata': result.metadata}
                elif name == 'state':
                    response = self.client.state()
                else:
                    fail('invalid_request', 'Unsupported OpenEnv SDK operation')
                canonical_json(response)
                if name in ('reset', 'step') and (
                        type(response['done']) is not bool or
                        response['reward'] is not None and type(response['reward']) not in (int, float)):
                    fail('schema_mismatch', 'OpenEnv returned invalid reward/done types')
                return copy.deepcopy(response)
            except Exception as exc:
                self.poisoned = True
                raise RemoteRequestUncertain(name, exc) from exc

    def close(self):
        with self._lock:
            if not self.closed:
                self.closed = True
                # No runtime/provider was supplied, so SDK close only releases
                # our socket. The attached host process is never terminated.
                self.client.close()
