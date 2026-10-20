"""Single-turn synthetic QA projected through the GymTS Task contract.

Parser semantics are a dependency-free port of ChatTS-Bench-new's
``plugins/parsers/structured_json/parser.py`` (strict mode, 0.1.0).  Task
semantic constraints supplement, rather than repair, the frozen source schema.
Neither this module nor the scorer imports the source checkout at runtime.
"""

import copy
import json

from gymts.contracts import GymTSError, in_scope
from gymts.contracts.schema import SchemaRegistry
from gymts.plugin_support import component, empty_update, fail, identifier, payload, unpack

PROTOCOL = "gymts.task/chatts-qa/1"
INPUT = "gymts.chatts/input/1"
OUTPUT = "gymts.chatts/output/1"
RESULT = "gymts.chatts/result/1"
OUTCOME = "gymts.chatts/outcome/1"
ALIGNMENT = "gymts.chatts/alignment/1"
CONTEXT = "gymts.chatts/context/1"
NATIVE = "gymts.chatts/native/1"
PARSER_REF = "chatts.structured-json/1"
MAX_OUTPUT_BYTES = 1_048_576

TASK_VERSIONS = {
    "pattern.trend_direction": ("0.1.0", "0.2.0"),
    "anomaly.point_indices": ("0.1.0", "0.2.0"),
    "forecast.numeric": ("0.1.0", "0.2.0"),
    "pattern.seasonality_profile": ("0.1.0",),
    "process.stationarity_type": ("0.1.0",),
    "relation.lagged_dependence": ("0.1.0",),
    "similarity.shape_retrieval": ("0.1.0",),
}
TASK_METRICS = {
    "pattern.trend_direction": ("accuracy",),
    "anomaly.point_indices": ("event_f1",),
    "forecast.numeric": ("mae", "rmse"),
    "pattern.seasonality_profile": ("accuracy",),
    "process.stationarity_type": ("accuracy",),
    "relation.lagged_dependence": ("exact_match",),
    "similarity.shape_retrieval": ("accuracy",),
}


def _object_schema(properties):
    return {"type": "object", "additionalProperties": False,
            "required": list(properties), "properties": properties}


TASK_OUTPUT_SCHEMAS = {
    "pattern.trend_direction": _object_schema({
        "trend_direction": {"type": "string", "enum": ["increasing", "decreasing", "stable"]}}),
    "anomaly.point_indices": _object_schema({"indices": {
        "type": "array", "uniqueItems": True, "items": {"type": "integer", "minimum": 0}}}),
    "forecast.numeric": _object_schema({"forecast": {
        "type": "array", "minItems": 1, "items": {"type": "number"}}}),
    "pattern.seasonality_profile": _object_schema({
        "profile": {"type": "string", "enum": ["none", "single_period", "multiple_periods"]}}),
    "process.stationarity_type": _object_schema({"type": {"type": "string", "enum": [
        "stationary", "deterministic_trend", "unit_root", "variance_regime"]}}),
    "relation.lagged_dependence": _object_schema({
        "direction": {"type": "string", "enum": ["x_to_y", "y_to_x", "neither"]},
        "lag": {"type": "integer", "minimum": 0, "maximum": 16}}),
    "similarity.shape_retrieval": _object_schema({"candidate_id": {
        "type": "string", "enum": ["candidate_a", "candidate_b", "candidate_c", "candidate_d"]}}),
}


def validate_task_params(spec):
    params = spec.get("params", {})
    if set(params) != {"task_id", "task_version"}:
        fail("invalid_config", "ChatTS parameters require exactly task_id and task_version")
    task_id, version = params["task_id"], params["task_version"]
    if task_id not in TASK_VERSIONS or version not in TASK_VERSIONS[task_id]:
        fail("unsupported_capability", "Unsupported ChatTS task/version")
    return copy.deepcopy(params)


class _DuplicateKey(ValueError):
    pass


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _non_finite(token):
    raise ValueError("non_finite_number")


