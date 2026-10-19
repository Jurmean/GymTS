"""Text-LLM QA integration contracts with mock HTTP and explicit format fixtures.

These tests make no remote API calls, use no real credentials, and do not claim
the constructed source rows or scripted replies as model-quality evidence.
"""
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import digest
from gymts.integrations.chatts.data import TASKS
from gymts.integrations.chatts.pipeline import run_pipeline
from gymts.storage import LocalExperimentRecords
from test_chatts_data import _fixture, _mutate


_ANSWERS = {
    "anomaly.point_indices": {"indices": [3]},
    "forecast.numeric": {"forecast": [4.0, 5.0]},
    "pattern.seasonality_profile": {"profile": "none"},
    "pattern.trend_direction": {"trend_direction": "increasing"},
    "process.stationarity_type": {"type": "stationary"},
    "relation.lagged_dependence": {"direction": "x_to_y", "lag": 2},
    "similarity.shape_retrieval": {"candidate_id": "candidate_a"},
}
_PRECISE_VALUES = [0.12345678901234566, -1.2345678901234567e-12,
                   2.0000000000000004, 3.141592653589793,
                   -123456.78901234567, 5.0, 6.0, 7.0]


def _candidate():
    return {"candidate_id": "mock-text-llm", "spec": {"adapter": "chatts-text-http", "version": "1.0.0",
        "artifact": None, "inherited_state": [], "params": {"base_url": "http://127.0.0.1:9999/v1",
            "model": "mock-text-model", "model_revision": "mock-fixed-revision",
            "thinking_mode": "disabled", "json_object": True}}}


