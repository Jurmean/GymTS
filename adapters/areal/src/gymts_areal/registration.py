"""Only new AReaL Candidate/evidence; Source, Task and Scorer stay replaceable."""
from gymts.contracts.schema import COMPONENT, OBJECT, STRING, obj
from gymts.plugin_support import component
from gymts_rl.contracts import INPUT, OUTPUT, PROTOCOL, rl_schemas
from .contracts import PARAMS, ROLLOUT, EVENT, SHARD, IDENTITY, TOKENIZER, TEMPLATE, REWARD_AUDIT, implementation_ref


def register_areal_plugins(registries, schemas):
    from .candidate import LiveTIRCandidate
    for ref, schema in rl_schemas().items():
        schemas.register(ref, schema)
    schemas.register(PARAMS, obj({"bridge_id": STRING, "policy_revision": STRING,
        "prompt_projection_ref": COMPONENT, "answer_codec_ref": COMPONENT,
        "model_ref": obj({"name": STRING, "version": STRING, "origin_ref": {"type": "null"}}),
        "native_revision": STRING}, required=["bridge_id", "policy_revision", "model_ref", "native_revision"]))
    for ref in (ROLLOUT, EVENT, SHARD, IDENTITY, TOKENIZER, TEMPLATE, REWARD_AUDIT):
        schemas.register(ref, OBJECT)
    item = {"component_ref": component("areal-live-tir"), "protocol_versions": ["gymts.candidate/1", PROTOCOL],
        "params_schema_ref": PARAMS, "origin_ref": None, "implementation_ref": implementation_ref(),
        "component_refs": [component("areal.TIRWorkflow", implementation_ref()["version"])],
        "supported_task_protocols": [PROTOCOL], "input_schema_refs": [INPUT], "output_schema_refs": [OUTPUT],
        "supports_fit": False, "fit_requires_targets": False, "supports_update": False,
        "model_revision_mode": "fixed", "capture_profiles": ["io", "native_rollout"],
        "execution_semantics": {"infer": "live_native_TIR_episode_inside_bound_Run",
            "training": "external_native_PPOTrainer_consumes_only_sealed_verified_rollout",
            "tool_scope": "calculator_only_current_input", "persistent_training_inside_candidate": False}}
    registries.candidates.register(item, LiveTIRCandidate)
