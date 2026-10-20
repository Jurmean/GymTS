"""Portable checkpoint integrity and pure planning; no model runtime needed."""
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import zipfile

from gymts import GymTS
from gymts.contracts import GymTSError, canonical_json, digest
from gymts_rl.candidate import LocalHFCandidate
from gymts_rl.checkpoint import BUNDLE, MANIFEST, MEDIA_TYPE, PROVENANCE, materialize_checkpoint, publish_checkpoint_bundle
from gymts_rl.environment import RLQASnapshotEnvironment
from gymts_rl.pipeline import experiment_spec, rollouts
from gymts_rl.task import RLVerifiableQATask
from test_rl_pipeline import FixturePolicy, fixture_sources


def archive(payloads=None, *, mutation=None):
    payloads = payloads or {"adapter/adapter_config.json": b"{}", "adapter/adapter_model.safetensors": b"fixture"}
    files = [{"path": name, "size_bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
             for name, body in sorted(payloads.items())]
    identity = {"family": "text", "base_revision": "fixed-base", "adapter_state_hash": "fixed-adapter",
                "adapter_files": [entry for entry in files if entry["path"].startswith("adapter/")], "asset_files": []}
    manifest = {"schema_version": MANIFEST, "files": files, "policy_identity": identity,
        "policy_revision": digest(identity), "family": "text", "base": {"identity": {"revision": "fixed-base"}},
        "adapter_state_hash": "fixed-adapter", "training_policy_revision": "training-revision",
        "training_provenance": {"schema_version": PROVENANCE, "adapter_state_hash": "fixed-adapter", "training_policy_revision": "training-revision"}}
    provenance_bytes = canonical_json(manifest["training_provenance"])
    provenance_hash = hashlib.sha256(provenance_bytes).hexdigest()
    manifest["training_provenance_ref"] = {"artifact_id": "f" * 64, "revision": provenance_hash,
        "content_hash": provenance_hash, "size_bytes": len(provenance_bytes),
        "schema_ref": PROVENANCE, "media_type": "application/json",
        "uri": "gymts-artifact://" + "f" * 64 + "/" + provenance_hash}
    if mutation:
        mutation(manifest, payloads)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as handle:
        handle.writestr("manifest.json", canonical_json(manifest))
        for name, body in payloads.items():
            handle.writestr(name, body)
    return output.getvalue()


class CheckpointContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.gym = GymTS(Path(self.temporary.name), integrations=("rl",))

    def tearDown(self):
        self.gym.close()
        self.temporary.cleanup()

    def bundle(self, body):
        return self.gym.artifacts.save_artifact(body, {"schema_ref": BUNDLE, "media_type": MEDIA_TYPE})

    def test_publication_rejects_base_files_replaced_after_training_load(self):
        from gymts_rl.policy import checkpoint_identity
        base = Path(self.temporary.name) / "declared-base-identity-fixture"
        base.mkdir()
        (base / "pytorch_model.bin").write_bytes(b"explicit identity fixture; never loaded as a model")
        loaded = checkpoint_identity(base)
        policy = SimpleNamespace(model_path=str(base), identity={"base": loaded})
        (base / "pytorch_model.bin").write_bytes(b"substituted base bytes")
        with self.assertRaises(GymTSError) as error:
            publish_checkpoint_bundle(self.gym, policy, base / "adapter", {}, {})
        self.assertEqual(error.exception.code, "conflict")

    def test_archive_roundtrip_is_one_authorized_artifact(self):
        reference = self.bundle(archive())
        root, manifest, temporary = materialize_checkpoint(self.gym.artifacts, reference)
        try:
            self.assertEqual((root / "adapter/adapter_model.safetensors").read_bytes(), b"fixture")
            self.assertEqual(manifest["policy_revision"], digest(manifest["policy_identity"]))
        finally:
            temporary.cleanup()
        self.assertFalse(root.exists())

    def test_payload_hash_and_policy_identity_tampering_are_rejected(self):
        for mutation in (
            lambda manifest, payloads: payloads.update({"adapter/adapter_model.safetensors": b"changed"}),
            lambda manifest, payloads: manifest.update(policy_revision="substituted"),
            lambda manifest, payloads: manifest["training_provenance"].update(adapter_state_hash="substituted"),
            lambda manifest, payloads: manifest["training_provenance"].update(steps_completed=999),
            lambda manifest, payloads: manifest["training_provenance_ref"].update(content_hash="0" * 64),
        ):
            with self.subTest(mutation=mutation), self.assertRaises(GymTSError):
                materialize_checkpoint(self.gym.artifacts, self.bundle(archive(mutation=mutation)))

    def test_archive_path_traversal_is_rejected(self):
        with self.assertRaises(GymTSError):
            materialize_checkpoint(self.gym.artifacts, self.bundle(archive({"adapter/../../escape": b"unsafe"})))

    def test_validate_never_constructs_components_or_reads_artifacts(self):
        prepared = fixture_sources(self.gym)
        sample = self.gym.artifacts.read_json(prepared["snapshot_ref"])["samples"][0]
        spec = experiment_spec(prepared["snapshot_ref"], prepared["dataset_revision"], sample, {}, 7)
        spec["candidate"]["artifact"] = self.bundle(archive())
        with patch.object(RLQASnapshotEnvironment, "__init__", side_effect=AssertionError("constructed environment")), \
             patch.object(RLVerifiableQATask, "__init__", side_effect=AssertionError("constructed task")), \
             patch.object(LocalHFCandidate, "__init__", side_effect=AssertionError("constructed candidate")), \
             patch.object(self.gym.artifacts, "read_json", side_effect=AssertionError("read artifact")), \
             patch("gymts_rl.checkpoint.load_checkpoint_policy", side_effect=AssertionError("loaded model")):
            result = self.gym.validate(spec)
        self.assertTrue(result["valid"], result)

    def test_artifact_candidate_rejects_seed_inside_identity_during_validation(self):
        prepared = fixture_sources(self.gym)
        sample = self.gym.artifacts.read_json(prepared["snapshot_ref"])["samples"][0]
        spec = experiment_spec(prepared["snapshot_ref"], prepared["dataset_revision"], sample, {}, 7,
                               legacy_candidate_seed=True)
        spec["candidate"]["artifact"] = self.bundle(archive())
        result = self.gym.validate(spec)
        self.assertFalse(result["valid"])
        self.assertTrue(any(item["code"] == "invalid_config" for item in result["issues"]))

    def test_task_pure_compatibility_rejects_incompatible_clock(self):
        with self.assertRaises(GymTSError) as error:
            RLVerifiableQATask.check_compatibility_spec({"environment": {
                "clock_domain": "utc", "observation_granularity": "transition"}})
        self.assertEqual(error.exception.code, "unsupported_capability")

    def test_new_run_execution_seed_reaches_sampling_without_candidate_seed(self):
        prepared = fixture_sources(self.gym)
        with patch.object(LocalHFCandidate, "_native_inputs", lambda candidate, generated, sample:
                candidate._save({"format": "unit-test-no-tensors"}, "gymts.native-inputs/1")):
            batch = rollouts(self.gym, prepared, ["eval-0", "eval-0"], FixturePolicy(), split="eval", seed_start=29)
        from gymts.plugin_support import unpack
        specs, actual = [], []
        for run_id in batch["run_ids"]:
            record = self.gym.records.get_run(run_id)
            self.assertEqual(record["result"]["status"], "succeeded")
            specs.append(self.gym.artifacts.read_json(record["result"]["resolved_spec_ref"])["candidate"])
            call = next(unpack(event["payload"], self.gym.artifacts) for event in record["events"] if event["kind"] == "model_call")
            actual.append(call["effective_params"]["seed"])
        self.assertEqual(specs[0], specs[1])
        self.assertNotIn("seed", specs[0]["params"])
        self.assertEqual(actual, [29, 30])
