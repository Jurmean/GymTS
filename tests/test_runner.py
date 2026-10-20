"""Core orchestration contracts with deterministic, effect-observable plugins."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import GymTSError, new_id, utc_now
from gymts.plugins import (CounterControlTask, CounterTransition, ForecastCandidate,
                           TimeSeriesReplay, WindowForecastTask)
from gymts.plugins.counter import CounterControlSession, IncrementPolicy
from gymts.plugins.forecast import ForecastSession


ROOT = Path(__file__).resolve().parents[1]


def update(inputs=None, feedback=None, done=False):
    return {"inputs": inputs or [], "feedback": feedback or [], "closed_cases": [], "done": done}


class RunnerContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.gym = GymTS(self.temporary.name)
        self.forecast = json.loads((ROOT / "examples/forecast_experiment.json").read_text())
        self.counter = json.loads((ROOT / "examples/counter_experiment.json").read_text())
        for spec in (self.forecast, self.counter):
            spec["recording"]["store_ref"] = "local"

    def tearDown(self):
        self.gym.close()
        self.temporary.cleanup()

    def register(self, role, original, name, factory, changes=None):
        registry = getattr(self.gym.registries, role)
        manifest = registry.resolve(original, "1.0.0")
        manifest["component_ref"]["name"] = name
        if changes:
            manifest.update(changes)
        registry.register(manifest, factory)

    def events(self, result, kind):
        return [event for event in self.gym.records.get_run(result["run_id"])["events"] if event["kind"] == kind]

    def test_candidate_failure_preserves_stage_and_cleans_all_components(self):
        calls = []
        class Failure(ForecastCandidate):
            def infer(self, task_input):
                calls.append("infer")
                raise RuntimeError("private request must not enter recorded errors")
            def finish(self):
                calls.append("candidate.finish")
                raise RuntimeError("cleanup also failed")
        self.register("candidates", "last-value", "failure-policy", Failure)
        self.forecast["candidate"]["adapter"] = "failure-policy"
        task_finish, env_finish = ForecastSession.finish, TimeSeriesReplay.finish
        def finish_task(instance, reason):
            calls.append("task.finish")
            return task_finish(instance, reason)
        def finish_environment(instance):
            calls.append("environment.finish")
            return env_finish(instance)
        with patch.object(ForecastSession, "finish", finish_task), patch.object(TimeSeriesReplay, "finish", finish_environment):
            result = self.gym.run(self.forecast)
        self.assertEqual("failed", result["status"])
        self.assertEqual(["infer", "candidate.finish", "task.finish", "environment.finish"], calls)
        self.assertEqual("candidate_failure", result["errors"][0]["code"])
        self.assertEqual("infer", result["errors"][0]["stage"])
        self.assertNotIn("private request", json.dumps(result["errors"]))
        self.assertEqual("failed", result["summary"]["cleanup"]["candidate"]["status"])
        self.assertEqual("succeeded", result["summary"]["cleanup"]["task"]["status"])
        self.assertEqual("succeeded", result["summary"]["cleanup"]["environment"]["status"])
        self.assertEqual(1, len(self.events(result, "input")))
        self.assertEqual(0, len(self.events(result, "candidate_output")))

    def test_unknown_action_is_recorded_once_and_never_resent(self):
        commands = []
        def unknown(instance, command):
            commands.append(copy.deepcopy(command))
            return {"receipt_id": new_id("receipt"), "request_id": command["request_id"],
                    "operation_id": command["operation_id"], "status": "unknown", "received_at": utc_now(),
                    "payload": None, "feedback": []}
        with patch.object(CounterTransition, "act", unknown):
            result = self.gym.run(self.counter)
        self.assertEqual("failed", result["status"])
        self.assertEqual(1, len(commands))
        self.assertEqual(1, len(self.events(result, "environment_operation")))
        self.assertEqual(1, len(self.events(result, "environment_receipt")))
        self.assertEqual("possible", result["errors"][0]["side_effect"])

    def test_online_feedback_is_deduplicated_before_new_infer_including_terminal_reward(self):
        calls = []
        class OnlineSession(CounterControlSession):
            def consume(self, batch):
                result = super().consume(batch)
                for raw in batch["feedback"]:
                    projected = {"feedback_id": "projected-" + raw["feedback_id"],
                                 "source_feedback_ids": [raw["feedback_id"]], "source_ref": raw["source_ref"],
                                 "input_id": None, "output_id": None, "available_at": raw["available_at"],
                                 "payload": raw["payload"]}
                    result["feedback"].extend([projected, copy.deepcopy(projected)])
                return result
        class OnlineTask(CounterControlTask):
            @staticmethod
            def describe_spec(spec):
                result = CounterControlTask.describe_spec(spec)
                result["plugin_ref"]["name"] = "online-task"
                return result
            def bind(self, spec, binding, environment, execution):
                return OnlineSession(execution, binding)
        class OnlineCandidate(IncrementPolicy):
            def prepare(self, context, training):
                result = super().prepare(context, training)
                self.revision = "r0"
                result["model_revision"] = self.revision
                return result
            def infer(self, task_input):
                calls.append(("infer", task_input["decision_time"]))
                result = super().infer(task_input)
                result["model_revision"] = self.revision
                return result
            def update(self, feedback):
                calls.append(("update", feedback["available_at"]))
                before = self.revision
                self.revision = "r" + str(feedback["available_at"])
                return {"feedback_id": feedback["feedback_id"], "before_revision": before,
                        "after_revision": self.revision, "state_refs": []}
        self.register("tasks", "counter_control", "online-task", OnlineTask)
        self.register("candidates", "increment-policy", "online-policy", OnlineCandidate,
                      {"supports_update": True, "model_revision_mode": "tracked"})
        self.counter["scene"]["task"]["plugin"] = "online-task"
        self.counter["candidate"]["adapter"] = "online-policy"
        self.counter["execution"]["learning"].update(online="update", allowed_feedback_sources=["counter-transition"])
        result = self.gym.run(self.counter)
        self.assertEqual("succeeded", result["status"], result["errors"])
        self.assertEqual([("infer", 0), ("update", 1), ("infer", 1), ("update", 2), ("infer", 2), ("update", 3)], calls)
        self.assertEqual(3, result["summary"]["counts"]["updates"])
        self.assertEqual(3, len(self.events(result, "environment_feedback")))
        terminal = self.events(result, "observation")[-1]["payload"]["value"]
        self.assertEqual("end", terminal["status"])
        self.assertEqual(3, terminal["feedback"][0]["event_time"])
        self.assertEqual(3, result["summary"]["counts"]["operations"])

    def test_query_continuation_precedes_other_queued_cases(self):
        calls = []
        class QuerySession(ForecastSession):
            def consume(self, batch):
                if batch["request_id"] == "query-case-a":
                    task_input = copy.deepcopy(self.first)
                    task_input.update(input_id="input-a-1", turn_id=1,
                                      observation_refs=[self.execution["data"].observation_ref(batch["batch_id"])])
                    self._done = True
                    return update([task_input], done=True)
                result = super().consume(batch)
                if result["inputs"]:
                    a = result["inputs"][0]
                    a.update(case_id="case-a", input_id="input-a-0")
                    b = copy.deepcopy(a)
                    b.update(case_id="case-b", input_id="input-b-0")
                    result["inputs"] = [a, b]
                    self.first = copy.deepcopy(a)
                    self._counts["cases_started"] += 1
                return result
            def interpret(self, task_input, output, output_id):
                if task_input["case_id"] == "case-a" and task_input["turn_id"] == 0:
                    return {"results": [], "complete": False, "requests": [{"kind": "query",
                        "request_id": "query-case-a", "case_id": "case-a", "output_id": output_id,
                        "observation": {"request_id": "query-case-a", "kind": "range", "entities": ["demo"],
                        "variables": ["value"], "scope": {"start": "2026-01-01T00:00:00Z", "end": "2026-01-01T00:01:00Z"}}}]}
                return super().interpret(task_input, output, output_id)
        class QueryTask(WindowForecastTask):
            @staticmethod
            def describe_spec(spec):
                result = WindowForecastTask.describe_spec(spec)
                result["plugin_ref"]["name"] = "query-task"
                return result
            def bind(self, spec, binding, environment, execution):
                return QuerySession(self.params, binding, execution)
        class OrderCandidate(ForecastCandidate):
            def infer(self, task_input):
                calls.append((task_input["case_id"], task_input["turn_id"]))
                return super().infer(task_input)
        self.register("tasks", "window_forecast", "query-task", QueryTask)
        self.register("candidates", "last-value", "order-policy", OrderCandidate)
        self.forecast["scene"]["task"]["plugin"] = "query-task"
        self.forecast["scene"]["task"]["params"]["window_points"] = 1
        self.forecast["candidate"]["adapter"] = "order-policy"
        result = self.gym.run(self.forecast)
        self.assertEqual("succeeded", result["status"], result["errors"])
        self.assertEqual([("case-a", 0), ("case-a", 1), ("case-b", 0)], calls)
        self.assertEqual(2, result["summary"]["counts"]["cases_completed"])
        self.assertEqual(2, result["summary"]["counts"]["results"])

    def test_attached_cleanup_only_detaches_own_session(self):
        business = {"running": True, "attaches": 0, "detaches": 0}
        class AttachedReplay(TimeSeriesReplay):
            @staticmethod
            def describe_spec(spec):
                result = TimeSeriesReplay.describe_spec(spec)
                result["adapter_ref"]["name"] = "attached-replay"
                result["capabilities"]["attach"] = True
                return result
            def start(self, spec):
                business["attaches"] += 1
                initial = copy.deepcopy(spec)
                initial["mode"] = "reinitialize"
                super().start(initial)
                self.session.update(actual_mode="attach", ownership="attached")
                return copy.deepcopy(self.session)
            def finish(self):
                if self._summary is None:
                    business["detaches"] += 1
                summary = super().finish()
                summary["backend_disposition"] = "detached"
                return summary
        self.register("environments", "local-timeseries-replay", "attached-replay", AttachedReplay)
        self.forecast["scene"]["environment"]["adapter"] = "attached-replay"
        self.forecast["execution"]["start"]["mode"] = "attach"
        result = self.gym.run(self.forecast)
        self.assertEqual("succeeded", result["status"], result["errors"])
        self.assertEqual({"running": True, "attaches": 1, "detaches": 1}, business)
        self.assertEqual("detached", result["summary"]["cleanup"]["environment"]["summary"]["backend_disposition"])

    def test_future_timestamp_with_forged_old_availability_is_rejected(self):
        observe = TimeSeriesReplay.observe
        def future(instance, request):
            batch = observe(instance, request)
            series = batch["data"]["time_series"]["series"]
            if series:
                series[0]["timestamps"][0] = "2027-01-01T00:00:00Z"
            return batch
        self.forecast["scene"]["task"]["params"]["window_points"] = 1
        with patch.object(TimeSeriesReplay, "observe", future), patch.object(ForecastCandidate, "infer") as infer:
            result = self.gym.run(self.forecast)
        self.assertEqual("failed", result["status"])
        self.assertEqual("permission_denied", result["errors"][0]["code"])
        infer.assert_not_called()

    def test_draining_reads_until_feedback_cutoff_without_further_infer(self):
        self.forecast["scene"]["task"]["params"]["window_points"] = 1
        self.forecast["execution"]["scope"]["end"] = "2026-01-01T00:03:00Z"
        self.forecast["execution"]["feedback_until"] = "2026-01-01T00:06:00Z"
        infer = ForecastCandidate.infer
        calls = []
        def record(instance, task_input):
            calls.append(task_input["decision_time"])
            return infer(instance, task_input)
        with patch.object(ForecastCandidate, "infer", record):
            result = self.gym.run(self.forecast)
        self.assertEqual("succeeded", result["status"], result["errors"])
        self.assertEqual(["2026-01-01T00:00:00Z", "2026-01-01T00:01:00Z", "2026-01-01T00:02:00Z"], calls)
        observations = self.events(result, "observation")
        self.assertEqual(6, len(observations))
        self.assertEqual("2026-01-01T00:06:00Z", observations[-1]["payload"]["value"]["clock"]["now"])
        self.assertEqual(0, result["summary"]["counts"]["operations"])

    def test_recording_failure_stops_before_candidate_or_environment_action(self):
        original = self.gym.records.append
        def failing(run_id, events):
            if any(event["kind"] == "input" for event in events):
                raise OSError("disk unavailable")
            return original(run_id, events)
        with patch.object(self.gym.records, "append", failing), patch.object(IncrementPolicy, "infer") as infer, patch.object(CounterTransition, "act") as act:
            with self.assertRaises(GymTSError) as caught:
                self.gym.run(self.counter)
        self.assertEqual("recording_failure", caught.exception.code)
        self.assertIsNotNone(caught.exception.run_id)
        infer.assert_not_called()
        act.assert_not_called()
        run = self.gym.records.get_run(caught.exception.run_id)
        self.assertIsNone(run["result"])

    def test_transition_terminal_at_decision_boundary_keeps_last_state_and_reward(self):
        self.counter["execution"]["scope"]["end"] = 3
        result = self.gym.run(self.counter)
        self.assertEqual("succeeded", result["status"], result["errors"])
        self.assertEqual("backend_terminated", result["completion"])
        self.assertEqual(3, result["summary"]["counts"]["operations"])
        self.assertEqual(3, result["summary"]["counts"]["feedback"])
        terminal = self.events(result, "observation")[-1]["payload"]["value"]
        self.assertEqual("end", terminal["status"])
        self.assertEqual(3, terminal["snapshot_time"])
        self.assertEqual(3, terminal["feedback"][0]["event_time"])
        decisions = [event["payload"]["value"]["decision_time"] for event in self.events(result, "input")]
        self.assertEqual([0, 1, 2], decisions)

    def test_session_public_context_schema_is_checked_before_candidate_prepare(self):
        start = TimeSeriesReplay.start
        def invalid_context(instance, spec):
            session = start(instance, spec)
            session["public_context"] = {"schema_ref": "unregistered/99", "storage": "inline", "value": {"private": "wrong"}}
            return session
        with patch.object(TimeSeriesReplay, "start", invalid_context), patch.object(ForecastCandidate, "prepare") as prepare:
            result = self.gym.run(self.forecast)
        self.assertEqual("failed", result["status"])
        self.assertEqual("schema_mismatch", result["errors"][0]["code"])
        prepare.assert_not_called()

    def test_frozen_candidate_may_keep_context_but_cannot_change_model_revision(self):
        class ContextCandidate(ForecastCandidate):
            def prepare(self, context, training):
                prepared = super().prepare(context, training)
                self.history = []
                prepared["model_revision"] = "fixed-r1"
                return prepared
            def infer(self, task_input):
                self.history.append(task_input["input_id"])
                output = super().infer(task_input)
                output["model_revision"] = "fixed-r1"
                return output
        self.register("candidates", "last-value", "context-policy", ContextCandidate,
                      {"model_revision_mode": "fixed"})
        self.forecast["candidate"]["adapter"] = "context-policy"
        result = self.gym.run(self.forecast)
        self.assertEqual("succeeded", result["status"], result["errors"])
        self.assertEqual(8, result["summary"]["counts"]["outputs"])
        infer = ContextCandidate.infer
        def changed(instance, task_input):
            output = infer(instance, task_input)
            output["model_revision"] = "unrecorded-r2"
            return output
        with patch.object(ContextCandidate, "infer", changed):
            result = self.gym.run(self.forecast)
        self.assertEqual("failed", result["status"])
        self.assertEqual("invalid_state", result["errors"][0]["code"])
        # Even the invalid raw output remains available for diagnosis.
        self.assertEqual(1, len(self.events(result, "candidate_output")))

    def test_nonterminal_transition_at_boundary_keeps_feedback_without_new_decision(self):
        self.counter["execution"]["scope"]["end"] = 2
        result = self.gym.run(self.counter)
        self.assertEqual("succeeded", result["status"], result["errors"])
        self.assertEqual("scope_reached", result["completion"])
        self.assertEqual(2, result["summary"]["counts"]["operations"])
        self.assertEqual(2, result["summary"]["counts"]["feedback"])
        self.assertEqual([0, 1], [event["payload"]["value"]["decision_time"] for event in self.events(result, "input")])

    def test_empty_window_without_progress_is_rejected_instead_of_busy_loop(self):
        observe = TimeSeriesReplay.observe
        def stalled(instance, request):
            batch = observe(instance, request)
            batch.update(status="data", end=None, coverage=None, data={"time_series": {"series": []}, "native": None})
            return batch
        with patch.object(TimeSeriesReplay, "observe", stalled), patch.object(ForecastCandidate, "infer") as infer:
            result = self.gym.run(self.forecast)
        self.assertEqual("failed", result["status"])
        self.assertEqual("schema_mismatch", result["errors"][0]["code"])
        infer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
