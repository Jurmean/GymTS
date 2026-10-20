"""Public, model-neutral domain contracts shared by independent adapters."""
import copy
import math

from gymts.contracts.schema import OBJECT, STRING, SchemaRegistry, array, nullable, obj
from gymts.plugin_support import fail

PROTOCOL = "gymts.task/timeseries-qa/1"
INPUT = "gymts.timeseries/qa-input/1"
OUTPUT = "gymts.timeseries/qa-output/1"
RESULT = "gymts.timeseries/qa-result/1"
OUTCOME = "gymts.timeseries/qa-outcome/1"
ALIGNMENT = "gymts.timeseries/qa-alignment/1"
SNAPSHOT = "gymts.timeseries/numeric-snapshot/1"
NATIVE = "gymts.timeseries/numeric-sample/1"
CONTEXT = "gymts.timeseries/source-context/1"
CSV = "gymts.timeseries/numeric-csv/1"
TOKEN = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
SERIES = array(obj({"name": {"type": "string", "minLength": 1},
                    "values": array({"type": "number"}, minItems=1)}), minItems=1)


def domain_schemas():
    sample = obj({"sample_token": TOKEN, "series": SERIES, "context": OBJECT, "annotations": OBJECT})
    return {
        "gymts.timeseries/sample-token/1": TOKEN,
        INPUT: obj({"task_id": STRING, "task_version": STRING, "question": STRING,
                    "series": SERIES, "context": OBJECT, "response_schema": OBJECT}),
        OUTPUT: obj({"raw_text": {"type": "string"}, "evidence": OBJECT}),
        RESULT: obj({"raw_text": {"type": "string"}, "parsed": nullable(OBJECT),
                     "reason": nullable(STRING), "parser_ref": {"const": "timeseries.structured-json/1"}}),
        OUTCOME: obj({"task_id": STRING, "task_version": STRING, "expected_output": OBJECT}),
        ALIGNMENT: obj({"dataset_revision": STRING, "sample_token": TOKEN}),
        NATIVE: sample,
        SNAPSHOT: obj({"schema_version": {"const": SNAPSHOT}, "dataset_revision": STRING,
                       "samples": array(sample, minItems=1)}),
        CONTEXT: obj({"dataset_revision": STRING, "sample_count": {"type": "integer", "minimum": 1}}),
    }


def _validate(ref, value):
    registry = SchemaRegistry()
    registry.register(ref, domain_schemas()[ref])
    registry.validate(ref, value)
    names = [item["name"] for item in value.get("series", [])]
    if len(names) != len(set(names)):
        fail("schema_mismatch", "Series names must be distinct within a sample")
    for item in value.get("series", []):
        if any(type(number) not in (int, float) or not math.isfinite(number) for number in item["values"]):
            fail("schema_mismatch", "Numeric observations must be finite")
    return copy.deepcopy(value)


def validate_sample(value):
    """Validate source facts without selecting a task or invoking its parser."""
    value = _validate(NATIVE, value)
    def public_fields(item):
        if isinstance(item, dict):
            if set(item) & {"expected_output", "gold", "answer", "labels", "test_label", "ground_truth"}:
                fail("permission_denied", "Private reference fields do not belong in public source facts")
            for child in item.values():
                public_fields(child)
        elif isinstance(item, list):
            for child in item:
                public_fields(child)
    public_fields(value["context"])
    public_fields(value["annotations"])
    return value


def validate_input(value):
    """Validate the public payload used by model adapters, without a model codec."""
    return _validate(INPUT, value)


def validate_snapshot(value):
    registry = SchemaRegistry()
    registry.register(SNAPSHOT, domain_schemas()[SNAPSHOT])
    registry.validate(SNAPSHOT, value)
    tokens = []
    for sample in value["samples"]:
        validate_sample(sample)
        tokens.append(sample["sample_token"])
    if len(tokens) != len(set(tokens)):
        fail("conflict", "A numeric snapshot must contain unique sample tokens")
    return copy.deepcopy(value)


__all__ = ["PROTOCOL", "INPUT", "OUTPUT", "RESULT", "OUTCOME", "ALIGNMENT", "SNAPSHOT",
           "NATIVE", "CONTEXT", "CSV", "domain_schemas", "validate_sample", "validate_input", "validate_snapshot"]
