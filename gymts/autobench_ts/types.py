"""JSON contracts for the public AutoBenchTS boundary."""
from typing import Any, Dict, List, Optional, TypedDict


class MetricCounts(TypedDict):
    eligible: int
    scored: int
    missing: int
    invalid: int
    excluded: int


class MetricResult(TypedDict):
    value: Optional[float]
    status: str
    counts: MetricCounts
    reason: Optional[str]


class EvaluationReport(TypedDict):
    protocol_version: str
    evaluation_id: str
    previous_evaluation_id: Optional[str]
    status: str
    created_at: str
    plan_ref: Dict[str, Any]
    run_manifest_ref: Dict[str, Any]
    result_view_refs: List[Dict[str, Any]]
    outcome_view_ref: Optional[Dict[str, Any]]
    scorer_ref: Dict[str, Any]
    metrics: List[Dict[str, Any]]
    comparisons: List[Dict[str, Any]]
    gate_results: List[Dict[str, Any]]
    coverage: Dict[str, int]
    verdict: str
    reasons: List[str]
    evidence_refs: List[Dict[str, Any]]
    errors: List[Dict[str, Any]]
