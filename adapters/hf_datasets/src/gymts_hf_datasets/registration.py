"""Public extension points only; enabling this integration does not load HF."""
from gymts.plugin_support import component
from . import contracts as c


def register(registries, schemas):
    from .runtime import ForecastTask, LastValueCandidate, ReferenceMAE, StaticEnvironment
    from .benchmark import StaticBenchmarkResolver
    for reference, definition in c.schemas().items():
        schemas.register(reference, definition)
    def manifest(name, protocols, params="gymts.hf-static/empty/1"):
        return {"component_ref": component(name), "protocol_versions": protocols,
                "params_schema_ref": params, "origin_ref": None}
    item = manifest("hf-static-snapshot", ["gymts.environment/1"], None)
    item.update(source_schema_ref="gymts.hf-static/source/1", mapping_schema_ref="gymts.hf-static/empty/1",
                options_schema_ref="gymts.hf-static/empty/1")
    registries.environments.register(item, StaticEnvironment, describe=StaticEnvironment.describe_spec)
    item = manifest("hf-static-forecast", ["gymts.task/1", c.PROTOCOL])
    item.update(task_protocol_ref=c.PROTOCOL, input_schema_ref=c.PUBLIC, output_schema_ref=c.OUTPUT,
                result_schema_ref=c.RESULT, outcome_schema_ref=c.OUTCOME, alignment_schema_ref=c.ALIGNMENT)
    registries.tasks.register(item, ForecastTask, describe=ForecastTask.describe_spec, compatibility=ForecastTask.compatibility)
    item = manifest("hf-static-last-value", ["gymts.candidate/1", c.PROTOCOL])
    item.update(implementation_ref=component("gymts_hf_datasets.runtime.LastValueCandidate", "0.1.0"),
                component_refs=[], supported_task_protocols=[c.PROTOCOL], input_schema_refs=[c.PUBLIC],
                output_schema_refs=[c.OUTPUT], supports_fit=False, fit_requires_targets=False,
                supports_update=False, model_revision_mode="fixed", capture_profiles=[])
    registries.candidates.register(item, LastValueCandidate)
    item = manifest("hf-static-reference-mae", ["gymts.scorer/1"])
    item.update(supported_task_protocols=[c.PROTOCOL], supported_alignment_matchings=["exact"],
        result_schema_refs=[c.RESULT], outcome_schema_refs=[c.OUTCOME], metrics={"mae": {
            "direction": "lower_better", "unit": "value", "requires_outcome": True,
            "eligibility_ref": component("one-frozen-source-row"), "eligibility_schema_ref": c.ALIGNMENT}})
    registries.scorers.register(item, ReferenceMAE)
    registries.benchmarks.register(c.RESOLVER_REF, StaticBenchmarkResolver())
