"""Explicit example configuration and fixed-output rescoring, not another evaluator."""
import copy
from datetime import datetime, timedelta, timezone

from gymts import GymTS
from gymts.contracts import digest, inline, utc_now


def evaluation_spec(endpoint, *, seconds=3, step_seconds=.25, expression="gymts_demo_value"):
    start = datetime.now(timezone.utc)
    stamp = lambda value: value.isoformat().replace("+00:00", "Z")
    period = str(step_seconds) + "s"
    return {"protocol_version": "gymts.evaluation/1", "name": "attached Prometheus telemetry", "purpose": "regression",
        "cases": [{"evaluation_case_id": "live-telemetry", "scene": {
            "environment": {"protocol_version": "gymts.environment/1", "adapter": "prometheus-live", "version": "1.0.0",
                "source": {"kind": "live", "locator": endpoint, "revision": "configured-telemetry-deployment-v1",
                    "credential_ref": None, "connection": {"base_url": endpoint,
                        "queries": {"value": {"expression": expression, "labels": {}}}, "timeout_seconds": 2}},
                "mapping": {"variables": {"value": {"unit": "value"}}},
                "options": {"entity": "testbed", "step_seconds": step_seconds}},
            "task": {"plugin": "window_forecast", "version": "1.0.0", "params": {"variable": "value", "unit": "value",
                "entity": "testbed", "window_points": 2, "horizon": period, "advance_by": period, "warmup_duration": None}},
            "binding": {"variables": {"value": {"source": "value", "unit": "value", "transform": None}}, "operations": {}}},
            "execution": {"mode": "stream", "start": {"mode": "attach"},
                "scope": {"start": stamp(start), "end": stamp(start + timedelta(seconds=seconds))},
                "feedback_until": None, "seed": None,
                "learning": {"prepare": "load_only", "online": "frozen", "training_view": None,
                    "training_targets": None, "alignment_schema_ref": None, "allowed_feedback_sources": []},
                "limits": {"max_inputs": None, "max_operations": None, "max_turns_per_case": 1, "max_wall_time_s": seconds + 10}},
            "recording": {"store_ref": "local://records/default", "inputs": "full", "outputs": "full", "artifacts": "reference",
                "model_calls": "none", "on_capture_failure": "fail_run", "redaction_policy_ref": None, "extra_event_kinds": []},
            "tags": {"source_type": "live", "provider": "prometheus"}}],
        "candidates": [{"candidate_id": "last-value", "spec": {"adapter": "last-value", "version": "1.0.0",
            "artifact": None, "params": {}, "inherited_state": []}}],
        "baseline_id": None, "repetitions": {"count": 1, "seeds": [None]},
        "scoring": {"scorer": {"adapter": "forecast-mae", "version": "1.0.0", "params": {}},
            "outcomes": {"sources": [], "as_of": None},
            "alignment": {"schema_ref": "gymts.builtin/forecast-alignment/1",
                "keys": ["entity", "variable", "issued_at", "target_time"], "matching": "exact", "params": {}, "duplicate_policy": "error"},
            "metrics": ["mae"], "evidence_requirements": {"min_scored": 1, "min_coverage": 1, "overrides": {}},
            "missing_outcome_policy": "report_insufficient"},
        "comparison": {"group_by": ["evaluation_case_id"], "repetition_aggregation": "mean", "aggregation": "macro_mean",
            "baseline_method": "difference", "gates": [{"metric": "run_failure_rate", "target": "absolute",
                "candidate_ids": None, "for_metric": None, "operator": "le", "threshold": 0, "scope": "aggregate"},
                {"metric": "scored_coverage", "target": "absolute", "candidate_ids": None,
                    "for_metric": "mae", "operator": "ge", "threshold": 1, "scope": "aggregate"}]},
        "failure_policy": {"partial_results": "include", "invalid_result_policy": "report"}}


def run_demo(store, endpoint, *, expected_value=None, seconds=3):
    """expected_value is an explicit independent fixture reference, never inferred from predictions."""
    with GymTS(store, integrations=("prometheus",)) as gym:
        spec = evaluation_spec(endpoint, seconds=seconds)
        initial = gym.autobench.evaluate(spec)
        plan = gym.artifacts.read_json(initial["plan_ref"])
        manifest = gym.artifacts.read_json(initial["run_manifest_ref"])
        units = {unit["unit_id"]: unit for unit in plan["expected_units"]}
        selections, original_hashes, rows = [], {}, []
        for entry in manifest["entries"]:
            run_id = entry["run_id"]
            if run_id is None:
                raise RuntimeError("No native telemetry Run was allocated")
            run = gym.records.get_run(run_id)
            if run["result"]["status"] != "succeeded":
                raise RuntimeError(str(run["result"]["errors"]))
            original_hashes[run_id] = (digest(run["result"]), digest(run["events"]))
            results = gym.artifacts.read_json(run["result"]["result_ref"])
            if not results:
                raise RuntimeError("The telemetry window produced no task decisions")
            unit = units[entry["unit_id"]]
            selections.append({"unit_id": unit["unit_id"], "evaluation_case_id": unit["evaluation_case_id"],
                "candidate_id": unit["candidate_id"], "repetition": unit["repetition"], "run_id": run_id,
                "unavailable_reason": None, "unit_spec_ref": unit["resolved_spec_ref"], "tags": unit["tags"]})
            rows.extend(results)
        views = []
        if expected_value is not None:
            source_ref = gym.artifacts.save_json({"fixture": "explicit exporter reference",
                "expected_value": expected_value}, "gymts.json/1")
            now = utc_now()
            outcomes = [{"outcome_id": "telemetry-" + digest(row["alignment_key"]), "revision": "1",
                "alignment_key": row["alignment_key"], "payload": inline({"value": expected_value}, "gymts.builtin/forecast-outcome/1"),
                "event_time": row["alignment_key"]["target_time"], "available_at": now, "recorded_at": now,
                "source_ref": source_ref, "supersedes_ref": None, "allowed_uses": ["evaluation"]} for row in rows]
            ref = gym.artifacts.save_json(outcomes, "gymts.outcome-records/1")
            views = [{"view_id": "independent-live-reference", "revision": ref["revision"], "source_refs": [ref],
                "selection": inline({"kind": "all", "source_index": 0}, "gymts.selection/1"), "as_of": None, "purpose": "evaluation"}]
        score = {"protocol_version": "gymts.score/1", "name": "sealed telemetry rescore", "purpose": "regression",
            "runs": selections, "previous_evaluation_id": initial["evaluation_id"],
            **{key: copy.deepcopy(spec[key]) for key in ("baseline_id", "scoring", "comparison", "failure_policy")}}
        score["scoring"]["outcomes"] = {"sources": views, "as_of": None}
        # Re-scoring must work while all environment reads are unavailable.
        from unittest.mock import patch
        from .environment import PrometheusEnvironment
        with patch.object(PrometheusEnvironment, "_get", side_effect=AssertionError("Rescore read the live service")):
            final = gym.autobench.score(score)
            repeated = gym.autobench.score(score)
        assert all((digest(gym.records.get_run(run_id)["result"]), digest(gym.records.get_run(run_id)["events"])) == hashes
                   for run_id, hashes in original_hashes.items())
        snapshot = gym.records.snapshot(list(original_hashes))
        return {"run_ids": list(original_hashes), "task_decisions": len(rows), "initial_report": initial,
            "final_report": final, "repeated_report": repeated, "score_spec": score,
            "sealed_result_and_event_hashes_unchanged": True, "rescore_new_http_requests": 0,
            "record_snapshot_ref": snapshot, "independent_reference_value": expected_value}
