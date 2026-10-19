"""Deterministic grouping and gate evaluation, with independent evidence counts."""
import math
from typing import Any, Dict, List, Optional

from gymts.contracts import canonical_json

COUNT_KEYS = ("eligible", "scored", "missing", "invalid", "excluded")


def empty_metric(reason: str, status: str = "insufficient_evidence") -> Dict[str, Any]:
    return {"value": None, "status": status,
            "counts": {key: 0 for key in COUNT_KEYS}, "reason": reason}


def group_key(unit: Dict[str, Any], comparison: Dict[str, Any]) -> Dict[str, Any]:
    key = {}
    for field in comparison["group_by"]:
        if field == "evaluation_case_id":
            key[field] = unit[field]
        else:
            key[field] = unit["tags"][field[5:]]
    if comparison["repetition_aggregation"] == "none":
        key["repetition"] = unit["repetition"]
    return key


def requirements(scoring: Dict[str, Any], metric: str) -> Dict[str, Any]:
    base = scoring["evidence_requirements"]
    return base.get("overrides", {}).get(metric, base)


def combine(results: List[Dict[str, Any]], requirement: Dict[str, Any]) -> Dict[str, Any]:
    counts = {key: sum(item["counts"][key] for item in results) for key in COUNT_KEYS}
    reason = None
    status = "ready"
    if not results or any(item["status"] != "ready" for item in results):
        status, reason = "insufficient_evidence", "expected_result_not_ready"
    coverage = counts["scored"] / counts["eligible"] if counts["eligible"] else None
    if coverage is None:
        status, reason = "insufficient_evidence", "empty_eligible_set"
    elif counts["scored"] < requirement["min_scored"] or coverage < requirement["min_coverage"]:
        status, reason = "insufficient_evidence", "evidence_requirement_not_met"
    value = sum(item["value"] for item in results) / len(results) if status == "ready" else None
    if value is not None and not math.isfinite(value):
        status, reason, value = "error", "non_finite_aggregate", None
    return {"value": value, "status": status, "counts": counts, "reason": reason}


def aggregate(units: List[Dict[str, Any]], unit_metrics: List[Dict[str, Any]],
              scoring: Dict[str, Any], comparison: Dict[str, Any]) -> List[Dict[str, Any]]:
    indexed = {(entry["unit_id"], entry["metric_id"]): entry["result"] for entry in unit_metrics}
    groups = {}
    for unit in units:
        key = group_key(unit, comparison)
        groups.setdefault((unit["candidate_id"], canonical_json(key)), (key, []))[1].append(unit)
    entries = []
    for (candidate_id, _), (key, members) in groups.items():
        for metric in scoring["metrics"]:
            result = combine([indexed[(unit["unit_id"], metric)] for unit in members], requirements(scoring, metric))
            entries.append({"level": "group", "candidate_id": candidate_id, "group_key": key,
                            "unit_id": None, "repetition": None, "metric_id": metric, "result": result})
    if comparison["aggregation"] == "macro_mean":
        candidates = list(dict.fromkeys(unit["candidate_id"] for unit in units))
        for candidate_id in candidates:
            for metric in scoring["metrics"]:
                relevant = [entry["result"] for entry in entries if entry["candidate_id"] == candidate_id and entry["metric_id"] == metric]
                entries.append({"level": "aggregate", "candidate_id": candidate_id, "group_key": {},
                                "unit_id": None, "repetition": None, "metric_id": metric,
                                "result": combine(relevant, requirements(scoring, metric))})
    return entries


def delta(candidate: Dict[str, Any], baseline: Optional[Dict[str, Any]], method: str) -> Dict[str, Any]:
    if candidate["status"] != "ready" or baseline is None or baseline["status"] != "ready":
        return {"value": None, "status": "insufficient_evidence", "reason": "comparison_evidence_missing"}
    if method == "relative_change" and baseline["value"] == 0:
        return {"value": None, "status": "insufficient_evidence", "reason": "zero_baseline"}
    value = candidate["value"] - baseline["value"]
    if method == "relative_change":
        value /= abs(baseline["value"])
    if not math.isfinite(value):
        return {"value": None, "status": "error", "reason": "non_finite_comparison"}
    return {"value": value, "status": "ready", "reason": None}


