"""Explicit optional RL registration; no model library is imported here."""

from gymts.plugin_support import component


def _manifest(name, protocols, params):
    return {"component_ref": component(name), "protocol_versions": protocols,
            "params_schema_ref": params, "origin_ref": None}


def register_rl_plugins(registries, schemas):
    from .contracts import ALIGNMENT, INPUT, OUTCOME, OUTPUT, PROTOCOL, RESULT, rl_schemas
    from .environment import RLQASnapshotEnvironment
    from .task import RLVerifiableQATask
    from .scoring import RLQAScorer
    from .candidate import LocalHFCandidate, PARAMS, candidate_schemas
    for definitions in (rl_schemas(), candidate_schemas()):
        for reference, definition in definitions.items():
            schemas.register(reference, definition)
    item = _manifest("rl-qa-snapshot", ["gymts.environment/1"], None)
    item.update(source_schema_ref="gymts.rl/source/1", mapping_schema_ref="gymts.rl/empty/1",
                options_schema_ref="gymts.rl/options/1")
    registries.environments.register(item, RLQASnapshotEnvironment)
    item = _manifest("rl-verifiable-qa", ["gymts.task/1", PROTOCOL], "gymts.rl/empty/1")
    item.update(task_protocol_ref=PROTOCOL, input_schema_ref=INPUT, output_schema_ref=OUTPUT,
                result_schema_ref=RESULT, outcome_schema_ref=OUTCOME, alignment_schema_ref=ALIGNMENT)
    registries.tasks.register(item, RLVerifiableQATask)
    item = _manifest("rl-local-hf", ["gymts.candidate/1", PROTOCOL], PARAMS)
    item.update(implementation_ref=component("rl-local-hf"), component_refs=[],
                supported_task_protocols=[PROTOCOL], input_schema_refs=[INPUT], output_schema_refs=[OUTPUT],
                supports_fit=False, fit_requires_targets=False, supports_update=False, model_revision_mode="fixed",
                capture_profiles=["io", "native_rollout"])
    registries.candidates.register(item, LocalHFCandidate, compatibility=LocalHFCandidate.compatibility)
    item = _manifest("rl-qa-scorer", ["gymts.scorer/1"], "gymts.rl/empty/1")
    item.update(supported_task_protocols=[PROTOCOL], supported_alignment_matchings=["exact"],
        result_schema_refs=[RESULT], outcome_schema_refs=[OUTCOME],
        metrics={name: {"direction": "higher_better", "unit": "ratio", "requires_outcome": name == "accuracy",
            "eligibility_ref": component("one-captured-rl-qa-case"), "eligibility_schema_ref": ALIGNMENT}
            for name in ("accuracy", "format_valid")})
    registries.scorers.register(item, RLQAScorer)


__all__ = ["register_rl_plugins"]
