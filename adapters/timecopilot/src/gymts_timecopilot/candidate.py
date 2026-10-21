"""Native agent decisions captured as public model/tool evidence during infer."""
import copy
import json
import math

from gymts.contracts import GymTSError, digest, new_id, utc_now
from gymts.plugin_support import component, payload, unpack
from gymts_timeseries.contracts import INPUT, OUTPUT, PROTOCOL, validate_input
from .registration import EVENT, IDENTITY, SESSION
from .runtime import TimeCopilotRuntime
from .source import FORECASTERS, PINNED_REVISION, checkout_identity


class TimeCopilotCandidate:
    @staticmethod
    def check_compatibility_spec(context):
        experiment = context["experiment"]
        learning = experiment["execution"]["learning"]
        candidate = experiment["candidate"]
        task = experiment["scene"]["task"]["params"]
        if task.get("task_id") != "forecast.numeric" or task.get("task_version") not in ("0.1.0", "0.2.0"):
            raise GymTSError("unsupported_capability", "TimeCopilot supports numeric forecasting tasks 0.1.0 and 0.2.0")
        if (learning["prepare"] != "load_only" or learning["online"] != "frozen" or
                learning["training_view"] is not None or learning["training_targets"] is not None or
                candidate["artifact"] is not None or candidate["inherited_state"]):
            raise GymTSError("unsupported_capability", "Native TimeCopilot tools fit only the current history; persistent training is unsupported")
        if candidate["params"]["implementation"].get("revision", PINNED_REVISION) != PINNED_REVISION:
            raise GymTSError("conflict", "TimeCopilot requires its declared fixed native revision")
        if candidate["params"]["model"]["revision"] in ("latest", "main", "master", ""):
            raise GymTSError("invalid_config", "The served LLM requires a fixed checkpoint identity")

    def __init__(self, spec):
        self.spec, self.params = copy.deepcopy(spec), copy.deepcopy(spec["params"])
        self.refs, self.state = [], "created"

    def prepare(self, context, training):
        if self.state != "created":
            raise GymTSError("invalid_state", "TimeCopilot Candidate prepares once")
        if (context["learning"]["prepare"] != "load_only" or context["learning"]["online"] != "frozen" or
                training is not None or context.get("training_targets") is not None or self.spec.get("artifact") or self.spec.get("inherited_state")):
            raise GymTSError("unsupported_capability", "TimeCopilot uses only the current public history")
        self.resources, self.traces = context["resources"], context.get("traces")
        try:
            source = checkout_identity(self.params["implementation"])
        except (ValueError, OSError) as error:
            raise GymTSError("conflict", str(error), stage="timecopilot.source") from error
        self.runtime = TimeCopilotRuntime(self.params["implementation"],
            timeout_seconds=self.params["limits"]["max_wall_time_s"],
            credential_env=self.params["model"].get("credential_env"))
        identity = self.runtime.invoke({"mode": "identity", "source": source})
        identity.update(model=copy.deepcopy(self.params["model"]),
                        forecasters=list(self.params.get("forecasters", FORECASTERS)),
                        model_configuration={"temperature": self.params.get("temperature", 0), "retries": self.params.get("retries", 2)},
                        execution_semantics="fresh_native_agent_and_forecasters_per_authorized_input")
        # An environment variable name is an identifier; its value never enters CAS.
        self.revision = digest(identity)
        self.identity_ref = self.resources.save_json(identity, IDENTITY)
        self.refs.append(self.identity_ref)
        self.state = "prepared"
        return {"model_revision": self.revision, "state_refs": [self.identity_ref], "training_provenance_ref": None}

    def _error(self, message, code="execution_failure"):
        return GymTSError(code, message, stage="timecopilot.native").to_dict()

    def _record(self, event, active, call_refs, event_refs):
        event_refs.append(self.resources.save_json(event, EVENT))
        kind = event["kind"]
        if kind in ("model_start", "tool_start"):
            item = copy.deepcopy(event)
            item["request_ref"] = self.resources.save_json(event["request"], "gymts.json/1")
            active[event["call_id"]] = item
        elif kind in ("model_end", "tool_end"):
            begun = active.pop(event["call_id"])
            response_ref = (self.resources.save_json(event["response"], "gymts.json/1")
                            if "response" in event else None)
            call_refs.append(self._capture(begun, event, response_ref))

    def _capture(self, begun, ended, response_ref=None):
        if self.traces is None:
            return None
        error = ended.get("error")
        base = {"call_id": begun["call_id"], "attempt_id": begun["attempt_id"],
                "parent_call_id": begun.get("parent_call_id"), "status": ended["status"],
                "started_at": begun["at"], "ended_at": ended.get("at"),
                "error": self._error(error) if error else None}
        if begun["kind"] == "tool_start":
            base.update(tool_ref=component("timecopilot." + begun["tool"], PINNED_REVISION),
                arguments_ref=begun["request_ref"], result_ref=response_ref,
                environment_request_id=None, operation_id=None)
            return self.traces.record_tool_call(base)
        base.update(model_ref=component(self.params["model"]["name"], self.params["model"]["revision"]),
            adapter_ref=component("timecopilot-agent"), policy_revision=self.params["model"]["revision"],
            request_ref=begun["request_ref"], response_ref=response_ref,
            requested_params={"temperature": self.params.get("temperature", 0),
                              "max_tokens": self.params["limits"]["max_response_tokens"]},
            effective_params={"provider_enforcement": "unverified", "request_body_ref": begun["request_ref"]},
            tokenizer_ref=None, chat_template_ref=None, native_inputs_ref=None,
            prompt_token_ids_ref=None, response_token_ids_ref=None, logprobs_ref=None,
            usage=ended.get("usage"), capture={"requested_profile": "io", "completeness": "complete",
                "acquired_fields": ["request_ref"] + (["response_ref"] if response_ref else []),
                "missing_fields": {}, "transforms": []})
        return self.traces.record_model_call(base)

    def infer(self, task_input):
        if self.state != "prepared" or task_input["task_protocol_ref"] != PROTOCOL or task_input["payload"]["schema_ref"] != INPUT:
            raise GymTSError("schema_mismatch", "TimeCopilot requires the neutral time-series QA protocol")
        data = validate_input(unpack(task_input["payload"], self.resources))
        context = data["context"]
        if data["task_id"] != "forecast.numeric" or len(data["series"]) != 1:
            raise GymTSError("unsupported_capability", "TimeCopilot supports a single univariate forecast per input")
        if not all(key in context for key in ("start", "freq", "seasonality", "horizon")):
            raise GymTSError("invalid_request", "TimeCopilot requires explicit start, freq, seasonality and horizon")
        if (type(context["horizon"]) is not int or not 1 <= context["horizon"] <= 1000 or
                type(context["seasonality"]) is not int or context["seasonality"] < 1):
            raise GymTSError("invalid_request", "Invalid forecast horizon or seasonal period")
        session_id, active, call_refs, event_refs = new_id("timecopilot-session"), {}, [], []
        request = {"mode": "analyze", "input": data, "params": self.params, "session_id": session_id}
        request_ref = self.resources.save_json(request, "gymts.json/1")
        started, failure, result = utc_now(), None, None
        try:
            result = self.runtime.invoke(request, lambda event: self._record(event, active, call_refs, event_refs))
            predictions = result["forecast"]
            if len(predictions) != context["horizon"] or any(type(x) not in (int, float) or not math.isfinite(x) for x in predictions):
                raise GymTSError("candidate_failure", "Native TimeCopilot returned an invalid forecast")
        except Exception as error:
            failure = error.to_dict() if isinstance(error, GymTSError) else self._error(type(error).__name__)
            raise
        finally:
            # An abrupt stop never invents a successful response or tool return.
            for begun in active.values():
                call_refs.append(self._capture(begun, {"status": "unknown", "at": None,
                    "error": "Worker ended before this invocation produced an acknowledged terminal event"}))
            session = {"session_id": session_id, "started_at": started, "ended_at": utc_now(),
                "status": "failed" if failure else "succeeded", "error": failure,
                "request_ref": request_ref, "identity_ref": self.identity_ref,
                "native_event_refs": event_refs, "call_refs": [x for x in call_refs if x],
                "result": result, "input_sha256": digest(data), "limits": self.params["limits"]}
            session_ref = self.resources.save_json(session, SESSION)
            self.refs.append(session_ref)
        return {"input_id": task_input["input_id"], "task_protocol_ref": PROTOCOL, "produced_at": utc_now(),
                "model_revision": self.revision, "payload": payload(OUTPUT, {
                    "raw_text": json.dumps({"forecast": result["forecast"]}, allow_nan=False),
                    "evidence": {"session_ref": session_ref, "identity_ref": self.identity_ref,
                                 "native_selected_model": result["analysis"]["selected_model"]}})}

    def update(self, feedback):
        raise GymTSError("unsupported_capability", "TimeCopilot does not persistently update the LLM or tool algorithms")

    def finish(self):
        self.state = "closed"
        return copy.deepcopy(self.refs)
