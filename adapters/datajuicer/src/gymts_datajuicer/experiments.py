"""Build native GymTS plans; no bespoke evaluator or hidden pipeline run."""
import copy
from gymts.contracts import inline, utc_now
from .common import sha
from . import contracts as c


def evaluation_spec(gym, source, reference, candidate_params, *, provenance=None):
    if source["source_revision"] != reference["source_revision"] or source["rows"] != reference["rows"]:
        raise ValueError("Public source and independent reference are not aligned")
    revision = source["source_revision"]
    snapshot = gym.artifacts.save_json({"dataset_revision": revision, "sample": source}, c.SNAPSHOT)
    private = gym.artifacts.save_json(reference, c.OUTCOME)
    timestamp = utc_now()
    outcome = {"outcome_id": "datajuicer-quality-" + revision, "revision": "1",
        "alignment_key": {"source_revision": revision}, "payload": {"schema_ref": c.OUTCOME,
            "storage": "artifact", "artifact_ref": private}, "event_time": 0,
        "available_at": timestamp, "recorded_at": timestamp, "source_ref": private,
        "supersedes_ref": None, "allowed_uses": ["evaluation"]}
    outcomes = gym.artifacts.save_json([outcome], "gymts.outcome-records/1")
    view = {"view_id": "datajuicer-independent-reference", "revision": outcomes["revision"],
        "source_refs": [outcomes], "selection": inline({"kind": "all", "source_index": 0}, "gymts.selection/1"),
        "as_of": None, "purpose": "evaluation"}
    case = {"evaluation_case_id": "pipeline-" + revision,
        "scene": {"environment": {"protocol_version": "gymts.environment/1", "adapter": "datajuicer-source",
            "version": "1.0.0", "source": {"kind": "dataset", "locator": "artifact://datajuicer/train-only",
                "revision": revision, "connection": {"artifact_refs": [snapshot]}, "credential_ref": None},
            "mapping": {}, "options": {}}, "task": {"plugin": "datajuicer-derive", "version": "1.0.0", "params": {}},
            "binding": {"variables": {"sample": {"source": "sample", "unit": "sample", "transform": None}}, "operations": {}}},
        "execution": {"mode": "stream", "start": {"mode": "reinitialize"}, "scope": {"start": 0, "end": 1},
            "feedback_until": None, "seed": 21, "learning": {"prepare": "load_only", "online": "frozen",
                "training_view": None, "training_targets": None, "alignment_schema_ref": None, "allowed_feedback_sources": []},
            "limits": {"max_inputs": 1, "max_operations": None, "max_turns_per_case": 1,
                       "max_wall_time_s": candidate_params["timeout_seconds"] + 90}},
        "recording": {"store_ref": "local://records/default", "inputs": "full", "outputs": "full",
            "artifacts": "reference", "model_calls": "io", "on_capture_failure": "fail_run",
            "redaction_policy_ref": None, "extra_event_kinds": []}, "tags": {"source_revision": revision}}
    gates = [{"metric": "run_failure_rate", "target": "absolute", "candidate_ids": None, "for_metric": None,
              "operator": "le", "threshold": 0, "scope": "aggregate"}]
    for metric in ("lineage_integrity", "holdout_clean"):
        gates.append({"metric": metric, "target": "absolute", "candidate_ids": None, "for_metric": None,
                      "operator": "ge", "threshold": 1, "scope": "aggregate"})
    result = {"protocol_version": "gymts.evaluation/1", "name": "Native Data-Juicer training-source derivation",
        "purpose": "acceptance", "cases": [case], "candidates": [{"candidate_id": "native-datajuicer-local-hf",
            "spec": {"adapter": "datajuicer-native", "version": "1.0.0", "artifact": None,
                     "params": copy.deepcopy(candidate_params), "inherited_state": []}}],
        "baseline_id": None, "repetitions": {"count": 1, "seeds": [21]},
        "scoring": {"scorer": {"adapter": "datajuicer-quality", "version": "1.0.0", "params": {}},
            "outcomes": {"sources": [view], "as_of": timestamp},
            "alignment": {"schema_ref": c.ALIGNMENT, "keys": ["source_revision"], "matching": "exact",
                          "params": {}, "duplicate_policy": "error"}, "metrics": list(c.METRICS),
            "evidence_requirements": {"min_scored": 1, "min_coverage": 1, "overrides": {}},
            "missing_outcome_policy": "report_insufficient"},
        "comparison": {"group_by": ["evaluation_case_id"], "repetition_aggregation": "mean",
            "aggregation": "macro_mean", "baseline_method": "difference", "gates": gates},
        "failure_policy": {"partial_results": "include", "invalid_result_policy": "report"}}
    if provenance is not None:
        ref = gym.artifacts.save_json(provenance, "gymts.json/1")
        result["provenance"] = {"source_refs": [ref], "usage_policy_ref": None, "benchmark_definition_ref": None}
    return result


def rescore(gym, spec, report):
    plan = gym.artifacts.read_json(report["plan_ref"])
    if gym.artifacts.read_json(plan["spec_ref"]) != spec:
        raise ValueError("Use the original sealed evaluation specification")
    entries = {row["unit_id"]: row for row in gym.artifacts.read_json(report["run_manifest_ref"])["entries"]}
    runs = [{"unit_id": unit["unit_id"], "evaluation_case_id": unit["evaluation_case_id"],
        "candidate_id": unit["candidate_id"], "repetition": unit["repetition"],
        "run_id": entries[unit["unit_id"]]["run_id"], "unavailable_reason": None,
        "unit_spec_ref": unit["resolved_spec_ref"], "tags": copy.deepcopy(unit["tags"])}
        for unit in plan["expected_units"]]
    return gym.autobench.score({"protocol_version": "gymts.score/1", "name": spec["name"] + " sealed re-score",
        "purpose": spec["purpose"], "runs": runs, "baseline_id": None,
        "previous_evaluation_id": report["evaluation_id"], "scoring": copy.deepcopy(spec["scoring"]),
        "comparison": copy.deepcopy(spec["comparison"]), "failure_policy": copy.deepcopy(spec["failure_policy"])})
