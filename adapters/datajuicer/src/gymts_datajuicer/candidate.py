"""Trusted external worker bridge; it cannot publish DatasetCatalog resources."""
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
from gymts.contracts import GymTSError, utc_now
from gymts.plugin_support import component, fail, payload, unpack
from .common import dumps, loads, sha, validate_source, write_json
from .contracts import OUTPUT, PROTOCOL


class NativePipelineCandidate:
    def __init__(self, spec):
        self.spec, self.state, self.refs = spec, "created", []
        self.params = spec["params"]
        self.revision = "datajuicer-local-hf/" + sha(self.params["model_identity"])

    def prepare(self, context, training):
        if (self.state != "created" or training is not None or context["learning"]["prepare"] != "load_only"
            or context["learning"]["online"] != "frozen" or self.spec["artifact"] is not None
            or self.spec["inherited_state"]):
            fail("unsupported_capability", "Native data processing is frozen load_only, with an explicit source view")
        if context["traces"] is None or context["traces"].profile != "io":
            fail("unsupported_capability", "Native Data-Juicer requires actual IO capture")
        self.resources, self.traces, self.state = context["resources"], context["traces"], "prepared"
        return {"model_revision": self.revision, "state_refs": [], "training_provenance_ref": None}

    def _save_files(self, directory):
        refs = []
        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.suffix not in {".json", ".jsonl", ".log"}:
                continue
            # Native cache/checkpoint directories are not silently copied. The
            # native export and full audit files are bounded by the Task input.
            if path.stat().st_size > 64 * 1024 * 1024:
                fail("recording_failure", "Worker evidence exceeded 64 MiB per file")
            ref = self.resources.save_artifact(path.read_bytes(), {"media_type":
                "application/json" if path.suffix == ".json" else "application/x-ndjson"
                if path.suffix == ".jsonl" else "text/plain", "schema_ref": None})
            refs.append(ref)
        self.refs.extend(refs)
        return refs

    def _capture(self, directory):
        stages = directory / "stages-journal.jsonl"
        if stages.exists():
            attempts = {}
            for line in stages.read_text().splitlines():
                if line.strip():
                    stage = loads(line)
                    attempts[stage["index"]] = stage
            for index, stage in attempts.items():
                status = "unknown" if stage["status"] == "started" else stage["status"]
                audited_qa = stage["operator"] == "gymts_audited_native_qa_mapper"
                arguments = self.resources.save_json({"operator": stage["operator"], "input": stage["input"],
                    "index": index, "native_operator_ref": component("datajuicer.generate_qa_from_text_mapper"
                    if audited_qa else "datajuicer." + stage["operator"], "1.6.1")}, "gymts.json/1")
                result = self.resources.save_json(stage, "gymts.json/1") if status == "succeeded" else None
                error = GymTSError("native_operator_failed", stage["error"]["message"],
                    stage="native_worker").to_dict() if status == "failed" else None
                self.traces.record_tool_call({"call_id": "dj-stage-" + str(index), "attempt_id": "attempt-1",
                    "parent_call_id": None, "started_at": stage["started_at"], "ended_at": stage.get("ended_at"),
                    "status": status, "tool_ref": component("gymts-datajuicer.native-qa-audit", "0.1.0")
                        if audited_qa else component("datajuicer." + stage["operator"], "1.6.1"),
                    "arguments_ref": arguments, "result_ref": result, "error": error,
                    "environment_request_id": None, "operation_id": None})
        path = directory / "model-calls.jsonl"
        if not path.exists():
            return
        entries = [loads(line) for line in path.read_text().splitlines() if line.strip()]
        attempts = {}
        for row in entries:
            attempts[(row["call_id"], row["attempt_id"])] = row
        for row in attempts.values():
            request_ref = self.resources.save_json({"messages": row["messages"], "params": row["params"],
                                                   "sample_id": row["sample_id"]}, "gymts.json/1")
            succeeded = row["status"] == "succeeded"
            response_ref = self.resources.save_json(row["response"], "gymts.json/1") if succeeded else None
            status = "unknown" if row["status"] == "started" else row["status"]
            error = (GymTSError("native_model_failed", row["error"]["message"], stage="native_worker").to_dict()
                     if status == "failed" else None)
            self.traces.record_model_call({"call_id": row["call_id"], "attempt_id": row["attempt_id"],
                "parent_call_id": "dj-stage-2", "started_at": row["started_at"], "ended_at": row["ended_at"],
                "status": status, "model_ref": component("local-qwen-datajuicer", self.revision),
                "adapter_ref": component("gymts-datajuicer-hf-io", "0.1.0"), "policy_revision": self.revision,
                "request_ref": request_ref, "response_ref": response_ref, "requested_params": row["params"],
                "effective_params": row["effective_params"], "tokenizer_ref": None, "chat_template_ref": None,
                "native_inputs_ref": None, "prompt_token_ids_ref": None, "response_token_ids_ref": None,
                "logprobs_ref": None, "usage": None, "error": error,
                "capture": {"requested_profile": "io", "acquired_fields": ["request_ref"] +
                    (["response_ref"] if succeeded else []), "missing_fields": {}, "transforms": [],
                    "completeness": "complete"}})

    def infer(self, task_input):
        if self.state != "prepared" or task_input["task_protocol_ref"] != PROTOCOL:
            fail("invalid_state", "Data-Juicer Candidate requires its prepared derivation Task")
        value = unpack(task_input["payload"], self.resources)
        validate_source(value["rows"])
        root = Path(self.params["work_root"]).resolve()
        root.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="run-", dir=root))
        request = {**self.params, **value}
        write_json(work / "request.json", request)
        output = work / "native"
        allowed = ("PATH", "LD_LIBRARY_PATH", "CUDA_VISIBLE_DEVICES", "TMPDIR", "LANG", "LC_ALL")
        env = {key: os.environ[key] for key in allowed if key in os.environ}
        env.update(PYTHONDONTWRITEBYTECODE="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                   HF_DATASETS_OFFLINE="1", HF_DATASETS_DISABLE_PROGRESS_BARS="1", TOKENIZERS_PARALLELISM="false",
                   GYMTS_DATAJUICER_PARENT_PID=str(os.getpid()))
        argv = [self.params["worker_python"], "-B", "-m", "gymts_datajuicer.worker",
                "--request", str(work / "request.json"), "--output", str(output)]
        failure = None
        with (work / "worker.log").open("wb") as log:
            process = subprocess.Popen(argv, cwd=str(work), env=env, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            previous_term = None
            def stop_owned_worker(signum, frame):
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                raise SystemExit(128 + signum)
            if threading.current_thread() is threading.main_thread():
                previous_term = signal.signal(signal.SIGTERM, stop_owned_worker)
            try:
                try:
                    process.wait(timeout=self.params["timeout_seconds"])
                except subprocess.TimeoutExpired:
                    failure = "Native worker timeout; only its own process group was stopped"
            finally:
                if previous_term is not None:
                    signal.signal(signal.SIGTERM, previous_term)
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=10)
        if output.exists():
            self._save_files(output)
            self._capture(output)
        self._save_files(work)
        if failure or process.returncode != 0 or not (output / "response.json").is_file():
            fail("native_pipeline_failed", failure or "Native Data-Juicer worker failed; sealed artifacts retain its error")
        response = loads((output / "response.json").read_text())
        response["artifact_refs"] = list(self.refs)
        if not response["identity"]["native_execution"] or response["identity"]["cpu_only"]:
            fail("invalid_state", "A CPU preflight is not an accepted model-backed derivation Run")
        return {"input_id": task_input["input_id"], "task_protocol_ref": PROTOCOL,
            "produced_at": utc_now(), "model_revision": self.revision, "payload": payload(OUTPUT, response)}

    def update(self, feedback):
        fail("unsupported_capability", "Data processing has no implicit online update")

    def finish(self):
        self.state = "closed"
        return list(self.refs)
