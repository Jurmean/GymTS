"""Hard deadlines preserve real Run evidence and stop descendant processes."""
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import GymTSError
from gymts_timesigma import execution


BASE = Path(__file__).resolve().parents[1]


def forecast():
    return json.loads((BASE / "tests/fixtures/forecast_experiment.json").read_text())


def child_command(operation):
    return [sys.executable, "-B", "-c", "\n".join([
        "from gymts_timesigma.execution import _worker_main",
        operation,
        "raise SystemExit(_worker_main(operation))",
    ])]


class TimeSigmaExecutionTests(unittest.TestCase):
    def test_capture_records_two_actual_runs_and_restores_public_method(self):
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym:
            implementation = gym.records.begin_run.__func__
            def operation():
                return [gym.run(forecast()), gym.run(forecast())]
            captured = execution.capture_runs(gym, operation)
            expected = [item["run_id"] for item in captured["result"]]
            self.assertEqual(expected, captured["run_ids"])
            self.assertEqual(2, len(set(expected)))
            self.assertIs(implementation, gym.records.begin_run.__func__)
            self.assertNotIn("begin_run", vars(gym.records))
            snapshot = gym.records.get_snapshot(captured["record_snapshot_ref"])
            self.assertEqual(expected, [item["run_id"] for item in snapshot["runs"]])
            self.assertTrue(all(item["result_ref"] is not None for item in snapshot["runs"]))
            receipt = gym.artifacts.read_json(captured["execution_receipt_ref"])
            self.assertEqual("completed", receipt["phase"])
            self.assertEqual(expected, receipt["run_ids"])

    def test_error_after_real_run_keeps_id_snapshot_and_safe_failure(self):
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym:
            completed = []
            def operation():
                completed.append(gym.run(forecast())["run_id"])
                raise RuntimeError("DO_NOT_PERSIST_PRIVATE_ERROR_TEXT")
            with self.assertRaises(GymTSError) as caught:
                execution.capture_runs(gym, operation)
            info = caught.exception.to_dict()
            self.assertEqual(completed, info["links"]["run_ids"])
            self.assertEqual("succeeded", gym.records.get_run(completed[0])["result"]["status"])
            self.assertEqual("failed", info["links"]["phase"])
            self.assertIsNotNone(info["links"]["record_snapshot_ref"])
            self.assertNotIn("DO_NOT_PERSIST_PRIVATE_ERROR_TEXT", json.dumps(info))

    def test_receipt_failure_after_allocation_prevents_candidate_preparation(self):
        from gymts.plugins.forecast import ForecastCandidate
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym:
            original = execution._write_receipt
            def failed_receipt(path, value):
                if value["phase"] == "run_allocated":
                    raise OSError("receipt durability unavailable")
                return original(path, value)
            with patch.object(execution, "_write_receipt", side_effect=failed_receipt), \
                    patch.object(ForecastCandidate, "prepare", autospec=True) as prepare:
                with self.assertRaises(GymTSError) as caught:
                    execution.capture_runs(gym, lambda: gym.run(forecast()))
            prepare.assert_not_called()
            ids = caught.exception.to_dict()["links"]["run_ids"]
            self.assertEqual(1, len(ids))
            run = gym.records.get_run(ids[0])
            self.assertIsNone(run["result"])
            self.assertEqual([], run["events"])
            snapshot = gym.records.get_snapshot(caught.exception.to_dict()["links"]["record_snapshot_ref"])
            self.assertEqual(ids[0], snapshot["runs"][0]["run_id"])
            self.assertIsNone(snapshot["runs"][0]["result_ref"])

    def test_initial_receipt_failure_prevents_any_operation_or_worker(self):
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym, \
                patch.object(execution, "_write_receipt", side_effect=OSError("unavailable")), \
                patch.object(execution.subprocess, "Popen") as spawn:
            called = []
            with self.assertRaises(GymTSError) as caught:
                execution.capture_runs(gym, lambda: called.append(True))
            self.assertEqual([], called)
            self.assertEqual([], caught.exception.to_dict()["links"]["run_ids"])
            with self.assertRaises(GymTSError) as caught:
                execution.run_with_deadline(gym, {"params": {}, "imported": {}},
                    deadline_unix_ms=int(time.time() * 1000) + 5000)
            self.assertEqual("recording_failure", caught.exception.code)
            spawn.assert_not_called()

    def test_final_receipt_write_failure_retains_already_published_native_snapshot(self):
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym:
            original = execution._write_receipt
            def failed_final(path, value):
                if value["phase"] == "completed":
                    raise OSError("final receipt publication failed")
                return original(path, value)
            with patch.object(execution, "_write_receipt", side_effect=failed_final):
                with self.assertRaises(GymTSError) as caught:
                    execution.capture_runs(gym, lambda: gym.run(forecast()))
            links = caught.exception.to_dict()["links"]
            self.assertEqual("capture_failed", links["phase"])
            self.assertEqual(1, len(links["run_ids"]))
            self.assertIsNotNone(links["record_snapshot_ref"])
            self.assertIsNotNone(links["execution_receipt_ref"])
            self.assertEqual(links["run_ids"], gym.artifacts.read_json(links["execution_receipt_ref"])["run_ids"])

    def test_expired_invalid_or_nonfinite_requests_never_spawn(self):
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym, \
                patch.object(execution.subprocess, "Popen") as spawn:
            for deadline, arguments in [
                (int(time.time() * 1000) - 1, {"params": {}, "imported": {}}),
                (True, {"params": {}, "imported": {}}),
                (int(time.time() * 1000) + 5000, {"params": {"bad": float("nan")}, "imported": {}}),
                (int(time.time() * 1000) + 5000, {"score_spec": {}, "params": {}, "imported": {}}),
                (int(time.time() * 1000) + 5000, {"score_spec": None}),
            ]:
                with self.subTest(deadline=deadline), self.assertRaises(GymTSError):
                    execution.run_with_deadline(gym, arguments, deadline_unix_ms=deadline)
            spawn.assert_not_called()

    def test_host_process_returns_real_store_refs_and_filters_provider_environment(self):
        operation = """
def operation(gym, arguments):
    import os
    assert 'TIMESIGMA_OPENAI_API_KEY' not in os.environ
    assert 'AUTHORIZATION' not in os.environ
    assert 'TIMESIGMA_PROVIDER_ENV_FILE' not in os.environ
    result = gym.run(arguments['imported'])
    return {'run_ids': [result['run_id']], 'result_ref': gym.records.get_run(result['run_id'])['result_ref']}
"""
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym, \
                patch.object(execution, "_worker_command", return_value=child_command(operation)), \
                patch.dict(os.environ, {"TIMESIGMA_OPENAI_API_KEY": "private-placeholder", "AUTHORIZATION": "Bearer private",
                    "TIMESIGMA_PROVIDER_ENV_FILE": "/private/placeholder.env"}):
            result = execution.run_with_deadline(gym, {"params": {}, "imported": forecast()},
                deadline_unix_ms=int(time.time() * 1000) + 10000)
            self.assertEqual("succeeded", gym.records.get_run(result["run_ids"][0])["result"]["status"])
            self.assertEqual("succeeded", gym.artifacts.read_json(result["result_ref"])["status"])
            receipts = list((Path(directory) / "timesigma/executions").glob("*/receipt.json"))
            self.assertEqual(1, len(receipts))
            self.assertEqual(result["run_ids"], json.loads(receipts[0].read_text())["run_ids"])

    def test_worker_error_after_allocating_run_returns_its_evidence(self):
        operation = """
def operation(gym, arguments):
    from gymts.contracts import GymTSError
    result = gym.run(arguments['imported'])
    raise GymTSError('conflict', 'Post-run evaluation failed', stage='evaluation.test')
"""
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym, \
                patch.object(execution, "_worker_command", return_value=child_command(operation)):
            with self.assertRaises(GymTSError) as caught:
                execution.run_with_deadline(gym, {"params": {}, "imported": forecast()},
                    deadline_unix_ms=int(time.time() * 1000) + 10000)
            links = caught.exception.to_dict()["links"]
            self.assertEqual("conflict", caught.exception.code)
            self.assertEqual("evaluation.test", links["actual_phase"])
            self.assertEqual(1, len(links["run_ids"]))
            self.assertEqual("succeeded", gym.records.get_run(links["run_ids"][0])["result"]["status"])
            self.assertEqual(links["run_ids"][0], gym.records.get_snapshot(links["record_snapshot_ref"])["runs"][0]["run_id"])

    def test_rescore_deadline_stops_real_host_scoring_callback_without_allocating_run(self):
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym:
            result = gym.run(forecast())
            run_id = result["run_id"]
            original = gym.records.get_run(run_id)
            spec = json.loads((BASE / "tests/fixtures/forecast_score_template.json").read_text())
            spec["runs"][0]["run_id"] = run_id
            # First exercise the production worker's score_spec dispatch.
            scored = execution.run_with_deadline(gym, {"score_spec": spec},
                deadline_unix_ms=int(time.time() * 1000) + 15000)
            self.assertEqual("gymts.evaluation-report/1", scored["protocol_version"])
            marker = Path(directory) / "scorer-entered"
            script = "\n".join([
                "from pathlib import Path",
                "import time",
                "from gymts.plugins.scoring import ForecastMAEScorer",
                "from gymts_timesigma.execution import _worker_main",
                "def blocked(self, results, outcomes, context):",
                "    Path(" + repr(str(marker)) + ").write_text('scoring')",
                "    time.sleep(60)",
                "ForecastMAEScorer.score = blocked",
                "raise SystemExit(_worker_main())",
            ])
            with patch.object(execution, "_worker_command", return_value=[sys.executable, "-B", "-c", script]):
                with self.assertRaises(GymTSError) as caught:
                    execution.run_with_deadline(gym, {"score_spec": spec},
                        deadline_unix_ms=int(time.time() * 1000) + 8000)
            self.assertTrue(marker.exists(), "Fixture must reach the actual AutoBench scoring callback")
            self.assertEqual("deadline_exceeded", caught.exception.code)
            links = caught.exception.to_dict()["links"]
            self.assertEqual([], links["run_ids"])
            self.assertEqual([], gym.records.get_snapshot(links["record_snapshot_ref"])["runs"])
            self.assertEqual(original, gym.records.get_run(run_id))
            for path in (Path(directory) / "timesigma/executions").glob("*/receipt.json"):
                self.assertEqual([], json.loads(path.read_text())["run_ids"])

    def test_worker_start_failure_has_an_empty_native_snapshot(self):
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym, \
                patch.object(execution.subprocess, "Popen", side_effect=OSError("unavailable")):
            with self.assertRaises(GymTSError) as caught:
                execution.run_with_deadline(gym, {"params": {}, "imported": {}},
                    deadline_unix_ms=int(time.time() * 1000) + 10000)
            links = caught.exception.to_dict()["links"]
            self.assertEqual("worker_start_failed", links["phase"])
            self.assertEqual([], links["run_ids"])
            self.assertEqual([], gym.records.get_snapshot(links["record_snapshot_ref"])["runs"])

    def test_invalid_response_keeps_allocated_run_evidence(self):
        script = """
import json, sys
from gymts import GymTS
from gymts_timesigma.execution import capture_runs
request = json.load(sys.stdin)
with GymTS(request['store']) as gym:
    capture_runs(gym, lambda: gym.run(request['arguments']['imported']), receipt_path=request['receipt_path'])
print('invalid worker response')
"""
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym, \
                patch.object(execution, "_worker_command", return_value=[sys.executable, "-B", "-c", script]):
            with self.assertRaises(GymTSError) as caught:
                execution.run_with_deadline(gym, {"params": {}, "imported": forecast()},
                    deadline_unix_ms=int(time.time() * 1000) + 10000)
            links = caught.exception.to_dict()["links"]
            self.assertEqual("worker_protocol_failed", links["phase"])
            self.assertEqual(1, len(links["run_ids"]))
            self.assertEqual("succeeded", gym.records.get_run(links["run_ids"][0])["result"]["status"])

    @unittest.skipUnless(hasattr(os, "killpg") and sys.platform.startswith("linux"), "Process-group verification needs Linux")
    def test_forced_kill_preserves_an_unsealed_native_prefix_without_faking_finalization(self):
        operation = """
def operation(gym, arguments):
    import signal, time
    from gymts.plugins.forecast import ForecastCandidate
    def blocked(self, task_input):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        time.sleep(60)
    ForecastCandidate.infer = blocked
    return gym.run(arguments['imported'])
"""
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym, \
                patch.object(execution, "_worker_command", return_value=child_command(operation)):
            started = time.monotonic()
            with self.assertRaises(GymTSError) as caught:
                execution.run_with_deadline(gym, {"params": {}, "imported": forecast()},
                    deadline_unix_ms=int(time.time() * 1000) + 8000)
            self.assertLess(time.monotonic() - started, 11)
            links = caught.exception.to_dict()["links"]
            self.assertEqual("deadline_exceeded", caught.exception.code)
            self.assertEqual(1, len(links["run_ids"]))
            run = gym.records.get_run(links["run_ids"][0])
            self.assertIsNone(run["result"])
            self.assertTrue(run["events"])
            self.assertEqual("running", links["run_states"][0]["status"])
            self.assertIsNone(gym.records.get_snapshot(links["record_snapshot_ref"])["runs"][0]["result_ref"])

    @unittest.skipUnless(hasattr(os, "killpg") and sys.platform.startswith("linux"), "Process-group verification needs Linux")
    def test_deadline_seals_failed_real_run_and_kills_term_ignoring_grandchild(self):
        operation = """
def operation(gym, arguments):
    import os, subprocess, sys, time
    from pathlib import Path
    from gymts.plugins.forecast import ForecastCandidate
    def slow(self, task_input):
        command = [sys.executable, '-B', '-c', 'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)']
        child = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        Path(arguments['params']['pid_file']).write_text(str(child.pid))
        time.sleep(60)
    ForecastCandidate.infer = slow
    return gym.run(arguments['imported'])
"""
        with tempfile.TemporaryDirectory() as directory, GymTS(Path(directory) / "store") as gym, \
                patch.object(execution, "_worker_command", return_value=child_command(operation)):
            marker = Path(directory) / "grandchild.pid"
            started = time.monotonic()
            try:
                with self.assertRaises(GymTSError) as caught:
                    execution.run_with_deadline(gym, {"params": {"pid_file": str(marker)}, "imported": forecast()},
                        deadline_unix_ms=int(time.time() * 1000) + 8000)
                self.assertEqual("deadline_exceeded", caught.exception.code)
                self.assertLess(time.monotonic() - started, 11)
                self.assertTrue(marker.exists(), "Fixture did not reach actual frozen inference before deadline")
                links = caught.exception.to_dict()["links"]
                self.assertEqual(1, len(links["run_ids"]))
                run = gym.records.get_run(links["run_ids"][0])
                self.assertIsNotNone(run["result"], "SIGTERM cleanup should seal the interrupted Runner")
                self.assertEqual("failed", run["result"]["status"])
                self.assertTrue(any(error["code"] == "deadline_exceeded" for error in run["result"]["errors"]))
                self.assertIsNotNone(links["record_snapshot_ref"])
                self.assertEqual("deadline_exceeded", gym.artifacts.read_json(links["execution_receipt_ref"])["phase"])
                pid = int(marker.read_text())
                stat = Path("/proc") / str(pid) / "stat"
                if stat.exists():
                    self.assertEqual("Z", stat.read_text().split()[2], "Scientific grandchild survived process-group cleanup")
            finally:
                if marker.exists():
                    try:
                        os.kill(int(marker.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass


if __name__ == "__main__":
    unittest.main()
