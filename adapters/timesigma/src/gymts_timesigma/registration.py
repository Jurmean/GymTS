"""Opt-in registration against GymTS interface specification 1.2.0."""

from gymts.plugin_support import component


def _manifest(name, protocols, params):
    return {"component_ref": component(name), "protocol_versions": protocols,
            "params_schema_ref": params, "origin_ref": None}


def register_timesigma_plugins(registries, schemas):
    from .contracts import (PROTOCOL, SOURCE, EMPTY, TASK_PARAMS, INPUT, OUTPUT, RESULT,
                            OUTCOME, ALIGNMENT, timesigma_schemas)
    from .environment import TimeSigmaSnapshotEnvironment
    from .task import TimeSigmaTask
    from .candidate import TimeSigmaCandidate, PARAMS, candidate_schemas
    from .scoring import (TimeSigmaOfficialScorer, SCORER_PARAMS_REF, METRIC_IDS, scorer_schemas)
    for definitions in (timesigma_schemas(), candidate_schemas(), scorer_schemas()):
        for ref, definition in definitions.items():
            schemas.register(ref, definition)
    item = _manifest("timesigma-snapshot", ["gymts.environment/1"], None)
    item.update(source_schema_ref=SOURCE, mapping_schema_ref=EMPTY, options_schema_ref=EMPTY)
    registries.environments.register(item, TimeSigmaSnapshotEnvironment)
    item = _manifest("timesigma-tsad", ["gymts.task/1", PROTOCOL], TASK_PARAMS)
    item.update(task_protocol_ref=PROTOCOL, input_schema_ref=INPUT, output_schema_ref=OUTPUT,
                result_schema_ref=RESULT, outcome_schema_ref=OUTCOME, alignment_schema_ref=ALIGNMENT)
    registries.tasks.register(item, TimeSigmaTask)
    item = _manifest("timesigma-native", ["gymts.candidate/1", PROTOCOL], PARAMS)
    item.update(implementation_ref=component("timesigma-native"), component_refs=[],
                supported_task_protocols=[PROTOCOL], input_schema_refs=[INPUT], output_schema_refs=[OUTPUT],
                supports_fit=True, fit_requires_targets=False, supports_update=False,
                model_revision_mode="fixed", capture_profiles=[])
    registries.candidates.register(item, TimeSigmaCandidate)
    item = _manifest("timesigma-official", ["gymts.scorer/1"], SCORER_PARAMS_REF)
    item.update(supported_task_protocols=[PROTOCOL], supported_alignment_matchings=["exact"],
                result_schema_refs=[RESULT], outcome_schema_refs=[OUTCOME],
                metrics={metric: {"direction": "higher_better", "unit": "ratio", "requires_outcome": True,
                    "eligibility_ref": component("timesigma.planned-evaluation-curves"),
                    "eligibility_schema_ref": "gymts.timesigma/curve-eligibility/1"} for metric in METRIC_IDS})
    registries.scorers.register(item, TimeSigmaOfficialScorer)
