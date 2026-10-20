"""Native payload, immutable evidence and numerical-baseline contract checks."""
import copy
import io
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from gymts.contracts import GymTSError
from gymts import GymTS
from gymts_chatts import register_chatts_plugins
from gymts_chatts.candidate import (ChatTSHTTPCandidate,
    ChatTSSignalBaseline, INPUT, PROTOCOL, TASK_IDS)
from gymts.plugin_support import payload
from gymts.storage import ArtifactStore


def task_input(timeseries=None, names=None, messages=None, context=None):
    arrays = timeseries if timeseries is not None else [[1.0, 2.0, 3.0]]
    return {"input_id": "input-1", "task_protocol_ref": PROTOCOL,
            "payload": payload(INPUT, {
                "messages": messages or [{"role": "user", "content": "Analyze " + " ".join("<ts><ts/>" for _ in arrays)}],
                "timeseries": arrays, "series_names": names or ["series"] * len(arrays),
                "output_schema": {"type": "object"}, "context": context or {}})}


class Response:
    status = 200

    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def read(self, size):
        return self.body[:size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


class Opener:
    def __init__(self, *bodies):
        self.bodies, self.calls = list(bodies), []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        body = self.bodies.pop(0)
        if isinstance(body, Exception):
            raise body
        return Response(body)


def completion(text='{"trend_direction":"increasing"}', fingerprint="fp-stable", model="chatts"):
    return {"model": model, "system_fingerprint": fingerprint,
            "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 17, "completion_tokens": 4}}


class ChatTSCandidateContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.artifacts = ArtifactStore(Path(self.temp.name) / "artifacts")
        self.context = {"resources": self.artifacts,
                        "learning": {"prepare": "load_only", "online": "frozen"}}

    def tearDown(self):
        self.temp.cleanup()

    def candidate(self, **params):
        spec = {"params": dict({"base_url": "http://127.0.0.1:12345/v1", "model": "chatts",
                                "model_revision": "fixed-checkpoint"}, **params),
                "artifact": None, "inherited_state": None}
        return ChatTSHTTPCandidate(spec)

    def test_top_level_native_arrays_exact_order_no_normalization_and_artifact_capture(self):
        candidate = self.candidate()
        prepared = candidate.prepare(self.context, None)
        candidate.opener = Opener(completion())
        native = [[-200.5, 0, 400.25], [90, 80, 70]]
        source = task_input(native, ["query", "candidate_a"])
        original = copy.deepcopy(source)
        output = candidate.infer(source)
        sent = json.loads(candidate.opener.calls[0][0].data)
        self.assertEqual(native, sent["timeseries"])
        self.assertEqual(original, source)
        self.assertEqual(False, sent["stream"])
        self.assertEqual(120.0, candidate.opener.calls[0][1])
        self.assertEqual("fixed-checkpoint", output["model_revision"])
        evidence = output["payload"]["value"]["evidence"]
        request = self.artifacts.read_json(evidence["request_ref"])
        self.assertEqual(native, request["native_timeseries"])
        self.assertEqual({"prompt_tokens": 17, "completion_tokens": 4}, evidence["usage"])
        self.assertEqual("not_collected", evidence["model_calls"])
        deployment = self.artifacts.read_json(prepared["state_refs"][0])
        self.assertEqual("configured", deployment["revision_provenance"])
        self.assertFalse(deployment["revision_verified"])
        self.assertNotIn("base_url", json.dumps(deployment))
        self.assertEqual(3, len(candidate.finish()))

    def test_execution_seed_is_requested_only_by_declared_wire_dialects(self):
        for dialect, sent in (("chatts-timeseries/v1", False), ("chatts-vllm-text-envelope/v1", True)):
            with self.subTest(dialect=dialect):
                candidate = self.candidate(dialect=dialect)
                prepared = candidate.prepare(dict(self.context, execution_seed=17), None)
                candidate.opener = Opener(completion())
                output = candidate.infer(task_input())
                wire = json.loads(candidate.opener.calls[0][0].data)
                self.assertEqual(sent, "seed" in wire)
                if sent:
                    self.assertEqual(17, wire["seed"])
                evidence = output["payload"]["value"]["evidence"]
                self.assertEqual({"requested_seed": 17, "parameter_sent": sent, "backend_enforcement": "unverified"},
                                 evidence["randomness"])
                self.assertEqual(evidence["randomness"], self.artifacts.read_json(prepared["state_refs"][0])["randomness"])
                self.assertNotIn("seed", candidate.spec["params"])

    def test_text_envelopes_use_existing_placeholders_in_order_without_duplicates(self):
        candidate = self.candidate(dialect="chatts-vllm-text-envelope/v1", enable_thinking=False, json_object=True)
        candidate.prepare(self.context, None)
        candidate.opener = Opener(completion())
        candidate.infer(task_input([[1, 2], [3, 4]], ["x", "y"], messages=[
            {"role": "system", "content": "Analyze."},
            {"role": "user", "content": "x: <ts><ts/> and y: <ts><ts/>. Return JSON."}]))
        sent = json.loads(candidate.opener.calls[0][0].data)
        self.assertNotIn("timeseries", sent)
        parts = sent["messages"][-1]["content"]
        self.assertEqual(2, sum(part["text"].count("<ts><ts/>") for part in parts))
        self.assertEqual(["chatts-timeseries:v1:[1,2]", "chatts-timeseries:v1:[3,4]"],
                         [part["text"] for part in parts if part["text"].startswith("chatts-timeseries:")])
        self.assertEqual({"enable_thinking": False}, sent["chat_template_kwargs"])
        self.assertEqual({"type": "json_object"}, sent["response_format"])

    def test_nonfinite_bool_and_partial_placeholder_mismatch_rejected_before_transport(self):
        for arrays, messages in [([[float("nan")]], None), ([[True]], None), ([[float("inf")]], None),
                                 ([[1, 2], [3, 4]], [{"role": "user", "content": "Only one <ts><ts/>."}])]:
            with self.subTest(arrays=arrays):
                candidate = self.candidate()
                candidate.prepare(self.context, None)
                candidate.opener = Opener(completion())
                with self.assertRaises(GymTSError) as caught:
                    candidate.infer(task_input(arrays, messages=messages))
                self.assertEqual("schema_mismatch", caught.exception.code)
                self.assertEqual([], candidate.opener.calls)

    def test_real_bench_named_prompt_without_placeholder_supported_by_both_dialects(self):
        prompt = [{"role": "system", "content": "You are a time-series analysis expert."},
                  {"role": "user", "content": "Determine the overall trend direction. The observed time series is named Series 1. Return JSON."}]
        source = task_input([[0.0, 1.0, 2.0, 3.0]], ["Series 1"], messages=prompt)
        for dialect in ("chatts-timeseries/v1", "chatts-vllm-text-envelope/v1"):
            with self.subTest(dialect=dialect):
                candidate = self.candidate(dialect=dialect)
                candidate.prepare(self.context, None)
                candidate.opener = Opener(completion())
                candidate.infer(source)
                wire = json.loads(candidate.opener.calls[0][0].data)
                if dialect == "chatts-timeseries/v1":
                    self.assertEqual(prompt, wire["messages"])
                    self.assertEqual([[0.0, 1.0, 2.0, 3.0]], wire["timeseries"])
                else:
                    parts = wire["messages"][-1]["content"]
                    self.assertEqual(prompt[-1]["content"], parts[0]["text"])
                    self.assertEqual("\nAttached time series Series 1: <ts><ts/>", parts[1]["text"])
                    self.assertEqual("chatts-timeseries:v1:[0.0,1.0,2.0,3.0]", parts[2]["text"])
        raw = self.baseline("pattern.trend_direction").infer(source)["payload"]["value"]["raw_text"]
        self.assertEqual({"trend_direction": "increasing"}, json.loads(raw))

    def test_auth_secret_is_only_in_transport_header_never_artifacts_or_output(self):
        secret = "fixture-secret-DO-NOT-PERSIST"
        candidate = self.candidate(api_key_env="GYMTS_TEST_SECRET")
        with patch.dict(os.environ, {"GYMTS_TEST_SECRET": secret}):
            candidate.prepare(self.context, None)
        candidate.opener = Opener(completion(text=secret))
        output = candidate.infer(task_input())
        self.assertEqual("Bearer " + secret, candidate.opener.calls[0][0].get_header("Authorization"))
        for ref in candidate.finish():
            self.assertNotIn(secret, self.artifacts.resolve(ref).read_text())
        self.assertNotIn(secret, json.dumps(output))
        self.assertEqual("[REDACTED]", output["payload"]["value"]["raw_text"])

    def test_expected_fingerprint_and_midrun_identity_change_fail_closed(self):
        candidate = self.candidate(expected_system_fingerprint="fp-stable")
        candidate.prepare(self.context, None)
        candidate.opener = Opener(completion(fingerprint="fp-other"))
        with self.assertRaises(GymTSError):
            candidate.infer(task_input())
        self.assertEqual(3, len(candidate.finish()))
        candidate = self.candidate()
        candidate.prepare(self.context, None)
        candidate.opener = Opener(completion(), completion(model="changed-backend"))
        candidate.infer(task_input())
        with self.assertRaisesRegex(GymTSError, "identity changed"):
            candidate.infer(task_input())
        self.assertEqual(2, len(candidate.opener.calls))

    def test_transport_failure_never_retries_and_keeps_error_secret_free(self):
        candidate = self.candidate()
        candidate.prepare(self.context, None)
        candidate.opener = Opener(urllib.error.URLError("https://private-host/private?token=SECRET"))
        with self.assertRaises(GymTSError) as caught:
            candidate.infer(task_input())
        self.assertEqual(1, len(candidate.opener.calls))
        self.assertNotIn("SECRET", json.dumps(caught.exception.to_dict()))
        self.assertEqual(2, len(candidate.finish()))

    def test_invalid_response_body_retained_as_artifact_and_no_output_fabricated(self):
        candidate = self.candidate()
        candidate.prepare(self.context, None)
        candidate.opener = Opener(b"not-json")
        with self.assertRaisesRegex(GymTSError, "invalid JSON") as caught:
            candidate.infer(task_input())
        ref = caught.exception.to_dict()["links"]["response_ref"]
        self.assertEqual("not-json", self.artifacts.read_json(ref)["unparsed_body"])

    def test_http_rejection_body_captured_redacted_once_without_retry(self):
        secret = "reject-fixture-secret"
        candidate = self.candidate(api_key_env="GYMTS_TEST_SECRET")
        with patch.dict(os.environ, {"GYMTS_TEST_SECRET": secret}):
            candidate.prepare(self.context, None)
        error = urllib.error.HTTPError("http://private-host", 429, "private-message", {},
                                       io.BytesIO(json.dumps({"error": {"message": secret}}).encode()))
        candidate.opener = Opener(error)
        with self.assertRaises(GymTSError) as caught:
            candidate.infer(task_input())
        recorded_error = caught.exception.to_dict()
        self.assertEqual(429, recorded_error["links"]["http_status"])
        body = self.artifacts.read_json(recorded_error["links"]["response_ref"])
        self.assertEqual("[REDACTED]", body["body"]["error"]["message"])
        self.assertNotIn(secret, json.dumps(recorded_error))
        self.assertEqual(1, len(candidate.opener.calls))

    def test_missing_usage_is_not_fabricated_as_zero_and_missing_content_fails(self):
        candidate = self.candidate()
        candidate.prepare(self.context, None)
        body = completion()
        del body["usage"]
        candidate.opener = Opener(body, {"choices": []})
        evidence = candidate.infer(task_input())["payload"]["value"]["evidence"]
        self.assertIsNone(evidence["usage"])
        with self.assertRaises(GymTSError):
            candidate.infer(task_input())

    def test_lifecycle_and_fixed_deployment_config_contracts(self):
        candidate = self.candidate()
        with self.assertRaises(GymTSError):
            candidate.infer(task_input())
        candidate.prepare(self.context, None)
        with self.assertRaises(GymTSError):
            candidate.prepare(self.context, None)
        with self.assertRaises(GymTSError):
            candidate.update({})
        self.assertEqual(candidate.finish(), candidate.finish())
        for params in ({"model_revision": ""}, {"dialect": "openai-chat/v1"},
                       {"base_url": "http://key:secret@localhost/v1"}, {"timeout_seconds": 0},
                       {"max_tokens": True}, {"temperature": -1}, {"api_key": "plaintext"},
                       {"api_key_env": "bad env"}, {"json_object": True}):
            with self.subTest(params=params), self.assertRaises(GymTSError):
                self.candidate(**params)

    def baseline(self, task_id):
        candidate = ChatTSSignalBaseline({"params": {"task_id": task_id}})
        candidate.prepare(self.context, None)
        return candidate

    def test_signal_baseline_gives_schema_shaped_outputs_for_all_seven_tasks(self):
        base = [math.sin(i * 2 * math.pi / 16) for i in range(128)]
        fixtures = {
            "pattern.trend_direction": task_input([[float(i) for i in range(32)]]),
            "anomaly.point_indices": task_input([[0.0] * 12 + [20.0] + [0.0] * 19]),
            "forecast.numeric": task_input([[float(i) for i in range(32)]], context={"horizon": 4}),
            "pattern.seasonality_profile": task_input([base]),
            "process.stationarity_type": task_input([[float(i) for i in range(64)]]),
            "relation.lagged_dependence": task_input([base, [0.0] * 3 + base[:-3]], ["series_x", "series_y"]),
            "similarity.shape_retrieval": task_input([base, base, list(reversed(base))], ["query", "candidate_a", "candidate_b"]),
        }
        expected_fields = {"pattern.trend_direction": "trend_direction", "anomaly.point_indices": "indices",
                           "forecast.numeric": "forecast", "pattern.seasonality_profile": "profile",
                           "process.stationarity_type": "type", "relation.lagged_dependence": "direction",
                           "similarity.shape_retrieval": "candidate_id"}
        self.assertEqual(set(TASK_IDS), set(fixtures))
        for task_id, input_ in fixtures.items():
            with self.subTest(task_id=task_id):
                output = self.baseline(task_id).infer(input_)
                value = output["payload"]["value"]
                prediction = json.loads(value["raw_text"])
                self.assertIn(expected_fields[task_id], prediction)
                self.assertEqual("signal_algorithm_baseline", value["evidence"]["kind"])
                self.assertFalse(value["evidence"]["gold_access"])
        self.assertEqual({"indices": [12]}, json.loads(self.baseline("anomaly.point_indices").infer(fixtures["anomaly.point_indices"])["payload"]["value"]["raw_text"]))
        self.assertEqual([32.0, 33.0, 34.0, 35.0], json.loads(self.baseline("forecast.numeric").infer(fixtures["forecast.numeric"])["payload"]["value"]["raw_text"])["forecast"])

    def test_baseline_ignores_gold_and_requires_public_forecast_horizon(self):
        candidate = self.baseline("pattern.trend_direction")
        input_ = task_input([[float(i) for i in range(32)]])
        first = candidate.infer(input_)["payload"]["value"]["raw_text"]
        input_["payload"]["value"]["gold"] = {"trend_direction": "decreasing"}
        input_["payload"]["value"]["context"] = {"gold": "decreasing", "label": "decreasing"}
        self.assertEqual(first, candidate.infer(input_)["payload"]["value"]["raw_text"])
        with self.assertRaisesRegex(GymTSError, "public positive horizon"):
            self.baseline("forecast.numeric").infer(task_input())

    def test_baseline_uses_source_display_names_not_modality_position(self):
        base = [math.sin(i * 2 * math.pi / 16) for i in range(96)]
        shape = task_input([list(reversed(base)), base, [value * 3 + 10 for value in base]],
                           ["Candidate B", "Query", "Candidate A"],
                           messages=[{"role": "user", "content": "Compare Query and Candidate A, Candidate B."}])
        answer = json.loads(self.baseline("similarity.shape_retrieval").infer(shape)["payload"]["value"]["raw_text"])
        self.assertEqual({"candidate_id": "candidate_a"}, answer)
        relation = task_input([base, [0.0] * 3 + base[:-3]], ["Series X", "Series Y"],
                              messages=[{"role": "user", "content": "Compare Series X and Series Y."}])
        answer = json.loads(self.baseline("relation.lagged_dependence").infer(relation)["payload"]["value"]["raw_text"])
        self.assertIn(answer["direction"], ("x_to_y", "y_to_x", "neither"))

    def test_real_snapshot_task_baseline_runner_contract_matches_flat_input(self):
        from gymts_chatts.pipeline import scene
        from gymts_chatts.task import TASK_OUTPUT_SCHEMAS
        with GymTS(Path(self.temp.name) / "runtime", integrations=("chatts",)) as gym:
            register_chatts_plugins(gym.registries, gym.schemas)
            model_input = task_input([[float(i) for i in range(32)]], context={"horizon": 4})["payload"]["value"]
            model_input["output_schema"] = copy.deepcopy(TASK_OUTPUT_SCHEMAS["forecast.numeric"])
            row = {"sample_token": "a" * 64, "task_id": "forecast.numeric", "task_version": "0.2.0",
                   "model_input": model_input}
            snapshot = {"schema_version": "gymts.chatts.snapshot/1", "dataset_revision": "fixture-fixed-revision", "samples": [row]}
            ref = gym.artifacts.save_json(snapshot, "gymts.chatts.snapshot/1")
            spec = json.loads((Path(__file__).resolve().parent / "fixtures/forecast_experiment.json").read_text())
            spec["scene"] = scene(ref, snapshot["dataset_revision"], row)
            spec["candidate"] = {"adapter": "chatts-signal-baseline", "version": "1.0.0", "artifact": None,
                                 "params": {"task_id": "forecast.numeric"}, "inherited_state": []}
            spec["execution"]["scope"] = {"start": 0, "end": 1}
            result = gym.run(spec)
            self.assertEqual("succeeded", result["status"], result["errors"])
            results = gym.artifacts.read_json(result["result_ref"])
            self.assertEqual(1, len(results))
            self.assertEqual("valid", results[0]["status"])
            self.assertEqual([32.0, 33.0, 34.0, 35.0], results[0]["payload"]["value"]["parsed"]["forecast"])
            events = gym.records.get_run(result["run_id"])["events"]
            input_events = [event for event in events if event["kind"] == "input"]
            saved = gym.artifacts.read_json(input_events[0]["payload"]["artifact_ref"]) if input_events[0]["payload"]["storage"] == "artifact" else input_events[0]["payload"]["value"]
            self.assertEqual(model_input, saved["payload"]["value"])


if __name__ == "__main__":
    unittest.main()
