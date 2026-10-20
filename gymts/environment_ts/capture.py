"""Bound, immediately persisted internal model/tool evidence.

Candidates save native arrays and request/response artifacts through their
restricted resources, then submit a call here. Domain identities come from the
Runner. This collector neither tokenizes text nor fabricates model internals.
"""
from __future__ import annotations

import copy
from datetime import datetime

from gymts.contracts import GymTSError, canonical_json, digest, parse_time


MODEL_CALL = "gymts.model-call/1"
TOOL_CALL = "gymts.tool-call/1"
TOKEN_IDS = "gymts.token-ids/1"
LOGPROBS = "gymts.logprobs/1"
NATIVE_INPUTS = "gymts.native-inputs/1"


def _require(condition, message):
    if not condition:
        raise GymTSError("capture_incomplete", message, stage="capture")


def _utc(value):
    parsed = parse_time(value)
    _require(isinstance(parsed, datetime), "Call timestamps must be UTC RFC3339 strings")
    original = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _require(original.utcoffset().total_seconds() == 0, "Call timestamps must use UTC")
    return parsed


def validate_model_call(value, schemas, artifacts, *, profile=None):
    """Validate the formal call and cross-artifact token/probability identity.

    Exporters can reuse this check on frozen artifacts without invoking a model.
    Missing probabilities are a target trainer decision; supplied probabilities
    must always identify exactly the recorded native token sequences.
    """
    schemas.validate(MODEL_CALL, value)
    for field in ("model_ref", "adapter_ref"):
        _require(value[field]["version"] not in {"latest", "main", "master"},
                 "Model-call components require fixed versions")
    started = _utc(value["started_at"])
    if value["ended_at"] is not None:
        _require(_utc(value["ended_at"]) >= started, "Model call ended before it started")
    _require(value["status"] == "unknown" or value["ended_at"] is not None,
             "A completed model attempt requires ended_at")
    _require(value["status"] != "failed" or value["error"] is not None,
             "A failed model attempt requires its error")
    for field in ("request_ref", "response_ref", "tokenizer_ref", "chat_template_ref", "native_inputs_ref",
                  "prompt_token_ids_ref", "response_token_ids_ref", "logprobs_ref"):
        if value[field] is not None:
            artifacts.resolve(value[field])
    captured = value["capture"]
    if profile is not None:
        _require(captured["requested_profile"] == profile, "Call capture profile differs from the Run")
    _require(captured["completeness"] != "complete" or not captured["missing_fields"],
             "Complete call capture cannot declare missing fields")
    for field in captured["acquired_fields"]:
        if field in value:
            _require(value[field] is not None, "A claimed captured field is missing: " + field)
    for transform in captured["transforms"]:
        _require(transform["version"] not in {"latest", "main", "master"},
                 "Capture transforms require fixed versions")
    if value["status"] == "succeeded":
        _require(value["request_ref"] is not None and value["response_ref"] is not None,
                 "Successful IO capture requires both request and response")
        _require(value["error"] is None, "A successful model call cannot contain an error")
        if (profile or captured["requested_profile"]) == "native_rollout":
            for field in ("policy_revision", "tokenizer_ref", "chat_template_ref", "native_inputs_ref",
                          "prompt_token_ids_ref", "response_token_ids_ref"):
                _require(value[field] is not None, "Native rollout capture requires " + field)
    sequences = {}
    for field in ("prompt_token_ids_ref", "response_token_ids_ref"):
        ref = value[field]
        if ref is not None:
            _require(ref["schema_ref"] == TOKEN_IDS, "Native tokens require the token-ID schema")
            sequences[field] = artifacts.read_json(ref)
            schemas.validate(TOKEN_IDS, sequences[field])
    if value["logprobs_ref"] is not None:
        _require(len(sequences) == 2, "Log probabilities require both native token sequences")
        _require(value["logprobs_ref"]["schema_ref"] == LOGPROBS,
                 "Log probabilities require the formal logprob schema")
        probabilities = artifacts.read_json(value["logprobs_ref"])
        schemas.validate(LOGPROBS, probabilities)
        _require(probabilities["call_id"] == value["call_id"] and
                 probabilities["attempt_id"] == value["attempt_id"],
                 "Log probabilities belong to another model attempt")
        for field, key in (("prompt_token_ids_ref", "prompt_sequence_hash"),
                           ("response_token_ids_ref", "response_sequence_hash")):
            _require(probabilities[key] == digest(sequences[field]),
                     "Log probabilities do not match the native token sequence")
        _require(len(probabilities["values"]) == len(sequences["response_token_ids_ref"]),
                 "Log probabilities and response tokens have different lengths")
        _require(probabilities["policy_revision"] == value["policy_revision"],
                 "Log probability policy revision differs from the model call")
        _require(canonical_json(probabilities["effective_params"]) == canonical_json(value["effective_params"]),
                 "Log probability parameters differ from the model call")
        if probabilities["policy_ref"] is not None:
            artifacts.resolve(probabilities["policy_ref"])
        _require(probabilities["policy_ref"] is not None or probabilities["policy_revision"] is not None,
                 "Log probabilities require the actual policy identity")
        if probabilities["source"] == "recomputed":
            _require(probabilities["policy_ref"] is not None and probabilities["computation_ref"] is not None,
                     "Recomputed probabilities require a policy and computation identity")
        if probabilities["computation_ref"] is not None:
            _require(probabilities["computation_ref"]["version"] not in {"latest", "main", "master"},
                     "Log probability computation requires a fixed version")
    return value


