"""Versioned reference plugins. Importing the package does not mutate registries."""

from ._common import component
from .counter import CounterControlTask, CounterTransition, IncrementPolicy
from .forecast import ForecastCandidate, WindowForecastTask
from .replay import TimeSeriesReplay
from .scoring import ForecastMAEScorer


def obj(properties, required=None, extra=False):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required, "additionalProperties": extra}


def array(items):
    return {"type": "array", "items": items}


STRING = {"type": "string"}
NUMBER = {"type": "number"}
INTEGER = {"type": "integer"}
NULL_STRING = {"type": ["string", "null"]}
NULL_NUMBER = {"type": ["number", "null"]}
EMPTY = obj({})
PARAMS = "gymts.builtin/forecast-params/1"
SOURCE = "gymts.builtin/replay-source/1"
MAPPING = "gymts.builtin/replay-mapping/1"
OPTIONS = "gymts.builtin/replay-options/1"


def schemas():
    """Return fresh schema objects; all plugin payload and configuration boundaries are declared."""
    forecast_value = obj({"prediction": NULL_NUMBER, "reason": NULL_STRING})
    point = obj({"timestamp": STRING, "available_at": STRING, "entity": STRING,
                 "values": {"type": "object", "additionalProperties": NULL_NUMBER}},
                required=["timestamp", "values"])
    return {
        "gymts.builtin/scalar/1": NUMBER,
        "gymts.builtin/empty/1": EMPTY,
        "gymts.builtin/replay-context/1": obj({"availability": STRING, "entity": STRING}),
        SOURCE: obj({"kind": {"enum": ["dataset", "generator"]}, "locator": STRING,
                     "revision": STRING, "credential_ref": {"type": "null"},
                     "connection": obj({"points": array(point), "generator": obj({
                         "start": STRING, "period": STRING, "length": {"type": "integer", "minimum": 1},
                         "start_value": NUMBER, "delta": NUMBER})}, required=[])}),
        MAPPING: obj({"variables": {"type": "object", "additionalProperties": obj({
            "field": STRING, "dtype": {"enum": ["float64"]}, "unit": STRING})}}),
        OPTIONS: obj({"availability": {"enum": ["event_time", "explicit"]},
                      "entity": STRING, "source_period": STRING}, required=["availability"]),
        PARAMS: obj({"variable": STRING, "unit": {"enum": ["value"]}, "entity": STRING,
                     "window_points": {"type": "integer", "minimum": 1},
                     "horizon": STRING, "advance_by": STRING, "warmup_duration": NULL_STRING},
                    required=["variable", "unit", "entity", "window_points", "horizon", "advance_by"]),
        "gymts.builtin/forecast-input/1": obj({"entity": STRING, "variable": STRING, "unit": STRING,
            "timestamps": array(STRING), "values": array(NULL_NUMBER),
            "valid_mask": array({"type": "boolean"}), "target_time": STRING}),
        "gymts.builtin/forecast-output/1": forecast_value,
        "gymts.builtin/forecast-result/1": forecast_value,
        "gymts.builtin/forecast-outcome/1": obj({"value": NUMBER}),
        "gymts.builtin/forecast-alignment/1": obj({"entity": STRING, "variable": STRING,
                                                   "issued_at": STRING, "target_time": STRING}),
        "gymts.builtin/forecast-item-scores/1": obj({"records": array(obj({
            "result_id": STRING, "outcome_id": STRING, "outcome_revision": STRING, "absolute_error": NUMBER}))}),
        "gymts.builtin/counter-source/1": obj({"kind": {"enum": ["simulator"]}, "locator": STRING,
            "revision": STRING, "connection": EMPTY, "credential_ref": {"type": "null"}}),
        "gymts.builtin/counter-options/1": obj({"max_steps": {"type": "integer", "minimum": 1}}),
        "gymts.builtin/counter-state/1": obj({"step": {"type": "integer", "minimum": 0}, "value": INTEGER}),
        "gymts.builtin/counter-input/1": obj({"step": {"type": "integer", "minimum": 0}, "value": INTEGER}),
        "gymts.builtin/increment-arguments/1": obj({"amount": {"type": "integer", "minimum": 1}}),
        "gymts.builtin/counter-output/1": obj({"amount": {"type": "integer", "minimum": 1}}),
        "gymts.builtin/counter-result/1": obj({"requested_amount": {"type": "integer", "minimum": 1}}),
        "gymts.builtin/counter-alignment/1": obj({"step": {"type": "integer", "minimum": 0}}),
    }


