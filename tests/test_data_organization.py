"""Core source identities and independently readable data from real sealed Runs."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import GymTSError, digest, inline
from gymts.contracts.resources import DATA_CAPTURE, DATA_SOURCE, DATASET
from gymts.environment_ts.datasets import EvaluationDatasets
from gymts.plugins.counter import CounterTransition, IncrementPolicy
from gymts.storage.resources import content_revision


ROOT = Path(__file__).resolve().parents[1]
ALL = {"allowed_uses": ["runtime", "evaluation", "training", "prepare", "dataset_build"], "training_allowed": True}
EVAL = {"allowed_uses": ["evaluation"], "training_allowed": False}


class DataOrganizationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.gym = GymTS(self.root / "runs", data_home=self.root / "data", cache_home=self.root / "cache")
        self.catalog = self.gym.environment_ts.datasets
        self.spec = json.loads((ROOT / "examples/counter_experiment.json").read_text())

    def tearDown(self):
        self.gym.close()
        self.temporary.cleanup()

    def source(self, kind="simulation", *, policy=None, parents=(), name=None, mode=None, seed=7):
        mode = mode or {"static": "snapshot", "synthetic": "seeded", "simulation": "seeded", "live_testbed": "recorded"}[kind]
        definition = {"protocol_version": DATA_SOURCE, "source_id": name or "test/" + kind,
            "config": "default", "revision": None, "kind": kind,
            "provider_ref": {"name": "counter-transition", "version": "1.0.0", "origin_ref": None},
            "configuration": copy.deepcopy({k: self.spec["scene"]["environment"][k] for k in ("source", "mapping", "options")}),
            "recipe": {"generator": "test-fixture", "parameters": {"count": 1}} if kind == "synthetic" else None,
            "reproducibility": {"mode": mode, "seed": seed if mode == "seeded" else None},
            "usage_policy": copy.deepcopy(policy or ALL), "parent_datasets": list(parents), "card_ref": None}
        return self.catalog.register_source(definition, aliases=("release-1",))

    @staticmethod
    def reference(source):
        return {key: source[key] for key in ("source_id", "config", "revision")}

    def capture(self, result, source, **kwargs):
        return self.catalog.capture_run(result["run_id"], source_id=source["source_id"], revision=source["revision"],
            dataset_id="test/captured", **kwargs)

    def test_four_source_kinds_persist_and_unseeded_synthetic_recipes_are_versioned(self):
        for kind in ("static", "synthetic", "simulation", "live_testbed"):
            source = self.source(kind)
            self.assertEqual(source, self.catalog.load_source(source["source_id"], revision="release-1"))
        recorded = self.source("synthetic", name="test/llm-generated", mode="recorded", seed=None)
        changed = copy.deepcopy(recorded)
        changed["revision"] = None
        changed["recipe"]["parameters"]["count"] = 2
        revised = self.catalog.register_source(changed)
        self.assertNotEqual(recorded["revision"], revised["revision"])
        self.assertIsNone(recorded["reproducibility"]["seed"])
        self.assertEqual(6, len(self.catalog.list_sources()))

    def test_static_snapshot_private_targets_and_legacy_manifest_identity(self):
        source = self.source("static", policy=EVAL)
        public = [{"sample_id": "a", "signal": [1, 2, 3]}]
        targets = [{"sample_id": "a", "answer": "PRIVATE_REFERENCE"}]
        fixed = self.catalog.register_snapshot(public, dataset_id="test/static", source_ref=self.reference(source),
            targets=targets, split="heldout", aliases=("release-1",))
        handle = self.catalog.load_dataset("test/static", revision="release-1", split="heldout", purpose="evaluation")
        self.assertEqual(public, list(handle))
        self.assertNotIn("PRIVATE_REFERENCE", json.dumps(handle.info) + json.dumps(list(handle)))
        with self.assertRaises(GymTSError):
            handle.read_asset(fixed["targets"][0])
        evaluator = EvaluationDatasets(self.catalog).load_dataset("test/static", revision=fixed["revision"], split="heldout")
        self.assertEqual(targets, evaluator.read_targets())
        legacy = {key: copy.deepcopy(value) for key, value in fixed.items() if key not in ("kind", "origin", "lineage", "attachments")}
        legacy.update(protocol_version=DATASET, dataset_id="test/legacy", revision=None)
        expected = content_revision(legacy)
        old = self.catalog.register_dataset(legacy)
        self.assertEqual(expected, old["revision"])
        self.assertEqual(old, self.catalog.load_manifest("test/legacy", revision=expected))
        listing = {row["dataset_id"]: row for row in self.catalog.list_datasets()}
        self.assertEqual("static", listing["test/static"]["kind"])
        self.assertNotIn("kind", listing["test/legacy"])

    def test_parent_release_is_frozen_and_existing_run_policy_cannot_be_broadened(self):
        parent_source = self.source("static", policy=EVAL)
        parent = self.catalog.register_snapshot([{"sample_id": "p"}], dataset_id="test/parent",
            source_ref=self.reference(parent_source), aliases=("evaluation-release",))
        reference = {"dataset_id": "test/parent", "config": "default", "revision": "evaluation-release", "split": "test"}
        child = self.source(name="test/derived", parents=(reference,))
        self.assertEqual(parent["revision"], child["parent_datasets"][0]["revision"])
        self.assertEqual(EVAL, child["usage_policy"])
        derived = self.catalog.register_snapshot([{"sample_id": "d"}], dataset_id="test/derived", source_ref=self.reference(child))
        self.assertEqual(parent["revision"], derived["lineage"]["parents"][0]["revision"])
        with self.assertRaises(GymTSError):
            self.catalog.load_dataset("test/derived", revision=derived["revision"], purpose="training")
        source = self.source(name="test/runtime")
        spec = copy.deepcopy(self.spec)
        runtime = {"allowed_uses": ["runtime"], "training_allowed": False}
        spec["provenance"] = {"source_refs": [], "usage_policy_ref": self.gym.artifacts.save_json(runtime, "gymts.source-usage-policy/1"),
            "benchmark_definition_ref": None}
        bound = self.catalog.bind_source(spec, source["source_id"], revision=source["revision"])
        self.assertEqual([], spec["provenance"]["source_refs"])
        result = self.gym.run(bound)
        fixed = self.capture(result, source, usage_policy=ALL)
        self.assertEqual(runtime, fixed["usage_policy"])

    def test_real_simulation_capture_is_idempotent_and_survives_removing_run_store(self):
        source = self.source()
        self.gym.schemas.register("test.capture-context/1", {"type": "object"})
        image = self.gym.artifacts.save_artifact(b"PUBLIC_IMAGE_BYTES", {"media_type": "application/octet-stream"})
        nested = self.gym.artifacts.save_json({"image": image}, "gymts.json/1")
        private_model = self.gym.artifacts.save_artifact(b"PRIVATE_MODEL_WEIGHTS", {"media_type": "application/octet-stream"})
        class BinaryCounter(CounterTransition):
            @staticmethod
            def describe_spec(spec):
                item = CounterTransition.describe_spec(spec)
                item["environment_id"] = "binary-counter"
                item["adapter_ref"]["name"] = "binary-counter"
                item["context_schema_ref"] = "test.capture-context/1"
                return item
            def start(self, spec):
                super().start(spec)
                self.session["environment_id"] = "binary-counter"
                self.session["public_context"]["schema_ref"] = "test.capture-context/1"
                return copy.deepcopy(self.session)
            def observe(self, request):
                batch = super().observe(request)
                batch["context"] = inline({"nested": nested}, "test.capture-context/1")
                return batch
        declaration = self.gym.registries.environments.resolve("counter-transition", "1.0.0")
        declaration["component_ref"]["name"] = "binary-counter"
        self.gym.registries.environments.register(declaration, BinaryCounter, describe=BinaryCounter.describe_spec)
        source = dict(source, source_id="test/binary-counter", revision=None,
            provider_ref={"name": "binary-counter", "version": "1.0.0", "origin_ref": None})
        source = self.catalog.register_source(source)
        spec = copy.deepcopy(self.spec)
        spec["scene"]["environment"]["adapter"] = "binary-counter"
        with patch.object(IncrementPolicy, "finish", return_value=[private_model]):
            result = self.gym.run(self.catalog.bind_source(spec, source["source_id"], revision=source["revision"]))
        self.assertEqual("succeeded", result["status"], result["errors"])
        before = digest(self.gym.records.get_run(result["run_id"]))
        fixed = self.capture(result, source)
        self.assertEqual(fixed, self.capture(result, source))
        self.assertEqual(before, digest(self.gym.records.get_run(result["run_id"])))
        handle = self.catalog.load_dataset("test/captured", revision=fixed["revision"], split="recorded")
        rows, capture = list(handle), handle.read_capture()
        self.gym.schemas.validate(DATA_CAPTURE, capture)
        self.assertEqual(("succeeded", 7, "created"), (capture["status"], capture["seed_used"], capture["ownership"]))
        self.assertEqual(4, capture["observation_count"])
        self.assertTrue(any(row["kind"] == "environment_operation" for row in rows))
        self.assertFalse(any(row["kind"] in ("model_call", "candidate_output", "outcome") for row in rows))
        wrapped = next(row for row in rows if row["kind"] == "observation")["value"]["context"]["value"]["nested"]
        nested_value = handle.resolve_payload(wrapped)
        self.assertEqual(b"PUBLIC_IMAGE_BYTES", handle.resolve_payload(nested_value["image"]))
        self.assertFalse(any(path.read_bytes() == b"PRIVATE_MODEL_WEIGHTS" for path in (self.root / "data/objects").rglob("*") if path.is_file()))
        self.gym.close()
        shutil.rmtree(self.root / "runs")
        self.gym = GymTS(self.root / "new-runs", data_home=self.root / "data", cache_home=self.root / "new-cache")
        restored = self.gym.environment_ts.datasets.load_dataset("test/captured", revision=fixed["revision"], split="recorded")
        self.assertEqual(rows, list(restored))
        self.assertEqual(capture, restored.read_capture())
        self.assertEqual(b"PUBLIC_IMAGE_BYTES", restored.resolve_payload(restored.resolve_payload(wrapped)["image"]))

    def test_failed_run_before_any_observation_remains_failed_empty_snapshot(self):
        source = self.source()
        with patch.object(CounterTransition, "start", side_effect=RuntimeError("backend unavailable")):
            result = self.gym.run(self.spec)
        self.assertEqual("failed", result["status"])
        fixed = self.capture(result, source)
        handle = self.catalog.load_dataset("test/captured", revision=fixed["revision"], split="recorded")
        self.assertEqual([], list(handle))
        self.assertEqual("failed", handle.read_capture()["status"])
        self.assertEqual(0, handle.read_capture()["observation_count"])
        self.assertIsNone(handle.read_capture()["session"])

    def test_different_event_selection_is_a_distinct_fixed_dataset_revision(self):
        source = self.source()
        result = self.gym.run(self.spec)
        all_events = self.capture(result, source)
        observations = self.capture(result, source, event_kinds=["observation"])
        self.assertNotEqual(all_events["revision"], observations["revision"])
        self.assertEqual(observations, self.capture(result, source, event_kinds=["observation"]))
        handle = self.catalog.load_dataset("test/captured", revision=observations["revision"], split="recorded")
        self.assertEqual({"observation"}, {row["kind"] for row in handle})
        with self.assertRaises(GymTSError):
            self.capture(result, source, event_kinds=["candidate_output"])
