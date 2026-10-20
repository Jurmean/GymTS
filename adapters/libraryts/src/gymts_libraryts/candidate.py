"""Stateless native estimators condition only on the current neutral QA input."""
import copy
import json
import math

from gymts.contracts import GymTSError, digest, new_id, utc_now
from gymts.plugin_support import payload, unpack
from gymts_timeseries.contracts import INPUT, OUTPUT, PROTOCOL, validate_input

from .source import PINNED_REVISION, implementation_ref, tool_ref
from .tools import LibraryTSTools


class LibraryTSQACandidate:
    SUPPORTED_TASK_IDS = ("forecast.numeric", "pattern.trend_direction")

    @staticmethod
    def check_compatibility_spec(context):
        experiment = context["experiment"]
        candidate, learning = experiment["candidate"], experiment["execution"]["learning"]
        task_id = experiment["scene"]["task"]["params"].get("task_id")
        if task_id is not None and task_id not in LibraryTSQACandidate.SUPPORTED_TASK_IDS:
            raise GymTSError("unsupported_capability", "LibraryTS QA supports only forecast.numeric and pattern.trend_direction")
        if (learning["prepare"] != "load_only" or learning["online"] != "frozen" or
                learning["training_view"] is not None or learning["training_targets"] is not None or
                candidate["artifact"] is not None or candidate["inherited_state"]):
            raise GymTSError("unsupported_capability", "LibraryTS stateless current-input fitting does not support persistent training or inherited state")
        revision = candidate["params"]["implementation"].get("revision", PINNED_REVISION)
        if revision != PINNED_REVISION:
            raise GymTSError("conflict", "LibraryTS Candidate requires its declared fixed native revision")

    def __init__(self, spec):
        self.spec = copy.deepcopy(spec)
        self.params = self.spec.get("params", {})
        if set(self.params) - {"implementation", "estimator", "estimator_params", "timeout_seconds", "trend_tolerance"}:
            raise GymTSError("invalid_config", "Unsupported LibraryTS Candidate parameter")
        if self.params.get("estimator", "naive") not in ("naive", "polynomial"):
            raise GymTSError("unsupported_capability", "LibraryTS QA supports naive and polynomial estimators")
        self.tool = "forecast." + self.params.get("estimator", "naive")
        self.state, self.refs = "created", []

    def prepare(self, context, training):
        if self.state != "created":
            raise GymTSError("invalid_state", "LibraryTS Candidate prepares once")
        if (context["learning"]["prepare"] != "load_only" or context["learning"]["online"] != "frozen" or
                training is not None or context.get("training_targets") is not None or
                self.spec.get("artifact") is not None or self.spec.get("inherited_state")):
            raise GymTSError("unsupported_capability", "Stateless LibraryTS methods use only current inputs; no persistent model training or inherited state")
        self.resources, self.traces = context["resources"], context.get("traces")
        self.tools = LibraryTSTools(self.resources, self.params["implementation"],
            timeout_seconds=self.params.get("timeout_seconds", 120), traces=self.traces,
            scope="current_input")
        source = self.tools.runtime.describe(self.tool)
        identity = {"source": source, "estimator": self.tool, "params": self.params.get("estimator_params", {}),
                    "execution_semantics": "fresh_native_fit_on_each_current_input; no_cross_call_state"}
        self.revision = digest(identity)
        ref = self.resources.save_json(identity, "gymts.libraryts/algorithm-identity/1")
        self.refs.append(ref)
        self.state = "prepared"
        return {"model_revision": self.revision, "state_refs": [ref], "training_provenance_ref": None}

    def _model_call(self, model_id, attempt, call, *, error=None):
        if self.traces is None:
            return None
        return self.traces.record_model_call({"call_id": model_id, "attempt_id": attempt,
            "parent_call_id": None, "status": "failed" if error else "succeeded",
            "started_at": call["started_at"], "ended_at": call["ended_at"],
            "model_ref": tool_ref(self.tool), "adapter_ref": {"name": "libraryts-qa", "version": "1.0.0", "origin_ref": None},
            "policy_revision": self.revision, "request_ref": call["request_ref"],
            "response_ref": call.get("response_ref"), "requested_params": copy.deepcopy(self.params.get("estimator_params", {})),
            "effective_params": copy.deepcopy(call.get("output", {}).get("params", {})),
            "tokenizer_ref": None, "chat_template_ref": None, "native_inputs_ref": None,
            "prompt_token_ids_ref": None, "response_token_ids_ref": None, "logprobs_ref": None,
            "usage": {"algorithm_execution": "stateless_current_input", "native_fit_occurred": True if not error else None},
            "error": error, "capture": {"requested_profile": "io", "acquired_fields": ["request_ref"] + ([] if error else ["response_ref"]),
                "missing_fields": {}, "transforms": [], "completeness": "complete"}})

    def infer(self, task_input):
        if self.state != "prepared" or task_input["task_protocol_ref"] != PROTOCOL or task_input["payload"]["schema_ref"] != INPUT:
            raise GymTSError("schema_mismatch", "LibraryTS Candidate requires the neutral time-series QA protocol")
        data = validate_input(unpack(task_input["payload"], self.resources))
        if data["task_id"] not in self.SUPPORTED_TASK_IDS or len(data["series"]) != 1:
            raise GymTSError("unsupported_capability", "This native QA adapter supports one series and forecasting/trend tasks")
        values = data["series"][0]["values"]
        horizon = data["context"].get("horizon", 1) if data["task_id"] == "forecast.numeric" else 2
        if type(horizon) is not int or not 1 <= horizon <= 10000:
            raise GymTSError("invalid_request", "Forecast horizon must be a positive integer <=10000")
        model_id, attempt = new_id("libraryts-model"), new_id("attempt")
        try:
            call = self.tools.call(self.tool, {"values": values, "horizons": list(range(1, horizon + 1))},
                self.params.get("estimator_params", {}), parent_call_id=model_id)
        except GymTSError as failure:
            request_ref = failure.info["links"].get("request_ref")
            if self.traces is not None and request_ref is not None:
                failed = self.resources.read_json(failure.info["links"]["failed_call_ref"])
                self._model_call(model_id, attempt, {**failed, "request_ref": request_ref}, error=failure.to_dict())
            raise
        model_ref = self._model_call(model_id, attempt, call)
        self.refs.append(call["call_ref"])
        output = call["output"]
        predictions = output["predictions"]
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in predictions):
            raise GymTSError("candidate_failure", "Native forecaster produced a non-finite prediction")
        if data["task_id"] == "forecast.numeric":
            answer = {"forecast": predictions}
        else:
            tolerance = self.params.get("trend_tolerance", 1e-8)
            slope = predictions[1] - predictions[0]
            answer = {"trend_direction": "increasing" if slope > tolerance else "decreasing" if slope < -tolerance else "stable"}
        evidence = {"libraryts_call_ref": call["call_ref"], "model_call_ref": model_ref,
                    "implementation_ref": implementation_ref(), "native_fit_occurred": output["fit_occurred"],
                    "fit_scope": output["fit_scope"], "fitted_state_sha256": output["fitted_state_sha256"],
                    "persistent_state_reused": False, "input_sha256": digest(data),
                    "algorithm_definition_revision": self.revision}
        return {"input_id": task_input["input_id"], "task_protocol_ref": PROTOCOL, "produced_at": utc_now(),
                "model_revision": self.revision, "payload": payload(OUTPUT, {"raw_text": json.dumps(answer, allow_nan=False), "evidence": evidence})}

    def update(self, feedback):
        raise GymTSError("unsupported_capability", "Stateless LibraryTS methods do not update persistent policy state")

    def finish(self):
        self.state = "closed"
        return copy.deepcopy(self.refs)
