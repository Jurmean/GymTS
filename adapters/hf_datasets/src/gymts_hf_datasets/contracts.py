"""Adapter-owned static forecast formats; no format logic in GymTS core."""
from gymts.contracts.schema import ARTIFACT, STRING, array, obj

PROTOCOL = "gymts.task/hf-static-forecast/1"
PUBLIC = "gymts.hf-static/public/1"
SNAPSHOT = "gymts.hf-static/snapshot/1"
OUTPUT = "gymts.hf-static/output/1"
RESULT = "gymts.hf-static/result/1"
OUTCOME = "gymts.hf-static/outcome/1"
ALIGNMENT = "gymts.hf-static/alignment/1"
CONTEXT = "gymts.hf-static/context/1"
TOKEN = "gymts.hf-static/sample-id/1"
IMPORTER_REF = {"name": "hf-static-forecast-freezer", "version": "1.0.0", "origin_ref": None}
RESOLVER_REF = {"name": "hf-static-forecast-benchmark", "version": "1.0.0", "origin_ref": None}
PROJECTION = "tail-holdout-context/1"


def schemas():
    token = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    values = array({"type": "number"}, minItems=1)
    public = obj({"sample_id": token, "dataset_id": STRING, "source_row": {"type": "integer", "minimum": 0},
                  "history": values, "horizon": {"type": "integer", "minimum": 1},
                  "series_column": STRING, "projection_ref": {"const": PROJECTION}})
    return {PUBLIC: public, SNAPSHOT: obj({"dataset_revision": STRING, "sample": public}),
            OUTPUT: obj({"values": values}), RESULT: obj({"values": values}), OUTCOME: obj({"values": values}),
            ALIGNMENT: obj({"dataset_revision": STRING, "sample_id": token}), TOKEN: token,
            CONTEXT: obj({"dataset_revision": STRING}),
            "gymts.hf-static/empty/1": obj({}),
            "gymts.hf-static/source/1": obj({"kind": {"const": "dataset"}, "locator": STRING,
                "revision": STRING, "connection": obj({"artifact_refs": array(ARTIFACT, minItems=1, maxItems=1)}),
                "credential_ref": {"type": "null"}})}
