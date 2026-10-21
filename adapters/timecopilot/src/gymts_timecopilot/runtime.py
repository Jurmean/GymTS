"""Isolated worker with durable host acknowledgement before native side effects."""
import json
import os
import selectors
import subprocess
import tempfile
import time

from gymts.contracts import GymTSError, canonical_json


def worker_environment(credential_env=None):
    allowed = {"PATH", "HOME", "USER", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "LD_LIBRARY_PATH",
               "LIBRARY_PATH", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"}
    if credential_env is not None:
        allowed.add(credential_env)
    environment = {key: value for key, value in os.environ.items() if key in allowed}
    environment.update(PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", CUDA_VISIBLE_DEVICES="",
                       OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMBA_NUM_THREADS="1",
                       GYMTS_TIMECOPILOT_PARENT_PID=str(os.getpid()))
    return environment


class TimeCopilotRuntime:
    def __init__(self, implementation, *, timeout_seconds=600, credential_env=None):
        self.implementation = dict(implementation)
        self.timeout = timeout_seconds
        self.credential_env = credential_env

    def invoke(self, request, on_event=None):
        """ACK only after on_event persisted the event; no pipe buffering of evidence."""
        request = dict(request, implementation=self.implementation)
        events, terminal, sequence = [], None, 0
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="gymts-timecopilot-worker-") as cwd, tempfile.TemporaryFile() as stderr:
            try:
                worker = subprocess.Popen([self.implementation["python"], "-I", "-B", "-m", "gymts_timecopilot.worker"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr, text=True, bufsize=1,
                    env=worker_environment(self.credential_env), cwd=cwd, start_new_session=True)
            except OSError as error:
                raise GymTSError("unsupported_capability", "TimeCopilot worker interpreter is unavailable") from error
            selector = selectors.DefaultSelector()
            selector.register(worker.stdout, selectors.EVENT_READ)
            try:
                worker.stdin.write(canonical_json(request).decode() + "\n")
                worker.stdin.flush()
                while True:
                    remaining = self.timeout - (time.monotonic() - started)
                    if remaining <= 0:
                        raise GymTSError("deadline_exceeded", "TimeCopilot worker wall-time budget exhausted", stage="timecopilot.native")
                    if not selector.select(min(remaining, 0.2)):
                        if worker.poll() is not None:
                            break
                        continue
                    line = worker.stdout.readline()
                    if not line:
                        break
                    event = json.loads(line)
                    sequence += 1
                    if event.get("sequence") != sequence:
                        raise GymTSError("execution_failure", "TimeCopilot worker event sequence is discontinuous")
                    events.append(event)
                    if on_event is not None:
                        on_event(event)
                    worker.stdin.write(json.dumps({"ack": sequence}) + "\n")
                    worker.stdin.flush()
                    if event["kind"] == "terminal":
                        terminal = event
                code = worker.wait(timeout=max(1, self.timeout - (time.monotonic() - started)))
                if terminal is None or code != 0 or terminal.get("status") != "succeeded":
                    native = terminal.get("error") if terminal else None
                    raise GymTSError("execution_failure", "Native TimeCopilot execution failed", stage="timecopilot.native",
                                     details={"native_error": native, "exit_code": code, "event_count": len(events)})
                return terminal["result"]
            except (ValueError, BrokenPipeError, subprocess.TimeoutExpired) as error:
                raise GymTSError("execution_failure", "TimeCopilot worker communication failed", stage="timecopilot.native") from error
            finally:
                selector.close()
                # The leader may have exited while native CPU children remain.
                # Popen created this dedicated session; never signal a shared group.
                import signal
                try:
                    os.killpg(worker.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                if worker.poll() is None:
                    worker.wait(timeout=10)
                worker.stdin.close()
                worker.stdout.close()
