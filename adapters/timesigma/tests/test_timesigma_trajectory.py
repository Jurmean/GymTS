"""Native Run evidence remains portable without inventing execution history."""
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from gymts import GymTS
from gymts.contracts import GymTSError, inline, utc_now
from gymts_timesigma.trajectory import (
    describe_run, export_evidence, import_evidence, inspect_archive,
)

BASE = Path(__file__).resolve().parents[1]


class TimeSigmaTrajectoryTests(unittest.TestCase):
    def test_multiple_runs_preserve_purpose_restricted_outcomes_and_metadata_closure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with GymTS(root / "source") as gym:
                spec = json.loads((BASE / "tests/fixtures/forecast_experiment.json").read_text())
                ids = [gym.run(spec)["run_id"], gym.run(spec)["run_id"]]
                dependency = gym.artifacts.save_json({"source": "original"}, "gymts.json/1")
                checkpoint = gym.artifacts.save_artifact(b"opaque", {"source_ref": dependency})
                for index, run_id in enumerate(ids):
                    gym.records.attach_outcomes(run_id, [{"outcome_id": "gold-" + str(index), "revision": "1",
                        "alignment_key": {"index": index}, "payload": inline({"gold": index}, "gymts.json/1"),
                        "event_time": 0, "available_at": utc_now(), "recorded_at": None,
                        "source_ref": dependency, "supersedes_ref": None, "allowed_uses": ["online_feedback"]}])
                export_evidence(gym, ids, root / "evidence.zip", roots=[checkpoint])
            with GymTS(root / "destination") as gym:
                imported = import_evidence(gym, root / "evidence.zip")
                self.assertEqual(ids, imported["run_ids"])
                self.assertEqual({"source": "original"}, gym.artifacts.read_json(dependency))
                body = inspect_archive(root / "evidence.zip")
                self.assertEqual([1, 1], [len(run["outcomes"]) for run in body["runs"]])
                self.assertEqual(["online_feedback"], body["runs"][0]["outcomes"][0]["allowed_uses"])

    def test_inline_run_index_cannot_disagree_with_immutable_native_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with GymTS(root / "source") as gym:
                result = gym.run(json.loads((BASE / "tests/fixtures/forecast_experiment.json").read_text()))
                export_evidence(gym, [result["run_id"]], root / "original.zip")
            for mutation in ("run_id", "event"):
                with self.subTest(mutation=mutation):
                    bad = root / (mutation + ".zip")
                    with zipfile.ZipFile(root / "original.zip") as source, zipfile.ZipFile(bad, "w") as target:
                        for name in source.namelist():
                            content = source.read(name)
                            if name == "manifest.json":
                                manifest = json.loads(content)
                                if mutation == "run_id":
                                    manifest["runs"][0]["run_id"] = "fabricated"
                                else:
                                    manifest["runs"][0]["events"][0]["payload"]["value"] = {"fabricated": True}
                                content = json.dumps(manifest).encode()
                            target.writestr(name, content)
                    with self.assertRaises(GymTSError):
                        inspect_archive(bad)

    def test_native_snapshot_roundtrip_preserves_artifact_identity_and_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with GymTS(root / "source") as gym:
                result = gym.run(json.loads((BASE / "tests/fixtures/forecast_experiment.json").read_text()))
                run_id = result["run_id"]
                self.assertEqual("succeeded", describe_run(gym, run_id)["status"])
                extra = gym.artifacts.save_artifact(b"native checkpoint", {"stage": "fit", "media_type": "application/octet-stream"})
                wrapper = gym.artifacts.save_json({"checkpoint_ref": extra}, "gymts.json/1")
                path = root / "evidence.zip"
                exported = export_evidence(gym, [run_id], path, roots=[wrapper])
                self.assertEqual(1, exported["run_count"])
                original = gym.records.get_run(run_id)
                with self.assertRaises(GymTSError):
                    export_evidence(gym, [run_id], path)
            with GymTS(root / "destination") as restored:
                imported = import_evidence(restored, path)
                self.assertEqual("imported_evidence", imported["status"])
                self.assertEqual(b"native checkpoint", restored.artifacts.resolve(extra).read_bytes())
                self.assertEqual(extra, restored.artifacts.read_json(wrapper)["checkpoint_ref"])
                manifest = inspect_archive(path)
                self.assertEqual(original["events"], manifest["runs"][0]["events"])
                self.assertEqual(original["result_ref"], manifest["runs"][0]["result_ref"])
                self.assertEqual(exported["record_snapshot_ref"], imported["record_snapshot_ref"])
                with self.assertRaises(GymTSError) as captured:
                    restored.records.get_run(run_id)
                self.assertEqual("run_not_found", captured.exception.code)

    def test_tampered_archive_publishes_no_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with GymTS(root / "source") as gym:
                result = gym.run(json.loads((BASE / "tests/fixtures/forecast_experiment.json").read_text()))
                export_evidence(gym, [result["run_id"]], root / "good.zip")
            with zipfile.ZipFile(root / "good.zip") as source, zipfile.ZipFile(root / "bad.zip", "w") as target:
                for index, name in enumerate(source.namelist()):
                    content = source.read(name)
                    target.writestr(name, content + b"tampered" if index == 1 else content)
            with GymTS(root / "destination") as gym:
                with self.assertRaises(GymTSError) as captured:
                    import_evidence(gym, root / "bad.zip")
                self.assertEqual("artifact_integrity", captured.exception.code)
                self.assertEqual([], list((gym.artifacts.root / "refs").rglob("*.json")))


if __name__ == "__main__":
    unittest.main()
