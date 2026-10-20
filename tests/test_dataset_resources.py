"""Resource integrity, evaluation-only uses and native benchmark resolution."""
import copy
from datetime import datetime, timedelta, timezone
import json
import multiprocessing
from queue import Empty
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import GymTSError, digest, inline, utc_now
from gymts.contracts.resources import BENCHMARK, DATASET
from gymts.contracts.schema import SchemaRegistry, register_core_schemas
from gymts.environment_ts.datasets import JSONL_READER
from gymts.storage.resources import ResourceStore, _publication_lock, content_revision


BASE = Path(__file__).resolve().parents[1]
RESOLVER = {"name": "test.resource-forecast", "version": "1.0.0", "origin_ref": None}
ROW_SCHEMA = "test.resource-row/1"


class ForecastResolver:
    """Test-only provider: public dataset points drive the existing replay."""
    def resolve(self, definition, resources, candidates, purpose, repetitions):
        reference = definition["datasets"][0]
        dataset = resources.datasets.load_dataset(**reference)
        points, targets = list(dataset), dataset.read_targets()
        result = json.loads((BASE / "examples/forecast_evaluation.json").read_text())
        result["candidates"], result["purpose"] = candidates, purpose
        result["baseline_id"] = candidates[-1]["candidate_id"]
        if repetitions is not None:
            result["repetitions"] = repetitions
        source = result["cases"][0]["scene"]["environment"]["source"]
        source.update(kind="dataset", locator="dataset://test/ramp", revision=reference["revision"],
            connection={"points": [{"timestamp": item["timestamp"], "values": {"value": item["value"]}}
                                    for item in points]})
        now, outcomes = utc_now(), []
        truth = resources.artifacts.save_json(targets, "gymts.json/1")
        for index in range(len(points) - 1):
            alignment = {"entity": "demo", "variable": "value", "issued_at": points[index]["timestamp"],
                         "target_time": points[index + 1]["timestamp"]}
            outcomes.append({"outcome_id": "resource-label-" + digest(alignment), "revision": "1",
                "alignment_key": alignment, "payload": inline({"value": targets[index + 1]["answer"]},
                    "gymts.builtin/forecast-outcome/1"), "event_time": points[index + 1]["timestamp"],
                "available_at": now, "recorded_at": now, "source_ref": truth,
                "supersedes_ref": None, "allowed_uses": ["evaluation"]})
        artifact = resources.artifacts.save_json(outcomes, "gymts.outcome-records/1")
        result["scoring"]["outcomes"] = {"sources": [{"view_id": "resource-evaluation", "revision": artifact["revision"],
            "source_refs": [artifact], "selection": inline({"kind": "all", "source_index": 0}, "gymts.selection/1"),
            "as_of": None, "purpose": "evaluation"}], "as_of": None}
        return result


def _publish_competing_release(data_home, manifest, barrier, results):
    """Independent process: no inherited SQLite connection or shared registry."""
    schemas = SchemaRegistry()
    register_core_schemas(schemas)
    store = ResourceStore(data_home, Path(data_home).parent / "worker-cache", schemas)
    barrier.wait(timeout=15)
    try:
        published = store.publish_definition("dataset", manifest, DATASET, aliases=("racing-release",))
        results.put({"status": "published", "revision": published["revision"]})
    except GymTSError as error:
        results.put({"status": error.code, "revision": content_revision(manifest)})


class DatasetResourceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.gym = GymTS(root / "runs", data_home=root / "data", cache_home=root / "cache")
        self.gym.schemas.register(ROW_SCHEMA, {"type": "object"})
        self.catalog = self.gym.environment_ts.datasets
        self.public = [{"sample_id": str(index), "timestamp": (datetime(2026, 1, 1, tzinfo=timezone.utc)
                        + timedelta(minutes=index)).isoformat().replace("+00:00", "Z"), "value": float(index)}
                       for index in range(12)]
        self.targets = [{"sample_id": str(index), "answer": float(index), "private_marker": "PRIVATE_REFERENCE"}
                        for index in range(12)]
        asset = lambda rows: self.catalog.publish_asset(
            ("\n".join(json.dumps(row) for row in rows) + "\n").encode(), media_type="application/jsonl")
        self.input_asset, self.target_asset = asset(self.public), asset(self.targets)
        self.manifest = {"protocol_version": DATASET, "dataset_id": "test/ramp", "config": "default", "revision": None,
            "schema_ref": ROW_SCHEMA, "reader_ref": JSONL_READER, "features": {"value": "float64"},
            "splits": {"test": {"row_count": 12, "split_origin": "test_fixture", "input_indices": [0], "target_indices": [0]}},
            "usage_policy": {"allowed_uses": ["evaluation"], "training_allowed": False},
            "source_files": [], "importer_ref": RESOLVER, "inputs": [self.input_asset], "series": [],
            "targets": [self.target_asset], "quality_report_ref": None, "card_ref": None}

    def tearDown(self):
        self.gym.close()
        self.directory.cleanup()

    def publish(self):
        return self.catalog.register_dataset(self.manifest, aliases=("1.0.0",))

    def test_fixed_identity_public_projection_and_explicit_evaluation_role(self):
        fixed = self.publish()
        again = self.publish()
        self.assertEqual(fixed, again)
        self.assertEqual(content_revision(fixed), fixed["revision"])
        handle = self.catalog.load_dataset("test/ramp", revision="1.0.0")
        self.assertEqual(12, len(handle))
        self.assertEqual(self.public[0], handle[0])
        self.assertNotIn("PRIVATE_REFERENCE", json.dumps(handle.info) + json.dumps(list(handle)))
        self.assertFalse(hasattr(handle, "read_targets"))
        self.assertNotIn("targets", handle.info)
        self.assertEqual([self.public[3], self.public[1]], list(handle.select([3, 1])))
        self.assertEqual([5, 5, 2], [len(batch) for batch in handle.iter_batches(5)])
        self.assertEqual([fixed["revision"]], [item["revision"] for item in self.catalog.list_datasets()])

    def test_evaluation_only_policy_rejects_training_split_and_prepare_exports(self):
        self.publish()
        for purpose in ("training", "prepare", "dataset_build"):
            with self.subTest(purpose=purpose), self.assertRaises(GymTSError) as error:
                self.catalog.load_dataset("test/ramp", revision="1.0.0", purpose=purpose)
            self.assertEqual("permission_denied", error.exception.code)
        with self.assertRaises(GymTSError):
            self.catalog.load_dataset("test/ramp", revision="1.0.0", split="train")
        bad = copy.deepcopy(self.manifest)
        bad["usage_policy"]["allowed_uses"].append("training")
        with self.assertRaises(GymTSError):
            self.catalog.register_dataset(bad)

    def test_reader_cannot_read_private_assets_outside_its_public_projection(self):
        target = self.target_asset
        class Reader:
            def read(self, services, assets):
                return services.read_asset(target)
        reference = {"name": "test.leaky-reader", "version": "1.0.0", "origin_ref": None}
        self.gym.registries.datasets.register(reference, Reader())
        self.manifest["reader_ref"] = reference
        self.publish()
        handle = self.catalog.load_dataset("test/ramp", revision="1.0.0")
        with self.assertRaises(GymTSError) as error:
            handle[0]
        self.assertEqual("permission_denied", error.exception.code)

    def test_alias_revision_and_asset_tampering_cannot_silently_replace_content(self):
        self.publish()
        bad = copy.deepcopy(self.manifest)
        bad["features"] = {"value": "different"}
        with self.assertRaises(GymTSError) as error:
            self.catalog.register_dataset(bad, aliases=("1.0.0",))
        self.assertEqual("conflict", error.exception.code)
        checksum = self.input_asset["sha256"]
        path = self.catalog.store.root / "objects" / "sha256" / checksum[:2] / checksum
        path.write_bytes(b"tampered")
        handle = self.catalog.load_dataset("test/ramp", revision="1.0.0")
        with self.assertRaises(GymTSError) as error:
            handle[0]
        self.assertEqual("artifact_integrity", error.exception.code)

    def test_generator_release_labels_survive_validation_and_publication_passes(self):
        fixed = self.catalog.register_dataset(self.manifest, aliases=(label for label in ("release-a", "release-b")))
        for label in ("release-a", "release-b"):
            self.assertEqual(fixed["revision"], self.catalog.load_dataset("test/ramp", revision=label).info["revision"])

    def test_competing_processes_cannot_rebind_one_release_label(self):
        context = multiprocessing.get_context("spawn")
        count = 3
        barrier, results = context.Barrier(count + 1), context.Queue()
        alias = self.catalog.store.root / "datasets/test/ramp/default/aliases/racing-release.json"
        alias.parent.mkdir(parents=True)
        processes = []
        try:
            # Hold the actual publication lock until every independent writer
            # starts competing. Ignoring the lock would expose a result here.
            with _publication_lock(alias):
                for index in range(count):
                    manifest = copy.deepcopy(self.manifest)
                    manifest["features"]["competing_definition"] = index
                    process = context.Process(target=_publish_competing_release,
                        args=(str(self.catalog.store.root), manifest, barrier, results))
                    process.start()
                    processes.append(process)
                barrier.wait(timeout=15)
                with self.assertRaises(Empty):
                    results.get(timeout=.4)
            reports = [results.get(timeout=20) for _ in processes]
            for process in processes:
                process.join(timeout=20)
                self.assertEqual(0, process.exitcode)
            winner = [row for row in reports if row["status"] == "published"]
            self.assertEqual(1, len(winner), reports)
            self.assertEqual(count - 1, sum(row["status"] == "conflict" for row in reports), reports)
            original = alias.read_bytes()
            resolved = self.catalog.store.load_definition("dataset", "test/ramp", "racing-release", DATASET, config="default")
            self.assertEqual(winner[0]["revision"], resolved["revision"])
            for row in reports:
                if row["status"] == "conflict":
                    competing = self.catalog.store.load_definition("dataset", "test/ramp", row["revision"], DATASET, config="default")
                    with self.assertRaises(GymTSError) as error:
                        self.catalog.store.publish_definition("dataset", competing, DATASET, aliases=("racing-release",))
                    self.assertEqual("conflict", error.exception.code)
                    self.assertEqual(original, alias.read_bytes())
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=5)
            results.close()

    def test_failed_publication_does_not_create_a_complete_manifest(self):
        self.manifest["inputs"][0] = dict(self.input_asset, sha256="a" * 64, uri="gymts-data://sha256/" + "a" * 64)
        with self.assertRaises(GymTSError):
            self.publish()
        self.assertEqual([], self.catalog.list_datasets())
        for identity in ("../outside", "test/../outside", "/absolute"):
            with self.assertRaises(GymTSError):
                self.catalog.load_dataset(identity, revision="1.0.0")

    def test_benchmark_resolves_existing_protocol_and_evaluation_preserves_provenance(self):
        fixed = self.publish()
        self.gym.registries.benchmarks.register(RESOLVER, ForecastResolver())
        definition = {"protocol_version": BENCHMARK, "benchmark_id": "test/forecast", "revision": None,
            "resolver_ref": RESOLVER, "datasets": [{"dataset_id": "test/ramp", "config": "default",
                "revision": "1.0.0", "split": "test"}], "params": {}, "card_ref": None}
        published = self.gym.autobench.register_benchmark(definition, aliases=("1.0.0",))
        self.assertEqual(fixed["revision"], published["datasets"][0]["revision"])
        candidates = json.loads((BASE / "examples/forecast_evaluation.json").read_text())["candidates"]
        spec = self.gym.autobench.resolve_benchmark("test/forecast", revision="1.0.0", candidates=candidates,
            repetitions={"count": 2, "seeds": [11, 22]})
        self.assertEqual("gymts.evaluation/1", spec["protocol_version"])
        self.assertNotIn("PRIVATE_REFERENCE", json.dumps(spec["cases"]))
        report = self.gym.autobench.evaluate(spec)
        self.assertEqual("pass", report["verdict"])
        executions = self.gym.artifacts.read_json(report["run_manifest_ref"])["entries"]
        self.assertEqual(4, len(executions))
        for entry in executions:
            run = self.gym.records.get_run(entry["run_id"])
            self.assertEqual(spec["provenance"]["source_refs"], run["metadata"]["source_refs"])
            self.assertEqual(spec["provenance"]["usage_policy_ref"], run["metadata"]["usage_policy_ref"])
            self.assertEqual("succeeded", run["result"]["status"])
        self.assertIn(spec["provenance"]["benchmark_definition_ref"], report["evidence_refs"])


if __name__ == "__main__":
    unittest.main()
