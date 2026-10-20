"""Versioned public/private TimeSigma wire contracts, independent of NumPy."""
import copy

from gymts.contracts.schema import ARTIFACT, OBJECT, STRING, SchemaRegistry, array, obj
from gymts.plugin_support import fail

PROTOCOL = "gymts.task/timesigma-tsad/1"
TRAINING = "gymts.timesigma/training/1"
SNAPSHOT = "gymts.timesigma/snapshot/1"
INPUT = "gymts.timesigma/input/1"
OUTPUT = "gymts.timesigma/output/1"
RESULT = "gymts.timesigma/result/1"
OUTCOME = "gymts.timesigma/outcome/1"
ALIGNMENT = "gymts.timesigma/alignment/1"
CONTEXT = "gymts.timesigma/context/1"
SOURCE = "gymts.timesigma/source/1"
EMPTY = "gymts.timesigma/empty/1"
TASK_PARAMS = "gymts.timesigma/task-params/1"
IMPORT_MANIFEST = "gymts.timesigma/import-manifest/1"
PRIVATE = "gymts.timesigma/private/1"
PLANNING_UNIT_ID = "gymts.timesigma/planning-unit-id/1"
SCHEMAS = ("naive", "all_in_one", "zero_shot")
IDENTITY_FIELDS = ("dataset_revision", "planning_unit_id", "dataset", "schema",
                   "training_members", "evaluation_members", "preprocessing_members")


def timesigma_schemas():
    names = array(STRING, minItems=1, uniqueItems=True)
    identity = {"dataset_revision": STRING, "planning_unit_id": STRING, "dataset": STRING,
                "schema": {"enum": list(SCHEMAS)}, "training_members": names,
                "evaluation_members": names, "preprocessing_members": names}
    curve = obj({"curve_id": STRING, "values": array({"type": "number"}, minItems=1),
                 "dtype": STRING}, required=["curve_id", "values"])
    unit = obj({**identity, "curves": array(curve, minItems=1)})
    alignment = obj({"dataset_revision": STRING, "planning_unit_id": STRING})
    answer = obj({"dataset_revision": STRING, "planning_unit_id": STRING,
        "curves": array(obj({"curve_id": STRING, "scores": array({"type": "number"}, minItems=1),
            "offset": {"type": "integer", "minimum": 0}, "raw_length": {"type": "integer", "minimum": 1}}), minItems=1),
        "evidence": OBJECT})
    truth = obj({"dataset_revision": STRING, "planning_unit_id": STRING,
        "curves": array(obj({"curve_id": STRING, "labels": array({"type": "integer", "enum": [0, 1]}, minItems=1)}), minItems=1)})
    return {TRAINING: copy.deepcopy(unit), SNAPSHOT: copy.deepcopy(unit), INPUT: copy.deepcopy(unit),
        OUTPUT: copy.deepcopy(answer), RESULT: copy.deepcopy(answer), OUTCOME: truth, ALIGNMENT: alignment,
        CONTEXT: obj({**identity, "evaluation_lengths": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 1}}}),
        SOURCE: obj({"kind": {"const": "dataset"}, "locator": STRING, "revision": STRING,
            "connection": obj({"artifact_refs": array(ARTIFACT, minItems=1, maxItems=1)}),
            "credential_ref": {"type": "null"}}), EMPTY: obj({}),
        TASK_PARAMS: obj({"planning_unit_id": STRING}), PLANNING_UNIT_ID: STRING, IMPORT_MANIFEST: OBJECT,
        PRIVATE: obj({"dataset_revision": STRING, "planning_unit_id": STRING,
                      "outcome": truth, "provenance": OBJECT})}


def validate(ref, value):
    registry = SchemaRegistry()
    registry.register(ref, timesigma_schemas()[ref])
    registry.validate(ref, value)


def identity(value):
    return {key: copy.deepcopy(value[key]) for key in IDENTITY_FIELDS}


def validate_unit(value, *, training=False):
    """Check semantic membership invariants without modifying source arrays."""
    validate(TRAINING if training else INPUT, value)
    fitted, evaluated, preprocessed = (value[key] for key in
        ("training_members", "evaluation_members", "preprocessing_members"))
    if value["schema"] == "naive":
        consistent = len(fitted) == 1 and fitted == evaluated == preprocessed
    elif value["schema"] == "all_in_one":
        consistent = fitted == evaluated == preprocessed
    else:
        consistent = not set(fitted) & set(evaluated) and set(fitted) | set(evaluated) == set(preprocessed)
    if not consistent:
        fail("schema_mismatch", "TimeSigma planning unit has inconsistent native Schema membership")
    expected = preprocessed if training else evaluated
    if [row["curve_id"] for row in value["curves"]] != expected:
        fail("schema_mismatch", "TimeSigma curve order differs from the frozen member order")
    return value


def validate_answer(value, model_input):
    validate(OUTPUT, value)
    if any(value[key] != model_input[key] for key in ("dataset_revision", "planning_unit_id")):
        fail("schema_mismatch", "TimeSigma output identity differs from its input")
    expected = {row["curve_id"]: len(row["values"]) for row in model_input["curves"]}
    if [row["curve_id"] for row in value["curves"]] != model_input["evaluation_members"]:
        fail("schema_mismatch", "TimeSigma scores must cover each evaluation member exactly once in frozen order")
    for row in value["curves"]:
        if row["raw_length"] != expected[row["curve_id"]] or row["offset"] + len(row["scores"]) != row["raw_length"]:
            fail("schema_mismatch", "TimeSigma score offset/count does not match its original test curve")
    return value
