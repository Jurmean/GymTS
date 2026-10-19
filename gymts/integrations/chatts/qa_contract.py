"""The existing versioned QA input contract shared by independent adapters.

This module validates public inputs only; it does not load a model or transport.
"""
import copy
import math

from gymts.plugin_support import fail as _fail, unpack


PROTOCOL = "gymts.task/chatts-qa/1"
INPUT = "gymts.chatts/input/1"
OUTPUT = "gymts.chatts/output/1"
PLACEHOLDER = "<ts><ts/>"
DIALECTS = ("chatts-timeseries/v1", "chatts-vllm-text-envelope/v1")
TASK_IDS = ("pattern.trend_direction", "anomaly.point_indices", "forecast.numeric",
            "pattern.seasonality_profile", "process.stationarity_type",
            "relation.lagged_dependence", "similarity.shape_retrieval")



def load_qa_input(task_input, resources):
    if task_input.get("task_protocol_ref") != PROTOCOL:
        _fail("schema_mismatch", "Candidate requires the ChatTS QA task protocol", "infer")
    model_input = unpack(task_input["payload"], resources)
    if not isinstance(model_input, dict):
        _fail("schema_mismatch", "TaskInput has no public model_input", "infer")
    messages, arrays = model_input.get("messages"), model_input.get("timeseries")
    names = model_input.get("series_names")
    if not isinstance(messages, list) or not messages:
        _fail("schema_mismatch", "messages must be a nonempty ordered list", "infer")
    for message in messages:
        if (not isinstance(message, dict) or message.get("role") not in ("system", "user", "assistant")
                or not isinstance(message.get("content"), str)):
            _fail("schema_mismatch", "ChatTS messages require textual role/content fields", "infer")
    if not isinstance(arrays, list) or not arrays:
        _fail("schema_mismatch", "Native timeseries must be a nonempty array list", "infer")
    for series in arrays:
        if not isinstance(series, list) or not series:
            _fail("schema_mismatch", "Each native timeseries must be a nonempty numeric list", "infer")
        if any(type(point) not in (float, int) or not math.isfinite(point) for point in series):
            _fail("schema_mismatch", "Native timeseries points must be finite numbers", "infer")
    if (not isinstance(names, list) or len(names) != len(arrays)
            or any(not isinstance(name, str) or not name for name in names)):
        _fail("schema_mismatch", "series_names must identify every native timeseries in order", "infer")
    count = sum(message["content"].count(PLACEHOLDER) for message in messages)
    # Bench profiles carry named native modalities separately and have no TS
    # placeholders. Original ChatTS SFT prompts already contain all of them.
    # Partial placeholder injection is ambiguous and must never be repaired.
    if count not in (0, len(arrays)):
        _fail("schema_mismatch", "Partial time-series placeholders differ from native array count", "infer")
    return copy.deepcopy(model_input)



__all__ = ["PROTOCOL", "INPUT", "OUTPUT", "PLACEHOLDER", "DIALECTS", "TASK_IDS", "load_qa_input"]
