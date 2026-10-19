"""Malformed plugin outputs must not corrupt records or leak future feedback."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import inline
from gymts.plugins import CounterTransition, ForecastCandidate
from gymts.plugins.counter import CounterControlSession, IncrementPolicy


ROOT = Path(__file__).resolve().parents[1]


class RunnerRegressions(unittest.TestCase):
    def test_non_json_output_seals_failed_run_with_incomplete_evidence(self):
        with tempfile.TemporaryDirectory() as root, GymTS(root) as gym:
            spec = json.loads((ROOT / "examples/forecast_experiment.json").read_text())
            for output in ({"prediction": float("nan")}, {"private": object()}):
                with self.subTest(output_type=type(output).__name__), patch.object(
                        ForecastCandidate, "infer", return_value=output):
                    result = gym.run(spec)
                self.assertEqual("failed", result["status"])
                self.assertEqual("incomplete", result["evidence_status"])
                self.assertEqual("schema_mismatch", result["errors"][0]["code"])
                saved = gym.records.get_run(result["run_id"])
                self.assertEqual(result, saved["result"])
                self.assertTrue(any(e["kind"] == "error" for e in saved["events"]))
                self.assertEqual("succeeded", result["summary"]["cleanup"]["environment"]["status"])
            # A plugin contract failure must leave the same store usable.
            self.assertEqual("succeeded", gym.run(spec)["status"])

    def test_unavailable_feedback_rejected_before_task_or_method_sees_it(self):
        observe = CounterTransition.observe

        def future_feedback(instance, request):
            batch = observe(instance, request)
            batch["feedback"].append({"feedback_id": "future-feedback", "operation_id": None,
                "kind": "event", "event_time": 100, "available_at": 100,
                "source_ref": {"name": "counter-transition", "version": "1.0.0", "origin_ref": None},
                "payload": inline({"future_label": 1}), "reward": None})
            return batch

        with tempfile.TemporaryDirectory() as root, GymTS(root) as gym:
            spec = json.loads((ROOT / "examples/counter_experiment.json").read_text())
            with patch.object(CounterTransition, "observe", future_feedback), \
                    patch.object(CounterControlSession, "consume") as consume, \
                    patch.object(IncrementPolicy, "infer") as infer:
                result = gym.run(spec)
            self.assertEqual("failed", result["status"])
            self.assertEqual("permission_denied", result["errors"][0]["code"])
            consume.assert_not_called()
            infer.assert_not_called()

    def test_non_json_cleanup_summary_becomes_cleanup_failure(self):
        finish = CounterTransition.finish

        def bad_summary(instance):
            summary = finish(instance)
            summary["private_object"] = object()
            return summary

        with tempfile.TemporaryDirectory() as root, GymTS(root) as gym:
            spec = json.loads((ROOT / "examples/counter_experiment.json").read_text())
            with patch.object(CounterTransition, "finish", bad_summary):
                result = gym.run(spec)
            self.assertEqual("failed", result["status"])
            self.assertEqual("failed", result["summary"]["cleanup"]["environment"]["status"])
            self.assertEqual("schema_mismatch", result["errors"][-1]["code"])
            self.assertEqual(result, gym.records.get_run(result["run_id"])["result"])


if __name__ == "__main__":
    unittest.main()
