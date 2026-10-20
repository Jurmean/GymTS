"""Real fixed Monash HF source -> Run -> evaluate -> independent re-score."""
import argparse
import hashlib
import json
from pathlib import Path

from gymts import GymTS
from gymts.contracts import canonical_json
from gymts_hf_datasets.benchmark import experiment_from_case, last_value_candidate, score_existing
from gymts_hf_datasets.importer import freeze_dataset, register_benchmark


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", default="/tmp/gymts-hf-static")
    parser.add_argument("--source", default=str(Path(__file__).with_name("monash_source.json")))
    parser.add_argument("--data-home")
    parser.add_argument("--dataset-id", default="hf/monash-tourism-monthly")
    parser.add_argument("--report")
    args = parser.parse_args()
    root = Path(args.work)
    root.mkdir(parents=True, exist_ok=True)
    with GymTS(root / "runs", data_home=args.data_home or root / "data", cache_home=root / "cache",
               integrations=("hf-datasets",)) as gym:
        source = json.loads(Path(args.source).read_text())
        fixed = freeze_dataset(gym, args.dataset_id, source, series_column="target", horizon=24,
            context_length=48, sample_indices=[0, 1, 2], aliases=("1.0.0",), cache_dir=root / "hf-cache")
        definition = register_benchmark(gym, args.dataset_id, revision=fixed["revision"], aliases=("1.0.0",))
        public = gym.environment_ts.datasets.load_dataset(args.dataset_id, revision="1.0.0")
        assert len(public) == 3 and not hasattr(public, "read_targets")
        assert all(set(row) == {"sample_id", "dataset_id", "source_row", "history", "horizon",
                               "series_column", "projection_ref"} for row in public)
        # Independent expected MAE from the committed evaluation reference asset.
        targets = [json.loads(line) for line in gym.environment_ts.datasets.store.read_asset(fixed["targets"][0]).splitlines()]
        by_id = {row["sample_id"]: row["values"] for row in targets}
        expected = {row["sample_id"]: sum(abs(row["history"][-1] - value) for value in by_id[row["sample_id"]])
                    / row["horizon"] for row in public}
        spec = gym.autobench.resolve_benchmark(args.dataset_id, revision=definition["revision"],
            candidates=[last_value_candidate()], purpose="acceptance", repetitions={"count": 2, "seeds": [11, 29]})
        experiment = experiment_from_case(spec)
        plan = gym.plan(experiment)
        assert plan["resource_checks"] == "deferred_to_open"
        direct = gym.environment_ts.run(experiment)
        assert direct["status"] == "succeeded", direct
        report = gym.autobench.evaluate(spec)
        assert report["verdict"] == "pass", report
        entries = gym.artifacts.read_json(report["run_manifest_ref"])["entries"]
        run_ids = [row["run_id"] for row in entries]
        assert len(run_ids) == 6 and len(set(run_ids)) == 6
        before = {run_id: hashlib.sha256(canonical_json(gym.records.get_run(run_id))).hexdigest() for run_id in run_ids}
        unit_metrics = [row for row in report["metrics"] if row["level"] == "unit" and row["metric_id"] == "mae"]
        assert len(unit_metrics) == 6
        for row in unit_metrics:
            assert abs(row["result"]["value"] - expected[row["group_key"]["evaluation_case_id"]]) < 1e-9, row
        rescored = score_existing(gym, spec, report)
        assert rescored["verdict"] == "pass"
        after = {run_id: hashlib.sha256(canonical_json(gym.records.get_run(run_id))).hexdigest() for run_id in run_ids}
        assert before == after
        summary = {"status": "passed", "source": source, "dataset_revision": fixed["revision"],
            "benchmark_revision": definition["revision"], "public_rows": len(public), "direct_run_id": direct["run_id"],
            "evaluation_run_ids": run_ids, "evaluation_id": report["evaluation_id"],
            "rescore_evaluation_id": rescored["evaluation_id"], "run_records_unchanged": before == after,
            "run_record_sha256": before, "expected_per_series_mae": expected,
            "expected_macro_mae": sum(expected.values()) / len(expected),
            "report": report, "rescore_report": rescored, "source_files": fixed["source_files"],
            "limitations": ["explicit 3-row projection, not complete Monash benchmark", "last-value engineering baseline"]}
    body = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).write_text(body)
    print(body)


if __name__ == "__main__":
    main()
