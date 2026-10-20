"""Reuse neutral QA evidence rules, then compute ready forecast metrics natively."""
import copy

from gymts.contracts import GymTSError
from gymts.plugin_support import unpack
from gymts_timeseries.scoring import TimeSeriesQAScorer
from .tools import LibraryTSTools


def _rows(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and isinstance(value.get("records"), list):
        return value["records"]
    raise GymTSError("schema_mismatch", "LibraryTS scoring requires fixed record lists")


class LibraryTSForecastScorer:
    def __init__(self, spec):
        self.params = copy.deepcopy(spec.get("params", {}))
        if self.params.get("task_id") != "forecast.numeric":
            raise GymTSError("unsupported_capability", "LibraryTS native metric scorer supports forecast.numeric")
        self.base = TimeSeriesQAScorer({"params": {key: self.params[key] for key in ("task_id", "task_version")}})

    def validate_scoring(self, scoring):
        self.base.validate_scoring(scoring)
        if any(metric not in ("mae", "rmse") for metric in scoring["metrics"]):
            raise GymTSError("unsupported_capability", "LibraryTS native forecast scorer exposes MAE/RMSE")

    def score(self, results, outcomes, context):
        self.validate_scoring(context["scoring"])
        # Existing public domain scorer owns alignment, parser checks, shape,
        # allowed_uses and eligible/missing/invalid counts. Native calls below
        # consume only its ready matched result/outcome identities.
        scored = self.base.score(results, outcomes, context)
        services = context["services"]
        rows = {row["result_id"]: row for row in _rows(services.read_json(results["records_ref"]))}
        gold = {(row["outcome_id"], row["revision"]): row
                for row in _rows(services.read_json(outcomes["records_ref"]))}
        diagnostics = services.read_json(scored["item_scores_ref"])["records"]
        tools = LibraryTSTools(services, self.params["implementation"],
                               timeout_seconds=self.params.get("timeout_seconds", 120))
        native_calls = []
        for item in diagnostics:
            metric = item["metric_id"]
            if scored["metrics"][metric]["status"] != "ready":
                continue
            prediction = unpack(rows[item["result_id"]]["payload"], services)["parsed"]["forecast"]
            target = unpack(gold[(item["outcome_id"], item["outcome_revision"])]["payload"], services)["expected_output"]["forecast"]
            call = tools.call("labts.metrics", {"task": "forecasting", "metrics": [metric],
                "context": {"values": target, "predictions": prediction}})
            value = call["output"]["metrics"][metric]
            scored["metrics"][metric]["value"] = value
            item["value"], item["native_call_ref"] = value, call["call_ref"]
            native_calls.append(call["call_ref"])
        scored["item_scores_ref"] = services.save_json({"records": diagnostics}, "gymts.json/1")
        scored["diagnostics_ref"] = services.save_json({"native_metric_calls": native_calls,
            "eligibility": "one planned neutral QA sample, independent of match availability"}, "gymts.json/1")
        return scored
