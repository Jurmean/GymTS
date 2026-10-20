"""Public v1 contracts for prompt-only, verifiable QA rollouts."""

from gymts.contracts.schema import ARTIFACT, OBJECT, STRING, array, nullable, obj

PROTOCOL = "gymts.task/rl-verifiable-qa/1"
INPUT = "gymts.rl/input/1"
OUTPUT = "gymts.rl/output/1"
RESULT = "gymts.rl/result/1"
OUTCOME = "gymts.rl/outcome/1"
ALIGNMENT = "gymts.rl/alignment/1"
SNAPSHOT = "gymts.rl.snapshot/1"
NATIVE = INPUT
CONTEXT = "gymts.rl/context/1"
PARSER_REF = "gymts.rl.verifiable-parser/1"
PRIVATE = "gymts.rl.private/1"
MANIFEST = "gymts.rl.dataset-manifest/1"
SUMMARY_SCHEMA = obj({name: {"type": "number"} for name in ("mean", "min", "max", "last")})


def rl_schemas():
    sample = obj({"sample_id": STRING, "group_id": STRING, "dataset_id": STRING,
        "split": {"enum": ["train", "eval"]}, "task_id": {"enum": ["gsm8k.numeric", "chatts.numeric_summary"]},
        "messages": array(obj({"role": {"enum": ["system", "user", "assistant"]}, "content": STRING}), minItems=1),
        "timeseries": array(array({"type": "number"}, minItems=1)), "series_names": array(STRING),
        "output_schema": OBJECT, "context": OBJECT})
    return {
        "gymts.rl/sample-id/1": STRING,
        INPUT: sample,
        OUTPUT: obj({"raw_text": STRING, "evidence": OBJECT}),
        RESULT: obj({"raw_text": STRING, "parsed": nullable(OBJECT), "reason": nullable(STRING),
                     "parser_ref": {"const": PARSER_REF}, "sample_id": STRING, "task_id": STRING}),
        OUTCOME: obj({"sample_id": STRING, "task_id": STRING, "reward_spec": OBJECT}),
        ALIGNMENT: obj({"dataset_revision": STRING, "sample_id": STRING, "group_id": STRING}),
        SNAPSHOT: obj({"schema_version": {"const": SNAPSHOT}, "dataset_revision": STRING,
                      "samples": array(sample, minItems=1)}),
        CONTEXT: obj({"dataset_revision": STRING, "sample_count": {"type": "integer", "minimum": 1}}),
        "gymts.rl/source/1": obj({"kind": {"const": "dataset"}, "locator": STRING, "revision": STRING,
            "connection": obj({"artifact_refs": array(ARTIFACT, minItems=1, maxItems=1)}),
            "credential_ref": {"type": "null"}}),
        "gymts.rl/empty/1": obj({}),
        "gymts.rl/options/1": obj({"sample_ids": array(STRING, minItems=1, uniqueItems=True)}),
    }
