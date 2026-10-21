"""JSON-only declarations; no runtime dependency imports or file access."""
from gymts.contracts.schema import ARTIFACT, STRING, array, obj
from gymts.plugin_support import component
from .contracts import ALIGNMENT, INPUT, OUTPUT, RESULT, OUTCOME, PROTOCOL, domain_schemas


def register(registries, schemas):
    from .environment import ITFormerSnapshotEnvironment
    from .task import ITFormerTask
    from .candidate import ITFormerCandidate
    from .scoring import ReferenceScorer
    for name, schema in domain_schemas().items():
        schemas.register(name, schema)
    empty = "gymts.itformer/empty/1"
    schemas.register(empty, obj({}))
    schemas.register("gymts.itformer/source/1", obj({"kind": {"const": "dataset"}, "locator": STRING,
        "revision": STRING, "connection": obj({"artifact_refs": array(ARTIFACT, minItems=1, maxItems=1)}),
        "credential_ref": {"type": "null"}}))
    schemas.register("gymts.itformer/source-options/1", obj({"row_count": {"type": "integer", "minimum": 1}}))
    schemas.register("gymts.itformer/candidate-params/1", obj({"source_path": STRING, "checkpoint_path": STRING,
        "base_model_path": STRING, "device": {"enum": ["cpu", "cuda:0"]},
        "max_new_tokens": {"type": "integer", "minimum": 1, "maximum": 1024}}))
    schemas.register("gymts.itformer/scorer-params/1", obj({"expected_alignments":
        array(domain_schemas()[ALIGNMENT], minItems=1, uniqueItems=True)}))
    def manifest(name, protocols, params=None):
        return {"component_ref": component(name), "protocol_versions": protocols,
            "params_schema_ref": params, "origin_ref": None}
    item = manifest("itformer-snapshot", ["gymts.environment/1"])
    item.update(source_schema_ref="gymts.itformer/source/1", mapping_schema_ref=empty,
        options_schema_ref="gymts.itformer/source-options/1")
    registries.environments.register(item, ITFormerSnapshotEnvironment, describe=ITFormerSnapshotEnvironment.describe_spec)
    item = manifest("itformer-qa", ["gymts.task/1", PROTOCOL], empty)
    item.update(task_protocol_ref=PROTOCOL, input_schema_ref=INPUT, output_schema_ref=OUTPUT,
        result_schema_ref=RESULT, outcome_schema_ref=OUTCOME, alignment_schema_ref=ALIGNMENT)
    registries.tasks.register(item, ITFormerTask, describe=ITFormerTask.describe_spec, compatibility=ITFormerTask.compatibility)
    item = manifest("itformer-native", ["gymts.candidate/1", PROTOCOL], "gymts.itformer/candidate-params/1")
    item.update(implementation_ref=component("gymts_itformer.candidate.ITFormerCandidate", "0.1.0"),
        component_refs=[component("itformer-native-codec")], supported_task_protocols=[PROTOCOL],
        input_schema_refs=[INPUT], output_schema_refs=[OUTPUT], supports_fit=False, fit_requires_targets=False,
        supports_update=False, model_revision_mode="fixed", capture_profiles=["io"])
    registries.candidates.register(item, ITFormerCandidate)
    item = manifest("itformer-reference", ["gymts.scorer/1"], "gymts.itformer/scorer-params/1")
    item.update(supported_task_protocols=[PROTOCOL], supported_alignment_matchings=["exact"],
        result_schema_refs=[RESULT], outcome_schema_refs=[OUTCOME], metrics={metric: {
            "direction": "higher_better", "unit": "ratio", "requires_outcome": metric != "format_valid",
            "eligibility_ref": component("one-planned-enginemt-qa"), "eligibility_schema_ref": ALIGNMENT}
            for metric in ("answer_exact_match", "lexical_token_f1", "format_valid")})
    registries.scorers.register(item, ReferenceScorer)
