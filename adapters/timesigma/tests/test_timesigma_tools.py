"""Tool dispatch persists request/response evidence before external effects."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import GymTSError
from gymts_timesigma.tools import TimeSigmaTools


class TimeSigmaToolTests(unittest.TestCase):
    def test_successful_and_failed_calls_are_durably_indexed_and_redacted(self):
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym:
            tools = TimeSigmaTools(gym, source_repo="unused", python="unused")
            manifest = tools.call("task.describe", {})
            self.assertEqual("gymts.task/timesigma-tsad/1", manifest["task_protocol_ref"])
            completed = gym.artifacts.read_json(tools.last_call_ref)
            self.assertEqual("completed", completed["phase"])
            request = gym.artifacts.read_json(completed["request_ref"])
            self.assertEqual({}, request["arguments"])
            with self.assertRaises(GymTSError):
                tools.call("not-allowed", {"env": {"PROVIDER_API_KEY": "sensitive-arbitrary"}})
            failed = gym.artifacts.read_json(tools.last_call_ref)
            self.assertEqual("failed", failed["phase"])
            self.assertNotIn("sensitive-arbitrary", json.dumps(gym.artifacts.read_json(failed["request_ref"])))
            indices = list((Path(directory) / "timesigma/tool-calls").glob("*.json"))
            self.assertEqual(4, len(indices))

    def test_capture_failure_and_expired_deadline_prevent_dispatch(self):
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym:
            tools = TimeSigmaTools(gym, source_repo="unused", python="unused")
            with patch.object(tools, "_call") as execute:
                with patch.object(gym.artifacts, "save_json", side_effect=GymTSError("persistence_failed", "storage")):
                    with self.assertRaises(GymTSError):
                        tools.call("experiment.run", {})
                with self.assertRaises(GymTSError):
                    tools.call("experiment.run", {}, deadline_unix_ms=int(time.time() * 1000) - 1)
                execute.assert_not_called()

    @unittest.skipUnless(os.environ.get("GYMTS_TIMESIGMA_NATIVE_TESTS") == "1", "Set GYMTS_TIMESIGMA_NATIVE_TESTS=1 for original domain tools")
    def test_original_health_and_catalog_accept_domain_payloads_without_provider(self):
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym:
            tools = TimeSigmaTools(gym,
                source_repo=os.environ.get("GYMTS_TIMESIGMA_REPO", "/tmp/gymts-timesigma-source"),
                python=os.environ.get("GYMTS_TIMESIGMA_PYTHON", "/tmp/gymts-timesigma-model-venv/bin/python"))
            health = tools.call("native.system.health", {})
            self.assertEqual("timesigma.bridge.v1", health["protocol_version"])
            catalog = tools.call("model.catalog", {})
            self.assertEqual(12, len(catalog["catalog"]))
            self.assertEqual(["AR", "IsolationForest"], catalog["adapter_execution_methods"])
            with self.assertRaises(GymTSError):
                tools.call("native.experiment.run", {})


if __name__ == "__main__":
    unittest.main()
