"""Protocol fixtures test edge contracts; the native example uses a real server."""
import copy
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from gymts import GymTS, GymTSError
from gymts.plugin_support import timestamp
from gymts_prometheus.demo import evaluation_spec
from gymts_prometheus.environment import PrometheusEnvironment


class FixtureHandler(BaseHTTPRequestHandler):
    mode, requests = "normal", []

    def do_GET(self):
        parsed = urlsplit(self.path)
        self.requests.append(self.path)
        if parsed.path == "/api/v1/status/buildinfo":
            data = {"version": "explicit-protocol-fixture"}
        else:
            params = parse_qs(parsed.query)
            if self.mode == "oversized":
                body = b'{"explicit_fixture_prefix":' + b' ' * 2048
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.mode == "error":
                body = b'{"status":"error","errorType":"bad_data","error":"explicit fixture rejection"}'
                self.send_response(400)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            start, end = float(params["start"][0]), float(params["end"][0])
            values = [[start, "42"], [start + (end - start) / 2, "NaN"], [end, "99"]]
            data = {"resultType": "matrix", "result": [{"metric": {"instance": "a"}, "values": values}]}
            if self.mode == "multiple":
                data["result"].append({"metric": {"instance": "b"}, "values": values})
            if self.mode == "empty":
                data["result"] = []
        body = json.dumps({"status": "success", "data": data}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class PrometheusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.gym = GymTS(Path(self.temp.name) / "runs", integrations=("prometheus",))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        FixtureHandler.mode, FixtureHandler.requests = "normal", []
        self.endpoint = "http://127.0.0.1:" + str(self.server.server_port)
        self.spec = evaluation_spec(self.endpoint, seconds=20)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.gym.close()
        self.temp.cleanup()

    def experiment(self):
        case = self.spec["cases"][0]
        return {"protocol_version": "gymts.experiment/1", "name": "fixture telemetry", "purpose": "development",
            "scene": case["scene"], "candidate": self.spec["candidates"][0]["spec"], "execution": case["execution"],
            "recording": case["recording"], "extensions": {}}

    def opened(self, *, two_variables=False, response_limit=None):
        scene = copy.deepcopy(self.spec["cases"][0]["scene"]["environment"])
        if two_variables:
            scene["mapping"]["variables"]["other"] = copy.deepcopy(scene["mapping"]["variables"]["value"])
            scene["source"]["connection"]["queries"]["other"] = {"expression": "other_metric"}
        if response_limit:
            scene["options"]["max_response_bytes"] = response_limit
        env = PrometheusEnvironment(scene, self.gym.artifacts)
        now = datetime.now(timezone.utc)
        scope = {"start": timestamp(now - timedelta(seconds=2)), "end": timestamp(now + timedelta(seconds=10))}
        session = env.start({"run_id": "fixture-only", "mode": "attach", "seed": None,
            "scope": scope, "read_scope": scope, "permitted_variables": list(scene["mapping"]["variables"]),
            "permitted_operations": []})
        return env, session

    def request(self, session):
        return {"request_id": "fixture-request", "kind": "next", "entities": ["testbed"], "variables": ["value"],
            "cursor": session["initial_cursor"], "advance_by": "1s", "max_wait_ms": 0}

    def test_pure_plan_and_invalid_seed_or_reset(self):
        with patch("gymts_prometheus.environment.build_opener", side_effect=AssertionError("Planning opened HTTP")):
            plan = self.gym.plan(self.experiment())
            self.assertEqual(plan["resource_checks"], "deferred_to_open")
            bad = self.experiment()
            bad["execution"]["seed"] = 9
            self.assertFalse(self.gym.validate(bad)["valid"])
        self.assertEqual(FixtureHandler.requests, [])

    def test_inclusive_prometheus_end_is_filtered_and_nonfinite_values_are_explicit(self):
        env, session = self.opened()
        batch = env.observe(self.request(session))
        series = batch["data"]["time_series"]["series"][0]
        self.assertEqual(series["values"], [42., None])
        self.assertEqual(series["valid_mask"], [True, False])
        self.assertTrue(all(t < batch["coverage"]["end"] for t in series["timestamps"]))
        self.assertTrue(all(t >= series["timestamps"][0] for t in series["available_at"]))
        summary = env.finish()
        self.assertTrue(summary["artifact_refs"])
        self.assertEqual(env.finish(), summary)
        self.assertEqual(summary["counts"]["operations"], 0)
        self.assertEqual(set(summary), {"session_id", "actual_scope", "last_cursor", "final_clock", "end",
            "counts", "pending_operations", "artifact_refs", "backend_disposition"})
        self.assertEqual(summary["backend_disposition"], "detached")
        self.assertEqual(summary["final_clock"], batch["clock"])

    def test_cached_history_does_not_dispatch_or_change_cursor_visibility(self):
        env, session = self.opened()
        batch = env.observe(self.request(session))
        before = len(FixtureHandler.requests)
        query = {"request_id": "history", "kind": "range", "entities": ["testbed"], "variables": ["value"],
            "scope": batch["coverage"]}
        result = env.observe(query)
        self.assertEqual(result["cursor"], batch["cursor"])
        self.assertEqual(result["clock"]["visible_until"], batch["clock"]["visible_until"])
        self.assertEqual(result["data"], batch["data"])
        self.assertEqual(len(FixtureHandler.requests), before)
        query["scope"] = dict(query["scope"], end=timestamp(datetime.now(timezone.utc)))
        with self.assertRaises(GymTSError):
            env.observe(query)

    def test_waiting_does_not_advance_and_empty_mature_window_does(self):
        env, session = self.opened()
        request = self.request(session)
        request["advance_by"] = "4s"
        waiting = env.observe(request)
        self.assertEqual(waiting["status"], "waiting")
        self.assertEqual(waiting["cursor"], session["initial_cursor"])
        self.assertIsNone(waiting["data"])
        self.assertIsNone(waiting["coverage"])
        self.assertEqual(waiting["clock"]["visible_until"], session["clock"]["visible_until"])
        FixtureHandler.mode = "empty"
        request["advance_by"] = "1s"
        batch = env.observe(request)
        self.assertEqual(batch["status"], "data")
        self.assertNotEqual(batch["cursor"], session["initial_cursor"])
        self.assertEqual(batch["data"]["time_series"]["series"], [])

    def test_ambiguous_series_are_rejected_and_explicit_labels_work(self):
        FixtureHandler.mode = "multiple"
        env, session = self.opened()
        with self.assertRaises(GymTSError) as error:
            env.observe(self.request(session))
        self.assertEqual(error.exception.code, "schema_mismatch")
        env.connection["queries"]["value"]["labels"] = {"instance": "a"}
        result = env.observe(self.request(session))
        self.assertEqual(result["data"]["time_series"]["series"][0]["values"][0], 42.)

    def test_read_only_permissions_and_credentials_are_not_recorded(self):
        secret = "explicit-fixture-credential-value"
        self.spec["cases"][0]["scene"]["environment"]["source"]["connection"]["token_env"] = "GYMTS_PROM_TEST_TOKEN"
        with patch.dict(os.environ, {"GYMTS_PROM_TEST_TOKEN": secret}):
            env, session = self.opened()
            batch = env.observe(self.request(session))
        with self.assertRaises(GymTSError):
            env.act({"name": "stop-server"})
        request = self.request(session)
        request["variables"] = ["not-granted"]
        with self.assertRaises(GymTSError):
            env.observe(request)
        self.assertNotIn(secret, json.dumps([json.loads(self.gym.artifacts.resolve(ref).read_bytes()) for ref in env._refs]))
        self.assertEqual(env.session["ownership"], "attached")
        self.assertFalse(self.gym.artifacts.read_json(env.finish()["artifact_refs"][-1])["server_stopped"])

    def test_bad_resource_open_is_a_sealed_failed_run(self):
        experiment = self.experiment()
        experiment["scene"]["environment"]["source"]["connection"]["base_url"] = "http://127.0.0.1:1"
        result = self.gym.run(experiment)
        self.assertEqual(result["status"], "failed")
        run = self.gym.records.get_run(result["run_id"])
        self.assertTrue(run["events"])
        self.assertTrue(any(event["kind"] == "error" for event in run["events"]))
        self.assertTrue(result["artifact_refs"])

    def test_http_failure_retains_actual_response_without_retry(self):
        env, session = self.opened()
        FixtureHandler.mode = "error"
        with self.assertRaises(GymTSError) as raised:
            env.observe(self.request(session))
        self.assertEqual(raised.exception.code, "execution_failure")
        self.assertEqual(len(FixtureHandler.requests), 2)  # One build-info and one failed range read.
        failure = self.gym.artifacts.read_json(env._refs[-1])
        self.assertEqual(failure["status_code"], 400)
        self.assertFalse(failure["retried"])
        self.assertEqual(json.loads(self.gym.artifacts.resolve(failure["response_ref"]).read_bytes())["errorType"], "bad_data")

    def test_wall_time_start_does_not_impersonate_historical_read_frontier(self):
        before = timestamp(datetime.now(timezone.utc))
        env, session = self.opened()
        self.assertGreaterEqual(session["clock"]["now"], before)
        self.assertEqual(session["clock"]["visible_until"], session["read_scope"]["start"])
        self.assertEqual(env.finish()["final_clock"], session["clock"])

    def test_history_requires_captured_variables_even_when_queried_window_was_empty(self):
        env, session = self.opened(two_variables=True)
        FixtureHandler.mode = "empty"
        first = env.observe(self.request(session))
        query = {"request_id": "history", "kind": "range", "entities": ["testbed"],
            "variables": ["other"], "scope": first["coverage"]}
        count = len(FixtureHandler.requests)
        with self.assertRaises(GymTSError) as raised:
            env.observe(query)
        self.assertEqual(raised.exception.code, "unsupported_capability")
        query["variables"] = ["value"]
        self.assertEqual(env.observe(query)["data"]["time_series"]["series"], [])
        self.assertEqual(len(FixtureHandler.requests), count)
        second_request = self.request(session)
        second_request["cursor"] = first["cursor"]
        second = env.observe(second_request)
        query["scope"] = {"start": first["coverage"]["start"], "end": second["coverage"]["end"]}
        self.assertEqual(env.observe(query)["coverage"], query["scope"])

    def test_oversized_response_keeps_bounded_prefix_and_marks_truncation(self):
        env, session = self.opened(response_limit=1024)
        FixtureHandler.mode = "oversized"
        with self.assertRaises(GymTSError) as raised:
            env.observe(self.request(session))
        self.assertEqual(raised.exception.code, "resource_exhausted")
        failure = self.gym.artifacts.read_json(env._refs[-1])
        self.assertTrue(failure["response_truncated"])
        self.assertFalse(failure["retried"])
        prefix = self.gym.artifacts.resolve(failure["response_ref"]).read_bytes()
        self.assertEqual(len(prefix), 1024)
        self.assertTrue(prefix.startswith(b'{"explicit_fixture_prefix":'))

    def test_unstarted_summary_is_complete_and_idempotent(self):
        env = PrometheusEnvironment(self.spec["cases"][0]["scene"]["environment"], self.gym.artifacts)
        summary = env.finish()
        self.assertEqual(summary["backend_disposition"], "not_started")
        self.assertIsNone(summary["session_id"])
        self.assertIsNone(summary["final_clock"])
        self.assertEqual(env.finish(), summary)
