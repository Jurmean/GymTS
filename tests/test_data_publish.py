"""CPU contract fixtures for portable publication, not model-training evidence."""
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from gymts import GymTS
from gymts.cli import main as cli_main
from gymts.contracts import GymTSError, canonical_json, inline, utc_now
from gymts.contracts.resources import DATASET, DATA_SOURCE
from gymts.environment_ts.datasets import JSONL_READER
from gymts.storage.resources import content_revision
from gymts.training import DatasetBuilderRegistry, build_dataset


ROOT = Path(__file__).resolve().parents[1]
BUILDER = {"name": "test.publication-builder", "version": "1.0.0", "origin_ref": None}
READER = {"name": "test.publication-reader", "version": "1.0.0", "origin_ref": None}
ROW = "test.published-training-row/1"
TRAIN = {"allowed_uses": ["dataset_build", "prepare", "training"], "training_allowed": True}
ALL = {"allowed_uses": ["runtime", "evaluation", "training", "prepare", "dataset_build"], "training_allowed": True}


class DocumentReader:
    """An independently registered codec, deliberately not the JSONL reader."""
    def read(self, store, assets):
        return [row for asset in assets for row in json.loads(store.read_asset(asset))["rows"]]


class FixtureBuilder:
    builder_ref = BUILDER
    target_formats = ("sft",)
    output_schema_refs = (ROW,)

    def build(self, spec, records, artifacts):
        tensor = artifacts.save_artifact(b"fixture-token-mask-bytes", {"media_type": "application/octet-stream"})
        tokenizer = artifacts.save_json({"token_mask": tensor, "fixture": True}, "gymts.json/1")
        shard = artifacts.save_json({"rows": [{"sample_id": "a", "messages": ["example-a"]},
            {"sample_id": "b", "messages": ["example-b"]}]}, ROW)
        reward = artifacts.save_json({"private_reward_note": "PRIVATE_BUILD_REFERENCE", "tensor": tensor}, "gymts.json/1")
        return {"protocol_version": "gymts.dataset/1", "dataset_id": "test/built", "revision": "builder-content-v1",
            "build_id": spec["build_id"], "builder_ref": BUILDER,
            "build_spec_ref": artifacts.save_json(spec, "gymts.dataset-build/1"),
            "input_snapshot_refs": spec["input_snapshots"], "output_schema_ref": ROW,
            "shards": [{"split": "train", "artifact_ref": shard, "sample_count": 2}],
            "counts": {"input_units": 1, "accepted_samples": 2, "excluded_units": 0},
            "lineage_ref": artifacts.save_json({"protocol_version": "gymts.lineage/1", "records": []}, "gymts.lineage/1"),
            "exclusion_summary_ref": artifacts.save_json({"counts": {}, "records": []}, "gymts.training/exclusions/1"),
            "tokenization_ref": tokenizer, "reward_refs": [reward], "created_at": utc_now()}


class BuildPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gymts-data-publish-")
        self.root = Path(self.temporary.name)
        self.gym = GymTS(self.root / "runs", data_home=self.root / "data", cache_home=self.root / "cache")
        self.install_codec(self.gym)
        self.catalog = self.gym.environment_ts.datasets
        self.experiment = json.loads((ROOT / "examples/counter_experiment.json").read_text())
        self.experiment["purpose"] = "training_collection"
        self.experiment["provenance"] = {"source_refs": [], "usage_policy_ref":
            self.gym.artifacts.save_json(TRAIN, "gymts.source-usage-policy/1"), "benchmark_definition_ref": None}
        result = self.gym.run(self.experiment)
        self.assertEqual("succeeded", result["status"])
        self.run_id = result["run_id"]
        snapshot = self.gym.records.snapshot([self.run_id])["snapshot_ref"]
        self.spec = {"protocol_version": "gymts.dataset-build/1", "build_id": "publication-fixture", "name": None,
            "builder_ref": BUILDER, "input_snapshots": [snapshot],
            "target": {"format": "sft", "schema_ref": ROW, "backend_ref": None},
            "selection": inline({}, "gymts.json/1"), "episode_mapping": inline({}, "gymts.json/1"),
            "splits": inline({}, "gymts.json/1"), "transforms": [], "reward_mapping": None,
            "pairing": None, "tokenization": None, "missing_data_policy": "reject_build", "require_sealed_runs": True}
        builders = DatasetBuilderRegistry(discover=False)
        builders.register(BUILDER, FixtureBuilder())
        self.build = build_dataset(self.spec, self.gym.records, self.gym.artifacts, builders=builders)

    @staticmethod
    def install_codec(gym):
        gym.schemas.register(ROW, {"type": "object"})
        gym.registries.datasets.register(READER, DocumentReader())

    def tearDown(self):
        self.gym.close()
        self.temporary.cleanup()

    def publish(self, build=None, **kwargs):
        return self.catalog.publish_build(self.build if build is None else build, reader_ref=READER, **kwargs)

    def parent(self, policy):
        asset = self.catalog.publish_asset(b'{"sample_id":"parent"}\n', media_type="application/jsonl")
        item = {"protocol_version": DATASET, "dataset_id": "test/parent", "config": "default", "revision": None,
            "schema_ref": "gymts.json/1", "reader_ref": JSONL_READER, "features": {},
            "splits": {"train": {"row_count": 1, "split_origin": "fixture", "input_indices": [0], "target_indices": []}},
            "usage_policy": policy, "source_files": [], "importer_ref": BUILDER, "inputs": [asset],
            "series": [], "targets": [], "quality_report_ref": None, "card_ref": None}
        item = self.catalog.register_dataset(item, aliases=("v1",))
        return {key: item[key] for key in ("dataset_id", "config", "revision")} | {"split": "train"}

    def test_publication_preserves_codec_shard_bytes_and_all_private_evidence_after_run_deletion(self):
        parent = self.parent(TRAIN)
        fixed = self.publish(parents=(dict(parent, revision="v1"),), aliases=("v1",))
        self.assertEqual(DATASET, fixed["protocol_version"])
        self.assertEqual(READER, fixed["reader_ref"])
        self.assertEqual(ROW, fixed["schema_ref"])
        self.assertEqual(TRAIN, fixed["usage_policy"])
        self.assertEqual([parent], fixed["features"]["parent_datasets"])
        shard_bytes = Path(self.gym.artifacts.resolve(self.build["shards"][0]["artifact_ref"])).read_bytes()
        self.assertEqual(shard_bytes, self.catalog.store.read_asset(fixed["inputs"][0]))
        self.assertEqual(fixed, self.publish(parents=(parent,)))
        source_files = {item["name"]: item["asset_ref"] for item in fixed["source_files"]}
        original = json.loads(self.catalog.store.read_asset(source_files["build-manifest.json"]))
        self.assertEqual(original, self.gym.artifacts.read_json(self.build["manifest_ref"]))
        proof = json.loads(self.catalog.store.read_asset(source_files["build-provenance.json"]))
        self.assertEqual(self.run_id, proof["runs"][0]["run_id"])
        self.assertTrue(proof["runs"][0]["event_refs"])
        self.assertTrue(proof["runs"][0]["execution_snapshot_ref"])
        self.assertEqual([parent], proof["parent_datasets"])
        self.assertTrue(any(item["source_artifact"]["schema_ref"] == "gymts.record-snapshot/1" for item in proof["artifact_index"]))
        token = next(item for item in proof["artifact_index"] if item["source_artifact"]["media_type"] == "application/octet-stream")
        handle = self.catalog.load_dataset(fixed["dataset_id"], revision="v1", split="train", purpose="training")
        rows = list(handle)
        self.assertNotIn("PRIVATE_BUILD_REFERENCE", json.dumps(rows) + json.dumps(handle.info))
        with self.assertRaises(GymTSError):
            handle.read_asset(source_files["build-provenance.json"])
        self.gym.close()
        shutil.rmtree(self.root / "runs")
        self.gym = GymTS(self.root / "new-runs", data_home=self.root / "data", cache_home=self.root / "fresh-cache")
        self.install_codec(self.gym)
        restored = self.gym.environment_ts.datasets.load_dataset(fixed["dataset_id"], revision="v1", split="train", purpose="training")
        self.assertEqual(rows, list(restored))
        store = self.gym.environment_ts.datasets.store
        self.assertEqual(b"fixture-token-mask-bytes", store.read_asset(token["original_asset"]))
        for entry in proof["artifact_index"]:
            store.read_asset(entry["original_asset"])
            store.read_asset(entry["portable_asset"])

    def test_reference_input_and_requested_policy_cannot_add_runtime_or_evaluation(self):
        fixed = self.publish(self.build["manifest_ref"], usage_policy=ALL)
        self.assertEqual(TRAIN, fixed["usage_policy"])
        for purpose in ("runtime", "evaluation"):
            with self.subTest(purpose=purpose), self.assertRaises(GymTSError):
                self.catalog.load_dataset(fixed["dataset_id"], revision=fixed["revision"], split="train", purpose=purpose)
        narrowed = self.publish(usage_policy={"allowed_uses": ["training"], "training_allowed": True})
        self.assertEqual(["training"], narrowed["usage_policy"]["allowed_uses"])
        self.assertNotEqual(fixed["revision"], narrowed["revision"])

    def test_organization_publish_stage_and_cli_persist_readable_data_after_original_store_removal(self):
        parent = self.parent(TRAIN)
        publication = {"manifest": None, "reader_ref": READER, "dataset_id": "test/group-published",
            "parents": [parent], "aliases": ["v1"]}
        definition = self.gym.experiments.register({"group_id": "test/publish-export", "name": "CPU build-publication fixture",
            "stages": [{"stage_id": "publish", "executor_ref": {"name": "gymts.publish-build", "version": "1.0.0", "origin_ref": None},
                "spec": publication, "inputs": {"build": {"kind": "artifact", "ref": self.build["manifest_ref"]}},
                "bindings": {"build": "/manifest"}, "outputs": {"dataset": ""}}]})
        state = self.gym.experiments.execute(definition["group_id"], revision=definition["revision"])
        self.assertEqual("succeeded", state["status"], state)
        self.assertEqual(1, len(state["attempts"]))
        attempt = state["attempts"][0]
        self.assertEqual("succeeded", attempt["status"])
        fixed = self.gym.artifacts.read_json(attempt["result_ref"])
        self.assertEqual(fixed, attempt["outputs"]["dataset"])
        self.assertEqual(self.build["manifest_ref"], self.gym.artifacts.read_json(attempt["request_ref"])["spec"]["manifest"])
        files = {item["name"] for item in fixed["source_files"]}
        self.assertTrue({"build-manifest.json", "build-provenance.json"} <= files)
        for filters in ({"dataset_id": parent["dataset_id"]},
                        {"dataset_id": parent["dataset_id"], "dataset_revision": parent["revision"]}):
            matches = self.gym.experiments.query(**filters)
            self.assertIn(definition["group_id"], [item["group_id"] for item in matches])
        self.assertEqual([], self.gym.experiments.query(dataset_id=parent["dataset_id"], dataset_revision="sha256:" + "0" * 64))
        self.assertEqual([], self.gym.experiments.query(dataset_id="test/unrelated-data"))
        events = self.gym.experiments.store.events(definition["group_id"], definition["revision"])
        self.assertEqual(["registered", "attempt_started", "attempt_finished"], [event["kind"] for event in events])
        # The real CLI opens another GymTS instance against the same local store;
        # no codec is invoked during publication and its external identity stays fixed.
        cli_spec = dict(publication, manifest=self.build["manifest_ref"], dataset_id="test/cli-published")
        spec_path, output_path = self.root / "publish.json", self.root / "published.json"
        spec_path.write_text(json.dumps(cli_spec))
        with redirect_stdout(io.StringIO()):
            exit_status = cli_main(["--store", str(self.root / "runs"), "--data-home", str(self.root / "data"),
                "--cache-home", str(self.root / "cli-cache"), "datasets", "publish-build", str(spec_path),
                "--output", str(output_path)])
        self.assertEqual(0, exit_status)
        cli_fixed = json.loads(output_path.read_text())
        self.assertEqual(READER, cli_fixed["reader_ref"])
        self.assertEqual(fixed["source_files"], cli_fixed["source_files"])
        self.gym.close()
        shutil.rmtree(self.root / "runs")
        self.gym = GymTS(self.root / "fresh-runs", data_home=self.root / "data", cache_home=self.root / "fresh-cache")
        self.install_codec(self.gym)
        for manifest in (fixed, cli_fixed):
            handle = self.gym.environment_ts.datasets.load_dataset(manifest["dataset_id"], revision="v1", split="train", purpose="training")
            self.assertEqual(["a", "b"], handle.sample_ids())
            for entry in manifest["source_files"]:
                self.gym.environment_ts.datasets.store.read_asset(entry["asset_ref"])

    def test_parent_evaluation_policy_cannot_be_overridden(self):
        parent = self.parent({"allowed_uses": ["evaluation"], "training_allowed": False})
        with self.assertRaises(GymTSError) as error:
            self.publish(parents=(parent,), usage_policy=ALL)
        self.assertEqual("permission_denied", error.exception.code)
        self.assertFalse(any(row["dataset_id"] == "test/built" for row in self.catalog.list_datasets()))

    def test_parent_resource_assets_must_exist_in_the_selected_data_home(self):
        parent = self.parent(TRAIN)
        item = self.catalog.load_manifest(parent["dataset_id"], revision=parent["revision"])
        asset = item["inputs"][0]
        (self.root / "data" / "objects" / "sha256" / asset["sha256"][:2] / asset["sha256"]).unlink()
        with self.assertRaises(GymTSError) as error:
            self.publish(parents=(parent,))
        self.assertEqual("artifact_unavailable", error.exception.code)
        self.assertFalse(any(row["dataset_id"] == "test/built" for row in self.catalog.list_datasets()))

    def test_parent_json_lineage_recursively_retains_its_cas_dependency(self):
        parent = self.parent(TRAIN)
        item = self.catalog.load_manifest(parent["dataset_id"], revision=parent["revision"])
        source_only = self.gym.artifacts.save_artifact(b"parent-only-dependency", {"media_type": "application/octet-stream"})
        lineage = self.catalog.publish_asset(canonical_json({"source_only": source_only}), media_type="application/json")
        item["revision"] = None
        item["source_files"] = [{"name": "parent-lineage.json", "asset_ref": lineage}]
        revised = self.catalog.register_dataset(item)
        parent["revision"] = revised["revision"]
        fixed = self.publish(parents=(parent,))
        proof_ref = next(item["asset_ref"] for item in fixed["source_files"] if item["name"] == "build-provenance.json")
        proof = json.loads(self.catalog.store.read_asset(proof_ref))
        retained = next(item for item in proof["artifact_index"] if item["source_artifact"] == source_only)
        self.assertEqual(b"parent-only-dependency", self.catalog.store.read_asset(retained["original_asset"]))
        self.assertTrue(proof["source_asset_documents"])

    def test_source_ref_parent_policy_is_inherited_even_without_direct_run_policy(self):
        parent = self.parent({"allowed_uses": ["evaluation"], "training_allowed": False})
        source = {"protocol_version": DATA_SOURCE, "source_id": "test/legacy-metadata", "config": "default",
            "revision": None, "kind": "simulation", "provider_ref": {"name": "counter-transition", "version": "1.0.0", "origin_ref": None},
            "configuration": {}, "recipe": None, "reproducibility": {"mode": "recorded", "seed": None},
            "usage_policy": ALL, "parent_datasets": [parent], "card_ref": None}
        # A schema-valid historical reference is not assumed to have inherited
        # its parent's permission correctly; publication resolves that parent.
        source["revision"] = content_revision(source)
        experiment = copy.deepcopy(self.experiment)
        experiment["purpose"] = "development"
        experiment["provenance"]["usage_policy_ref"] = None
        experiment["provenance"]["source_refs"] = [self.gym.artifacts.save_json(source, DATA_SOURCE)]
        run = self.gym.run(experiment)
        spec = copy.deepcopy(self.spec)
        spec["input_snapshots"] = [self.gym.records.snapshot([run["run_id"]])["snapshot_ref"]]
        raw = FixtureBuilder().build(spec, self.gym.records, self.gym.artifacts)
        with self.assertRaises(GymTSError) as error:
            self.publish(raw, usage_policy=ALL)
        self.assertEqual("permission_denied", error.exception.code)

    def test_changed_saved_manifest_and_build_spec_are_rejected(self):
        changed = copy.deepcopy(self.build)
        changed["build_id"] = "substituted"
        with self.assertRaises(GymTSError):
            self.publish(changed)
        changed.pop("manifest_ref")
        with self.assertRaises(GymTSError):
            self.publish(changed)

    def test_missing_transitive_artifact_does_not_publish_a_dataset(self):
        ref = self.build["tokenization_ref"]
        nested = self.gym.artifacts.read_json(ref)["token_mask"]
        Path(self.gym.artifacts.resolve(nested)).unlink()
        with self.assertRaises(GymTSError):
            self.publish()
        self.assertEqual([], self.catalog.list_datasets())

    def test_prefix_snapshot_cannot_be_published_as_sealed_evidence(self):
        spec = copy.deepcopy(self.spec)
        spec["input_snapshots"] = [self.gym.records.snapshot([self.run_id], {"through_seq": {self.run_id: 1}})["snapshot_ref"]]
        raw = FixtureBuilder().build(spec, self.gym.records, self.gym.artifacts)
        with self.assertRaises(GymTSError) as error:
            self.publish(raw)
        self.assertEqual("invalid_state", error.exception.code)

    def test_explicit_prefix_keeps_its_boundary_without_copying_later_run_events(self):
        spec = copy.deepcopy(self.spec)
        spec["require_sealed_runs"] = False
        spec["input_snapshots"] = [self.gym.records.snapshot([self.run_id], {"through_seq": {self.run_id: 1}})["snapshot_ref"]]
        raw = FixtureBuilder().build(spec, self.gym.records, self.gym.artifacts)
        fixed = self.publish(raw)
        proof_ref = next(item["asset_ref"] for item in fixed["source_files"] if item["name"] == "build-provenance.json")
        proof = json.loads(self.catalog.store.read_asset(proof_ref))
        run = proof["runs"][0]
        self.assertEqual("running", run["snapshot_entry"]["status"])
        self.assertTrue(all(event["seq"] <= 1 for event in run["events"]))
        self.assertIsNone(run["result_ref"])
        self.assertIsNone(run["execution_snapshot_ref"])

    def test_multiple_splits_preserve_their_reader_assets_and_empty_exports_are_readable(self):
        raw = {key: copy.deepcopy(value) for key, value in self.build.items() if key != "manifest_ref"}
        extra = self.gym.artifacts.save_json({"rows": [{"sample_id": "c", "messages": ["held-back"]}]}, ROW)
        raw["shards"].append({"split": "validation", "artifact_ref": extra, "sample_count": 1})
        raw["counts"]["accepted_samples"] = 3
        fixed = self.publish(raw)
        validation = self.catalog.load_dataset(fixed["dataset_id"], revision=fixed["revision"], split="validation", purpose="training")
        self.assertEqual(["c"], validation.sample_ids())
        training = self.catalog.load_dataset(fixed["dataset_id"], revision=fixed["revision"], split="train", purpose="training")
        self.assertEqual(["a", "b"], training.sample_ids())
        raw["shards"] = []
        raw["counts"]["accepted_samples"] = 0
        empty = self.publish(raw, dataset_id="test/empty-build")
        self.assertEqual([], list(self.catalog.load_dataset("test/empty-build", revision=empty["revision"], split="train", purpose="training")))


if __name__ == "__main__":
    unittest.main()
