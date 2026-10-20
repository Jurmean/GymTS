"""External builders dispatch through fixed public services and Manifest identity."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import GymTSError, digest, inline, utc_now
from gymts.training import DatasetBuilderRegistry, build_dataset

REF = {"name": "independent-builder", "version": "1", "origin_ref": None}


class IndependentBuilder:
    builder_ref = REF
    target_formats = ("sft",)
    output_schema_refs = ("independent.messages/1",)

    def build(self, spec, records, artifacts):
        self.received = (spec, records, artifacts)
        spec_ref = artifacts.save_json(spec, "gymts.dataset-build/1")
        lineage = artifacts.save_json({"protocol_version": "gymts.lineage/1", "records": []}, "gymts.lineage/1")
        exclusions = artifacts.save_json({"counts": {}, "records": []}, "gymts.training/exclusions/1")
        manifest = {"protocol_version": "gymts.dataset/1", "dataset_id": "independent", "revision": "fixed-revision",
            "build_id": spec["build_id"], "build_spec_ref": spec_ref, "builder_ref": copy.deepcopy(REF),
            "input_snapshot_refs": spec["input_snapshots"], "output_schema_ref": "independent.messages/1",
            "shards": [], "counts": {"input_units": 0, "accepted_samples": 0, "excluded_units": 0},
            "lineage_ref": lineage, "exclusion_summary_ref": exclusions, "tokenization_ref": None,
            "reward_refs": [], "created_at": utc_now()}
        return manifest


class Entry:
    def __init__(self, name, factory):
        self.name, self.factory, self.loads = name, factory, 0

    def load(self):
        self.loads += 1
        return self.factory


class TrainingServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.gym = GymTS(Path(self.directory.name))
        snapshot = self.gym.records.snapshot([])
        self.spec = {"protocol_version": "gymts.dataset-build/1", "build_id": "independent-build", "name": None,
            "builder_ref": copy.deepcopy(REF), "input_snapshots": [snapshot["snapshot_ref"]],
            "target": {"format": "sft", "schema_ref": "independent.messages/1", "backend_ref": None},
            "selection": inline({}, "independent.selection/1"), "episode_mapping": inline({}, "independent.episodes/1"),
            "splits": inline({}, "independent.splits/1"), "transforms": [], "reward_mapping": None,
            "pairing": None, "tokenization": None, "missing_data_policy": "reject_build", "require_sealed_runs": True}

    def tearDown(self):
        self.gym.close()
        self.directory.cleanup()

    def registry(self, provider=None):
        registry = DatasetBuilderRegistry(discover=False)
        registry.register(REF, provider or IndependentBuilder())
        return registry

    def test_independent_provider_needs_only_records_artifacts_and_fixed_spec(self):
        provider = IndependentBuilder()
        before = copy.deepcopy(self.spec)
        result = build_dataset(self.spec, self.gym.records, self.gym.artifacts, builders=self.registry(provider))
        self.assertEqual(self.spec, before)
        self.assertIs(provider.received[1], self.gym.records)
        self.assertIs(provider.received[2], self.gym.artifacts)
        self.assertEqual(result["revision"], "fixed-revision")  # Providers own revision conventions.
        self.assertEqual(self.gym.artifacts.read_json(result["manifest_ref"]),
                         {key: value for key, value in result.items() if key != "manifest_ref"})
        self.assertFalse(hasattr(provider, "gym"))

    def test_evaluation_only_source_cannot_be_exported_by_another_profile(self):
        import json
        policy_ref = self.gym.artifacts.save_json({"allowed_uses": ["evaluation"], "training_allowed": False},
                                                  "gymts.source-usage-policy/1")
        spec = json.loads((Path(__file__).resolve().parents[1] / "examples/forecast_experiment.json").read_text())
        spec["provenance"] = {"source_refs": [], "usage_policy_ref": policy_ref, "benchmark_definition_ref": None}
        result = self.gym.run(spec)
        self.assertEqual("succeeded", result["status"])
        self.spec["input_snapshots"] = [self.gym.records.snapshot([result["run_id"]])["snapshot_ref"]]
        provider = IndependentBuilder()
        with self.assertRaises(GymTSError) as caught:
            build_dataset(self.spec, self.gym.records, self.gym.artifacts, builders=self.registry(provider))
        self.assertEqual("permission_denied", caught.exception.code)
        self.assertFalse(hasattr(provider, "received"))

    def test_entry_point_loads_only_selected_fixed_provider(self):
        selected = Entry(REF["name"], IndependentBuilder)
        unused = Entry("another-project", lambda: self.fail("Unselected provider imported"))
        with patch("gymts.training.service.entry_points", return_value={"gymts.dataset_builders": [selected, unused]}):
            build_dataset(self.spec, self.gym.records, self.gym.artifacts)
        self.assertEqual((selected.loads, unused.loads), (1, 0))

    def test_absent_conflicting_and_wrong_version_providers_are_explicit(self):
        for entries, code in (([], "unsupported_capability"),
                              ([Entry(REF["name"], IndependentBuilder)] * 2, "conflict")):
            with self.subTest(code=code), patch("gymts.training.service.entry_points", return_value={"gymts.dataset_builders": entries}):
                with self.assertRaises(GymTSError) as error:
                    build_dataset(self.spec, self.gym.records, self.gym.artifacts)
                self.assertEqual(error.exception.code, code)
                self.assertTrue(all(entry.loads == 0 for entry in entries))
        wrong = copy.deepcopy(REF)
        wrong["version"] = "2"
        with self.assertRaises(GymTSError):
            self.registry().resolve(wrong)

    def test_unknown_schema_is_rejected_before_provider_runs(self):
        provider = IndependentBuilder()
        self.spec["target"]["schema_ref"] = "unknown/1"
        with self.assertRaises(GymTSError) as error:
            build_dataset(self.spec, self.gym.records, self.gym.artifacts, builders=self.registry(provider))
        self.assertEqual(error.exception.code, "unsupported_capability")
        self.assertFalse(hasattr(provider, "received"))

    def test_provider_cannot_substitute_build_id_snapshot_or_saved_spec(self):
        for field in ("build_id", "input_snapshot_refs", "build_spec_ref"):
            class Substituted(IndependentBuilder):
                def build(inner, spec, records, artifacts):
                    result = super().build(spec, records, artifacts)
                    if field == "build_spec_ref":
                        wrong = dict(spec, name="different selection")
                        result[field] = artifacts.save_json(wrong, "gymts.dataset-build/1")
                    else:
                        result[field] = "different" if field == "build_id" else []
                    return result
            with self.subTest(field=field), self.assertRaises(GymTSError):
                build_dataset(self.spec, self.gym.records, self.gym.artifacts, builders=self.registry(Substituted()))

    def test_published_manifest_cannot_differ_from_returned_envelope(self):
        class Substituted(IndependentBuilder):
            def build(inner, spec, records, artifacts):
                result = super().build(spec, records, artifacts)
                reference = artifacts.save_json(result, "gymts.dataset/1")
                return dict(result, dataset_id="shadow", manifest_ref=reference)
        with self.assertRaisesRegex(GymTSError, "Published Manifest differs"):
            build_dataset(self.spec, self.gym.records, self.gym.artifacts, builders=self.registry(Substituted()))

    def test_mutable_public_mapper_transform_and_backend_refs_are_rejected(self):
        for field in ("mapper", "transform", "backend"):
            spec = copy.deepcopy(self.spec)
            mutable = {"name": "external-component", "version": "latest", "origin_ref": None}
            if field == "mapper":
                spec["reward_mapping"] = {"mapper_ref": mutable, "params": {}, "source_refs": []}
            elif field == "transform":
                spec["transforms"] = [{"component_ref": mutable, "params": {}}]
            else:
                spec["target"]["backend_ref"] = mutable
            provider = IndependentBuilder()
            with self.subTest(field=field), self.assertRaises(GymTSError) as error:
                build_dataset(spec, self.gym.records, self.gym.artifacts, builders=self.registry(provider))
            self.assertEqual(error.exception.code, "invalid_config")
            self.assertFalse(hasattr(provider, "received"))

    def test_conflicting_manual_registration_and_mutable_versions_fail(self):
        registry = self.registry()
        with self.assertRaises(GymTSError) as error:
            registry.register(REF, IndependentBuilder())
        self.assertEqual(error.exception.code, "conflict")
        with self.assertRaises(GymTSError):
            registry.resolve(dict(REF, version="latest"))


if __name__ == "__main__":
    unittest.main()
