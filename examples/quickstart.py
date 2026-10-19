"""Run the local framework and rescore the same immutable outputs after labels arrive.

Run from the project root: python3 examples/quickstart.py --root .gymts-demo
"""

import argparse
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

# Permit running this example before an editable package installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gymts import GymTS
from gymts.contracts import digest, utc_now


HERE = Path(__file__).resolve().parent


def read_example(name):
    return json.loads((HERE / name).read_text())


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main(root):
    with GymTS(root=root) as gym:
        experiment = read_example("forecast_experiment.json")
        validation = gym.validate(experiment)
        require(validation["valid"], "The forecast example must validate")
        forecast = gym.run(experiment)
        require(forecast["status"] == "succeeded", "The forecast run must succeed")
        counter = gym.run(read_example("counter_experiment.json"))
        require(counter["status"] == "succeeded", "The counter control run must succeed")
        require(counter["summary"]["counts"]["operations"] == 3, "The counter must execute exactly 3 operations")

        evaluation = read_example("forecast_evaluation.json")
        empty_report = gym.autobench.evaluate(evaluation)
        require(empty_report["status"] == "completed", "Empty-label evaluation must finish normally")
        require(empty_report["verdict"] == "insufficient_evidence", "Missing labels must be reported explicitly")
        plan = gym.artifacts.read_json(empty_report["plan_ref"])
        manifest = gym.artifacts.read_json(empty_report["run_manifest_ref"])
        units = {unit["unit_id"]: unit for unit in plan["expected_units"]}
        run_ids = [entry["run_id"] for entry in manifest["entries"]]
        require(all(run_ids), "Both expected units must retain their Run IDs")
        before = {run_id: digest(gym.records.get_run(run_id)["result"]) for run_id in run_ids}

        # Ground truth comes independently from the synthetic source definition,
        # without inspecting or modifying Candidate predictions.
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        text_time = lambda i: (start + timedelta(minutes=i)).isoformat().replace("+00:00", "Z")
        truth_ref = gym.artifacts.save_json(
            [{"timestamp": text_time(i), "value": i} for i in range(12)], "gymts.json/1")
        outcomes = []
        for i in range(11):
            alignment = {"entity": "demo", "variable": "value", "issued_at": text_time(i), "target_time": text_time(i + 1)}
            outcomes.append({"outcome_id": "ramp-label-" + digest(alignment), "revision": "1",
                "alignment_key": alignment, "payload": {"schema_ref": "gymts.builtin/forecast-outcome/1",
                    "storage": "inline", "value": {"value": i + 1}},
                "event_time": text_time(i + 1), "available_at": "2026-01-01T01:00:00Z", "recorded_at": None,
                "source_ref": truth_ref, "supersedes_ref": None, "allowed_uses": ["evaluation"]})
        for run_id in run_ids:
            gym.records.attach_outcomes(run_id, outcomes)
        cutoff = utc_now()
        fixed_outcomes = gym.records.read_outcomes({"run_ids": run_ids, "outcomes_as_of": cutoff, "purpose": "evaluation"})
        outcome_ref = gym.artifacts.save_json(fixed_outcomes, "gymts.outcome-records/1")
        view = {"view_id": "fixed-ramp-labels", "revision": outcome_ref["revision"], "source_refs": [outcome_ref],
            "selection": {"schema_ref": "gymts.selection/1", "storage": "inline", "value": {"kind": "all", "source_index": 0}},
            "as_of": None, "purpose": "evaluation"}
        scoring = copy.deepcopy(evaluation["scoring"])
        scoring["outcomes"] = {"sources": [view], "as_of": cutoff}
        selected = []
        for entry in manifest["entries"]:
            unit = units[entry["unit_id"]]
            selected.append({"unit_id": unit["unit_id"], "evaluation_case_id": unit["evaluation_case_id"],
                "candidate_id": unit["candidate_id"], "repetition": unit["repetition"], "run_id": entry["run_id"],
                "unavailable_reason": None, "unit_spec_ref": unit["resolved_spec_ref"]})
        score_spec = {"protocol_version": "gymts.score/1", "name": "same-runs-after-labels", "purpose": "regression",
            "runs": selected, "baseline_id": evaluation["baseline_id"], "scoring": scoring,
            "comparison": evaluation["comparison"], "failure_policy": evaluation["failure_policy"],
            "previous_evaluation_id": empty_report["evaluation_id"]}
        report = gym.autobench.score(score_spec)
        rescored_manifest = gym.artifacts.read_json(report["run_manifest_ref"])
        after_ids = [entry["run_id"] for entry in rescored_manifest["entries"]]
        require(after_ids == run_ids, "Rescoring must retain exactly the same Run IDs")
        require(all(digest(gym.records.get_run(run_id)["result"]) == before[run_id] for run_id in run_ids),
                "Attaching outcomes and rescoring must not modify original RunResult")
        aggregate = {entry["candidate_id"]: entry["result"]["value"] for entry in report["metrics"]
                     if entry["level"] == "aggregate" and entry["metric_id"] == "mae"}
        require(aggregate == {"last-value": 1.0, "window-mean": 2.0}, "Expected independent MAE values were not reproduced")
        require(report["verdict"] == "pass", "The configured last-value MAE gate must pass")
        print(json.dumps({"forecast_run_id": forecast["run_id"], "counter_run_id": counter["run_id"],
            "counter_operations": 3, "initial_verdict": empty_report["verdict"],
            "rescored_verdict": report["verdict"], "mae": aggregate, "rescored_run_ids": after_ids,
            "same_run_ids": True, "original_results_unchanged": True, "records_root": str(Path(root).resolve())},
            ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".gymts-demo", help="Local durable record/artifact directory")
    main(parser.parse_args().root)
