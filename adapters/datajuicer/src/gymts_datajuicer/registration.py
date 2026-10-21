"""Pure metadata registration; no upstream, datasets, torch or file access."""
from gymts.plugin_support import component
from . import contracts as c


def register(registries, schemas):
    from .candidate import NativePipelineCandidate
    from .runtime import SourceEnvironment, DerivationTask
    from .scoring import QualityScorer
    for reference, definition in c.schemas().items():
        schemas.register(reference, definition)
    def manifest(name, protocols, params=c.EMPTY):
        return {"component_ref": component(name), "protocol_versions": protocols,
                "params_schema_ref": params, "origin_ref": None}
    item = manifest("datajuicer-source", ["gymts.environment/1"], None)
    item.update(source_schema_ref="gymts.datajuicer/source/1", mapping_schema_ref=c.EMPTY, options_schema_ref=c.EMPTY)
    registries.environments.register(item, SourceEnvironment, describe=SourceEnvironment.describe_spec)
    item = manifest("datajuicer-derive", ["gymts.task/1", c.PROTOCOL])
    item.update(task_protocol_ref=c.PROTOCOL, input_schema_ref=c.PUBLIC, output_schema_ref=c.OUTPUT,
                result_schema_ref=c.RESULT, outcome_schema_ref=c.OUTCOME, alignment_schema_ref=c.ALIGNMENT)
    registries.tasks.register(item, DerivationTask, describe=DerivationTask.describe_spec,
                             compatibility=DerivationTask.compatibility)
    item = manifest("datajuicer-native", ["gymts.candidate/1", c.PROTOCOL], c.PARAMS)
    item.update(implementation_ref=component("gymts_datajuicer.candidate.NativePipelineCandidate", "0.1.0"),
        component_refs=[], supported_task_protocols=[c.PROTOCOL], input_schema_refs=[c.PUBLIC],
        output_schema_refs=[c.OUTPUT], supports_fit=False, fit_requires_targets=False,
        supports_update=False, model_revision_mode="fixed", capture_profiles=["io"])
    registries.candidates.register(item, NativePipelineCandidate)
    item = manifest("datajuicer-quality", ["gymts.scorer/1"])
    item.update(supported_task_protocols=[c.PROTOCOL], supported_alignment_matchings=["exact"],
        result_schema_refs=[c.RESULT], outcome_schema_refs=[c.OUTCOME], metrics={name: {
            "direction": "higher_better", "unit": "ratio", "requires_outcome": True,
            "eligibility_ref": component("frozen-training-source-pipeline/1"), "eligibility_schema_ref": c.ALIGNMENT}
            for name in c.METRICS})
    registries.scorers.register(item, QualityScorer)