def _schema_reason(value, schema):
    # Register first: a malformed source schema is a configuration error, not a
    # model parse rejection.  The core subset covers all seven source schemas.
    registry = SchemaRegistry()
    registry.register("chatts.answer-schema/1", schema)
    try:
        registry.validate("chatts.answer-schema/1", value)
    except (GymTSError, OverflowError, RecursionError):
        return "schema_violation"
    return None


def answer_semantic_reason(task_id, value, model_input=None, expected=None):
    """Return a stable invalid reason; never coerce, reorder or truncate answers."""
    reason = _schema_reason(value, TASK_OUTPUT_SCHEMAS[task_id])
    if reason:
        return reason
    if task_id == "anomaly.point_indices":
        indices = value["indices"]
        if any(a >= b for a, b in zip(indices, indices[1:])):
            return "indices_not_strictly_increasing"
        if model_input is not None:
            series = model_input["timeseries"]
            if len(series) != 1:
                fail("schema_mismatch", "Point anomaly task requires exactly one series")
            if any(index >= len(series[0]) for index in indices):
                return "index_out_of_bounds"
    elif task_id == "forecast.numeric":
        horizon = None
        if model_input is not None:
            horizon = model_input.get("context", {}).get("horizon")
            if horizon is None:
                schema = model_input["output_schema"]["properties"]["forecast"]
                if schema.get("minItems") == schema.get("maxItems"):
                    horizon = schema.get("minItems")
            if type(horizon) is not int or horizon < 1:
                fail("invalid_config", "Forecast input requires a public positive context.horizon")
        elif expected is not None:
            horizon = len(expected["forecast"])
        if horizon is not None and len(value["forecast"]) != horizon:
            return "forecast_horizon_mismatch"
    elif task_id == "relation.lagged_dependence":
        if (value["direction"] == "neither" and value["lag"] != 0 or
                value["direction"] != "neither" and value["lag"] < 1):
            return "direction_lag_inconsistent"
    return None


def parse_answer(raw_text, output_schema, task_id, model_input):
    """Strict JSON parsing followed by source-schema and task validation."""
    if not isinstance(raw_text, str):
        return None, "output_is_not_text"
    if len(raw_text.encode("utf-8")) > MAX_OUTPUT_BYTES:
        return None, "output_too_large"
    if not raw_text.strip():
        return None, "empty_output"
    try:
        value = json.loads(raw_text, object_pairs_hook=_unique_object, parse_constant=_non_finite)
    except _DuplicateKey:
        return None, "duplicate_key"
    except json.JSONDecodeError:
        return None, "invalid_json"
    except (ValueError, OverflowError):
        return None, "non_finite_number"
    except RecursionError:
        return None, "output_too_deep"
    if not isinstance(value, dict):
        return None, "root_type_mismatch"
    reason = _schema_reason(value, output_schema)
    if reason:
        return None, reason
    reason = answer_semantic_reason(task_id, value, model_input)
    return (None, reason) if reason else (value, None)


class ChatTSSyntheticQATask:
    def __init__(self, spec):
        self.params = validate_task_params(spec)

    @staticmethod
    def describe_spec(spec):
        validate_task_params(spec)
        return {"plugin_ref": component("chatts-synthetic-qa"), "task_protocol_ref": PROTOCOL,
                "input_schema_ref": INPUT, "output_schema_ref": OUTPUT,
                "result_schema_ref": RESULT, "outcome_schema_ref": OUTCOME,
                "alignment_schema_ref": ALIGNMENT,
                "required_variables": {"sample": {"dtype": "string", "shape": [], "unit": "sample"}},
                "required_operations": {}, "required_capabilities": [],
                "use_default_command": False, "warmup": {"duration": None, "min_points": 0}}

    def describe(self):
        return self.describe_spec({"params": self.params})

    @staticmethod
    def check_compatibility_spec(context):
        environment = context["environment"]
        if (environment["native_schema_ref"] != "gymts.chatts/native/1" or
                environment["clock_domain"] != "step" or environment["observation_granularity"] != "transition"):
            fail("unsupported_capability", "Legacy ChatTS QA requires its native sample contract on a step snapshot")

    def bind(self, spec, binding, environment, execution):
        if environment["clock_domain"] != "step" or environment["observation_granularity"] != "transition":
            fail("unsupported_capability", "Synthetic QA requires a step snapshot environment", "bind")
        return ChatTSQASession(self.params, binding, execution)


