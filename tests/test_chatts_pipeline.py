"""End-to-end QA pipeline contracts on explicitly constructed format fixtures.

No rows in this test module are claimed to be genuine generator output or model
quality evidence. HTTP replies are deterministic mocks; real source-generation
smoke runs are performed separately by the integration workflow.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import GymTSError, digest
from gymts.integrations.chatts.candidate import ChatTSSignalBaseline
from gymts.integrations.chatts.data import TASKS, import_profiles
from gymts.integrations.chatts.pipeline import baseline, execution, recording, run_pipeline, scene
from gymts.storage import LocalExperimentRecords
from test_chatts_data import _fixture


class _Reply:
    status = 200

    def __init__(self, content):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, maximum):
        return json.dumps({"model": "mock-chatts", "system_fingerprint": "mock-fixed",
            "choices": [{"message": {"role": "assistant", "content": self.content},
                         "finish_reason": "stop"}]}).encode()


class _Opener:
    def __init__(self, content):
        self.content, self.requests = content, []

    def open(self, request, timeout):
        self.requests.append(json.loads(request.data))
        return _Reply(self.content)


def _http_entry():
    return {"candidate_id": "mock-http", "spec": {"adapter": "chatts-http", "version": "1.0.0",
        "artifact": None, "inherited_state": [], "params": {"base_url": "http://127.0.0.1:9999/v1",
            "model": "mock-chatts", "model_revision": "mock-revision-1",
            "dialect": "chatts-timeseries/v1", "expected_system_fingerprint": "mock-fixed"}}}


def _read(path):
    return json.loads(Path(path).read_text())


def _rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


class ChatTSPipelineContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_seven_tasks_eval_bundles_repetitions_rescore_and_frozen_trajectories(self):
        native = _fixture(self.root / "native", tasks=tuple(list(TASKS)[:3]), bundles=2)
        classical = _fixture(self.root / "classical", tasks=tuple(list(TASKS)[3:]), bundles=2)
        output = self.root / "pipeline"
        before_labels = {}
        original_attach = LocalExperimentRecords.attach_outcomes

        def observe_attach(records, run_id, outcomes):
            run = records.get_run(run_id)
            before_labels[run_id] = {"result_ref": copy.deepcopy(run["result_ref"]),
                                     "result_digest": digest(run["result"])}
            return original_attach(records, run_id, outcomes)

        with patch.object(LocalExperimentRecords, "attach_outcomes", observe_attach):
            summary = run_pipeline(output, profile_dirs=[native, classical], repetitions=2)
        self.assertEqual("completed", summary["status"])
        self.assertEqual("eval", summary["evaluation_split"])
        self.assertEqual(set(TASKS), set(summary["tasks"]))
        self.assertEqual(28, summary["source_samples"])
        exported = summary["synthetic_sft"]
        train, evaluation = exported["splits"]["train"], exported["splits"]["eval"]
        self.assertFalse(set(train["bundle_tokens"]) & set(evaluation["bundle_tokens"]))
        self.assertFalse(set(train["sample_tokens"]) & set(evaluation["sample_tokens"]))
        self.assertEqual(14, len(evaluation["sample_tokens"]))
        planned_tokens, all_runs = set(), set()
        with GymTS(output / "records", integrations=("chatts",)) as gym:
            for task_id in TASKS:
                stem = task_id.replace(".", "_")
                initial = _read(output / "reports" / (stem + ".before_labels.json"))
                scored = _read(output / "reports" / (stem + ".json"))
                plan = gym.artifacts.read_json(scored["plan_ref"])
                expected = plan["expected_units"]
                self.assertEqual(4, len(expected))  # 2 held-out views x 2 repetitions.
                self.assertEqual({0, 1}, {unit["repetition"] for unit in expected})
                planned_tokens.update(unit["evaluation_case_id"] for unit in expected)
                old_manifest = gym.artifacts.read_json(initial["run_manifest_ref"])
                new_manifest = gym.artifacts.read_json(scored["run_manifest_ref"])
                self.assertEqual(old_manifest["entries"], new_manifest["entries"])
                self.assertEqual(4, scored["coverage"]["succeeded_runs"])
                self.assertEqual(0, scored["coverage"]["failed_runs"])
                for metric in initial["metrics"]:
                    if metric["level"] == "unit":
                        self.assertEqual(1, metric["result"]["counts"]["missing"])
                for metric in scored["metrics"]:
                    if metric["level"] == "unit":
                        self.assertEqual({"eligible": 1, "scored": 1, "missing": 0, "invalid": 0, "excluded": 0},
                                         metric["result"]["counts"])
                for entry in new_manifest["entries"]:
                    run_id = entry["run_id"]
                    all_runs.add(run_id)
                    run = gym.records.get_run(run_id)
                    self.assertEqual(before_labels[run_id]["result_ref"], run["result_ref"])
                    self.assertEqual(before_labels[run_id]["result_digest"], digest(run["result"]))
                    labels = gym.records.read_outcomes({"run_ids": [run_id], "purpose": "evaluation"})
                    self.assertEqual(1, len(labels))
            self.assertEqual(set(evaluation["sample_tokens"]), planned_tokens)
            self.assertEqual(28, len(all_runs))
            frozen = gym.artifacts.read_json(summary["trajectories"]["record_snapshot_ref"])
            frozen_runs = {run["run_id"]: run for run in frozen["runs"]}
            trajectories = _rows(summary["trajectories"]["path"])
            self.assertEqual(28, len(trajectories))
            self.assertEqual(all_runs, set(frozen_runs))
            for row in trajectories:
                self.assertEqual("gymts.run-result/1", row["run_result_ref"]["schema_ref"])
                self.assertEqual(frozen_runs[row["run_id"]]["result_ref"], row["run_result_ref"])
                run_result = gym.artifacts.read_json(row["run_result_ref"])
                self.assertEqual(row["run_id"], run_result["run_id"])
                self.assertEqual("succeeded", run_result["status"])
                self.assertFalse(row["capture"]["token_ids"])
                self.assertFalse(row["capture"]["logprobs"])
                model_input = row["input"]["payload"]["value"]
                self.assertNotIn("expected_output", model_input)
                self.assertNotIn("SECRET_LABEL", json.dumps(model_input))
                self.assertIsInstance(model_input["timeseries"][0], list)

    def test_two_candidates_and_repetitions_share_one_immutable_outcome(self):
        source = _fixture(self.root / "native", bundles=2)
        opener = _Opener('{"trend_direction":"increasing"}')
        with patch("gymts.http_candidate.urllib.request.build_opener", return_value=opener):
            summary = run_pipeline(self.root / "pipeline", profile_dirs=[source],
                candidate_entries=[_http_entry()], repetitions=2, max_per_task=1)
        self.assertEqual("completed", summary["status"])
        self.assertEqual(2, len(opener.requests))
        for wire in opener.requests:
            self.assertEqual([[float(n) for n in range(8)]], wire["timeseries"])
            self.assertNotIn("SECRET_LABEL", json.dumps(wire))
            self.assertNotIn("expected_output", wire)
        report = _read(self.root / "pipeline/reports/pattern_trend_direction.json")
        self.assertEqual(4, report["coverage"]["expected_units"])
        self.assertEqual({"signal-baseline", "mock-http"}, {r["candidate_id"] for r in report["metrics"]})
        labels_by_run = []
        with GymTS(self.root / "pipeline/records", integrations=("chatts",)) as gym:
            manifest = gym.artifacts.read_json(report["run_manifest_ref"])
            for entry in manifest["entries"]:
                self.assertEqual("succeeded", entry["status"])
                labels = gym.records.read_outcomes({"run_ids": [entry["run_id"]], "purpose": "evaluation"})
                self.assertEqual(1, len(labels))
                labels_by_run.append(labels[0])
            self.assertTrue(all(label == labels_by_run[0] for label in labels_by_run))
            frozen = gym.artifacts.read_json(summary["trajectories"]["record_snapshot_ref"])
            self.assertEqual(1, len(frozen["outcome_refs"]))
        self.assertEqual(4, summary["trajectories"]["row_count"])

    def test_empty_http_answer_remains_raw_invalid_and_keeps_planned_denominator(self):
        source = _fixture(self.root / "native", bundles=2)
        opener = _Opener("")
        with patch("gymts.http_candidate.urllib.request.build_opener", return_value=opener):
            summary = run_pipeline(self.root / "pipeline", profile_dirs=[source],
                candidate_entries=[_http_entry()], include_baseline=False, max_per_task=1)
        self.assertEqual("failed", summary["status"])
        self.assertEqual(1, len(opener.requests))
        report = _read(self.root / "pipeline/reports/pattern_trend_direction.json")
        self.assertEqual(1, report["coverage"]["expected_units"])
        self.assertEqual(1, report["coverage"]["succeeded_runs"])
        self.assertEqual(0, report["coverage"]["failed_runs"])
        metric = next(m for m in report["metrics"] if m["level"] == "unit")
        self.assertEqual({"eligible": 1, "scored": 0, "missing": 0, "invalid": 1, "excluded": 0},
                         metric["result"]["counts"])
        rows = _rows(summary["trajectories"]["path"])
        self.assertEqual(1, len(rows))
        self.assertEqual("", rows[0]["output"]["payload"]["value"]["raw_text"])
        result = rows[0]["result"]
        self.assertEqual("invalid", result["status"])
        self.assertEqual("empty_output", result["payload"]["value"]["reason"])
        with GymTS(self.root / "pipeline/records", integrations=("chatts",)) as gym:
            evidence = rows[0]["output"]["payload"]["value"]["evidence"]
            response = gym.artifacts.read_json(evidence["response_ref"])
            self.assertEqual("", response["body"]["choices"][0]["message"]["content"])
            self.assertEqual("succeeded", gym.artifacts.read_json(rows[0]["run_result_ref"])["status"])

    def test_environment_grant_does_not_grant_candidate_snapshot_or_private_gold(self):
        source = _fixture(self.root / "native", bundles=2)
        with GymTS(self.root / "gym", integrations=("chatts",)) as gym:
            imported = import_profiles(gym, [source])
            row = imported["samples"][0]
            spec = {"protocol_version": "gymts.experiment/1", "name": "permission-boundary-fixture",
                "purpose": "development", "scene": scene(imported["snapshot_ref"], imported["dataset_revision"], row),
                "candidate": baseline(row["task_id"])["spec"], "execution": execution(),
                "recording": recording(), "extensions": {}}
            checks = []
            original_prepare = ChatTSSignalBaseline.prepare

            def probe(candidate, context, training):
                for ref in (imported["snapshot_ref"], imported["private_ref"]):
                    with self.assertRaises(GymTSError) as caught:
                        context["resources"].read_json(ref)
                    self.assertEqual("permission_denied", caught.exception.code)
                    checks.append(ref)
                return original_prepare(candidate, context, training)

            with patch.object(ChatTSSignalBaseline, "prepare", probe):
                result = gym.run(spec)
            # The same explicitly granted public source was read by Environment,
            # while Candidate could only receive its projected TaskInput.
            self.assertEqual("succeeded", result["status"])
            self.assertEqual(2, len(checks))
            trace = gym.artifacts.read_json(result["trace_ref"])
            inputs = [event for event in trace["events"] if event["kind"] == "input"]
            self.assertEqual(1, len(inputs))


if __name__ == "__main__":
    unittest.main()
