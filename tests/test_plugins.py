import copy
import json
import unittest
from pathlib import Path

from gymts.contracts import GymTSError, utc_now
from gymts.contracts.schema import SchemaRegistry, register_core_schemas
from gymts.plugins import (CounterTransition, ForecastCandidate, ForecastMAEScorer,
                          TimeSeriesReplay, WindowForecastTask, register_builtin_plugins)
from gymts.registries import Registries


BASE = Path(__file__).resolve().parents[1]


def example(name="forecast_experiment"):
    return json.loads((BASE / "examples" / (name + ".json")).read_text())


class MemoryServices:
    def __init__(self):
        self.items = {}

    def save_json(self, value, schema_ref="gymts.json/1"):
        ref = {"artifact_id": str(len(self.items)), "schema_ref": schema_ref}
        self.items[ref["artifact_id"]] = copy.deepcopy(value)
        return ref

    def read_json(self, ref):
        return copy.deepcopy(self.items[ref["artifact_id"]])

    def observation_ref(self, batch_id):
        return "committed-event-" + batch_id


def started_replay(spec=None):
    spec = spec or example()
    env = TimeSeriesReplay(spec["scene"]["environment"], MemoryServices())
    session = env.start({"run_id": "test-run", "mode": "reinitialize",
        "scope": spec["execution"]["scope"], "read_scope": spec["execution"]["scope"],
        "feedback_until": None, "seed": 7, "permitted_variables": ["value"], "permitted_operations": []})
    return env, session


def next_request(cursor, advance="1min"):
    return {"request_id": "request", "kind": "next", "entities": ["demo"], "variables": ["value"],
            "cursor": cursor, "advance_by": advance, "max_wait_ms": 0}


