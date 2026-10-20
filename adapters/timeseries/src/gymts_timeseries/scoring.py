"""One-sample QA scorer with exact alignment and separate evidence counts.

Metric semantics follow ChatTS-Bench-new 0.1.0 implementations in
``plugins/metrics/{classification/accuracy,classification/exact_match,
anomaly/event_f1,forecast/mae,forecast/rmse}/metric.py``: type-sensitive JSON
comparison, one-to-one event matching, and shape-strict numeric errors.  This
small stdlib port avoids installing the source benchmark as a runtime engine.
"""

import math

from gymts.contracts import canonical_json, parse_time
from gymts.plugin_support import fail, unpack
from .semantics import PARSER_REF, TASK_METRICS, answer_semantic_reason, validate_task_params


def _records(value):
    if isinstance(value, list):
        return value
    for key in ("records", "results", "outcomes", "items"):
        if key in value and isinstance(value[key], list):
            return value[key]
    fail("schema_mismatch", "QA snapshot must contain a records list", "score")


def _event_f1(predicted, target):
    if not predicted and not target:
        return 1.0
    # The frozen source task uses tolerance=0.  Matching never consumes one
    # prediction twice; sorted indices are checked before this function.
    i = j = true_positive = 0
    while i < len(predicted) and j < len(target):
        if predicted[i] < target[j]:
            i += 1
        elif target[j] < predicted[i]:
            j += 1
        else:
            i += 1
            j += 1
            true_positive += 1
    return 2 * true_positive / (len(predicted) + len(target))


def point_metric(task_id, metric, prediction, expected):
    """Return (finite scalar or None, reason or None) without answer repair."""
    reason = answer_semantic_reason(task_id, expected)
    if reason:
        return None, "invalid_expected_output:" + reason
    reason = answer_semantic_reason(task_id, prediction, expected=expected)
    if reason:
        return None, reason
    if metric == "accuracy":
        key = {"pattern.trend_direction": "trend_direction", "pattern.seasonality_profile": "profile",
               "process.stationarity_type": "type", "similarity.shape_retrieval": "candidate_id"}[task_id]
        return float(canonical_json(prediction[key]) == canonical_json(expected[key])), None
    if metric == "exact_match":
        return float(canonical_json(prediction) == canonical_json(expected)), None
    if metric == "event_f1":
        return _event_f1(prediction["indices"], expected["indices"]), None
    if metric in ("mae", "rmse"):
        pairs = list(zip(prediction["forecast"], expected["forecast"]))
        try:
            value = (math.fsum(abs(a - b) for a, b in pairs) / len(pairs) if metric == "mae"
                     else math.sqrt(math.fsum((a - b) ** 2 for a, b in pairs) / len(pairs)))
        except (OverflowError, ValueError):
            return None, "non_finite_result"
        return (value, None) if math.isfinite(value) else (None, "non_finite_result")
    fail("unsupported_capability", "Unsupported QA metric", "score")


class TimeSeriesQAScorer:
    def __init__(self, spec):
        self.params = validate_task_params(spec)

    def validate_scoring(self, scoring):
        alignment = scoring["alignment"]
        if (alignment["matching"] != "exact" or len(alignment["keys"]) != 2 or
                set(alignment["keys"]) != {"dataset_revision", "sample_token"}):
            fail("unsupported_capability", "QA requires exact dataset_revision/sample_token alignment", "validate_scoring")
        if alignment["duplicate_policy"] not in ("error", "latest_available"):
            fail("unsupported_capability", "Unsupported QA outcome duplicate policy", "validate_scoring")
        if any(metric not in TASK_METRICS[self.params["task_id"]] for metric in scoring["metrics"]):
            fail("unsupported_capability", "Requested metric is not bound to this QA task", "validate_scoring")

    def score(self, results, outcomes, context):
        services, scoring = context["services"], context["scoring"]
        self.validate_scoring(scoring)
        rows = _records(services.read_json(results["records_ref"]))
        if len(rows) > 1:
            fail("schema_mismatch", "One QA evaluation unit must contain at most one result", "score")
        alignment = scoring["alignment"]

        def match_key(item):
            try:
                return canonical_json({key: item["alignment_key"][key] for key in alignment["keys"]})
            except KeyError:
                fail("schema_mismatch", "Outcome/result lacks a declared QA alignment key", "score")

        matched = {}
        for outcome in _records(services.read_json(outcomes["records_ref"])):
            if "evaluation" not in outcome.get("allowed_uses", []):
                fail("permission_denied", "QA outcome is not authorized for evaluation", "score")
            gold = unpack(outcome["payload"], services)
            if any(gold.get(key) != self.params[key] for key in ("task_id", "task_version")):
                fail("schema_mismatch", "Outcome task identity differs from scorer", "score")
            key = match_key(outcome)
            previous = matched.get(key)
            if previous is not None:
                if alignment["duplicate_policy"] == "error":
                    fail("conflict", "Duplicate outcome for a QA sample", "score")
                ordering = lambda item: (parse_time(item["available_at"]), parse_time(item["recorded_at"]))
                if ordering(previous) == ordering(outcome):
                    fail("conflict", "Latest QA outcome has ambiguous timestamps", "score")
                if ordering(previous) > ordering(outcome):
                    continue
            matched[key] = outcome

        scores, diagnostics = {}, []
        for metric in scoring["metrics"]:
            counts = {"eligible": 1, "scored": 0, "missing": 0, "invalid": 0, "excluded": 0}
            value, reason, outcome, row = None, None, None, rows[0] if rows else None
            if row is None:
                counts["missing"], reason = 1, "missing_result"
            else:
                answer = unpack(row["payload"], services)
                if row["status"] != "valid" or answer.get("parsed") is None:
                    counts["invalid"], reason = 1, answer.get("reason") or "invalid_result"
                elif answer.get("parser_ref") != PARSER_REF:
                    fail("schema_mismatch", "QA result has an unsupported parser revision", "score")
                else:
                    outcome = matched.get(match_key(row))
                    if outcome is None:
                        counts["missing"], reason = 1, "missing_outcome"
                    else:
                        gold = unpack(outcome["payload"], services)
                        value, reason = point_metric(self.params["task_id"], metric,
                                                     answer["parsed"], gold["expected_output"])
                        counts["scored" if reason is None else "invalid"] = 1
            scores[metric] = {"value": value, "status": "ready" if value is not None else "insufficient_evidence",
                              "counts": counts, "reason": reason}
            diagnostics.append({"metric_id": metric, "result_id": row["result_id"] if row else None,
                                "outcome_id": outcome["outcome_id"] if outcome else None,
                                "outcome_revision": outcome["revision"] if outcome else None,
                                "value": value, "reason": reason})
        return {"metrics": scores, "item_scores_ref": services.save_json({"records": diagnostics}, "gymts.json/1"),
                "diagnostics_ref": None}
