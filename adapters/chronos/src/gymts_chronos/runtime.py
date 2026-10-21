"""Owned persistent worker with bounded RPC and no source path injection."""
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import tempfile
import time

from gymts.contracts import GymTSError, canonical_json


class Worker:
    def __init__(self, python, timeout=300):
        self.timeout = timeout
        self.directory = tempfile.TemporaryDirectory(prefix="gymts-chronos-worker-")
        self.log = open(Path(self.directory.name)/"stderr.log", "w+b")
        env = {k: v for k, v in os.environ.items() if k in {
            'PATH','HOME','LANG','LC_ALL','TZ','TMPDIR','LD_LIBRARY_PATH',
            'CUDA_VISIBLE_DEVICES','CUDA_HOME','OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'}}
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", PYTHONDONTWRITEBYTECODE="1",
                   OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", TOKENIZERS_PARALLELISM="false")
        try:
            self.process = subprocess.Popen([python, "-I", "-B", "-m", "gymts_chronos.worker"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
                cwd=self.directory.name, env=env, start_new_session=True)
        except BaseException:
            self.log.close()
            self.directory.cleanup()
            raise
        self.buffer = b""

    def call(self, method, arguments):
        self.process.stdin.write(canonical_json({"method": method, "arguments": arguments})+b"\n")
        self.process.stdin.flush()
        deadline = time.monotonic()+self.timeout
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while b"\n" not in self.buffer:
                remaining = deadline-time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise GymTSError("deadline_exceeded", "Chronos worker exceeded its RPC deadline")
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise GymTSError("execution_failure", "Chronos worker exited before returning its result")
                self.buffer += chunk
                if len(self.buffer) > 64*1024*1024:
                    raise GymTSError("execution_failure", "Chronos worker response exceeds the size limit")
        raw, self.buffer = self.buffer.split(b"\n", 1)
        reply = json.loads(raw)
        if not reply["ok"]:
            raise GymTSError("execution_failure", "Native Chronos operation failed", details={"native_error": reply["error"]})
        return reply["result"]

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                os.killpg(self.process.pid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=3)
        self.process.stdout.close()
        self.log.close()
        self.directory.cleanup()