class ChatTSQASession:
    def __init__(self, params, binding, execution):
        self.params, self.binding, self.execution = copy.deepcopy(params), copy.deepcopy(binding), execution
        self.cursor = execution["session"]["initial_cursor"]
        public = unpack(execution["session"]["public_context"], execution["data"])
        self.dataset_revision = public["dataset_revision"]
        self.done = False
        self.seen = {}
        self.completed = set()
        self.counts = {"cases_started": 0, "cases_completed": 0, "cases_incomplete": 0,
                       "results_valid": 0, "results_invalid": 0}
        self._summary = None

    def next_observation(self):
        return {"request_id": identifier("request"), "kind": "next", "entities": ["samples"],
                "variables": [self.binding["variables"]["sample"]["source"]],
                "cursor": self.cursor, "max_wait_ms": 0}

    def consume(self, batch):
        self.cursor = batch["cursor"]
        update = empty_update(self.done)
        if batch["data"] is not None and batch["data"].get("native") is not None:
            native = unpack(batch["data"]["native"], self.execution["data"])
            if any(native[key] != self.params[key] for key in ("task_id", "task_version")):
                fail("schema_mismatch", "Snapshot task identity differs from the bound Task", "consume")
            point = batch["snapshot_time"]
            if type(point) is not int or point < 0:
                fail("schema_mismatch", "QA snapshot_time must be a nonnegative integer step", "consume")
            token = native["sample_token"]
            if token in self.seen:
                if self.seen[token] != native["model_input"]:
                    fail("conflict", "Same sample token has conflicting model input", "consume")
            elif not self.done and in_scope(point, self.execution["effective_scope"]):
                self.seen[token] = copy.deepcopy(native["model_input"])
                update["inputs"].append({
                    "run_id": self.execution["run_id"], "case_id": identifier("case"), "turn_id": 0,
                    "input_id": identifier("input"), "task_protocol_ref": PROTOCOL,
                    "decision_time": point,
                    "alignment_key": {"dataset_revision": self.dataset_revision, "sample_token": token},
                    "observation_refs": [self.execution["data"].observation_ref(batch["batch_id"])],
                    "payload": payload(INPUT, native["model_input"])})
                self.counts["cases_started"] += 1
        # A terminal snapshot can contain the last sample.  Emit it before the
        # monotone done flag so the Runner drains the already committed input.
        self.done = self.done or batch["status"] == "end"
        update["done"] = self.done
        return update

    def on_action(self, receipt):
        fail("unsupported_capability", "Synthetic QA has no environment actions", "on_action")

    def interpret(self, task_input, output, output_id):
        if task_input["input_id"] in self.completed:
            fail("conflict", "QA input has already been interpreted", "interpret")
        model_input = unpack(task_input["payload"], self.execution["data"])
        raw = unpack(output["payload"], self.execution["data"])["raw_text"]
        parsed, reason = parse_answer(raw, model_input["output_schema"], self.params["task_id"], model_input)
        valid = reason is None
        record = {key: copy.deepcopy(task_input[key]) for key in (
            "run_id", "case_id", "turn_id", "input_id", "task_protocol_ref", "decision_time", "alignment_key")}
        record.update(result_id=identifier("result"), output_id=output_id,
                      status="valid" if valid else "invalid", payload=payload(RESULT, {
                          "raw_text": raw, "parsed": parsed, "reason": reason, "parser_ref": PARSER_REF}))
        self.completed.add(task_input["input_id"])
        self.counts["cases_completed"] += 1
        self.counts["results_valid" if valid else "results_invalid"] += 1
        return {"results": [record], "requests": [], "complete": True}

    def finish(self, reason):
        if self._summary is None:
            self.counts["cases_incomplete"] = self.counts["cases_started"] - self.counts["cases_completed"]
            self._summary = dict(self.counts, pending_requests=[], artifact_refs=[])
        return copy.deepcopy(self._summary)
