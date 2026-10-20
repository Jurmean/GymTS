"""Explicit data/task/model tools backed by the public GymTS services.

This host protocol does not impersonate the upstream Pi bridge: upstream
experiment.run validates its own complete directory-based Evidence format.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from uuid import uuid4

from gymts.contracts import GymTSError, canonical_json


NATIVE_TOOLS = frozenset({"system.health", "capability.lookup", "memory.search", "memory.read",
    "memory.compare", "research.context", "experiment.preview", "recommendation.context"})


class TimeSigmaTools:
    """Trusted local tool calls; credentials and paid providers are not required."""
    def __init__(self, gym, *, source_repo, python, timeout_seconds=300):
        gym.enable_integration("timesigma")
        self.gym = gym
        self.source_repo, self.python, self.timeout_seconds = str(source_repo), str(python), timeout_seconds
        self.last_call_ref = None

    def describe(self):
        return {"protocol_version": "gymts.timesigma.tools/1", "tools": {
            "data.import": "Freeze one EasyTSAD planning unit with separate training, test and private-label artifacts",
            "task.describe": "Inspect the registered TSAD task and exact wire schemas",
            "model.catalog": "Inspect the fixed native catalog and the subset enabled by this adapter",
            "experiment.run": "Fit and score one fixed pipeline through GymTS, then independently evaluate sealed scores",
            "experiment.rescore": "Rescore sealed GymTS outputs with a gymts.score/1 specification",
            "run.inspect": "Inspect a native Run and its preparation/result references",
            "trajectory.snapshot": "Freeze native Run event and outcome boundaries",
            "trajectory.export": "Export a fixed trajectory and the exact CAS reference closure",
            **{"native." + tool: "Call the original TimeSigma domain tool with its original complete scope payload"
               for tool in sorted(NATIVE_TOOLS)}},
            "native_tool_effects": {"experiment.preview": "writes a preview artifact under the original scope.experiment_root"},
            "execution_methods": ["AR", "IsolationForest"],
            "native_pi_experiment_bridge": "requires_upstream_evidence_adapter"}

    def _native(self, operation, arguments, *, deadline_unix_ms=None):
        timeout = self.timeout_seconds
        if deadline_unix_ms is not None:
            timeout = min(timeout, max(.001, (deadline_unix_ms - time.time() * 1000) / 1000))
        request = {"source_repo": self.source_repo, "operation": operation, "arguments": arguments,
            "request_id": "gymts-" + uuid4().hex,
            "deadline_unix_ms": int((time.time() + timeout) * 1000)}
        environment = {key: value for key, value in os.environ.items()
                       if not re.search(r"api.?key|access.?token|secret|password|authorization", key, re.I)}
        environment.pop("PYTHONPATH", None)
        environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", CUDA_VISIBLE_DEVICES="")
        for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
            environment[name] = "1"
        try:
            with tempfile.TemporaryDirectory(prefix="gymts-timesigma-tools-") as directory:
                result = subprocess.run([self.python, "-B", "-m", "gymts_timesigma.tool_worker"],
                    input=canonical_json(request), capture_output=True, env=environment, cwd=directory,
                    timeout=timeout)
            response = json.loads(result.stdout)
        except subprocess.TimeoutExpired as error:
            raise GymTSError("deadline_exceeded", "TimeSigma tool deadline exceeded") from error
        except (OSError, ValueError) as error:
            raise GymTSError("unsupported_capability", "TimeSigma tool runtime is unavailable or returned invalid JSON") from error
        if result.returncode or not response.get("ok"):
            raise GymTSError("tool_failure", "The original TimeSigma tool rejected the request",
                             details={"operation": operation, "error_type": response.get("error_type")})
        return response["result"]

    def _publish_call(self, call_id, phase, reference):
        directory = Path(self.gym.root) / "timesigma" / "tool-calls"
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / (call_id + "." + phase + ".json")).open("xb") as stream:
            stream.write(canonical_json({"call_id": call_id, "phase": phase, "call_ref": reference}))
            stream.flush()
            os.fsync(stream.fileno())
        descriptor = os.open(str(directory), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def call(self, tool, arguments, *, deadline_unix_ms=None):
        """Capture before dispatch; preserve failed calls as immutable CAS evidence."""
        from gymts.contracts import utc_now
        from .research import redact
        call_id = "call-" + uuid4().hex
        request_ref = self.gym.artifacts.save_json({"call_id": call_id, "phase": "started", "tool": tool,
            "arguments": redact(arguments), "started_at": utc_now(), "deadline_unix_ms": deadline_unix_ms},
            "gymts.timesigma/tool-call/1")
        self.last_call_ref = request_ref
        self._publish_call(call_id, "started", request_ref)
        try:
            if deadline_unix_ms is not None and time.time() * 1000 >= deadline_unix_ms:
                raise GymTSError("deadline_exceeded", "TimeSigma tool deadline has expired")
            result = self._call(tool, arguments, deadline_unix_ms=deadline_unix_ms)
        except BaseException as error:
            self.last_call_ref = self.gym.artifacts.save_json({"call_id": call_id, "phase": "failed", "tool": tool,
                "request_ref": request_ref, "completed_at": utc_now(),
                "error": redact(error.to_dict() if isinstance(error, GymTSError) else {"type": type(error).__name__})},
                "gymts.timesigma/tool-call/1")
            self._publish_call(call_id, "failed", self.last_call_ref)
            raise
        self.last_call_ref = self.gym.artifacts.save_json({"call_id": call_id, "phase": "completed", "tool": tool,
            "request_ref": request_ref, "completed_at": utc_now(), "result": redact(result)}, "gymts.timesigma/tool-call/1")
        self._publish_call(call_id, "completed", self.last_call_ref)
        return result

    def _call(self, tool, arguments, *, deadline_unix_ms=None):
        if not isinstance(arguments, dict):
            raise GymTSError("invalid_request", "Tool arguments must be a JSON object")
        if tool == "data.import":
            from .data import import_dataset
            return import_dataset(self.gym, **dict(arguments, source_repo=self.source_repo))
        if tool == "task.describe":
            if arguments:
                raise GymTSError("invalid_request", "task.describe takes no arguments")
            return self.gym.registries.tasks.resolve("timesigma-tsad", "1.0.0")
        if tool == "model.catalog":
            if arguments:
                raise GymTSError("invalid_request", "model.catalog takes no arguments")
            return self._native("model.catalog", {}, deadline_unix_ms=deadline_unix_ms)
        if tool == "experiment.run":
            from .pipeline import run_experiment
            params = dict(arguments["params"], source_repo=self.source_repo, python=self.python)
            params.setdefault("timeout_seconds", self.timeout_seconds)
            if deadline_unix_ms is not None:
                from .execution import run_with_deadline
                return run_with_deadline(self.gym, dict(arguments, params=params), deadline_unix_ms=deadline_unix_ms)
            return run_experiment(self.gym, arguments["imported"], params,
                                  artifact=arguments.get("artifact"), metrics=arguments.get("metrics"))
        if tool == "experiment.rescore":
            if deadline_unix_ms is not None:
                from .execution import run_with_deadline
                return run_with_deadline(self.gym, {"score_spec": arguments["spec"]}, deadline_unix_ms=deadline_unix_ms)
            return self.gym.autobench.score(arguments["spec"])
        if tool == "run.inspect":
            from .trajectory import describe_run
            return describe_run(self.gym, arguments["run_id"])
        if tool == "trajectory.snapshot":
            return self.gym.records.snapshot(arguments["run_ids"], arguments.get("query"))
        if tool == "trajectory.export":
            from .trajectory import export_evidence
            return export_evidence(self.gym, arguments["run_ids"], arguments["path"], roots=arguments.get("roots", ()))
        if tool.startswith("native.") and tool[7:] in NATIVE_TOOLS:
            return self._native(tool[7:], arguments, deadline_unix_ms=deadline_unix_ms)
        raise GymTSError("unsupported_capability", "Unknown or unsupported TimeSigma tool: " + str(tool))
