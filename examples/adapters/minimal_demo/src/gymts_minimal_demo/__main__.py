"""Real evaluate/score smoke check for the installed tutorial distribution."""

import argparse
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import digest, utc_now


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def evaluation_spec():
    scene = {
        "environment": {"protocol_version": "gymts.environment/1", "adapter": "local-timeseries-replay",
            "version": "1.0.0", "source": {"kind": "generator", "locator": "builtin://linear-ramp",
                "revision": "tutorial-ramp-v1", "credential_ref": None,
                "connection": {"generator": {"start": "2026-01-01T00:00:00Z", "period": "1min",
                    "length": 12, "start_value": 0, "delta": 1}}},
            "mapping": {"variables": {"value": {"field": "value", "dtype": "float64", "unit": "value"}}},
            "options": {"availability": "event_time", "entity": "demo"}},
        "task": {"plugin": "window_forecast", "version": "1.0.0", "params": {"variable": "value",
            "unit": "value", "entity": "demo", "window_points": 3, "horizon": "1min", "advance_by": "1min"}},
        "binding": {"variables": {"value": {"source": "value", "unit": "value", "transform": None}},
                    "operations": {}}}
    execution = {"mode": "stream", "start": {"mode": "reinitialize"},
        "scope": {"start": "2026-01-01T00:00:00Z", "end": "2026-01-01T00:10:00Z"},
        "feedback_until": None, "seed": 7,
        "learning": {"prepare": "load_only", "online": "frozen", "training_view": None,
            "training_targets": None, "alignment_schema_ref": None, "allowed_feedback_sources": []},
        "limits": {"max_inputs": None, "max_operations": None, "max_turns_per_case": 32, "max_wall_time_s": 30}}
    recording = {"store_ref": "local://records/default", "inputs": "full", "outputs": "full",
        "artifacts": "reference", "model_calls": "none", "on_capture_failure": "fail_run",
        "redaction_policy_ref": None, "extra_event_kinds": []}
    candidate = lambda adapter, params: {"adapter": adapter, "version": "1.0.0", "artifact": None,
                                        "params": params, "inherited_state": []}
    return {"protocol_version": "gymts.evaluation/1", "name": "external-drift-tutorial", "purpose": "regression",
        "cases": [{"evaluation_case_id": "ramp", "scene": scene, "execution": execution,
                   "recording": recording, "tags": {"source": "tutorial"}}],
        "candidates": [{"candidate_id": "drift", "spec": candidate("example-drift", {"damping": 1.0})},
                       {"candidate_id": "last-value", "spec": candidate("last-value", {})}],
        "baseline_id": "last-value", "repetitions": {"count": 1, "seeds": [7]},
        "scoring": {"scorer": {"adapter": "forecast-mae", "version": "1.0.0", "params": {}},
            "outcomes": {"sources": [], "as_of": None},
            "alignment": {"schema_ref": "gymts.builtin/forecast-alignment/1",
                "keys": ["entity", "variable", "issued_at", "target_time"], "matching": "exact",
                "params": {}, "duplicate_policy": "error"},
            "metrics": ["mae"], "evidence_requirements": {"min_scored": 1, "min_coverage": 1, "overrides": {}},
            "missing_outcome_policy": "report_insufficient"},
        "comparison": {"group_by": ["evaluation_case_id"], "repetition_aggregation": "mean",
            "aggregation": "macro_mean", "baseline_method": "difference", "gates": [{"metric": "mae",
                "target": "absolute", "candidate_ids": ["drift"], "for_metric": None,
                "operator": "le", "threshold": 0.0, "scope": "aggregate"}]},
        "failure_policy": {"partial_results": "include", "invalid_result_policy": "report"}}


