"""Per-unit MAE scorer, with the denominator fixed before outcome matching."""

import math

from gymts.contracts import canonical_json
from ._common import fail, unpack


def _records(value):
    if isinstance(value, list):
        return value
    for key in ("records", "results", "outcomes", "items"):
        if key in value:
            return value[key]
    fail("schema_mismatch", "Scoring snapshot must contain a records list", "score")


class ForecastMAEScorer:
    def __init__(self, spec):
        self.spec = spec

    def validate_scoring(self, scoring):
        if scoring["alignment"]["matching"] != "exact":
            fail("unsupported_capability", "The reference MAE scorer supports exact matching only", "validate_scoring")

    def score(self, results, outcomes, context):
        services = context["services"]
        result_records = _records(services.read_json(results["records_ref"]))
        outcome_records = _records(services.read_json(outcomes["records_ref"]))
        scoring = context["scoring"]
        alignment = scoring["alignment"]
        self.validate_scoring(scoring)
        keys = alignment["keys"]

        def match_key(item):
            try:
                return canonical_json({key: item["alignment_key"][key] for key in keys})
            except KeyError:
                fail("schema_mismatch", "Alignment key is missing a declared matching field", "score")

        matched = {}
        for outcome in outcome_records:
            if "evaluation" not in outcome.get("allowed_uses", []):
                fail("permission_denied", "Outcome is not authorized for evaluation", "score")
            key = match_key(outcome)
            prior = matched.get(key)
            if prior is not None:
                if alignment["duplicate_policy"] == "error":
                    fail("scorer_failure", "Duplicate outcome for an exact alignment key", "score")
                ordering = lambda item: (item["available_at"], item["recorded_at"])
                if ordering(prior) == ordering(outcome):
                    fail("conflict", "Latest outcome has ambiguous availability/commit timestamps", "score")
                if ordering(prior) > ordering(outcome):
                    continue
            matched[key] = outcome
        counts = {"eligible": len(result_records), "scored": 0, "missing": 0, "invalid": 0, "excluded": 0}
        errors = []
        item_scores = []
        for result in result_records:
            if result["status"] != "valid":
                counts["invalid"] += 1
                continue
            value = unpack(result["payload"], services).get("prediction")
            if value is None or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                counts["invalid"] += 1
                continue
            outcome = matched.get(match_key(result))
            if outcome is None:
                counts["missing"] += 1
                continue
            truth = unpack(outcome["payload"], services).get("value")
            if truth is None or isinstance(truth, bool) or not isinstance(truth, (int, float)) or not math.isfinite(truth):
                counts["invalid"] += 1
                continue
            error = abs(value - truth)
            counts["scored"] += 1
            errors.append(error)
            item_scores.append({"result_id": result["result_id"], "outcome_id": outcome["outcome_id"],
                                "outcome_revision": outcome["revision"], "absolute_error": error})
        # Statistical precondition only; AutoBenchTS applies the configured
        # evidence thresholds at the candidate/group/aggregate boundary.
        ready = bool(errors)
        metric = {"value": sum(errors) / len(errors) if ready else None,
                  "status": "ready" if ready else "insufficient_evidence", "counts": counts,
                  "reason": None if ready else "no_scored_items"}
        ref = services.save_json({"records": item_scores}, "gymts.builtin/forecast-item-scores/1")
        return {"metrics": {"mae": metric}, "item_scores_ref": ref, "diagnostics_ref": None}
