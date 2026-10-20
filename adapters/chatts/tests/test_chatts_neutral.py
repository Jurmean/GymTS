"""New public numerical path; historical /1 behavior is tested separately."""
import copy
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import GymTSError, digest
from gymts_timeseries.contracts import INPUT, OUTPUT, PROTOCOL, SNAPSHOT
from gymts_timeseries.task import make_task_input
from gymts_chatts import neutral_data
from gymts_chatts.neutral_candidate import NeutralChatTSHTTPCandidate, NeutralSignalBaseline, NeutralTextLLMHTTPCandidate, encode_input
from gymts_chatts.pipeline import attach_and_rescore, baseline, evaluation_spec, run_pipeline

from test_chatts_data import _fixture, _mutate


class NeutralChatTSContracts(unittest.TestCase):
    def sample(self):
        return {"sample_token": "a" * 64, "series": [{"name": "Series 1", "values": [0.12345678901234566, 1., 2., 3.]}],
                "context": {"horizon": 2}, "annotations": {}}

    def test_model_owned_codec_generates_messages_after_neutral_task(self):
        value = make_task_input(self.sample(), "forecast.numeric", "0.2.0")
        original = copy.deepcopy(value)
        native = encode_input(value, native=True)
        text = encode_input(value)
        self.assertEqual(original, value)
        self.assertNotIn("messages", value)
        self.assertNotIn("<ts>", json.dumps(value))
        self.assertEqual(1, native["messages"][0]["content"].count("<ts><ts/>"))
        self.assertNotIn("<ts>", text["messages"][0]["content"])
        self.assertEqual([self.sample()["series"][0]["values"]], native["timeseries"])
        self.assertEqual(PROTOCOL, NeutralChatTSHTTPCandidate.TASK_PROTOCOL_REF)
        self.assertEqual(OUTPUT, NeutralTextLLMHTTPCandidate.OUTPUT_SCHEMA_REF)

    def test_source_reader_does_not_call_legacy_task_interpretation(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = _fixture(Path(directory) / "source", tasks=("forecast.numeric",), bundles=2)
            with GymTS(Path(directory) / "records", integrations=("chatts",)) as gym, \
                    patch("gymts_chatts.data._model_input", side_effect=AssertionError("Legacy Task interpretation called")):
                imported = neutral_data.import_profiles(gym, [profile])
                manifest = gym.artifacts.read_json(imported["manifest_ref"])
                self.assertEqual(imported["prompt_policy"], manifest["prompt_policy"])
                self.assertFalse(manifest["prompt_policy"]["original_source_messages_used"])
                self.assertFalse(manifest["prompt_policy"]["equivalent_to_original_benchmark_prompt"])
                public = gym.artifacts.read_json(imported["snapshot_ref"])
                self.assertEqual(SNAPSHOT, public["schema_version"])
                for sample in public["samples"]:
                    self.assertEqual({"sample_token", "series", "context", "annotations"}, set(sample))
                    self.assertNotIn("model_input", json.dumps(sample))
                    self.assertNotIn("messages", json.dumps(sample))
                    self.assertNotIn("expected_output", json.dumps(sample))
                    self.assertEqual("forecast.numeric", sample["annotations"]["benchmark_task_id"])
                    self.assertEqual(2, sample["context"]["horizon"])

    def test_default_pipeline_uses_shared_task_and_scorer_for_seven_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = _fixture(root / "native", tasks=("pattern.trend_direction", "anomaly.point_indices", "forecast.numeric"), bundles=2)
            classical = _fixture(root / "classical", tasks=("pattern.seasonality_profile", "process.stationarity_type",
                "relation.lagged_dependence", "similarity.shape_retrieval"), bundles=2)
            summary = run_pipeline(root / "experiment", profile_dirs=[native, classical])
            self.assertEqual("completed", summary["status"], summary)
            self.assertEqual(PROTOCOL, summary["task_protocol_ref"])
            self.assertFalse(summary["prompt_policy"]["equivalent_to_original_benchmark_prompt"])
            self.assertEqual(7, len(summary["tasks"]))
            spec = json.loads((root / "experiment/configs/forecast_numeric.evaluation.json").read_text())
            self.assertEqual("numeric-snapshot", spec["cases"][0]["scene"]["environment"]["adapter"])
            self.assertEqual("timeseries-qa", spec["cases"][0]["scene"]["task"]["plugin"])
            self.assertEqual("timeseries-qa-scorer", spec["scoring"]["scorer"]["adapter"])
            self.assertEqual("timeseries-signal-baseline", spec["candidates"][0]["spec"]["adapter"])
            formal_report = json.loads((root / "experiment/reports/forecast_numeric.json").read_text())
            self.assertNotIn("prompt_policy", formal_report)
            self.assertEqual(summary["prompt_policy"], summary["tasks"]["forecast.numeric"]["prompt_policy"])
            rows = [json.loads(line) for line in Path(summary["trajectories"]["path"]).read_text().splitlines()]
            self.assertTrue(rows)
            for row in rows:
                value = row["input"]["payload"]["value"]
                self.assertEqual(INPUT, row["input"]["payload"]["schema_ref"])
                self.assertNotIn("messages", value)
                self.assertNotIn("<ts>", json.dumps(value))
                self.assertNotIn("expected_output", json.dumps(value))
                self.assertTrue(row["record_snapshot_ref"])

    def test_neutral_and_legacy_plan_without_source_or_model_open_and_reject_baseline_mismatch(self):
        from gymts_chatts import data
        from gymts_chatts.candidate import ChatTSSignalBaseline
        from gymts_chatts.environment import ChatTSSnapshotEnvironment
        from gymts_chatts.task import ChatTSSyntheticQATask
        from gymts_timeseries.environment import NumericSnapshotEnvironment
        from gymts_timeseries.task import TimeSeriesQATask
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = _fixture(root / "source", tasks=("pattern.trend_direction",), bundles=2)
            with GymTS(root / "records", integrations=("chatts",)) as gym:
                for neutral, importer in ((True, neutral_data), (False, data)):
                    with self.subTest(neutral=neutral):
                        imported = importer.import_profiles(gym, [profile])
                        public = gym.artifacts.read_json(imported["snapshot_ref"])
                        rows = {row["sample_token"]: row for row in public["samples"]}
                        evaluation = evaluation_spec(gym, imported, rows, imported["samples"][:1],
                            "pattern.trend_direction", [baseline("pattern.trend_direction", neutral=neutral)], neutral=neutral)
                        case = evaluation["cases"][0]
                        spec = {"protocol_version": "gymts.experiment/1", "name": "pure adapter plan fixture", "purpose": "development",
                            "scene": copy.deepcopy(case["scene"]), "execution": copy.deepcopy(case["execution"]),
                            "recording": copy.deepcopy(case["recording"]), "candidate": copy.deepcopy(evaluation["candidates"][0]["spec"]), "extensions": {}}
                        with ExitStack() as stack:
                            for cls in (NumericSnapshotEnvironment, TimeSeriesQATask, NeutralSignalBaseline,
                                    ChatTSSnapshotEnvironment, ChatTSSyntheticQATask, ChatTSSignalBaseline):
                                stack.enter_context(patch.object(cls, "__init__", side_effect=AssertionError("Planning constructed a role")))
                            for name in ("resolve", "read_json", "read_view", "save_json"):
                                stack.enter_context(patch.object(gym.artifacts, name, side_effect=AssertionError("Planning accessed source bytes")))
                            self.assertTrue(gym.validate(spec)["valid"])
                            spec["candidate"]["params"]["task_id"] = "forecast.numeric"
                            validation = gym.validate(spec)
                            self.assertFalse(validation["valid"])
                            self.assertEqual("unsupported_capability", validation["issues"][0]["code"])

    def test_benchmark_cannot_silently_change_task_or_reuse_gold(self):
        value = self.sample()
        value["annotations"] = {"benchmark_task_id": "forecast.numeric", "benchmark_task_version": "0.2.0"}
        with self.assertRaises(GymTSError) as caught:
            make_task_input(value, "pattern.trend_direction", "0.2.0")
        self.assertEqual("unsupported_capability", caught.exception.code)

    def test_invalid_gold_is_preserved_by_source_and_rejected_by_independent_scorer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = _fixture(root / "source", tasks=("pattern.trend_direction",), bundles=2)
            def invalid_gold(rows):
                for row in rows:
                    row["expected_output"] = {"trend_direction": "not-a-class"}
            _mutate(profile, "instances.jsonl", invalid_gold)
            with GymTS(root / "probe-records", integrations=("chatts",)) as gym:
                imported = neutral_data.import_profiles(gym, [profile])
                saved = gym.artifacts.read_json(imported["private_ref"])
                self.assertTrue(all(row["expected_output"] == {"trend_direction": "not-a-class"} for row in saved["samples"]))
            summary = run_pipeline(root / "experiment", profile_dirs=[profile])
            self.assertEqual("failed", summary["status"])
            report = json.loads((root / "experiment/reports/pattern_trend_direction.json").read_text())
            aggregate = [row for row in report["metrics"] if row["level"] == "aggregate"]
            self.assertTrue(aggregate)
            self.assertEqual(0, aggregate[0]["result"]["counts"]["scored"])
            self.assertGreater(aggregate[0]["result"]["counts"]["invalid"], 0)
            self.assertTrue(summary["tasks"]["pattern.trend_direction"]["sealed_results_unchanged"])

    def test_rescore_preserves_task_tags_and_original_runs_without_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = _fixture(root / "source", tasks=("pattern.trend_direction",), bundles=2)
            with GymTS(root / "records", integrations=("chatts",)) as gym:
                imported = neutral_data.import_profiles(gym, [profile])
                public = gym.artifacts.read_json(imported["snapshot_ref"])
                public_rows = {row["sample_token"]: row for row in public["samples"]}
                spec = evaluation_spec(gym, imported, public_rows, imported["samples"][:1],
                    "pattern.trend_direction", [baseline("pattern.trend_direction", neutral=True)], neutral=True)
                spec["comparison"]["group_by"].append("tags.task_id")
                before = gym.autobench.evaluate(spec)
                before_manifest = gym.artifacts.read_json(before["run_manifest_ref"])
                before_runs = [entry["run_id"] for entry in before_manifest["entries"]]
                hashes = {run_id: digest(gym.records.get_run(run_id)["result"]) for run_id in before_runs}
                with patch.object(NeutralSignalBaseline, "infer", side_effect=AssertionError("Rescoring ran inference")):
                    after, score_spec, run_ids = attach_and_rescore(gym, imported, spec, before)
                self.assertEqual("completed", after["status"])
                self.assertEqual("pass", after["verdict"])
                self.assertEqual(before_runs, run_ids)
                self.assertEqual(hashes, {run_id: digest(gym.records.get_run(run_id)["result"]) for run_id in run_ids})
                self.assertTrue(all(row["tags"] == {"task_id": "pattern.trend_direction"} for row in score_spec["runs"]))
                groups = [row for row in after["metrics"] if row["level"] == "group"]
                self.assertTrue(groups)
                self.assertTrue(all(row["group_key"]["tags.task_id"] == "pattern.trend_direction" for row in groups))
                self.assertTrue(all(row["result"]["status"] == "ready" for row in groups))


if __name__ == "__main__":
    unittest.main()
