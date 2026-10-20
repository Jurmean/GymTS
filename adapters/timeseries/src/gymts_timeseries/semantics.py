"""Single-turn synthetic QA projected through the GymTS Task contract.

Parser semantics are a dependency-free port of ChatTS-Bench-new's
``plugins/parsers/structured_json/parser.py`` (strict mode, 0.1.0).  Task
semantic constraints supplement, rather than repair, the frozen source schema.
Neither this module nor the scorer imports the source checkout at runtime.
"""

import copy
import json

from gymts.contracts import GymTSError
from gymts.contracts.schema import SchemaRegistry
from gymts.plugin_support import fail

PARSER_REF = "timeseries.structured-json/1"
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
        fail("invalid_config", "time-series parameters require exactly task_id and task_version")
    task_id, version = params["task_id"], params["task_version"]
    if task_id not in TASK_VERSIONS or version not in TASK_VERSIONS[task_id]:
        fail("unsupported_capability", "Unsupported time-series task/version")
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
    registry.register("timeseries.answer-schema/1", schema)
    try:
        registry.validate("timeseries.answer-schema/1", value)
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
            series = [item["values"] for item in model_input["series"]]
            if len(series) != 1:
                fail("schema_mismatch", "Point anomaly task requires exactly one series")
            if any(index >= len(series[0]) for index in indices):
                return "index_out_of_bounds"
    elif task_id == "forecast.numeric":
        horizon = None
        if model_input is not None:
            horizon = model_input.get("context", {}).get("horizon")
            if horizon is None:
                schema = model_input["response_schema"]["properties"]["forecast"]
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

