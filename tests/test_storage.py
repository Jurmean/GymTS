"""Failure-oriented contracts for durable local evidence storage."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gymts.contracts import GymTSError
from gymts.storage import ArtifactStore, LocalExperimentRecords


class StorageContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.artifacts = ArtifactStore(self.root / "artifacts")
        self.records = LocalExperimentRecords(self.root / "records", self.artifacts)
        self.config = self.artifacts.save_json({"protocol_version": "gymts.experiment/1"}, "gymts.experiment/1")
        self.meta = {"run_id": "run-a", "resolved_spec_ref": self.config, "created_at": "2026-10-12T00:00:00Z"}
        self.records.begin_run(self.meta)

    def tearDown(self):
        self.records.close()
        self.temporary.cleanup()

    def event(self, event_id="event-a", kind="input", caused_by=None):
        return {"event_id": event_id, "run_id": "run-a", "kind": kind,
                "producer_ref": {"name": "test", "version": "1", "origin_ref": None},
                "source_event_time": None, "caused_by": caused_by or [], "links": {},
                "payload": {"schema_ref": "test/1", "storage": "inline", "value": {"value": event_id}}}

    def finalization(self):
        return {"protocol_version": "gymts.run-result/1", "run_id": "run-a", "purpose": "development",
                "status": "succeeded", "completion": "task_completed", "started_at": "2026-10-12T00:00:00Z",
                "ended_at": "2026-10-12T01:00:00Z", "resolved_spec_ref": self.config,
                "result_ref": self.artifacts.save_json([], "gymts.results/1"), "artifact_refs": [],
                "evidence_status": "complete", "errors": [], "summary": {"stop_reason": "done"}}

    def outcome(self, revision="1", value=1):
        return {"outcome_id": "outcome-a", "revision": revision, "alignment_key": {"case_id": "case-a"},
                "payload": {"schema_ref": "test.outcome/1", "storage": "inline", "value": value},
                "event_time": "2026-10-10T00:00:00Z", "available_at": "2026-10-10T00:00:00Z",
                "recorded_at": None, "source_ref": self.artifacts.save_json({"truth": value}, "test/1"),
                "supersedes_ref": None, "allowed_uses": ["evaluation"]}

    def assertCode(self, code, callback):
        with self.assertRaises(GymTSError) as caught:
            callback()
        self.assertEqual(code, caught.exception.code)

    def test_artifact_roundtrip_and_restart(self):
        ref = self.artifacts.save_json({"rows": [1, 2]}, "test/1")
        self.assertEqual(ref, self.artifacts.save_json({"rows": [1, 2]}, "test/1"))
        reopened = ArtifactStore(self.root / "artifacts")
        self.assertEqual({"rows": [1, 2]}, reopened.read_json(ref))
        self.assertEqual(7, len(ref))
        self.assertCode("invalid_artifact", lambda: reopened.save_json({"bad": float("nan")}, "test/1"))

    def test_ref_cannot_select_external_file_or_relabel_schema(self):
        ref = self.artifacts.save_json({"private": 1}, "test/1")
        forged = dict(ref, uri="file:///etc/passwd")
        self.assertCode("artifact_integrity", lambda: self.artifacts.resolve(forged))
        self.assertCode("artifact_integrity", lambda: self.artifacts.read_json(dict(ref, schema_ref="public/1")))
        self.assertCode("invalid_artifact", lambda: self.artifacts.resolve(dict(ref, artifact_id="../../etc/passwd")))
        self.artifacts.resolve(ref).write_bytes(b"tampered")
        self.assertCode("artifact_integrity", lambda: self.artifacts.read_json(ref))

    def test_data_view_bounds_sources_and_rejects_unknown_selection(self):
        source = self.artifacts.save_json({"rows": [{"v": 1}, {"v": 2}]}, "test/1")
        view = {"view_id": "view", "revision": "1", "source_refs": [source], "as_of": None,
                "purpose": "runtime", "selection": {"schema_ref": "gymts.selection/1", "storage": "inline",
                "value": {"kind": "json_pointer", "pointer": "/rows/1/v"}}}
        self.assertEqual(2, self.artifacts.read_view(view)["value"])
        bad = copy.deepcopy(view)
        bad["selection"]["value"]["source_index"] = 1
        self.assertCode("invalid_view", lambda: self.artifacts.read_view(bad))
        bad["selection"]["value"] = {"kind": "sql", "query": "SELECT *"}
        self.assertCode("unsupported_capability", lambda: self.artifacts.read_view(bad))

    def test_metadata_and_event_identity_survive_restart(self):
        self.assertEqual(self.records.begin_run(self.meta)["run_id"], "run-a")
        self.assertCode("conflict", lambda: self.records.begin_run(dict(self.meta, origin="imported")))
        event = self.event()
        first = self.records.append("run-a", [event])
        self.records.close()
        self.records = LocalExperimentRecords(self.root / "records", self.artifacts)
        self.assertEqual(first, self.records.append("run-a", [event]))
        run = self.records.get_run("run-a")
        self.assertEqual(self.config, run["resolved_spec_ref"])
        self.assertEqual(1, len(run["events"]))
        self.assertEqual(run["events"][0], self.artifacts.read_json(run["event_refs"][0]))

    def test_append_batch_conflict_rolls_back_every_event(self):
        event = self.event()
        self.records.append("run-a", [event])
        different = copy.deepcopy(event)
        different["payload"]["value"] = 999
        self.assertCode("conflict", lambda: self.records.append("run-a", [self.event("would-be-new"), different]))
        self.assertEqual(["event-a"], [item["event_id"] for item in self.records.get_run("run-a")["events"]])
        self.assertCode("invalid_record", lambda: self.records.append("run-a", [self.event("unknown-cause", caused_by=["missing"])]))

    def test_sealing_is_consistent_idempotent_and_not_self_referential(self):
        event = self.event()
        self.records.append("run-a", [event])
        final = self.finalization()
        result = self.records.end_run("run-a", final)
        self.assertEqual(result, self.records.end_run("run-a", final))
        trace = self.artifacts.read_json(result["trace_ref"])
        self.assertEqual("run_end", trace["events"][-1]["kind"])
        self.assertNotIn("trace_ref", trace["events"][-1]["payload"]["value"])
        run = self.records.get_run("run-a")
        self.assertEqual(result, self.artifacts.read_json(run["result_ref"]))
        self.assertEqual({"event-a": 1}, self.records.append("run-a", [event])["positions"])
        self.assertCode("run_sealed", lambda: self.records.append("run-a", [self.event("new")]))
        self.assertCode("conflict", lambda: self.records.end_run("run-a", dict(final, completion="limit_reached")))

    def test_failed_seal_does_not_publish_run_end_or_partial_result(self):
        self.records.append("run-a", [self.event()])
        final = self.finalization()
        original = self.artifacts.save_json
        def fail_trace(value, schema_ref):
            if schema_ref == "gymts.execution-trace/1":
                raise OSError("injected disk failure")
            return original(value, schema_ref)
        with patch.object(self.artifacts, "save_json", side_effect=fail_trace):
            self.assertCode("persistence_failed", lambda: self.records.end_run("run-a", final))
        run = self.records.get_run("run-a")
        self.assertIsNone(run["result"])
        self.assertEqual(["input"], [event["kind"] for event in run["events"]])
        self.assertEqual("succeeded", self.records.end_run("run-a", final)["status"])

    def test_outcome_as_of_checks_recording_time_and_freezes_snapshots(self):
        outcome = self.outcome()
        with patch("gymts.storage.records.utc_now", return_value="2026-10-12T01:00:00Z"):
            snapshot_ref = self.records.attach_outcomes("run-a", [outcome])
        self.assertEqual([{"outcome_id": "outcome-a", "revision": "1"}], self.artifacts.read_json(snapshot_ref))
        historical = self.records.snapshot(["run-a"], {"outcomes_as_of": "2026-10-11T00:00:00Z"})
        self.assertEqual([], historical["outcome_refs"])
        fixed = self.records.snapshot(["run-a"], {"outcomes_as_of": "2026-10-12T02:00:00Z"})
        next_revision = self.outcome("2", 2)
        next_revision["supersedes_ref"] = {"outcome_id": "outcome-a", "revision": "1"}
        self.records.attach_outcomes("run-a", [next_revision])
        frozen = self.records.read_outcomes({"snapshot_ref": fixed["snapshot_ref"], "purpose": "evaluation"})
        self.assertEqual(["1"], [item["revision"] for item in frozen])
        self.assertCode("purpose_denied", lambda: self.records.read_outcomes({"snapshot_ref": fixed["snapshot_ref"], "purpose": "training_export"}))

    def test_outcome_batch_conflict_and_service_clock_cannot_be_forged(self):
        first = self.outcome()
        self.records.attach_outcomes("run-a", [first])
        self.records.attach_outcomes("run-a", [first])
        self.assertCode("conflict", lambda: self.records.attach_outcomes("run-a", [self.outcome("2", 2), self.outcome("1", 9)]))
        self.assertEqual(["1"], [item["revision"] for item in self.records.read_outcomes({"run_ids": ["run-a"]})])
        forged = self.outcome("3", 3)
        forged["recorded_at"] = "2026-01-01T00:00:00Z"
        self.assertCode("invalid_record", lambda: self.records.attach_outcomes("run-a", [forged]))

    def test_snapshot_event_prefix_and_pagination_do_not_drift(self):
        self.records.append("run-a", [self.event("a"), self.event("b", caused_by=["a"])])
        fixed = self.records.snapshot(["run-a"], {})
        self.records.append("run-a", [self.event("c")])
        page = self.records.read_events("run-a", {"limit": 1, "snapshot_ref": fixed["snapshot_ref"]})
        self.assertEqual("a", page["events"][0]["event_id"])
        page2 = self.records.read_events("run-a", {"after_seq": page["next_after_seq"], "snapshot_ref": fixed["snapshot_ref"]})
        self.assertEqual(["b"], [item["event_id"] for item in page2["events"]])
        self.assertEqual([], self.records.read_events("run-a", {"kinds": []})["events"])
        self.records.end_run("run-a", self.finalization())
        prefix = self.records.snapshot(["run-a"], {"through_seq": {"run-a": 2}})
        self.assertIsNone(prefix["runs"][0]["result_ref"])
        self.assertEqual(fixed, self.records.get_snapshot(fixed["snapshot_ref"]))
        self.assertCode("invalid_query", lambda: self.records.snapshot(["run-a"], {"through_seq": {"run-a": 999}}))


if __name__ == "__main__":
    unittest.main()
