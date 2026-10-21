"""Data-processing formats belong to this adapter, not GymTS core."""
from gymts.contracts.schema import ARTIFACT, OBJECT, STRING, array, obj

PROTOCOL = "gymts.task/datajuicer-derive/1"
PUBLIC = "gymts.datajuicer/input/1"
SNAPSHOT = "gymts.datajuicer/snapshot/1"
OUTPUT = "gymts.datajuicer/output/1"
RESULT = "gymts.datajuicer/result/1"
OUTCOME = "gymts.datajuicer/outcome/1"
ALIGNMENT = "gymts.datajuicer/alignment/1"
CONTEXT = "gymts.datajuicer/context/1"
EMPTY = "gymts.datajuicer/empty/1"
PARAMS = "gymts.datajuicer/candidate-params/1"
DATA_ROW = "gymts.datajuicer/derived-row/1"
METRICS = ("answer_accuracy", "structure_rate", "source_coverage", "unique_rate", "lineage_integrity", "holdout_clean")


def schemas():
    public = obj({"source_revision": STRING, "rows": array(OBJECT, minItems=1, maxItems=256)})
    output = obj({"rows": array(OBJECT), "stages": array(OBJECT), "model_calls": array(OBJECT),
        "identity": OBJECT, "export_text": {"type": "string"}, "export_sha256": STRING,
        "artifact_refs": array(ARTIFACT)})
    return {PUBLIC: public, SNAPSHOT: obj({"dataset_revision": STRING, "sample": public}),
        OUTPUT: output, RESULT: output,
        OUTCOME: obj({"source_revision": STRING, "rows": array(OBJECT), "holdout_families": array(STRING),
                      "holdout_series_sha256": array(STRING)}),
        ALIGNMENT: obj({"source_revision": STRING}), CONTEXT: obj({"dataset_revision": STRING}), EMPTY: obj({}),
        DATA_ROW: OBJECT,
        "gymts.datajuicer/source/1": obj({"kind": {"const": "dataset"}, "locator": STRING,
            "revision": STRING, "connection": obj({"artifact_refs": array(ARTIFACT, minItems=1, maxItems=1)}),
            "credential_ref": {"type": "null"}}),
        PARAMS: obj({"worker_python": STRING, "upstream": STRING, "model_path": STRING,
            "model_identity": OBJECT, "timeout_seconds": {"type": "integer", "minimum": 10, "maximum": 3600},
            "max_new_tokens": {"type": "integer", "minimum": 16, "maximum": 1024},
            "work_root": STRING})}