class RunTraceCollector:
    """Synchronous collector scoped to one active Candidate.infer invocation."""

    def __init__(self, run_id, profile, schemas, artifacts, publish, problem, storage_failure,
                 execution_events=None):
        self.run_id, self.profile = run_id, profile
        self.schemas, self.artifacts = schemas, artifacts
        self._publish, self._problem, self._storage_failure = publish, problem, storage_failure
        self._execution_events = execution_events
        self._binding = None
        self._refs, self._attempts, self._model_count = [], {}, 0
        self._ref_start = 0
        self._failure = None

    @property
    def context(self):
        _require(self._binding is not None, "Call capture is available only during infer")
        return copy.deepcopy(self._binding)

    @property
    def artifact_refs(self):
        return copy.deepcopy(self._refs[self._ref_start:])

    def bind(self, run_id, task_input, output_id):
        _require(self._binding is None, "Collector already has an active infer binding")
        _require(run_id == self.run_id and task_input["run_id"] == run_id,
                 "Collector was bound to a different Run")
        self._binding = {"run_id": run_id, "input_id": task_input["input_id"], "output_id": output_id}
        self._model_count = 0
        self._ref_start = len(self._refs)

    def _save(self, value, schema):
        try:
            ref = self.artifacts.save_json(value, schema)
        except Exception as error:
            self._storage_failure(error)
        self._refs.append(ref)
        return ref

    def _identity(self, value, schema):
        binding = self.context
        _require(isinstance(value, dict), "Captured call must be an object")
        value = copy.deepcopy(value)
        for field, actual in dict(binding, protocol_version=schema).items():
            _require(field not in value or value[field] == actual,
                     "Captured call has a mismatched " + field)
            value[field] = actual
        return value

    def _report(self, message, reference, reason):
        try:
            self._problem(message, reference, reason)
        except GymTSError as error:
            # A Candidate may catch an adapter error; that must not silently
            # override the Run's fail_run recording policy.
            self._failure = error
            raise

    def _record(self, kind, value, schema):
        # Saving malformed finite evidence separately preserves what was supplied
        # without falsely publishing it as a valid formal model_call event.
        original = value
        try:
            value = self._identity(value, schema)
            canonical_json(value)
            if kind == "model_call":
                validate_model_call(value, self.schemas, self.artifacts, profile=self.profile)
            else:
                self.schemas.validate(schema, value)
                started = _utc(value["started_at"])
                if value["ended_at"] is not None:
                    _require(_utc(value["ended_at"]) >= started, "Tool call ended before it started")
                _require(value["status"] == "unknown" or value["ended_at"] is not None,
                         "A completed tool attempt requires ended_at")
                _require(value["tool_ref"]["version"] not in {"latest", "main", "master"},
                         "Tool-call components require fixed versions")
                _require(value["status"] != "failed" or value["error"] is not None,
                         "A failed tool attempt requires its error")
                for field in ("arguments_ref", "result_ref"):
                    if value[field] is not None:
                        self.artifacts.resolve(value[field])
                if value["status"] == "succeeded":
                    _require(value["arguments_ref"] is not None and value["result_ref"] is not None,
                             "A successful tool call requires arguments and result")
                    _require(value["error"] is None, "A successful tool call cannot contain an error")
                self._validate_tool_operation(value)
        except (GymTSError, TypeError, ValueError, KeyError) as error:
            rejected = None
            try:
                canonical_json(original)
            except (TypeError, ValueError):
                pass
            else:
                rejected = self._save({"kind": kind, "binding": self.context, "supplied": original}, "gymts.json/1")
                self._publish("artifact", rejected, dict(self.context, role="rejected_" + kind))
            self._report("Captured " + kind + " failed validation", rejected,
                         error.code if isinstance(error, GymTSError) else "schema_mismatch")
            return rejected
        attempt = (kind, value["call_id"], value["attempt_id"])
        previous = self._attempts.get(attempt)
        if previous is not None:
            if canonical_json(previous[0]) != canonical_json(value):
                self._report("A captured attempt identity already has different evidence", previous[1], "conflict")
            return copy.deepcopy(previous[1])
        ref = self._save(value, schema)
        links = dict(self.context, call_id=value["call_id"], attempt_id=value["attempt_id"])
        self._publish(kind, ref, links)
        self._attempts[attempt] = (copy.deepcopy(value), ref)
        if kind == "model_call":
            self._model_count += 1
            if value["capture"]["completeness"] != "complete":
                self._report("Requested model-call capture is incomplete", ref, "capture_incomplete")
        return ref

    def _validate_tool_operation(self, value):
        if value["operation_id"] is None and value["environment_request_id"] is None:
            return
        events = self._execution_events() if self._execution_events else []
        operations, requests = set(), set()
        for event in events:
            links = event["links"]
            if event["kind"] == "environment_operation":
                operations.add((links.get("operation_id"), links.get("request_id")))
            elif event["kind"] == "environment_request":
                requests.add(links.get("request_id"))
        if value["operation_id"] is not None:
            _require((value["operation_id"], value["environment_request_id"]) in operations,
                     "Environment tool operation has not passed through the Runner")
        else:
            _require(value["environment_request_id"] in requests,
                     "Environment tool read has not passed through the Runner")

    def record_model_call(self, value):
        return self._record("model_call", value, MODEL_CALL)

    def record_tool_call(self, value):
        return self._record("tool_call", value, TOOL_CALL)

    def flush(self):
        _require(self._binding is not None, "Collector has no active infer binding")
        try:
            if self._failure is not None:
                raise self._failure
            if not self._model_count:
                self._report("Candidate returned no model-call evidence for the requested profile", None,
                             "capture_incomplete")
            return self.artifact_refs
        finally:
            self._binding = None