def manifest(name, protocols, params):
    return {"component_ref": component(name), "protocol_versions": protocols,
            "params_schema_ref": params, "origin_ref": None}


def candidate_manifest(name, protocol, input_schema, output_schema):
    item = manifest(name, ["gymts.candidate/1", protocol], "gymts.builtin/empty/1")
    item.update(implementation_ref=component(name), component_refs=[], supported_task_protocols=[protocol],
                input_schema_refs=[input_schema], output_schema_refs=[output_schema], supports_fit=False,
                fit_requires_targets=False, supports_update=False, model_revision_mode="none", capture_profiles=[])
    return item


def last_value_factory(spec):
    return ForecastCandidate(spec, "last")


def window_mean_factory(spec):
    return ForecastCandidate(spec, "mean")


def register_builtin_plugins(registries, schema_registry):
    """Register deterministic examples; production sources/models are separate plugins."""
    for ref, schema in schemas().items():
        schema_registry.register(ref, schema)
    item = manifest("local-timeseries-replay", ["gymts.environment/1"], None)
    item.update(source_schema_ref=SOURCE, mapping_schema_ref=MAPPING, options_schema_ref=OPTIONS)
    registries.environments.register(item, TimeSeriesReplay)
    item = manifest("counter-transition", ["gymts.environment/1"], None)
    item.update(source_schema_ref="gymts.builtin/counter-source/1", mapping_schema_ref="gymts.builtin/empty/1",
                options_schema_ref="gymts.builtin/counter-options/1")
    registries.environments.register(item, CounterTransition)
    for name, protocol, prefix, params, factory in (
        ("window_forecast", "gymts.task/forecast/1", "forecast", PARAMS, WindowForecastTask),
        ("counter_control", "gymts.task/counter-control/1", "counter", "gymts.builtin/empty/1", CounterControlTask),
    ):
        item = manifest(name, ["gymts.task/1", protocol], params)
        item.update(task_protocol_ref=protocol, input_schema_ref="gymts.builtin/" + prefix + "-input/1",
            output_schema_ref="gymts.builtin/" + prefix + "-output/1",
            result_schema_ref="gymts.builtin/" + prefix + "-result/1",
            outcome_schema_ref="gymts.builtin/forecast-outcome/1" if prefix == "forecast" else None,
            alignment_schema_ref="gymts.builtin/" + prefix + "-alignment/1")
        registries.tasks.register(item, factory)
    for name, factory in (("last-value", last_value_factory), ("window-mean", window_mean_factory)):
        item = candidate_manifest(name, "gymts.task/forecast/1", "gymts.builtin/forecast-input/1", "gymts.builtin/forecast-output/1")
        registries.candidates.register(item, factory)
    item = candidate_manifest("increment-policy", "gymts.task/counter-control/1", "gymts.builtin/counter-input/1", "gymts.builtin/counter-output/1")
    item["params_schema_ref"] = "gymts.builtin/increment-arguments/1"
    registries.candidates.register(item, IncrementPolicy)
    item = manifest("forecast-mae", ["gymts.scorer/1"], "gymts.builtin/empty/1")
    item.update(supported_task_protocols=["gymts.task/forecast/1"],
        supported_alignment_matchings=["exact"],
        result_schema_refs=["gymts.builtin/forecast-result/1"], outcome_schema_refs=["gymts.builtin/forecast-outcome/1"],
        metrics={"mae": {"direction": "lower_better", "unit": "value", "requires_outcome": True,
            "eligibility_ref": component("one-task-result-one-forecast"),
            "eligibility_schema_ref": "gymts.builtin/forecast-alignment/1"}})
    registries.scorers.register(item, ForecastMAEScorer)


__all__ = ["register_builtin_plugins", "TimeSeriesReplay", "WindowForecastTask", "ForecastCandidate",
           "ForecastMAEScorer", "CounterTransition", "CounterControlTask", "IncrementPolicy"]