class _Response:
    status = 200

    def __init__(self, content):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, maximum):
        return json.dumps({"model": "mock-text-model", "system_fingerprint": "mock-fixed",
            "choices": [{"message": {"role": "assistant", "content": self.content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 25, "completion_tokens": 5, "total_tokens": 30}}).encode()


class _Opener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(json.loads(request.data))
        return _Response(next(self.responses))


class ChatTSTextPipelineContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def _profiles(self, seven=True):
        native_tasks = tuple(list(TASKS)[:3]) if seven else ("pattern.trend_direction",)
        native = _fixture(self.root / "native", tasks=native_tasks, bundles=2)
        profiles = [native]
        if seven:
            profiles.append(_fixture(self.root / "classical", tasks=tuple(list(TASKS)[3:]), bundles=2))
        for profile in profiles:
            def input_precision(rows):
                for row in rows:
                    for modality in row["input"]["modalities"].values():
                        modality["content"] = list(_PRECISE_VALUES)
            def artifact_precision(rows):
                for row in rows:
                    for series in row["series"]:
                        series["values"] = list(_PRECISE_VALUES)
            _mutate(profile, "instances.jsonl", input_precision)
            _mutate(profile, "generation.jsonl", artifact_precision)
        return profiles

    def test_seven_tasks_text_wire_precision_private_boundary_and_rescore(self):
        profiles = self._profiles()
        opener = _Opener([json.dumps(_ANSWERS[task_id]) for task_id in sorted(TASKS)])
        old_results = {}
        attach = LocalExperimentRecords.attach_outcomes

        def capture_before_labels(records, run_id, outcomes):
            run = records.get_run(run_id)
            old_results[run_id] = (run["result_ref"], digest(run["result"]))
            return attach(records, run_id, outcomes)

        with patch("urllib.request.build_opener", return_value=opener), patch.object(
                LocalExperimentRecords, "attach_outcomes", capture_before_labels):
            summary = run_pipeline(self.root / "pipeline", profile_dirs=profiles,
                candidate_entries=[_candidate()], include_baseline=False, max_per_task=1)
        self.assertEqual("completed", summary["status"])
        self.assertEqual(set(TASKS), set(summary["tasks"]))
        self.assertEqual(7, len(opener.requests))
        native_json = json.dumps(_PRECISE_VALUES, separators=(",", ":"))
        for wire in opener.requests:
            self.assertEqual("mock-text-model", wire["model"])
            self.assertEqual({"type": "json_object"}, wire["response_format"])
            self.assertEqual({"type": "disabled"}, wire["thinking"])
            self.assertFalse(wire.get("stream", False))
            self.assertNotIn("timeseries", wire)
            self.assertNotIn("chat_template_kwargs", wire)
            self.assertTrue(all(isinstance(message["content"], str) for message in wire["messages"]))
            text = "\n".join(message["content"] for message in wire["messages"])
            self.assertIn(native_json, re.sub(r"\s+", "", text))
            encoded = json.dumps(wire)
            for private in ("SECRET_LABEL", "DO_NOT_SEND", "source_instance_id", "source_metadata",
                            "sample_token", "dataset_revision", "bundle_token", "expected_output", "synthetic_gold"):
                self.assertNotIn(private, encoded)
            for native_marker in ("<ts><ts/>", "chatts-timeseries:v1:"):
                self.assertNotIn(native_marker, encoded)
        with GymTS(self.root / "pipeline/records", integrations=("chatts",)) as gym:
            for task_id in TASKS:
                stem = task_id.replace(".", "_")
                initial = json.loads((self.root / "pipeline/reports" / (stem + ".before_labels.json")).read_text())
                scored = json.loads((self.root / "pipeline/reports" / (stem + ".json")).read_text())
                self.assertEqual(1, scored["coverage"]["expected_units"])
                self.assertEqual(1, scored["coverage"]["succeeded_runs"])
                self.assertEqual(0, scored["coverage"]["failed_runs"])
                old = gym.artifacts.read_json(initial["run_manifest_ref"])["entries"]
                new = gym.artifacts.read_json(scored["run_manifest_ref"])["entries"]
                self.assertEqual(old, new)
                run = gym.records.get_run(new[0]["run_id"])
                self.assertEqual(old_results[run["run_id"]], (run["result_ref"], digest(run["result"])))
                for metric in scored["metrics"]:
                    if metric["level"] == "unit":
                        self.assertEqual({"eligible": 1, "scored": 1, "missing": 0, "invalid": 0, "excluded": 0},
                                         metric["result"]["counts"])
                labels = gym.records.read_outcomes({"run_ids": [run["run_id"]], "purpose": "evaluation"})
                self.assertEqual(1, len(labels))
            trajectories = [json.loads(row) for row in Path(summary["trajectories"]["path"]).read_text().splitlines()]
            self.assertEqual(7, len(trajectories))
            for row in trajectories:
                self.assertEqual("gymts.run-result/1", row["run_result_ref"]["schema_ref"])
                self.assertEqual(_PRECISE_VALUES, row["input"]["payload"]["value"]["timeseries"][0])
                self.assertIsNotNone(row["output"])
                self.assertEqual("valid", row["result"]["status"])
                evidence = row["output"]["payload"]["value"]["evidence"]
                self.assertEqual("text_llm_http", evidence["kind"])
                self.assertEqual("configured_alias", evidence["revision_provenance"])
                self.assertEqual("named_numeric_json/v1", evidence["input_representation"])
                self.assertFalse(evidence["weights_pinned"])

    def test_invalid_text_reply_is_retained_and_cannot_shrink_denominator(self):
        opener = _Opener(['The answer is {"trend_direction":"increasing"}.'])
        with patch("urllib.request.build_opener", return_value=opener):
            summary = run_pipeline(self.root / "pipeline", profile_dirs=self._profiles(seven=False),
                candidate_entries=[_candidate()], include_baseline=False, max_per_task=1)
        self.assertEqual("failed", summary["status"])
        self.assertEqual(1, len(opener.requests))
        report = json.loads((self.root / "pipeline/reports/pattern_trend_direction.json").read_text())
        self.assertEqual(1, report["coverage"]["expected_units"])
        self.assertEqual(1, report["coverage"]["succeeded_runs"])
        self.assertEqual(0, report["coverage"]["failed_runs"])
        unit = next(metric for metric in report["metrics"] if metric["level"] == "unit")
        self.assertEqual({"eligible": 1, "scored": 0, "missing": 0, "invalid": 1, "excluded": 0},
                         unit["result"]["counts"])
        rows = [json.loads(row) for row in Path(summary["trajectories"]["path"]).read_text().splitlines()]
        self.assertEqual(1, len(rows))
        self.assertEqual('The answer is {"trend_direction":"increasing"}.',
                         rows[0]["output"]["payload"]["value"]["raw_text"])
        self.assertEqual("invalid", rows[0]["result"]["status"])
        self.assertIsNone(rows[0]["result"]["payload"]["value"]["parsed"])
        with GymTS(self.root / "pipeline/records", integrations=("chatts",)) as gym:
            self.assertEqual("succeeded", gym.artifacts.read_json(rows[0]["run_result_ref"])["status"])

    def test_text_and_native_http_candidates_keep_distinct_transport_evidence(self):
        source = self._profiles(seven=False)
        native = {"candidate_id": "mock-native-chatts", "spec": {"adapter": "chatts-http", "version": "1.0.0",
            "artifact": None, "inherited_state": [], "params": {"base_url": "http://127.0.0.1:9999/v1",
                "model": "mock-native-chatts", "model_revision": "mock-native-revision",
                "dialect": "chatts-timeseries/v1"}}}
        opener = _Opener([json.dumps(_ANSWERS["pattern.trend_direction"])] * 2)
        with patch("urllib.request.build_opener", return_value=opener):
            summary = run_pipeline(self.root / "pipeline", profile_dirs=source,
                candidate_entries=[_candidate(), native], include_baseline=False, max_per_task=1)
        self.assertEqual("completed", summary["status"])
        self.assertEqual(2, len(opener.requests))
        text_wire = next(wire for wire in opener.requests if wire["model"] == "mock-text-model")
        native_wire = next(wire for wire in opener.requests if wire["model"] == "mock-native-chatts")
        self.assertNotIn("timeseries", text_wire)
        self.assertEqual([_PRECISE_VALUES], native_wire["timeseries"])
        rows = [json.loads(row) for row in Path(summary["trajectories"]["path"]).read_text().splitlines()]
        kinds = {row["candidate_id"]: row["output"]["payload"]["value"]["evidence"]["kind"] for row in rows}
        self.assertEqual({"mock-text-llm": "text_llm_http", "mock-native-chatts": "chatts_http"}, kinds)


if __name__ == "__main__":
    unittest.main()
