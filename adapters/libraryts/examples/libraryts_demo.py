"""Small real LibraryTS/AutoBenchTS experiment with independent evaluation data."""
import argparse
import copy
import json

from gymts import GymTS
from gymts.contracts import digest, inline, utc_now
from gymts_timeseries.contracts import OUTCOME
from gymts_timeseries.experiments import scene, scoring
from gymts_libraryts.data import load_dataset


def candidate(implementation, estimator, params):
    return {"adapter": "libraryts-qa", "version": "1.0.0", "artifact": None,
            "params": {"implementation": implementation, "estimator": estimator, "estimator_params": params},
            "inherited_state": []}


def run_demo(store, implementation):
    with GymTS(store, integrations=("timeseries", "libraryts")) as gym:
        source = load_dataset(gym, implementation, dataset="airline", horizon=12)
        token, task, version = source["sample_tokens"][0], "forecast.numeric", "0.1.0"
        scoring_spec = scoring(task, version)
        scoring_spec["scorer"] = {"adapter": "libraryts-forecast-scorer", "version": "1.0.0",
            "params": {"task_id": task, "task_version": version, "implementation": implementation}}
        spec = {"protocol_version": "gymts.evaluation/1", "name": "Native airline forecast", "purpose": "development",
            "cases": [{"evaluation_case_id": "airline-h12", "scene": scene(source["snapshot_ref"], source["dataset_revision"], token, task, version),
                "execution": {"mode": "stream", "start": {"mode": "reinitialize"}, "scope": {"start": 0, "end": 1},
                    "feedback_until": None, "seed": 1,
                    "learning": {"prepare": "load_only", "online": "frozen", "training_view": None, "training_targets": None,
                        "alignment_schema_ref": None, "allowed_feedback_sources": []},
                    "limits": {"max_inputs": 1, "max_operations": 1, "max_turns_per_case": 1, "max_wall_time_s": 120}},
                "recording": {"store_ref": "local://records/default", "inputs": "full", "outputs": "full", "artifacts": "reference",
                    "model_calls": "io", "on_capture_failure": "fail_run", "redaction_policy_ref": None, "extra_event_kinds": []},
                "tags": {"dataset": "airline"}}],
            "candidates": [{"candidate_id": "naive-drift", "spec": candidate(implementation, "naive", {"strategy": "drift"})},
                           {"candidate_id": "polynomial-linear", "spec": candidate(implementation, "polynomial", {"degree": 1})}],
            "baseline_id": "naive-drift", "repetitions": {"count": 1, "seeds": [1]}, "scoring": scoring_spec,
            "comparison": {"group_by": ["evaluation_case_id", "tags.dataset"], "repetition_aggregation": "mean",
                "aggregation": "macro_mean", "baseline_method": "difference", "gates": []},
            "failure_policy": {"partial_results": "include", "invalid_result_policy": "report"}}
        initial = gym.autobench.evaluate(spec)
        plan = gym.artifacts.read_json(initial["plan_ref"])
        manifest = gym.artifacts.read_json(initial["run_manifest_ref"])
        gold = gym.artifacts.read_json(source["private_ref"])
        outcome = {"outcome_id": "libraryts-airline-" + digest(gold).removeprefix("sha256:"), "revision": "1",
            "alignment_key": {"dataset_revision": source["dataset_revision"], "sample_token": token},
            "payload": inline({"task_id": task, "task_version": version, "expected_output": {"forecast": gold["values"]}}, OUTCOME),
            "event_time": 0, "available_at": utc_now(), "recorded_at": None, "source_ref": source["private_ref"],
            "supersedes_ref": None, "allowed_uses": ["evaluation"]}
        selections, originals = [], {}
        units = {unit["unit_id"]: unit for unit in plan["expected_units"]}
        for entry in manifest["entries"]:
            run_id, unit = entry["run_id"], units[entry["unit_id"]]
            if run_id is None:
                raise RuntimeError("LibraryTS demo could not allocate its Run")
            original = gym.records.get_run(run_id)
            if original["result"]["status"] != "succeeded":
                raise RuntimeError(json.dumps(original["result"]["errors"]))
            originals[run_id] = digest(original["result"])
            gym.records.attach_outcomes(run_id, [outcome])
            selections.append({"unit_id": unit["unit_id"], "evaluation_case_id": unit["evaluation_case_id"],
                "candidate_id": unit["candidate_id"], "repetition": unit["repetition"], "run_id": run_id,
                "unavailable_reason": None, "unit_spec_ref": unit["resolved_spec_ref"], "tags": copy.deepcopy(unit["tags"])})
        records = gym.records.read_outcomes({"run_ids": list(originals), "purpose": "evaluation"})
        reference = gym.artifacts.save_json(records, "gymts.outcome-records/1")
        view = {"view_id": "libraryts-airline-outcomes", "revision": reference["revision"], "source_refs": [reference],
            "selection": inline({"kind": "all", "source_index": 0}, "gymts.selection/1"), "as_of": None, "purpose": "evaluation"}
        score_spec = {"protocol_version": "gymts.score/1", "name": "Native airline fixed-output score", "purpose": "development",
            "runs": selections, "baseline_id": spec["baseline_id"], "scoring": copy.deepcopy(spec["scoring"]),
            "comparison": spec["comparison"], "failure_policy": spec["failure_policy"], "previous_evaluation_id": initial["evaluation_id"]}
        score_spec["scoring"]["outcomes"] = {"sources": [view], "as_of": None}
        final = gym.autobench.score(score_spec)
        assert all(digest(gym.records.get_run(run_id)["result"]) == identity for run_id, identity in originals.items())
        return {"source": source, "run_ids": list(originals), "initial_report": initial, "report": final}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--python", required=True)
    args = parser.parse_args()
    print(json.dumps(run_demo(args.store, {"repository": args.repository, "python": args.python}), indent=2))


if __name__ == "__main__":
    main()
