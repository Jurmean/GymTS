"""Static resource identity, role separation and native evaluation conformance."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
from unittest.mock import patch

from gymts import GymTS, GymTSError
from gymts.contracts import canonical_json
from gymts_hf_datasets.benchmark import StaticBenchmarkResolver, experiment_from_case, last_value_candidate, score_existing
from gymts_hf_datasets.contracts import PROJECTION
from gymts_hf_datasets.importer import freeze_dataset, register_benchmark
from gymts_hf_datasets.runtime import StaticEnvironment


class RegistrationTests(unittest.TestCase):
    def test_enabling_independent_integration_does_not_import_hf_runtime(self):
        result = subprocess.run([sys.executable, "-I", "-c", "from gymts import GymTS; import sys,tempfile; "
            "t=tempfile.TemporaryDirectory(); "
            "g=GymTS(t.name,integrations=('hf-datasets',)); "
            "assert 'datasets' not in sys.modules; assert 'huggingface_hub' not in sys.modules; g.close()"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unsupported_definition_semantics_do_not_open_any_resource(self):
        with self.assertRaises(GymTSError) as error:
            StaticBenchmarkResolver().resolve({"datasets": [{}], "params": {"scope": "all_frozen_rows"}},
                                             None, [], "regression", None)
        self.assertEqual(error.exception.code, "unsupported_capability")


class HFStaticTests(unittest.TestCase):
    def setUp(self):
        try:
            import datasets
        except ImportError:
            self.skipTest("optional HF runtime not installed")
        self.datasets = datasets
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.gym = GymTS(self.root / "runs", data_home=self.root / "data", cache_home=self.root / "cache",
                         integrations=("hf-datasets",))
        self.source_file = self.root / "source.jsonl"
        self.source_file.write_text("\n".join(json.dumps(row) for row in [
            {"target": [0, 1, 2, 3, 10, 20], "private_note": "PRIVATE GOLD"},
            {"target": [9, 8, 7, 6, 5, 4], "private_note": "PRIVATE GOLD"}]) + "\n")
        self.source = {"mode": "local_files", "format": "json", "files": [str(self.source_file)], "split": "test"}

    def tearDown(self):
        if hasattr(self, "gym"):
            self.gym.close()
            self.tmp.cleanup()

    def freeze(self, source=None, dataset_id="test/hf"):
        return freeze_dataset(self.gym, dataset_id, source or self.source, series_column="target",
            horizon=2, context_length=3, aliases=("1.0.0",), cache_dir=self.root / "hf-cache")

    def spec(self):
        fixed = self.freeze()
        register_benchmark(self.gym, "test/hf", revision=fixed["revision"], aliases=("1.0.0",))
        return self.gym.autobench.resolve_benchmark("test/hf", revision="1.0.0", candidates=[last_value_candidate()],
            repetitions={"count": 2, "seeds": [3, 19]})

    def test_real_hf_local_files_fixed_identity_and_private_reference_projection(self):
        first, second = self.freeze(), self.freeze()
        self.assertEqual(first, second)
        handle = self.gym.environment_ts.datasets.load_dataset("test/hf", revision="1.0.0")
        self.assertEqual(handle[0]["history"], [1, 2, 3])
        self.assertEqual(handle[1]["history"], [8, 7, 6])
        self.assertNotIn("PRIVATE GOLD", json.dumps(list(handle)) + json.dumps(handle.info))
        self.assertFalse(hasattr(handle, "read_targets"))
        self.assertNotIn("targets", handle.info)
        self.assertEqual([row["sample_id"] for row in handle.to_hf()], handle.sample_ids())
        for purpose in ("training", "prepare", "dataset_build"):
            with self.subTest(purpose=purpose), self.assertRaises(GymTSError) as error:
                self.gym.environment_ts.datasets.load_dataset("test/hf", revision="1.0.0", purpose=purpose)
            self.assertEqual(error.exception.code, "permission_denied")
        self.source_file.unlink()
        self.assertEqual(handle[0]["history"], [1, 2, 3])
        original = first["source_files"][0]["asset_ref"]
        self.assertEqual(hashlib.sha256(self.gym.environment_ts.datasets.store.read_asset(original)).hexdigest(), original["sha256"])

    def test_real_save_to_disk_datasetdict_and_explicit_unsplit_name(self):
        saved = self.root / "saved"
        data = self.datasets.Dataset.from_dict({"target": [[1, 2, 3, 4, 5, 6]]})
        self.datasets.DatasetDict({"validation": data}).save_to_disk(str(saved))
        source = {"mode": "save_to_disk", "path": str(saved), "split": "validation"}
        fixed = self.freeze(source, "test/saved")
        public = self.gym.environment_ts.datasets.load_dataset("test/saved", revision=fixed["revision"])
        self.assertEqual(public[0]["history"], [2, 3, 4])
        self.assertEqual(fixed["splits"]["test"]["split_origin"], "explicit_evaluation_view_of_validation")
        self.assertTrue(any(row["name"].endswith(".arrow") for row in fixed["source_files"]))
        unsplit = self.root / "unsplit"
        data.save_to_disk(str(unsplit))
        with self.assertRaises(GymTSError):
            self.freeze({"mode": "save_to_disk", "path": str(unsplit), "split": "test"}, "test/unsplit")
        self.freeze({"mode": "save_to_disk", "path": str(unsplit), "split": "data"}, "test/unsplit")

    def test_pure_plan_then_native_run_evaluate_and_same_run_rescore(self):
        spec = self.spec()
        experiment = experiment_from_case(spec)
        with patch.object(StaticEnvironment, "__init__", side_effect=AssertionError("opened during plan")), \
             patch.object(self.datasets, "load_dataset", side_effect=AssertionError("HF read during plan")), \
             patch.object(self.gym.artifacts, "read_json", side_effect=AssertionError("CAS read during plan")):
            plan = self.gym.plan(experiment)
            self.assertEqual(plan["resource_checks"], "deferred_to_open")
        direct = self.gym.environment_ts.run(experiment)
        self.assertEqual(direct["status"], "succeeded")
        report = self.gym.autobench.evaluate(spec)
        self.assertEqual(report["verdict"], "pass")
        aggregate = next(row for row in report["metrics"] if row["level"] == "aggregate" and row["metric_id"] == "mae")
        self.assertEqual(aggregate["result"]["value"], 6.75)
        entries = self.gym.artifacts.read_json(report["run_manifest_ref"])["entries"]
        self.assertEqual(len(entries), 4)
        run_ids = [row["run_id"] for row in entries]
        before = {run_id: canonical_json(self.gym.records.get_run(run_id)) for run_id in run_ids}
        with patch.object(StaticEnvironment, "__init__", side_effect=AssertionError("opened during re-score")):
            rescored = score_existing(self.gym, spec, report)
        self.assertEqual(rescored["verdict"], "pass")
        self.assertEqual(before, {run_id: canonical_json(self.gym.records.get_run(run_id)) for run_id in run_ids})
        for run_id in run_ids:
            run = self.gym.records.get_run(run_id)
            self.assertEqual(run["metadata"]["source_refs"], spec["provenance"]["source_refs"])
            for event in run["events"]:
                if event["kind"] == "input":
                    self.assertNotIn("PRIVATE GOLD", json.dumps(event))

    def test_missing_snapshot_is_deferred_to_open_and_sealed_failed_run(self):
        experiment = experiment_from_case(self.spec())
        ref = experiment["scene"]["environment"]["source"]["connection"]["artifact_refs"][0]
        bad = copy.deepcopy(ref)
        bad.update(artifact_id="sha256:" + "f" * 64, revision="sha256:" + "f" * 64, content_hash="f" * 64)
        experiment["scene"]["environment"]["source"]["connection"]["artifact_refs"] = [bad]
        self.gym.plan(experiment)
        result = self.gym.run(experiment)
        self.assertEqual(result["status"], "failed")
        record = self.gym.records.get_run(result["run_id"])
        self.assertEqual(record["result"]["status"], "failed")
        self.assertTrue(record["events"])

    def test_fixed_hub_commit_exact_files_selection_and_projection_validation(self):
        bad = {"mode": "hub", "repo_id": "does/not-matter", "revision": "main", "format": "parquet",
               "files": ["test.parquet"], "split": "test"}
        with self.assertRaises(GymTSError) as error:
            self.freeze(bad)
        self.assertEqual(error.exception.code, "invalid_config")
        bad["revision"] = "a" * 40
        bad["files"] = ["data/*.parquet"]
        with self.assertRaises(GymTSError):
            self.freeze(bad)
        for indices in ([0, 0], [2], []):
            with self.subTest(indices=indices), self.assertRaises(GymTSError):
                freeze_dataset(self.gym, "test/bad", self.source, series_column="target", horizon=2,
                               context_length=3, sample_indices=indices, cache_dir=self.root / "hf-cache")
        self.assertEqual(self.gym.environment_ts.datasets.list_datasets(), [])

    def test_unsupported_definition_semantics_rejected_before_resources(self):
        params = {"projection_ref": PROJECTION, "scope": "all_frozen_rows", "metrics": ["mae"]}
        for change in ({"selection": [0]}, {"metrics": ["accuracy"]}, {"projection_ref": "other/1"}):
            with self.subTest(change=change), self.assertRaises(GymTSError) as error:
                StaticBenchmarkResolver().resolve({"params": dict(params, **change), "datasets": [{}]}, None, [], "regression", None)
            self.assertEqual(error.exception.code, "unsupported_capability")


if __name__ == "__main__":
    unittest.main()
