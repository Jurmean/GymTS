"""Text LLM transport preserves numerical input and distinguishes its evidence."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from gymts import GymTS
from gymts.contracts import GymTSError
from gymts_chatts import register_chatts_plugins
from gymts_chatts.candidate import INPUT, PROTOCOL
from gymts_chatts.text_candidate import TextLLMHTTPCandidate
from gymts.plugin_support import payload
from gymts.storage import ArtifactStore


class Response:
    status = 200

    def __init__(self, body):
        self.data = json.dumps(body).encode()

    def read(self, size):
        return self.data[:size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


class Opener:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return Response(response)


def response(content='{"trend_direction":"increasing"}', **extra):
    body = {"model": "fixture-text-model", "system_fingerprint": "fixture-fp",
            "choices": [{"message": {"content": content, "reasoning_content": "fixture provider auxiliary field"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 8, "prompt_cache_hit_tokens": 3}}
    body.update(extra)
    return body


def input_(arrays=None, names=None, text="Analyze the named time series and return JSON.", messages=None):
    arrays = arrays if arrays is not None else [[0.0, 1.0, 2.0]]
    return {"input_id": "text-input-1", "task_protocol_ref": PROTOCOL,
            "payload": payload(INPUT, {"messages": messages or [{"role": "user", "content": text}],
                "timeseries": arrays, "series_names": names or ["Series 1"],
                "output_schema": {"type": "object"}, "context": {}})}


class TextCandidateContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.artifacts = ArtifactStore(Path(self.temp.name) / "artifacts")
        self.context = {"resources": self.artifacts, "learning": {"prepare": "load_only", "online": "frozen"}}

    def tearDown(self):
        self.temp.cleanup()

    def candidate(self, **params):
        candidate = TextLLMHTTPCandidate({"params": dict({"base_url": "http://127.0.0.1:19234/v1",
            "model": "fixture-text-model", "model_revision": "fixture-configured-alias"}, **params)})
        candidate.prepare(self.context, None)
        return candidate

    def test_named_numeric_text_is_lossless_ordered_and_has_no_native_wire_fields(self):
        candidate = self.candidate(json_object=True, thinking_mode="disabled")
        candidate.opener = Opener(response())
        arrays = [[1.2345678901234567, 10**18 + 1, -0.00000000001], [50.125, -4, 0.0]]
        source = input_(arrays, ["Query", "Candidate A"])
        before = copy.deepcopy(source)
        output = candidate.infer(source)
        wire = json.loads(candidate.opener.calls[0][0].data)
        self.assertNotIn("timeseries", wire)
        self.assertNotIn("modalities", wire)
        self.assertNotIn("chat_template_kwargs", wire)
        text = wire["messages"][-1]["content"]
        self.assertIsInstance(text, str)
        encoded = json.loads(text.split("\n")[-1])
        self.assertEqual("named_numeric_json/v1", encoded["representation"])
        self.assertEqual([{"name": "Query", "values": arrays[0]}, {"name": "Candidate A", "values": arrays[1]}], encoded["series"])
        self.assertNotIn("<ts>", text)
        self.assertNotIn("chatts-timeseries:", text)
        self.assertEqual(before, source)
        self.assertEqual({"type": "disabled"}, wire["thinking"])
        self.assertEqual({"type": "json_object"}, wire["response_format"])
        evidence = output["payload"]["value"]["evidence"]
        self.assertEqual("text_llm_http", evidence["kind"])
        self.assertEqual("none", evidence["normalization"])
        self.assertEqual("named_numeric_json/v1", evidence["input_representation"])
        self.assertEqual("configured_alias", evidence["revision_provenance"])
        self.assertFalse(evidence["weights_pinned"])

    def test_existing_placeholders_replaced_once_with_named_series_json_in_order(self):
        candidate = self.candidate()
        candidate.opener = Opener(response())
        candidate.infer(input_([[1.5, 2.5], [8, 9]], ["Series X", "Series Y"], text="X=<ts><ts/>; Y=<ts><ts/>. Compare."))
        wire = json.loads(candidate.opener.calls[0][0].data)
        text = wire["messages"][-1]["content"]
        decoder = json.JSONDecoder()
        first, count = decoder.raw_decode(text[2:])
        rest = text[2 + count:]
        second, _ = decoder.raw_decode(rest[len("; Y="):])
        self.assertEqual([{"name": "Series X", "values": [1.5, 2.5]}], first["series"])
        self.assertEqual([{"name": "Series Y", "values": [8, 9]}], second["series"])
        self.assertEqual(2, text.count('"representation":"named_numeric_json/v1"'))
        self.assertNotIn("<ts>", text)

    def test_last_user_modified_while_system_and_assistant_messages_preserved(self):
        candidate = self.candidate()
        candidate.opener = Opener(response())
        messages = [{"role": "system", "content": "Use only supplied evidence."},
                    {"role": "user", "content": "Earlier question."},
                    {"role": "assistant", "content": "Earlier answer."},
                    {"role": "user", "content": "Current question."}]
        candidate.infer(input_(messages=messages))
        wire = json.loads(candidate.opener.calls[0][0].data)
        self.assertEqual(messages[:-1], wire["messages"][:-1])
        self.assertTrue(wire["messages"][-1]["content"].startswith("Current question."))

    def test_response_content_remains_raw_and_auxiliary_provider_fields_are_captured(self):
        candidate = self.candidate()
        raw = "```json\n{\"trend_direction\": \"increasing\"}\n```"
        candidate.opener = Opener(response(raw))
        output = candidate.infer(input_())
        self.assertEqual(raw, output["payload"]["value"]["raw_text"])
        evidence = output["payload"]["value"]["evidence"]
        captured = self.artifacts.read_json(evidence["response_ref"])["body"]
        self.assertEqual("fixture provider auxiliary field", captured["choices"][0]["message"]["reasoning_content"])
        self.assertEqual(3, evidence["usage"]["prompt_cache_hit_tokens"])
        self.assertEqual("fixture-text-model", evidence["response_model"])
        self.assertEqual("fixture-fp", evidence["system_fingerprint"])
        self.assertEqual("configured_service_alias", evidence["model_revision_semantics"])

    def test_fixture_auth_redaction_no_retry_and_fingerprint_checks_reused(self):
        fixture_secret = "TEXT_FIXTURE_KEY_DO_NOT_PERSIST"
        with patch.dict(os.environ, {"GYMTS_TEXT_FIXTURE_KEY": fixture_secret}):
            candidate = self.candidate(api_key_env="GYMTS_TEXT_FIXTURE_KEY")
        candidate.opener = Opener(response(fixture_secret))
        output = candidate.infer(input_())
        self.assertEqual("Bearer " + fixture_secret, candidate.opener.calls[0][0].get_header("Authorization"))
        self.assertEqual("[REDACTED]", output["payload"]["value"]["raw_text"])
        for ref in candidate.finish():
            self.assertNotIn(fixture_secret, self.artifacts.resolve(ref).read_text())
        candidate = self.candidate()
        candidate.opener = Opener(urllib.error.URLError("PRIVATE_PROVIDER_ERROR"))
        with self.assertRaises(GymTSError) as caught:
            candidate.infer(input_())
        self.assertNotIn("PRIVATE_PROVIDER_ERROR", str(caught.exception))
        self.assertEqual(1, len(candidate.opener.calls))
        candidate = self.candidate(expected_system_fingerprint="pinned-fixture")
        candidate.opener = Opener(response())
        with self.assertRaises(GymTSError):
            candidate.infer(input_())

    def test_explicit_text_dialect_controls_and_public_input_checks(self):
        for invalid in ({"dialect": "chatts-timeseries/v1"}, {"thinking_mode": "automatic"},
                        {"thinking_mode": False}, {"enable_thinking": False}, {"json_object": "true"}):
            with self.subTest(invalid=invalid), self.assertRaises(GymTSError):
                self.candidate(**invalid)
        for messages in ([{"role": "assistant", "content": "No user message"}],
                         [{"role": "system", "content": "<ts><ts/>"}, {"role": "user", "content": "Analyze"}]):
            candidate = self.candidate()
            candidate.opener = Opener(response())
            with self.assertRaises(GymTSError):
                candidate.infer(input_(messages=messages))
            self.assertEqual([], candidate.opener.calls)

    def test_registered_text_candidate_runs_real_task_and_preserves_strict_parser(self):
        from gymts_chatts.pipeline import scene
        from gymts_chatts.task import TASK_OUTPUT_SCHEMAS
        with GymTS(Path(self.temp.name) / "runtime", integrations=("chatts",)) as gym:
            register_chatts_plugins(gym.registries, gym.schemas)
            model_input = input_(arrays=[[float(i) for i in range(32)]])["payload"]["value"]
            model_input["output_schema"] = copy.deepcopy(TASK_OUTPUT_SCHEMAS["pattern.trend_direction"])
            row = {"sample_token": "b" * 64, "task_id": "pattern.trend_direction", "task_version": "0.2.0", "model_input": model_input}
            snapshot = {"schema_version": "gymts.chatts.snapshot/1", "dataset_revision": "text-fixture-revision", "samples": [row]}
            ref = gym.artifacts.save_json(snapshot, "gymts.chatts.snapshot/1")
            spec = json.loads((Path(__file__).resolve().parent / "fixtures/forecast_experiment.json").read_text())
            spec["scene"] = scene(ref, snapshot["dataset_revision"], row)
            spec["candidate"] = {"adapter": "chatts-text-http", "version": "1.0.0", "artifact": None,
                "params": {"base_url": "http://127.0.0.1:19234/v1", "model": "fixture-text-model",
                           "model_revision": "configured-fixture-alias", "thinking_mode": "disabled", "json_object": True},
                "inherited_state": []}
            spec["execution"]["scope"] = {"start": 0, "end": 1}
            with patch("urllib.request.build_opener", return_value=Opener(response())):
                result = gym.run(spec)
            self.assertEqual("succeeded", result["status"], result["errors"])
            records = gym.artifacts.read_json(result["result_ref"])
            self.assertEqual("valid", records[0]["status"])
            with patch("urllib.request.build_opener", return_value=Opener(response('```json\n{"trend_direction":"increasing"}\n```'))):
                result = gym.run(spec)
            records = gym.artifacts.read_json(result["result_ref"])
            self.assertEqual("invalid", records[0]["status"])
            self.assertIsNone(records[0]["payload"]["value"]["parsed"])


if __name__ == "__main__":
    unittest.main()
