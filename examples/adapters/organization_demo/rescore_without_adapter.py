"""Read registered data and rescore sealed Runs with only the installed core."""
import argparse
import importlib.util
import json
import math
from pathlib import Path
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import digest
from gymts.plugins.forecast import ForecastCandidate
from gymts.plugins.replay import TimeSeriesReplay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", required=True)
    parser.add_argument("--require-absent", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    absent = importlib.util.find_spec("gymts_organization_demo") is None
    if args.require_absent and not absent:
        raise RuntimeError("Uninstall gymts-organization-demo before checking its absence")
    root = Path(args.work)
    receipt = json.loads((root / "receipt.json").read_text())
    def forbidden(*args, **kwargs):
        raise AssertionError("Reading and rescoring must not execute models, sources or subprocesses")
    with GymTS(root / "store", data_home=root / "data", cache_home=root / "cache") as gym:
        with patch.object(gym.environment_ts, "run", forbidden), patch.object(ForecastCandidate, "infer", forbidden), \
                patch.object(TimeSeriesReplay, "__init__", forbidden), patch("subprocess.Popen", forbidden):
            handle = gym.environment_ts.datasets.load_dataset(**receipt["dataset"], purpose="runtime")
            public = list(handle)
            assert not hasattr(handle, "read_targets")
            assert all(set(row) == {"timestamp", "value"} for row in public)
            assert digest(public) == receipt["public_rows_hash"]
            organization = gym.experiments.inspect(receipt["group_id"], revision=receipt["revision"])
            assert organization["status"] == "succeeded"
            assert len(gym.experiments.query(dataset_id=receipt["dataset"]["dataset_id"],
                dataset_revision=receipt["dataset"]["revision"])) == 1
            assert len(gym.records.list_runs(dataset_id=receipt["dataset"]["dataset_id"],
                dataset_revision=receipt["dataset"]["revision"])) == len(receipt["run_ids"])
            # Earlier external stages remain completed. Only the builtin score
            # stage is explicitly rerun, preserving a complete new attempt link.
            resumed = gym.experiments.execute(receipt["group_id"], revision=receipt["revision"], rerun=("score",))
            score_attempt = [attempt for attempt in resumed["attempts"] if attempt["stage_id"] == "score"][-1]
            assert score_attempt["status"] == "succeeded"
            score = gym.artifacts.read_json(score_attempt["result_ref"])
            assert score["status"] == "completed" and not score["errors"]
            assert score["verdict"] == "insufficient_evidence" and "no_acceptance_gate" in score["reasons"]
            assert score["metrics"] == receipt["score_report"]["metrics"]
            actual = {run_id: {"result": digest(gym.records.get_run(run_id)["result"]),
                "events": digest(gym.records.get_run(run_id)["events"])} for run_id in receipt["run_ids"]}
            assert actual == receipt["sealed_fingerprints"]
            metrics = {entry["candidate_id"]: entry["result"] for entry in score["metrics"]
                       if entry["level"] == "aggregate" and entry["metric_id"] == "mae"}
            assert set(metrics) == set(receipt["expected_mae"])
            for candidate, expected in receipt["expected_mae"].items():
                assert metrics[candidate]["status"] == "ready"
                assert metrics[candidate]["counts"]["scored"] == receipt["expected_count"]
                assert math.isclose(metrics[candidate]["value"], expected, rel_tol=1e-12, abs_tol=1e-12)
        result = {"status": "passed", "adapter_absent": absent, "model_source_subprocess_calls": 0,
            "public_rows": len(public), "dataset": receipt["dataset"], "organization_query": True,
            "run_dataset_query": True, "organization_events": len(gym.experiments.events(receipt["group_id"], revision=receipt["revision"])),
            "run_ids": receipt["run_ids"], "sealed_results_and_events_unchanged": True,
            "metrics_exact": True, "numeric_reference_matches": True, "metrics": metrics,
            "evaluation_id": score["evaluation_id"], "verdict": score["verdict"],
            "organized_score_attempt_id": score_attempt["attempt_id"],
            "completed_external_stages_reused": True,
            "report_ref": gym.autobench.last_report_ref}
    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
