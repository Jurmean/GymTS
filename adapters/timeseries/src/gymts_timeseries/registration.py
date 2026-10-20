"""Register independent sources, domain tasks and scoring under public v1 roles."""
from gymts.contracts.schema import ARTIFACT, OBJECT, STRING, array, obj
from gymts.plugin_support import component

from .contracts import ALIGNMENT, INPUT, NATIVE, OUTCOME, OUTPUT, PROTOCOL, RESULT, TOKEN, domain_schemas


def register_timeseries_plugins(registries, schemas):
    from .environment import CSVNumericEnvironment, NumericSnapshotEnvironment
    from .task import TimeSeriesQATask, TASK_VERSIONS
    from .scoring import TimeSeriesQAScorer
    for ref, definition in domain_schemas().items():
        schemas.register(ref, definition)
    schemas.register("gymts.timeseries/source/1", obj({"kind": {"const": "dataset"}, "locator": STRING,
        "revision": STRING, "connection": obj({"artifact_refs": array(ARTIFACT, minItems=1, maxItems=1)}),
        "credential_ref": {"type": "null"}}))
    schemas.register("gymts.timeseries/empty/1", obj({}))
    schemas.register("gymts.timeseries/source-options/1", obj({
        "sample_tokens": array(TOKEN, minItems=1, uniqueItems=True)}))
    schemas.register("gymts.timeseries/csv-options/1", obj({
        "sample_tokens": array(TOKEN, minItems=1, uniqueItems=True), "context": OBJECT}))
    schemas.register("gymts.timeseries/task-params/1", obj({"task_id": {"enum": list(TASK_VERSIONS)},
        "task_version": STRING}))
    def manifest(name, protocols, params=None):
        return {"component_ref": component(name), "protocol_versions": protocols,
                "params_schema_ref": params, "origin_ref": None}
    for name, factory in (("numeric-snapshot", NumericSnapshotEnvironment), ("csv-numeric-snapshot", CSVNumericEnvironment)):
        item = manifest(name, ["gymts.environment/1"])
        item.update(source_schema_ref="gymts.timeseries/source/1", mapping_schema_ref="gymts.timeseries/empty/1",
                    options_schema_ref=("gymts.timeseries/csv-options/1" if name == "csv-numeric-snapshot"
                                        else "gymts.timeseries/source-options/1"))
        registries.environments.register(item, factory)
    item = manifest("timeseries-qa", ["gymts.task/1", PROTOCOL], "gymts.timeseries/task-params/1")
    item.update(task_protocol_ref=PROTOCOL, input_schema_ref=INPUT, output_schema_ref=OUTPUT,
                result_schema_ref=RESULT, outcome_schema_ref=OUTCOME, alignment_schema_ref=ALIGNMENT)
    registries.tasks.register(item, TimeSeriesQATask)
    item = manifest("timeseries-qa-scorer", ["gymts.scorer/1"], "gymts.timeseries/task-params/1")
    item.update(supported_task_protocols=[PROTOCOL], supported_alignment_matchings=["exact"],
        result_schema_refs=[RESULT], outcome_schema_refs=[OUTCOME], metrics={metric: {
            "direction": "lower_better" if metric in ("mae", "rmse") else "higher_better",
            "unit": "value" if metric in ("mae", "rmse") else "ratio", "requires_outcome": True,
            "eligibility_ref": component("one-planned-timeseries-sample"), "eligibility_schema_ref": ALIGNMENT}
            for metric in ("accuracy", "exact_match", "event_f1", "mae", "rmse")})
    registries.scorers.register(item, TimeSeriesQAScorer)