class PluginContractsTest(unittest.TestCase):
    def test_registration_and_closed_params_schema(self):
        schemas = SchemaRegistry()
        register_core_schemas(schemas)
        registries = Registries(schemas)
        register_builtin_plugins(registries, schemas)
        register_builtin_plugins(registries, schemas)
        spec = example()
        schemas.validate("gymts.experiment/1", spec)
        with self.assertRaises(GymTSError):
            schemas.validate("gymts.builtin/forecast-params/1", dict(spec["scene"]["task"]["params"], typo=True))

    def test_future_query_rejected_and_read_query_does_not_advance(self):
        env, session = started_replay()
        batch = env.observe(next_request(session["initial_cursor"]))
        query = {"request_id": "query", "kind": "range", "entities": ["demo"], "variables": ["value"],
                 "scope": {"start": "2026-01-01T00:00:00Z", "end": "2026-01-01T00:02:00Z"}}
        with self.assertRaises(GymTSError) as caught:
            env.observe(query)
        self.assertEqual(caught.exception.code, "permission_denied")
        query["scope"]["end"] = "2026-01-01T00:01:00Z"
        queried = env.observe(query)
        self.assertEqual(queried["cursor"], batch["cursor"])
        self.assertEqual(queried["data"]["time_series"]["series"][0]["values"], [0])
        with self.assertRaises(GymTSError) as caught:
            env.observe(next_request(session["initial_cursor"]))
        self.assertEqual(caught.exception.code, "cursor_mismatch")

    def test_empty_window_advances_empty_selection_does_not_mean_all(self):
        spec = example()
        env_spec = spec["scene"]["environment"]
        env_spec["source"]["connection"] = {"points": [{"timestamp": "2026-01-01T00:03:00Z", "values": {"value": 7}}]}
        env, session = started_replay(spec)
        empty = env.observe(next_request(session["initial_cursor"]))
        self.assertEqual(empty["status"], "data")
        self.assertEqual(empty["data"]["time_series"]["series"], [])
        self.assertNotEqual(empty["cursor"], session["initial_cursor"])
        query = {"request_id": "query", "kind": "range", "entities": [], "variables": [],
                 "scope": {"start": "2026-01-01T00:00:00Z", "end": "2026-01-01T00:01:00Z"}}
        self.assertEqual(env.observe(query)["cursor"], empty["cursor"])

    def test_late_point_is_delivered_only_after_actual_availability(self):
        spec = example()
        env_spec = spec["scene"]["environment"]
        env_spec["options"]["availability"] = "explicit"
        env_spec["source"]["connection"] = {"points": [{"timestamp": "2026-01-01T00:00:00Z",
            "available_at": "2026-01-01T00:02:00Z", "values": {"value": 8}}]}
        env, session = started_replay(spec)
        first = env.observe(next_request(session["initial_cursor"]))
        second = env.observe(next_request(first["cursor"]))
        self.assertEqual(second["data"]["time_series"]["series"], [])
        third = env.observe(next_request(second["cursor"]))
        series = third["data"]["time_series"]["series"][0]
        self.assertEqual(series["timestamps"], ["2026-01-01T00:00:00Z"])
        self.assertEqual(series["available_at"], ["2026-01-01T00:02:00Z"])
        self.assertEqual(env.finish()["counts"]["late_points"], 1)

    def test_terminal_repeat_does_not_redeliver_final_values(self):
        env, session = started_replay()
        batch = env.observe(next_request(session["initial_cursor"], "10min"))
        self.assertEqual(batch["status"], "end")
        self.assertEqual(len(batch["data"]["time_series"]["series"][0]["values"]), 10)
        terminal = env.observe(next_request(batch["cursor"]))
        self.assertIsNone(terminal["data"])
        self.assertEqual(terminal["end"], batch["end"])
        self.assertEqual(env.finish(), env.finish())

    def test_forecast_warmup_and_raw_prediction_stay_separate(self):
        spec = example()
        env, session = started_replay(spec)
        services = MemoryServices()
        task = WindowForecastTask(spec["scene"]["task"]).bind(spec["scene"]["task"], spec["scene"]["binding"],
            env.describe(), {"run_id": "test-run", "session": session, "effective_scope": spec["execution"]["scope"],
                             "execution": spec["execution"], "data": services})
        candidate = ForecastCandidate(spec["candidate"])
        candidate.prepare({"learning": spec["execution"]["learning"], "resources": services}, None)
        for i in range(3):
            update = task.consume(env.observe(task.next_observation()))
            self.assertEqual(len(update["inputs"]), int(i == 2))
        task_input = update["inputs"][0]
        self.assertTrue(task_input["observation_refs"][0].startswith("committed-event-"))
        raw = candidate.infer(task_input)
        effect = task.interpret(task_input, raw, "output")
        self.assertEqual(raw["payload"]["value"]["prediction"], 2)
        self.assertEqual(effect["results"][0]["alignment_key"]["target_time"], "2026-01-01T00:03:00Z")
        self.assertEqual(effect["results"][0]["output_id"], "output")
        self.assertEqual(task.finish("done"), task.finish("other"))

    def test_counter_observe_never_steps_and_actions_require_consumption(self):
        spec = example("counter_experiment")
        env = CounterTransition(spec["scene"]["environment"], MemoryServices())
        session = env.start({"run_id": "counter-run", "mode": "reinitialize", "scope": {"start": 0, "end": 10},
            "read_scope": {"start": 0, "end": 10}, "feedback_until": None, "seed": 7,
            "permitted_variables": ["counter"], "permitted_operations": ["increment"]})
        command = {"operation_id": "op-1", "request_id": "action-1", "output_id": "output-1",
            "origin": "candidate", "trigger_batch_id": None, "name": "increment", "idempotency_key": None,
            "arguments": {"schema_ref": "gymts.builtin/increment-arguments/1", "storage": "inline", "value": {"amount": 1}}}
        with self.assertRaises(GymTSError):
            env.act(command)
        request = {"request_id": "next", "kind": "next", "entities": ["counter"], "variables": ["counter"],
                   "cursor": session["initial_cursor"], "max_wait_ms": 0}
        initial = env.observe(request)
        request["cursor"] = initial["cursor"]
        self.assertEqual(env.observe(request)["status"], "waiting")
        self.assertEqual(env.step, 0)
        env.act(command)
        with self.assertRaises(GymTSError):
            env.act(command)
        transition = env.observe(request)
        self.assertEqual(transition["snapshot_time"], 1)
        self.assertEqual(len(transition["feedback"]), 1)
        request["cursor"] = transition["cursor"]
        self.assertEqual(env.observe(request)["feedback"], [])
        self.assertEqual(env.finish(), env.finish())

    def test_mae_missing_outcomes_preserves_eligible_denominator(self):
        services = MemoryServices()
        records = []
        for i in range(2):
            records.append({"result_id": str(i), "status": "valid", "alignment_key": {"target_time": str(i)},
                "payload": {"storage": "inline", "schema_ref": "gymts.builtin/forecast-result/1",
                            "value": {"prediction": 2.0, "reason": None}}})
        outcome = {"outcome_id": "label", "revision": "1", "alignment_key": {"target_time": "0"},
            "payload": {"storage": "inline", "schema_ref": "gymts.builtin/forecast-outcome/1", "value": {"value": 1}},
            "available_at": utc_now(), "recorded_at": utc_now(), "allowed_uses": ["evaluation"]}
        result_view = {"records_ref": services.save_json({"records": records})}
        outcome_view = {"records_ref": services.save_json({"records": [outcome]})}
        scoring = {"alignment": {"matching": "exact", "keys": ["target_time"], "duplicate_policy": "error"},
                   "evidence_requirements": {"min_scored": 1, "min_coverage": .5, "overrides": {}}}
        scorer = ForecastMAEScorer({"params": {}})
        result = scorer.score(result_view, outcome_view, {"services": services, "scoring": scoring})["metrics"]["mae"]
        self.assertEqual(result["counts"], {"eligible": 2, "scored": 1, "missing": 1, "invalid": 0, "excluded": 0})
        self.assertEqual(result["value"], 1)
        outcome_view = {"records_ref": services.save_json({"records": []})}
        insufficient = scorer.score(result_view, outcome_view, {"services": services, "scoring": scoring})["metrics"]["mae"]
        self.assertEqual(insufficient["status"], "insufficient_evidence")
        self.assertIsNone(insufficient["value"])

    def test_forecast_durations_rejected_during_task_creation(self):
        for field in ("horizon", "advance_by", "warmup_duration"):
            spec = example()["scene"]["task"]
            spec["params"][field] = "not-a-duration"
            with self.assertRaises(GymTSError):
                WindowForecastTask(spec)


if __name__ == "__main__":
    unittest.main()
