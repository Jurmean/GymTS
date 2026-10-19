"""Regression cases for committed references and local evidence boundaries."""

import copy
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from gymts.contracts import GymTSError, digest
from gymts.storage import ArtifactStore, LocalExperimentRecords


class StorageRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.artifacts = ArtifactStore(self.root / "artifacts")
        self.records = LocalExperimentRecords(self.root / "records", self.artifacts)
        self.addCleanup(self.records.close)
        self.spec_ref = self.artifacts.save_json({}, "gymts.experiment/1")
        self.records.begin_run({"run_id": "run", "resolved_spec_ref": self.spec_ref})

    def event(self, identity, payload):
        return {"event_id": identity, "run_id": "run", "kind": "input",
                "producer_ref": {"name": "test", "version": "1", "origin_ref": None},
                "source_event_time": None, "caused_by": [], "links": {}, "payload": payload}

    def missing_ref(self):
        return {"artifact_id": "0" * 64, "revision": "1" * 64,
                "uri": "gymts-artifact://{}/{}".format("0" * 64, "1" * 64),
                "content_hash": "1" * 64, "media_type": "application/json",
                "schema_ref": "test/1", "size_bytes": 1}

    def test_blob_publication_does_not_follow_external_directory_symlink(self):
        content = b"external-write-regression"
        content_hash = hashlib.sha256(content).hexdigest()
        outside = self.root / "outside-blobs"
        outside.mkdir()
        (self.artifacts.root / "blobs" / content_hash[:2]).symlink_to(outside, target_is_directory=True)
        with self.assertRaises(GymTSError):
            self.artifacts.save_artifact(content, {"media_type": "text/plain"})
        self.assertEqual([], list(outside.iterdir()))

    def test_manifest_publication_does_not_follow_external_directory_symlink(self):
        content, metadata = b"manifest-write-regression", {"media_type": "text/plain"}
        content_hash = hashlib.sha256(content).hexdigest()
        identity = digest({"content_hash": content_hash, "metadata": metadata}).removeprefix("sha256:")
        outside = self.root / "outside-refs"
        outside.mkdir()
        (self.artifacts.root / "refs" / identity).symlink_to(outside, target_is_directory=True)
        with self.assertRaises(GymTSError):
            self.artifacts.save_artifact(content, metadata)
        self.assertEqual([], list(outside.iterdir()))

    def test_uncommitted_payload_rolls_back_entire_append_batch(self):
        first = self.event("first", {"schema_ref": "test/1", "storage": "inline", "value": 1})
        second = self.event("second", {"schema_ref": "test/1", "storage": "artifact", "artifact_ref": self.missing_ref()})
        with self.assertRaises(GymTSError) as caught:
            self.records.append("run", [first, second])
        self.assertEqual("artifact_unavailable", caught.exception.code)
        self.assertEqual([], self.records.get_run("run")["events"])

    def test_payload_reference_cannot_be_relabelled(self):
        ref = self.artifacts.save_json({"value": 1}, "private/1")
        event = self.event("relabelled", {"schema_ref": "public/1", "storage": "artifact", "artifact_ref": ref})
        with self.assertRaises(GymTSError) as caught:
            self.records.append("run", [event])
        self.assertEqual("invalid_record", caught.exception.code)

    def test_outcome_does_not_publish_an_uncommitted_payload(self):
        outcome = {"outcome_id": "outcome", "revision": "1", "alignment_key": {"case": "one"},
                   "payload": {"schema_ref": "test/1", "storage": "artifact", "artifact_ref": self.missing_ref()},
                   "event_time": 0, "available_at": "2026-01-01T00:00:00Z",
                   "source_ref": self.spec_ref, "supersedes_ref": None, "allowed_uses": ["evaluation"]}
        with self.assertRaises(GymTSError):
            self.records.attach_outcomes("run", [outcome])
        self.assertEqual([], self.records.read_outcomes({"run_ids": ["run"]}))

    def test_attached_outcomes_require_unique_supported_purposes(self):
        for uses in ("evaluation", ["evaluation", "evaluation"], ["evaluation", "unknown"], ["evaluation", 1]):
            with self.subTest(uses=uses):
                outcome = {"outcome_id": "outcome", "revision": "1", "alignment_key": {"case": "one"},
                           "payload": {"schema_ref": "test/1", "storage": "inline", "value": 1},
                           "event_time": 0, "available_at": "2026-01-01T00:00:00Z", "source_ref": self.spec_ref,
                           "supersedes_ref": None, "allowed_uses": uses}
                with self.assertRaises(GymTSError) as caught:
                    self.records.attach_outcomes("run", [outcome])
                self.assertEqual("invalid_record", caught.exception.code)
        self.assertEqual([], self.records.read_outcomes({"run_ids": ["run"]}))

    def test_valid_artifact_payload_remains_available_after_restart(self):
        ref = self.artifacts.save_json({"value": 1}, "test/1")
        event = self.event("valid", {"schema_ref": "test/1", "storage": "artifact", "artifact_ref": ref})
        first = self.records.append("run", [event])
        self.assertEqual(first, self.records.append("run", [copy.deepcopy(event)]))
        reopened = ArtifactStore(self.artifacts.root)
        self.assertEqual({"value": 1}, reopened.read_json(self.records.get_run("run")["events"][0]["payload"]["artifact_ref"]))

    def test_json_read_returns_the_bytes_that_passed_integrity_verification(self):
        ref = self.artifacts.save_json({"verified": True}, "test/1")
        blob = self.artifacts.resolve(ref)
        original = Path.read_bytes
        def replace_after_read(path):
            data = original(path)
            if path == blob:
                path.write_bytes(b'{"forged":true}')
            return data
        with patch.object(Path, "read_bytes", autospec=True, side_effect=replace_after_read):
            value = self.artifacts.read_json(ref)
        self.assertEqual({"verified": True}, value)
        with self.assertRaises(GymTSError) as caught:
            self.artifacts.read_json(ref)
        self.assertEqual("artifact_integrity", caught.exception.code)

    def test_malformed_manifest_raises_a_storage_error(self):
        ref = self.artifacts.save_json({"value": 1}, "test/1")
        manifest = self.artifacts.root / "refs" / ref["artifact_id"] / (ref["revision"] + ".json")
        manifest.write_text("[]", encoding="utf-8")
        with self.assertRaises(GymTSError):
            self.artifacts.resolve(ref)

    def test_artifact_metadata_must_be_a_finite_json_object(self):
        for metadata in ([], {"media_type": "application/json", "source": float("nan")}):
            with self.subTest(metadata=metadata):
                with self.assertRaises(GymTSError) as caught:
                    self.artifacts.save_artifact(b"content", metadata)
                self.assertEqual("invalid_artifact", caught.exception.code)

    def test_unsupported_platform_is_reported_before_creating_a_store(self):
        root = self.root / "unsupported"
        with patch("gymts.storage.artifacts.os.supports_dir_fd", set()):
            with self.assertRaises(GymTSError) as caught:
                ArtifactStore(root)
        self.assertEqual("unsupported_capability", caught.exception.code)
        self.assertFalse(root.exists())

    def test_malformed_public_references_are_storage_errors(self):
        for ref in (None, [], {}, {"media_type": "application/json", "schema_ref": "test/1"}):
            with self.subTest(ref=ref):
                with self.assertRaises(GymTSError):
                    self.artifacts.resolve(ref)
                with self.assertRaises(GymTSError):
                    self.artifacts.read_json(ref)


if __name__ == "__main__":
    unittest.main()
