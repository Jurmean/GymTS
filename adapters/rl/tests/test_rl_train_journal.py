"""Training-parent evidence survives initialization failure and nonfinite metrics."""

import builtins
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import GymTSError
from gymts_rl.train import _persist_training_summary, run_training


class TrainingJournalTests(unittest.TestCase):
    def test_initialization_failure_keeps_started_and_failed_parent_revisions(self):
        actual_import = builtins.__import__

        def fail_runtime(name, *args, **kwargs):
            if name == "torch":
                raise ImportError("intentional missing optional runtime")
            return actual_import(name, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory, GymTS(Path(directory) / "state") as gym:
            output = Path(directory) / "training"
            manifest_ref = gym.artifacts.save_json({"fixture": True}, "gymts.json/1")
            with patch("builtins.__import__", side_effect=fail_runtime), self.assertRaisesRegex(ImportError, "intentional"):
                run_training(gym, {"manifest_ref": manifest_ref}, SimpleNamespace(model_path="explicit-fixture", family="text"), output)
            summary = json.loads((output / "training-summary.json").read_text())
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["steps_completed"], 0)
            self.assertEqual(summary["rollout_batches"], [])
            self.assertEqual(summary["error"]["type"], "ImportError")
            failed = gym.artifacts.read_json(summary["summary_ref"])
            started = gym.artifacts.read_json(failed["previous_summary_ref"])
            self.assertEqual(started["status"], "initializing")
            self.assertIsNone(started["previous_summary_ref"])

    def test_journal_sanitizes_nonfinite_diagnostics_without_losing_their_location(self):
        with tempfile.TemporaryDirectory() as directory, GymTS(Path(directory) / "state") as gym:
            output = Path(directory) / "training"
            output.mkdir()
            summary = {"schema_version": "gymts.rl/training/1", "status": "running", "train_metrics": {"loss": float("nan"), "clip": float("inf")}}
            first = _persist_training_summary(gym, output, summary)
            stored = gym.artifacts.read_json(first)
            self.assertEqual(stored["train_metrics"], {"loss": None, "clip": None})
            self.assertEqual(set(stored["non_finite_fields"]), {"$.train_metrics.loss", "$.train_metrics.clip"})
            summary["status"] = "failed"
            second = _persist_training_summary(gym, output, summary)
            self.assertEqual(gym.artifacts.read_json(second)["previous_summary_ref"], first)
            document = json.loads((output / "training-summary.json").read_text())
            self.assertEqual(document["summary_ref"], second)
            self.assertEqual(list(output.glob(".training-summary-*")), [])

    def test_invalid_learning_rate_fails_before_runtime_import_or_output_creation(self):
        with tempfile.TemporaryDirectory() as directory, GymTS(Path(directory) / "state") as gym:
            for index, value in enumerate((0, -1, float("nan"), float("inf"), True)):
                output = Path(directory) / ("training-" + str(index))
                with self.subTest(value=value), self.assertRaises(GymTSError) as error:
                    run_training(gym, {}, None, output, learning_rate=value)
                self.assertEqual(error.exception.code, "invalid_config")
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