def compare(entries: List[Dict[str, Any]], baseline_id: Optional[str], method: str) -> List[Dict[str, Any]]:
    if baseline_id is None:
        return []
    index = {(entry["level"], entry["candidate_id"], canonical_json(entry["group_key"]), entry["metric_id"]): entry["result"] for entry in entries}
    output = []
    for entry in entries:
        if entry["level"] == "unit" or entry["candidate_id"] == baseline_id:
            continue
        baseline = index.get((entry["level"], baseline_id, canonical_json(entry["group_key"]), entry["metric_id"]))
        value = delta(entry["result"], baseline, method)
        output.append({"candidate_id": entry["candidate_id"], "baseline_id": baseline_id,
                       "group_key": entry["group_key"], "metric_id": entry["metric_id"], "method": method, **value})
    return output


def gates(units: List[Dict[str, Any]], executions: List[Dict[str, Any]], entries: List[Dict[str, Any]],
          comparison: Dict[str, Any], baseline_id: Optional[str]) -> List[Dict[str, Any]]:
    candidates = list(dict.fromkeys(unit["candidate_id"] for unit in units))
    index = {(entry["level"], entry["candidate_id"], canonical_json(entry["group_key"]), entry["metric_id"]): entry["result"] for entry in entries}
    execution_index = {entry["unit_id"]: entry for entry in executions}
    output = []
    operators = {"ge": lambda a, b: a >= b, "gt": lambda a, b: a > b,
                 "le": lambda a, b: a <= b, "lt": lambda a, b: a < b}
    for gate_index, gate in enumerate(comparison["gates"]):
        selected = gate["candidate_ids"]
        if selected is None:
            selected = [candidate for candidate in candidates if candidate != baseline_id] if len(candidates) > 1 else candidates
        for candidate_id in selected:
            candidate_units = [unit for unit in units if unit["candidate_id"] == candidate_id]
            expected_groups = {canonical_json(group_key(unit, comparison)): group_key(unit, comparison) for unit in candidate_units}
            keys = [{}] if gate["scope"] == "aggregate" else list(expected_groups.values())
            for key in keys:
                level = "aggregate" if gate["scope"] == "aggregate" else "group"
                members = candidate_units if level == "aggregate" else [unit for unit in candidate_units if group_key(unit, comparison) == key]
                metric_id = gate["for_metric"] if gate["metric"] == "scored_coverage" else gate["metric"]
                result = index.get((level, candidate_id, canonical_json(key), metric_id))
                value, reason = None, None
                if gate["metric"] == "run_failure_rate":
                    value = sum(execution_index[unit["unit_id"]]["status"] != "succeeded" for unit in members) / len(members) if members else None
                elif gate["metric"] == "scored_coverage":
                    if result and result["counts"]["eligible"]:
                        value = result["counts"]["scored"] / result["counts"]["eligible"]
                    else:
                        reason = "empty_eligible_set"
                elif result is not None and gate["target"] == "absolute":
                    if result["status"] == "ready":
                        value = result["value"]
                    else:
                        reason = result["reason"]
                elif result is not None:
                    baseline = index.get((level, baseline_id, canonical_json(key), metric_id))
                    difference = delta(result, baseline, gate["target"])
                    value, reason = difference["value"], difference["reason"]
                if value is None:
                    status, reason = "insufficient_evidence", reason or "gate_evidence_missing"
                else:
                    status = "pass" if operators[gate["operator"]](value, gate["threshold"]) else "fail"
                output.append({"gate_index": gate_index, "candidate_id": candidate_id,
                               "group_key": None if level == "aggregate" else key,
                               "status": status, "value": value, "reason": reason})
    return output
