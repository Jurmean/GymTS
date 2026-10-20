"""Pinned TimeSigma scientific processes; no scientific imports in the host."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from gymts.contracts import GymTSError, canonical_json

SOURCE_URL = "https://github.com/WithAnOrch1d/TimeSigma-GymTS"
SOURCE_REVISION = "5a953c1a84d0a442d1c41b17b4e8aba8c013be10"
EASYTSAD_REVISION = "e7be92374a4543d7c52d6e34ef7047f4d6776be0"


def _git(repository, *arguments):
    try:
        result = subprocess.run(["git", "-C", str(repository), *arguments], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GymTSError("invalid_config", "Cannot inspect the fixed TimeSigma checkout", details={"reason": str(error)}) from error
    if result.returncode:
        raise GymTSError("invalid_config", "TimeSigma checkout inspection failed", details={"stderr": result.stderr[-4000:]})
    return result.stdout.strip()


def resolve_source(params):
    location = params.get("source_repo") or os.environ.get("GYMTS_TIMESIGMA_REPO")
    if not location:
        raise GymTSError("invalid_config", "TimeSigma requires an explicit source_repo")
    repository = Path(location).expanduser().resolve()
    revision = _git(repository, "rev-parse", "HEAD")
    remote = _git(repository, "remote", "get-url", "origin")
    normalized = remote.rstrip("/").removesuffix(".git").replace("git@github.com:", "https://github.com/")
    if revision != SOURCE_REVISION or normalized.lower() != SOURCE_URL.lower():
        raise GymTSError("conflict", "TimeSigma source origin/revision differs from the fixed implementation",
                         details={"expected": SOURCE_REVISION, "actual": revision})
    if _git(repository, "status", "--porcelain", "--untracked-files=no"):
        raise GymTSError("conflict", "TimeSigma tracked source is dirty")
    files = {name: hashlib.sha256((repository / name).read_bytes()).hexdigest() for name in (
        "pyproject.toml", "uv.lock", "timesigma/algorithms/checkpoint.py", "timesigma/benchmark/artifacts.py")}
    adapter = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
               for name in ("candidate.py", "runtime.py", "worker.py")}
    return {"repository": str(repository), "repository_url": SOURCE_URL, "revision": revision,
            "easytsad_revision": EASYTSAD_REVISION, "source_files": files,
            "adapter_source_files": adapter,
            "python": params.get("python") or os.environ.get("GYMTS_TIMESIGMA_PYTHON") or sys.executable,
            "tracked_clean": True}


class TimeSigmaRuntime:
    def __init__(self, params):
        self.params = dict(params)

    def describe(self):
        return resolve_source(self.params)

    def call(self, operation, payload):
        source = self.describe()
        environment = {name: value for name, value in os.environ.items()
                       if not re.search(r"(?:api.?key|token|secret|password)", name, re.I)}
        environment.pop("PYTHONPATH", None)
        environment.update(PYTHONNOUSERSITE="1", PYTHONUNBUFFERED="1", CUDA_VISIBLE_DEVICES="")
        for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
            environment[name] = "1"
        request = {"operation": operation, "payload": payload, "source": source}
        timeout = self.params.get("timeout_seconds", 600)
        try:
            with tempfile.TemporaryDirectory(prefix="gymts-timesigma-native-") as directory:
                process = subprocess.run([source["python"], "-m", "gymts_timesigma.worker"],
                    input=canonical_json(request).decode(), capture_output=True, text=True, cwd=directory,
                    env=environment, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            def decoded(value):
                return value.decode(errors="replace") if isinstance(value, bytes) else value
            raise GymTSError("candidate_failure", "TimeSigma native process timed out", stage=operation,
                details={"source": source, "timeout_seconds": timeout, "timed_out": True,
                         "stdout": decoded(error.stdout), "stderr": decoded(error.stderr)}) from error
        except OSError as error:
            raise GymTSError("candidate_failure", "TimeSigma native process could not start", stage=operation,
                             details={"source": source, "reason": str(error)}) from error
        try:
            envelope = json.loads(process.stdout)
        except (ValueError, TypeError) as error:
            raise GymTSError("candidate_failure", "TimeSigma worker returned invalid JSON", stage=operation,
                details={"exit_code": process.returncode, "stdout": process.stdout, "stderr": process.stderr, "source": source}) from error
        if process.returncode or not isinstance(envelope, dict) or envelope.get("ok") is not True:
            raise GymTSError("candidate_failure", "TimeSigma native operation failed", stage=operation,
                details={"exit_code": process.returncode, "worker_envelope": envelope,
                         "stdout": process.stdout, "stderr": process.stderr, "source": source})
        if self.describe() != source:
            raise GymTSError("conflict", "TimeSigma source changed during native execution")
        result = envelope["result"]
        result["worker_logs"] = {"stderr": process.stderr, "exit_code": process.returncode}
        return result