def score_spec(gym, evaluation, initial):
    plan = gym.artifacts.read_json(initial["plan_ref"])
    entries = {entry["unit_id"]: entry for entry in gym.artifacts.read_json(initial["run_manifest_ref"])["entries"]}
    # This reference is derived from the fixture formula, never the predictions.
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    stamp = lambda i: (start + timedelta(minutes=i)).isoformat().replace("+00:00", "Z")
    truth = gym.artifacts.save_json({"formula": "value=minutes_since_2026-01-01T00:00:00Z"}, "gymts.json/1")
    now = utc_now()
    outcomes = [{"outcome_id": "tutorial-ramp-" + str(i), "revision": "1",
        "alignment_key": {"entity": "demo", "variable": "value", "issued_at": stamp(i), "target_time": stamp(i + 1)},
        "payload": {"schema_ref": "gymts.builtin/forecast-outcome/1", "storage": "inline", "value": {"value": i + 1}},
        "event_time": stamp(i + 1), "available_at": now, "recorded_at": None,
        "source_ref": truth, "supersedes_ref": None, "allowed_uses": ["evaluation"]} for i in range(11)]
    run_ids = [entries[unit["unit_id"]]["run_id"] for unit in plan["expected_units"]]
    require(all(run_ids), "Every evaluation unit must have a Run")
    for run_id in run_ids:
        gym.records.attach_outcomes(run_id, outcomes)
    cutoff = utc_now()
    fixed = gym.records.read_outcomes({"run_ids": run_ids, "outcomes_as_of": cutoff, "purpose": "evaluation"})
    ref = gym.artifacts.save_json(fixed, "gymts.outcome-records/1")
    scoring = copy.deepcopy(evaluation["scoring"])
    scoring["outcomes"] = {"sources": [{"view_id": "tutorial-ramp-reference", "revision": ref["revision"],
        "source_refs": [ref], "selection": {"schema_ref": "gymts.selection/1", "storage": "inline",
            "value": {"kind": "all", "source_index": 0}}, "as_of": None, "purpose": "evaluation"}], "as_of": cutoff}
    return {"protocol_version": "gymts.score/1", "name": "sealed-ramp-score", "purpose": "regression",
        "runs": [{"unit_id": unit["unit_id"], "evaluation_case_id": unit["evaluation_case_id"],
            "candidate_id": unit["candidate_id"], "repetition": unit["repetition"],
            "run_id": entries[unit["unit_id"]]["run_id"], "unavailable_reason": None,
            "unit_spec_ref": unit["resolved_spec_ref"], "tags": unit["tags"]} for unit in plan["expected_units"]],
        "previous_evaluation_id": initial["evaluation_id"], "baseline_id": evaluation["baseline_id"],
        "scoring": scoring, "comparison": copy.deepcopy(evaluation["comparison"]),
        "failure_policy": copy.deepcopy(evaluation["failure_policy"])}


def fingerprints(gym, run_ids):
    return {run_id: {"result": digest(gym.records.get_run(run_id)["result"]),
                     "events": digest(gym.records.get_run(run_id)["events"])} for run_id in run_ids}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="New local directory for records and tutorial receipts")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    require(not (root / "receipt.json").exists(), "Choose a fresh root for this tutorial")
    with GymTS(root=root, integrations=("minimal-demo",), data_home=root / "datasets", cache_home=root / "cache") as gym:
        spec = evaluation_spec()
        case = spec["cases"][0]
        experiment = {"protocol_version": "gymts.experiment/1", "name": "pure-assembly-check",
            "scene": case["scene"], "candidate": spec["candidates"][0]["spec"],
            "execution": case["execution"], "recording": case["recording"]}
        with patch("gymts_minimal_demo.candidate.DriftCandidate.__init__", side_effect=AssertionError("plan opened Candidate")):
            require(gym.validate(experiment)["valid"], "Pure validation must succeed")
            gym.plan(experiment)
        initial = gym.autobench.evaluate(spec)
        require(initial["verdict"] == "insufficient_evidence", "Missing references must be explicit")
        scoring = score_spec(gym, spec, initial)
        run_ids = [item["run_id"] for item in scoring["runs"]]
        before = fingerprints(gym, run_ids)
        with patch("gymts_minimal_demo.candidate.DriftCandidate.infer", side_effect=AssertionError("score reran Candidate")):
            report = gym.autobench.score(scoring)
            repeated = gym.autobench.score(dict(scoring, previous_evaluation_id=report["evaluation_id"]))
        mae = {item["candidate_id"]: item["result"]["value"] for item in report["metrics"]
               if item["level"] == "aggregate" and item["metric_id"] == "mae"}
        require(mae == {"drift": 0.0, "last-value": 1.0}, "Expected independently calculated fixture MAE")
        require(report["verdict"] == repeated["verdict"] == "pass", "Both scores must pass")
        require(fingerprints(gym, run_ids) == before, "Score must preserve sealed RunResult and events")
        declaration = gym.registries.candidates.resolve("example-drift", "1.0.0")
        archived = {"manifest": declaration,
                    "params_schema": gym.schemas.resolve(declaration["params_schema_ref"])}
        (root / "candidate-declaration.json").write_text(json.dumps(archived, indent=2) + "\n", encoding="utf-8")
        (root / "score-spec.json").write_text(json.dumps(scoring, indent=2) + "\n", encoding="utf-8")
        receipt = {"root": str(root), "run_ids": run_ids, "initial_evaluation_id": initial["evaluation_id"],
            "score_evaluation_id": report["evaluation_id"], "repeated_evaluation_id": repeated["evaluation_id"],
            "mae": mae, "sealed_fingerprints": before, "same_run_ids": True, "run_evidence_unchanged": True}
        (root / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
