"""Register LibraryTS implementations; tasks/sources belong to the domain package."""
from gymts.contracts.schema import OBJECT, STRING, obj
from gymts.plugin_support import component
from gymts_timeseries.contracts import ALIGNMENT, INPUT, OUTCOME, OUTPUT, PROTOCOL, RESULT, domain_schemas
from .source import implementation_ref, tool_ref

PARAMS = "gymts.libraryts/qa-params/1"
SCORER_PARAMS = "gymts.libraryts/forecast-scorer-params/1"


def register_libraryts_plugins(registries, schemas):
    from .candidate import LibraryTSQACandidate
    from .scoring import LibraryTSForecastScorer
    for ref, definition in domain_schemas().items():
        schemas.register(ref, definition)
    implementation = obj({"repository": STRING, "revision": STRING, "python": STRING}, required=["repository"])
    timeout = {"type": "number", "exclusiveMinimum": 0}
    schemas.register(PARAMS, obj({"implementation": implementation,
        "estimator": {"enum": ["naive", "polynomial"]}, "estimator_params": OBJECT,
        "timeout_seconds": timeout, "trend_tolerance": {"type": "number", "minimum": 0}}, required=["implementation"]))
    schemas.register(SCORER_PARAMS, obj({"implementation": implementation, "task_id": {"const": "forecast.numeric"},
        "task_version": STRING, "timeout_seconds": timeout}, required=["implementation", "task_id", "task_version"]))
    for ref in ("tool-request", "tool-response", "algorithm-identity", "dataset-holdout", "source-provenance"):
        schemas.register("gymts.libraryts/" + ref + "/1", OBJECT)
    item = {"component_ref": component("libraryts-qa"), "protocol_versions": ["gymts.candidate/1", PROTOCOL],
        "params_schema_ref": PARAMS, "origin_ref": None,
        "implementation_ref": implementation_ref("sktime"),
        "component_refs": [tool_ref("forecast.naive"), tool_ref("forecast.polynomial")],
        "supported_task_protocols": [PROTOCOL], "input_schema_refs": [INPUT], "output_schema_refs": [OUTPUT],
        "supports_fit": False, "fit_requires_targets": False, "supports_update": False,
        "model_revision_mode": "fixed", "capture_profiles": ["io"],
        "execution_semantics": {"prepare": "stateless_algorithm_configuration",
            "infer": "fresh_native_fit_on_current_authorized_input",
            "persistent_training": False, "cross_call_state": False}}
    registries.candidates.register(item, LibraryTSQACandidate)
    item = {"component_ref": component("libraryts-forecast-scorer"), "protocol_versions": ["gymts.scorer/1"],
        "params_schema_ref": SCORER_PARAMS, "origin_ref": None,
        "supported_task_protocols": [PROTOCOL], "supported_alignment_matchings": ["exact"],
        "result_schema_refs": [RESULT], "outcome_schema_refs": [OUTCOME],
        "metrics": {metric: {"direction": "lower_better", "unit": "value", "requires_outcome": True,
            "eligibility_ref": component("one-planned-timeseries-sample"), "eligibility_schema_ref": ALIGNMENT}
            for metric in ("mae", "rmse")}}
    registries.scorers.register(item, LibraryTSForecastScorer)
