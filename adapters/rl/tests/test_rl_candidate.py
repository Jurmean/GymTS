"""Native rollout call identities, failure evidence, and frozen policy boundary."""
import copy
from pathlib import Path
import tempfile
import unittest

from gymts import GymTS
from gymts.contracts import GymTSError, digest
from gymts.environment_ts.capture import RunTraceCollector, NATIVE_INPUTS, validate_model_call
from gymts_rl.candidate import LocalHFCandidate, INPUT, PROTOCOL
from gymts.plugin_support import component, payload


class FakeTokenizer:
    chat_template = "fixed-template"


class FakePolicy:
    family = "text"
    model_path = None
    identity = {"revision": "fixed-test-policy"}
    revision = "fixed-test-policy"
    tokenizer = FakeTokenizer()
    processor = None
    model_ref = component("test-policy")
    adapter_ref = component("test-native-adapter")

    def tokenizer_manifest(self):
        return {"class": "FakeTokenizer", "checkpoint_identity": self.identity}

    def generate(self, sample, seed, params):
        self.last_sample = copy.deepcopy(sample)
        return {"prompt_ids": [2, 3], "completion_ids": [4, 1],
            "raw_model_logprobs": [-.3, -.2], "sampling_logprobs": [-.4, -.1],
            "tensor_bundle": {}, "response": "42", "rendered_prompt": "question",
            "effective_params": {"temperature": 1.0, "top_k": 0, "top_p": 1.0, "seed": seed},
            "policy_revision": self.revision, "finish_reason": "eos"}


class ArrayFreeCandidate(LocalHFCandidate):
    def _native_inputs(self, generated, sample):
        return self._save({"format": "unit-test-no-tensors", "sample_id": sample["sample_id"]}, NATIVE_INPUTS)


class NativeCandidateContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.gym = GymTS(Path(self.temp.name))
        self.published, self.problems = [], []
        self.collector = RunTraceCollector("run-test", "native_rollout", self.gym.schemas,
            self.gym.artifacts, lambda kind, ref, links: self.published.append((kind, ref, links)),
            lambda *args: self.problems.append(args), lambda error: (_ for _ in ()).throw(error))
        self.sample = {"sample_id": "sample-1", "group_id": "sample-1", "dataset_id": "gsm8k",
            "split": "train", "task_id": "gsm8k.numeric", "messages": [{"role": "user", "content": "21 + 21?"}],
            "timeseries": [], "series_names": [], "output_schema": {}, "context": {}}
        self.input = {"run_id": "run-test", "input_id": "input-1", "task_protocol_ref": PROTOCOL,
                      "payload": payload(INPUT, self.sample)}
        self.collector.bind("run-test", self.input, "output-from-runner")
        self.policy = FakePolicy()
        self.candidate = ArrayFreeCandidate({"params": {}, "artifact": None, "inherited_state": None}, self.policy)
        self.context = {"resources": self.gym.artifacts, "traces": self.collector,
            "learning": {"prepare": "load_only", "online": "frozen"}}

    def tearDown(self):
        self.gym.records.close()
        self.temp.cleanup()

    def test_call_uses_bound_identity_exact_native_tokens_and_two_distributions(self):
        prepared = self.candidate.prepare(self.context, None)
        result = self.candidate.infer(self.input)
        evidence = result["payload"]["value"]["evidence"]
        call = self.gym.artifacts.read_json(evidence["model_call_ref"])
        validate_model_call(call, self.gym.schemas, self.gym.artifacts, profile="native_rollout")
        self.assertEqual("output-from-runner", call["output_id"])
        self.assertEqual("input-1", call["input_id"])
        self.assertEqual("run-test", call["run_id"])
        self.assertEqual([4, 1], self.gym.artifacts.read_json(call["response_token_ids_ref"]))
        raw = self.gym.artifacts.read_json(evidence["raw_model_logprobs_ref"])
        sampling = self.gym.artifacts.read_json(evidence["sampling_logprobs_ref"])
        self.assertEqual("model", raw["distribution"])
        self.assertEqual("sampling", sampling["distribution"])
        self.assertEqual(digest([4, 1]), sampling["response_sequence_hash"])
        self.assertEqual(2, len(raw["values"]))
        self.assertEqual("fixed-test-policy", prepared["model_revision"])
        self.assertEqual([], self.problems)
        self.assertEqual(self.sample, self.policy.last_sample)
        self.assertTrue(self.collector.flush())

    def test_policy_update_inside_run_is_rejected(self):
        self.candidate.prepare(self.context, None)
        self.policy.revision = "changed"
        with self.assertRaises(GymTSError) as error:
            self.candidate.infer(self.input)
        self.assertEqual("conflict", error.exception.code)
        self.assertEqual([], self.published)

    def test_private_reward_cannot_enter_generation(self):
        self.candidate.prepare(self.context, None)
        self.input["payload"]["value"]["reward_spec"] = {"ground_truth": "42"}
        with self.assertRaises(GymTSError) as error:
            self.candidate.infer(self.input)
        self.assertEqual("permission_denied", error.exception.code)

    def test_generation_error_keeps_formal_failed_attempt_and_request(self):
        self.candidate.prepare(self.context, None)
        def fail(*args):
            raise RuntimeError("intentional test failure")
        self.policy.generate = fail
        with self.assertRaises(RuntimeError):
            self.candidate.infer(self.input)
        calls = [self.gym.artifacts.read_json(ref) for kind, ref, links in self.published if kind == "model_call"]
        self.assertEqual(1, len(calls))
        self.assertEqual("failed", calls[0]["status"])
        self.assertEqual(self.sample, self.gym.artifacts.read_json(calls[0]["request_ref"])["sample"])
        self.assertEqual("partial", calls[0]["capture"]["completeness"])

    def test_prepare_requires_capture_and_rejects_fit(self):
        with self.assertRaises(GymTSError):
            self.candidate.prepare({**self.context, "traces": None}, None)
        candidate = ArrayFreeCandidate({"params": {}}, self.policy)
        with self.assertRaises(GymTSError):
            candidate.prepare({**self.context, "learning": {"prepare": "fit", "online": "frozen"}}, None)

    def test_unknown_or_boolean_seed_is_rejected(self):
        for params in ({"seed": True}, {"generation": {"top_k": -1}}, {"hidden": 1}):
            with self.subTest(params=params), self.assertRaises(GymTSError):
                LocalHFCandidate({"params": params}, self.policy)


if __name__ == "__main__":
    unittest.main()
