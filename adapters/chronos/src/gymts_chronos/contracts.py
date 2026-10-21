"""Distribution forecast semantics live outside the GymTS framework."""
import copy
import math
from datetime import datetime

from gymts.plugin_support import fail

PROTOCOL = "gymts.task/forecast-distribution/1"
INPUT = "gymts.forecast-distribution/input/1"
OUTPUT = "gymts.forecast-distribution/output/1"
RESULT = "gymts.forecast-distribution/result/1"
OUTCOME = "gymts.forecast-distribution/outcome/1"
PARSER = "forecast-distribution.strict-json/1"
METRICS = ("mae", "rmse", "pinball", "coverage_80", "width_80")
UPSTREAM = "1224fafa91e1ecd6674f5204066b159e40b5e4a1"
PIPELINE_SHA256 = "9fad1e4fb7251471463a40408a32d25d31b23b7afb88069911f095071b9b0599"


def _finite(values, length):
    return (isinstance(values, list) and len(values) == length and
            all(type(x) in (int, float) and math.isfinite(x) for x in values))


def validate_input(value):
    if set(value) != {"series", "context"}:
        fail("schema_mismatch", "Forecast input contains unexpected fields")
    series, context = value["series"], value["context"]
    allowed = {"horizon", "targets", "quantiles", "timestamps", "future_timestamps", "future_covariates"}
    if set(context) != allowed or not series:
        fail("schema_mismatch", "Forecast context must explicitly declare targets, times and covariates")
    h, levels = context["horizon"], context["quantiles"]
    if type(h) is not int or not 1 <= h <= 512:
        fail("invalid_request", "Horizon must be an integer in [1,512]")
    if (not isinstance(levels, list) or levels != sorted(set(levels)) or
            not all(type(q) in (int, float) and 0 < q < 1 for q in levels) or
            not {0.1, 0.5, 0.9}.issubset(levels)):
        fail("invalid_request", "Quantiles must be increasing and include .1, .5, .9")
    names = [s["name"] for s in series]
    if len(set(names)) != len(names) or not context["targets"] or len(set(context["targets"])) != len(context["targets"]):
        fail("invalid_request", "Series and target names must be unique")
    if set(context["targets"]) - set(names):
        fail("invalid_request", "Forecast target is absent from the historical input")
    n = len(series[0]["values"])
    if n < 2 or any(not _finite(s["values"], n) for s in series):
        fail("invalid_request", "All historical series must have aligned finite values")
    ts, future = context["timestamps"], context["future_timestamps"]
    if len(ts) != n or len(future) != h:
        fail("invalid_request", "Timestamps do not match the historical and future grids")
    points = [datetime.fromisoformat(t) for t in ts + future]
    delta = points[1] - points[0]
    if delta.total_seconds() <= 0 or any(b-a != delta for a, b in zip(points, points[1:])):
        fail("invalid_request", "Forecast requires one regular increasing timestamp grid")
    by_name = {s["name"]: s["values"] for s in series}
    # Initial delivered profile supports provably known calendar covariates.
    # Arbitrary user assertions of availability cannot expose future targets.
    for name, values in context["future_covariates"].items():
        if name not in {"calendar_hour", "calendar_weekday"} or name in context["targets"] or name not in by_name:
            fail("permission_denied", "Only explicitly derived calendar covariates may be known in the future")
        attribute = "hour" if name == "calendar_hour" else "weekday"
        def calendar(t):
            v = getattr(datetime.fromisoformat(t), attribute)
            return v() if callable(v) else v
        if values != [calendar(t) for t in future] or by_name[name] != [calendar(t) for t in ts]:
            fail("permission_denied", "Calendar covariate differs from the declared timestamp grid")
    return copy.deepcopy(value)


def validate_prediction(value, context):
    if not isinstance(value, dict) or set(value) != {"targets"} or not isinstance(value["targets"], dict):
        raise ValueError("Prediction must contain exactly the target mapping")
    if set(value["targets"]) != set(context["targets"]):
        raise ValueError("Prediction targets differ from the task")
    keys = {str(float(q)) for q in context["quantiles"]}
    for item in value["targets"].values():
        if not isinstance(item, dict) or set(item) != {"mean", "quantiles"}:
            raise ValueError("Forecast must contain point and quantile predictions")
        if not _finite(item["mean"], context["horizon"]) or set(item["quantiles"]) != keys:
            raise ValueError("Forecast shape or quantile levels differ from the task")
        if any(not _finite(xs, context["horizon"]) for xs in item["quantiles"].values()):
            raise ValueError("Quantiles require exact finite forecast horizons")
        for i in range(context["horizon"]):
            values = [item["quantiles"][str(float(q))][i] for q in context["quantiles"]]
            if values != sorted(values):
                raise ValueError("Quantile crossing")
    return value


def native_inputs(value):
    value = validate_input(value)
    by_name = {s["name"]: s["values"] for s in value["series"]}
    c = value["context"]
    return [{"target": [by_name[n] for n in c["targets"]],
             "past_covariates": {k: v for k, v in by_name.items() if k not in c["targets"]},
             "future_covariates": copy.deepcopy(c["future_covariates"])}]
