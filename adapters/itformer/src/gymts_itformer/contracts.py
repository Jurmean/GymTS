"""Project-owned contracts; no ITFormer formats are added to GymTS core."""
from gymts.contracts.schema import OBJECT, STRING, array, nullable, obj

UPSTREAM_SHA = "b80142fc8b6ab2be8f148f3bb7a7534bb32f318b"
DATA_REVISION = "ea2051a15512212976c22c1a075ec549c7d48eef"
MODEL_REVISION = "a5f52d265b7303bae513e77512453d86d477c44b"
PROTOCOL = "gymts.task/itformer-qa/1"
PUBLIC = "gymts.itformer/public/1"
INPUT = "gymts.itformer/input/1"
OUTPUT = "gymts.itformer/output/1"
RESULT = "gymts.itformer/result/1"
OUTCOME = "gymts.itformer/outcome/1"
ALIGNMENT = "gymts.itformer/alignment/1"
SNAPSHOT = "gymts.itformer/snapshot/1"
CONTEXT = "gymts.itformer/context/1"
TOKEN = "gymts.itformer/sample-id/1"
PARSER_REF = "itformer-strict-answer/1"


def domain_schemas():
    token = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    number = {"type": "number"}
    integer = {"type": "integer", "minimum": 0}
    public = obj({"sample_id": token, "source_line": integer, "qa_offset": integer,
        "flattened_index": integer, "signal_ids": array(STRING, minItems=1),
        "stage": {"enum": [1, 2, 3, 4]}, "form": STRING, "question": STRING,
        "signal": array(array(number, minItems=1), minItems=1),
        "signal_shape": array({"type": "integer", "minimum": 1}, minItems=2, maxItems=2),
        "projection_ref": {"const": "itformer-native-h5-selection/1"}})
    return {PUBLIC: public, INPUT: public, TOKEN: token,
        SNAPSHOT: obj({"dataset_revision": STRING, "samples": array(public, minItems=1)}),
        CONTEXT: obj({"dataset_revision": STRING, "sample_count": {"type": "integer", "minimum": 1}}),
        OUTPUT: obj({"raw_text": {"type": "string"}, "evidence": OBJECT}),
        RESULT: obj({"raw_text": {"type": "string"}, "parsed_options": nullable(array(STRING)),
            "stage": {"enum": [1, 2, 3, 4]}, "reason": nullable(STRING),
            "parser_ref": {"const": PARSER_REF}}),
        OUTCOME: obj({"answer": STRING, "stage": {"enum": [1, 2, 3, 4]},
            "reference_status": {"const": "known"}}),
        ALIGNMENT: obj({"dataset_revision": STRING, "sample_id": token})}
