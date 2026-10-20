"""Parent journals preserve budgets, failed calls and native child references."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import GymTSError
from gymts_timesigma.research import ResearchEpisode, redact
from gymts_timesigma.trajectory import export_evidence, inspect_archive


BUDGET = {"max_experiments": 1, "max_requests": 2, "max_total_tokens": 100, "max_wall_seconds": 60}


class Tools:
    def __init__(self):
        self.calls = []

    def call(self, tool, arguments, *, deadline_unix_ms=None):
        self.calls.append((tool, arguments))
        if tool == "fail":
            raise RuntimeError("PRIVATE_IMPLEMENTATION_DETAIL")
        return {"run_ids": [], "experiment_ref": None, "record_snapshot_ref": None}


class ResearchEpisodeTests(unittest.TestCase):
    def test_closed_writer_cannot_fork_resumed_journal(self):
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym:
            old = ResearchEpisode(gym, budget=BUDGET)
            identity, head = old.episode_id, old.head_ref
            old.close()
            with ResearchEpisode(gym, episode_id=identity) as resumed:
                for operation in (lambda: old.reserve_model_request({}, max_total_tokens=1),
                                  lambda: old.call_tool(Tools(), "task.describe", {}), old.finish, old.snapshot):
                    with self.assertRaises(GymTSError):
                        operation()
                self.assertEqual(head, resumed.head_ref)
                self.assertEqual(1, len(resumed.entries()))

    def test_secret_headers_and_environment_names_are_redacted_without_known_key_prefix(self):
        captured = redact({"env": {"TIMESIGMA_OPENAI_API_KEY": "private-value"},
            "headers": {"x-api-key": "private-value", "Authorization": "Bearer arbitrary"},
            "clientSecret": "private-value", "usage": {"total_tokens": 12}, "credential_ref": "local://provider"})
        self.assertNotIn("private-value", json.dumps(captured))
        self.assertNotIn("Bearer arbitrary", json.dumps(captured))
        self.assertEqual(12, captured["usage"]["total_tokens"])
        self.assertEqual("local://provider", captured["credential_ref"])

    def test_provider_usage_overrun_is_recorded_truthfully_and_stops_execution(self):
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym:
            with ResearchEpisode(gym, budget=BUDGET) as episode:
                ticket = episode.reserve_model_request({}, max_total_tokens=50)
                with self.assertRaises(GymTSError):
                    episode.settle_model_request(ticket, response={"text": "usage"}, total_tokens=120)
                self.assertEqual(120, episode.state["tokens_accounted"])
                self.assertEqual("budget_exceeded", episode.state["status"])
                with self.assertRaises(GymTSError):
                    episode.reserve_model_request({}, max_total_tokens=1)
                self.assertEqual(120, episode.entries()[-1]["payload"]["reported_total_tokens"])
                episode.finish(reason="provider_usage_overrun")

    def test_resumption_preserves_charged_requests_and_redacted_transcript(self):
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym:
            secret = "sk-" + "x" * 40
            with ResearchEpisode(gym, budget=BUDGET) as episode:
                identity = episode.episode_id
                ticket = episode.reserve_model_request({"authorization": secret, "messages": [{"content": "key=" + secret}]}, max_total_tokens=60)
                episode.settle_model_request(ticket, response={"text": "controlled hypothesis"}, total_tokens=40)
                # An interrupted/unknown request keeps its whole reservation.
                episode.reserve_model_request({"messages": []}, max_total_tokens=50)
                head = episode.head_ref
            with ResearchEpisode(gym, episode_id=identity) as resumed:
                self.assertEqual(head, resumed.head_ref)
                self.assertEqual(90, resumed.state["tokens_accounted"])
                self.assertEqual(2, resumed.state["requests"])
                with self.assertRaises(GymTSError):
                    resumed.reserve_model_request({}, max_total_tokens=1)
                captured = json.dumps(resumed.entries())
                self.assertNotIn(secret, captured)
                self.assertIn("[redacted]", captured)
                ref = resumed.finish(reason="request_budget")
                self.assertEqual("finished", gym.artifacts.read_json(ref)["state"]["status"])
            with self.assertRaises(GymTSError):
                ResearchEpisode(gym, episode_id=identity, budget=dict(BUDGET, max_requests=3))

    def test_failed_tool_is_recorded_and_duplicate_call_cannot_execute_again(self):
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym:
            tools = Tools()
            with ResearchEpisode(gym, budget=BUDGET) as episode:
                with self.assertRaises(RuntimeError):
                    episode.call_tool(tools, "fail", {}, call_id="same")
                with self.assertRaises(GymTSError):
                    episode.call_tool(tools, "fail", {}, call_id="same")
                entries = episode.entries()
                self.assertEqual(["episode_start", "tool_request", "tool_error"], [item["kind"] for item in entries])
                self.assertNotIn("PRIVATE_IMPLEMENTATION_DETAIL", json.dumps(entries))
                self.assertEqual(1, len(tools.calls))

    def test_scope_and_experiment_budget_are_enforced_before_execution(self):
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym:
            tools = Tools()
            with ResearchEpisode(gym, budget=BUDGET, scope={"planning_unit_id": "fixed"}) as episode:
                with self.assertRaises(GymTSError):
                    episode.call_tool(tools, "experiment.run", {"imported": {"planning_unit_id": "other"}})
                self.assertEqual([], tools.calls)
                episode.call_tool(tools, "experiment.run", {"imported": {"planning_unit_id": "fixed"}})
                with self.assertRaises(GymTSError):
                    episode.call_tool(tools, "experiment.run", {"imported": {"planning_unit_id": "fixed"}})
                self.assertEqual(1, len(tools.calls))

    def test_capture_failure_prevents_tool_side_effect_and_poisoned_writer_stops(self):
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym:
            tools = Tools()
            with ResearchEpisode(gym, budget=BUDGET) as episode:
                with patch.object(gym.artifacts, "save_json", side_effect=GymTSError("persistence_failed", "storage")):
                    with self.assertRaises(GymTSError):
                        episode.call_tool(tools, "anything", {})
                self.assertEqual([], tools.calls)
                with self.assertRaises(GymTSError):
                    episode.call_tool(tools, "anything", {})

    def test_parent_archive_includes_hash_chain_and_single_writer_is_enforced(self):
        with tempfile.TemporaryDirectory() as directory, GymTS(Path(directory) / "store") as gym:
            with ResearchEpisode(gym, budget=BUDGET) as episode:
                with self.assertRaises(BlockingIOError):
                    ResearchEpisode(gym, episode_id=episode.episode_id)
                episode.call_tool(Tools(), "task.describe", {})
                reference = episode.finish()
                path = Path(directory) / "parent.zip"
                export_evidence(gym, [], path, roots=[reference])
                archived = inspect_archive(path)
                journal = [item for item in archived["artifacts"]
                           if item["reference"]["schema_ref"] == "gymts.timesigma/research-entry/1"]
                self.assertEqual(4, len(journal))


if __name__ == "__main__":
    unittest.main()
