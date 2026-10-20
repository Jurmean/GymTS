"""Subprocess boundary without source-path injection or hidden data reads."""
import json
import math
import os
import re
import subprocess
import tempfile

from gymts.contracts import GymTSError, canonical_json
from .source import resolve_source


class LibraryTSRuntime:
    def __init__(self, implementation, *, timeout_seconds=120):
        self.implementation = dict(implementation)
        if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise GymTSError("invalid_config", "LibraryTS timeout must be positive and finite")
        self.timeout = timeout_seconds

    def describe(self, tool):
        return resolve_source(self.implementation, tool)

    def invoke(self, tool, arguments=None, params=None):
        source = self.describe(tool)
        arguments = {} if arguments is None else arguments
        params = {} if params is None else params
        if not isinstance(arguments, dict) or not isinstance(params, dict):
            raise GymTSError("invalid_request", "LibraryTS arguments and params must be JSON objects")
        request = {"tool": tool, "arguments": arguments, "params": params, "provenance": source}
        raw = canonical_json(request)
        environment = {key: value for key, value in os.environ.items()
                       if not re.search(r"api.?key|access.?token|secret|password|authorization|credential", key, re.I)}
        environment.pop("PYTHONPATH", None)
        environment.update(PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", CUDA_VISIBLE_DEVICES="",
                           OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMBA_NUM_THREADS="1")
        try:
            with tempfile.TemporaryDirectory(prefix="gymts-libraryts-worker-") as directory:
                completed = subprocess.run([source["python"], "-I", "-B", "-m", "gymts_libraryts.worker"],
                    input=raw, capture_output=True, env=environment, cwd=directory, timeout=self.timeout)
        except subprocess.TimeoutExpired as error:
            raise GymTSError("deadline_exceeded", "LibraryTS native tool timed out", stage="libraryts.native",
                             details={"tool": tool, "source": source, "timeout_seconds": self.timeout}) from error
        except OSError as error:
            raise GymTSError("unsupported_capability", "LibraryTS scientific interpreter is unavailable") from error
        try:
            envelope = json.loads(completed.stdout)
        except (ValueError, UnicodeError) as error:
            raise GymTSError("execution_failure", "LibraryTS native worker returned invalid JSON", stage="libraryts.native",
                details={"exit_code": completed.returncode, "stderr": completed.stderr.decode(errors="replace")[-8000:],
                         "stdout": completed.stdout.decode(errors="replace")[-8000:], "source": source}) from error
        if completed.returncode or envelope.get("ok") is not True:
            raise GymTSError("execution_failure", "LibraryTS native tool failed", stage="libraryts.native",
                details={"source": source, "native_error": envelope.get("error"),
                         "stderr": completed.stderr.decode(errors="replace")[-8000:], "exit_code": completed.returncode})
        if self.describe(tool) != source:
            raise GymTSError("conflict", "LibraryTS source changed during the native call")
        return envelope["output"]
