"""Shared training evidence contracts; concrete dataset exporters are plugins.

The framework does not choose a task, episode mapping, row layout or trainer.
Project-specific exports are implemented by independently installed adapters.
"""
from gymts.contracts.schema import ARTIFACT, COMPONENT, OBJECT, PAYLOAD, STRING, array, nullable, obj

REWARD = "gymts.reward/1"


def register_training_schemas(schemas):
    """Register the formal v1 export messages without choosing a project or exporter profile."""
    tokenization = obj({"mode": {"enum": ["native_rollout", "reconstructed"]},
        "tokenizer_ref": nullable(ARTIFACT), "chat_template_ref": nullable(ARTIFACT),
        "mask_builder_ref": COMPONENT, "reconstructor_ref": nullable(COMPONENT),
        "logprob_policy": {"enum": ["captured", "recompute", "not_required"]},
        "recompute_policies": array(obj({"call_id": STRING, "attempt_id": STRING, "policy_ref": ARTIFACT,
            "computation_ref": COMPONENT, "distribution": {"enum": ["model", "sampling"]},
            "effective_params": OBJECT}))})
    schemas.register("gymts.record-snapshot/1", obj({"captured_at": STRING,
        "runs": array(obj({"run_id": STRING, "through_seq": {"type": "integer", "minimum": 0},
            "result_ref": nullable(ARTIFACT), "status": {"enum": ["running", "succeeded", "failed", "cancelled"]}})),
        "outcome_refs": array(obj({"outcome_id": STRING, "revision": STRING}))}))
    schemas.register("gymts.dataset-build/1", obj({"protocol_version": {"const": "gymts.dataset-build/1"},
        "build_id": STRING, "name": nullable(STRING), "builder_ref": COMPONENT,
        "input_snapshots": array(ARTIFACT, minItems=1),
        "target": obj({"format": {"enum": ["sft", "preference", "rl"]}, "schema_ref": STRING,
                       "backend_ref": nullable(COMPONENT)}),
        "selection": PAYLOAD, "episode_mapping": PAYLOAD, "splits": PAYLOAD,
        "transforms": array(obj({"component_ref": COMPONENT, "params": OBJECT})),
        "reward_mapping": nullable(obj({"mapper_ref": COMPONENT, "params": OBJECT,
                                        "source_refs": array(ARTIFACT)})),
        "pairing": nullable(PAYLOAD), "tokenization": nullable(tokenization),
        "missing_data_policy": {"enum": ["reject_build", "exclude_samples"]},
        "require_sealed_runs": {"type": "boolean"}}))
    schemas.register(REWARD, obj({"protocol_version": {"const": REWARD}, "reward_id": STRING,
        "target_refs": array(ARTIFACT, minItems=1), "granularity": {"enum": ["run", "episode", "case", "call", "token"]},
        "value": {"anyOf": [{"type": "number"}, array({"type": "number"})]},
        "source_refs": array(ARTIFACT, minItems=1), "mapper_ref": COMPONENT, "created_at": STRING}))
    schemas.register("gymts.lineage/1", obj({"protocol_version": {"const": "gymts.lineage/1"},
        "records": array(OBJECT)}))
    schemas.register("gymts.training/tokenization/1", tokenization)
    schemas.register("gymts.training/exclusions/1", obj({"counts": {"type": "object", "additionalProperties": {
        "type": "integer", "minimum": 0}}, "records": array(OBJECT)}))
    schemas.register("gymts.dataset/1", obj({"protocol_version": {"const": "gymts.dataset/1"},
        "dataset_id": STRING, "revision": STRING, "build_id": STRING, "build_spec_ref": ARTIFACT,
        "builder_ref": COMPONENT, "input_snapshot_refs": array(ARTIFACT), "output_schema_ref": STRING,
        "shards": array(obj({"split": STRING, "artifact_ref": ARTIFACT, "sample_count": {"type": "integer", "minimum": 0}})),
        "counts": obj({key: {"type": "integer", "minimum": 0} for key in
                       ("input_units", "accepted_samples", "excluded_units")}),
        "lineage_ref": ARTIFACT, "exclusion_summary_ref": ARTIFACT,
        "tokenization_ref": nullable(ARTIFACT), "reward_refs": array(ARTIFACT), "created_at": STRING}))

