"""Likelihood alignment checks with real autograd and a tiny deterministic model."""
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

from gymts.contracts import GymTSError, canonical_json
from gymts_rl.policy import LocalPolicy, checkpoint_identity, completion_logprobs, load_native_inputs, validate_safetensors


class CheckpointIdentityTests(unittest.TestCase):
    def test_added_token_init_values_are_saved_as_json_token_strings(self):
        class AddedToken:
            def __str__(self):
                return "<eos>"
        class Tokenizer:
            name_or_path = "fixed-model"
            special_tokens_map = {"eos_token": "<eos>"}
            init_kwargs = {"eos_token": AddedToken(), "clean_up_tokenization_spaces": False}
            def __len__(self):
                return 16
        policy = LocalPolicy(None, Tokenizer(), revision="fixed")
        manifest = policy.tokenizer_manifest()
        self.assertEqual("<eos>", manifest["init_kwargs"]["eos_token"])
        self.assertTrue(canonical_json(manifest))

    def test_identity_hashes_bytes_and_rejects_missing_declared_shard(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            (path / "config.json").write_text('{}')
            (path / "pytorch_model.bin").write_bytes(b"checkpoint-first")
            before = checkpoint_identity(path)
            (path / "pytorch_model.bin").write_bytes(b"checkpoint-other")
            self.assertNotEqual(before["revision"], checkpoint_identity(path)["revision"])
            (path / "model.safetensors.index.json").write_text('{"weight_map":{"x":"missing.safetensors"}}')
            with self.assertRaises(GymTSError):
                checkpoint_identity(path)

    def test_truncated_safetensors_is_rejected_before_model_load(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "model.safetensors"
            header = json.dumps({"weight": {"dtype": "F32", "shape": [2], "data_offsets": [0, 8]}}).encode()
            content = struct.pack("<Q", len(header)) + header + struct.pack("<ff", 1., 2.)
            path.write_bytes(content)
            self.assertEqual(1, validate_safetensors(path)["tensor_count"])
            path.write_bytes(content[:-3])
            with self.assertRaises(GymTSError) as error:
                validate_safetensors(path)
            self.assertEqual(3, error.exception.to_dict()["links"]["missing_bytes"])


@unittest.skipUnless(importlib.util.find_spec("torch"), "Optional local-model torch dependency is not installed")
class NativeLikelihoodTests(unittest.TestCase):
    def _model(self, expanded=False):
        import torch
        from types import SimpleNamespace

        class TinyModel(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.weight = torch.nn.Parameter(torch.arange(35, dtype=torch.float32).reshape(5, 7) / 20)

            def forward(self, input_ids, attention_mask, **kwargs):
                # Distinct position rows detect an off-by-one token alignment.
                rows = torch.arange(input_ids.shape[1], device=input_ids.device)
                if expanded:
                    positions = rows + 2
                    logits = self.weight[(torch.arange(input_ids.shape[1] + 2) % 5)].unsqueeze(0)
                else:
                    positions = None
                    logits = self.weight[(rows % 5)].unsqueeze(0)
                return SimpleNamespace(logits=logits, new_token_positions=positions.unsqueeze(0) if expanded else None)

        return TinyModel()

    def test_text_likelihood_aligns_predictor_positions_and_preserves_gradients(self):
        import torch
        model = self._model()
        actual = completion_logprobs(model, [1, 2, 3], [4, 6])
        expected = torch.log_softmax(model.weight[[2, 3]], dim=-1)[[0, 1], [4, 6]].unsqueeze(0)
        torch.testing.assert_close(actual, expected)
        (-actual.mean()).backward()
        self.assertGreater(float(model.weight.grad.abs().sum()), 0)

    def test_multimodal_likelihood_uses_expanded_new_token_positions(self):
        import torch
        model = self._model(expanded=True)
        actual = completion_logprobs(model, [1, 2, 3], [4, 6], {"timeseries": torch.zeros(1, 4, 1)})
        expected = torch.log_softmax(model.weight[[4, 0]], dim=-1)[[0, 1], [4, 6]].unsqueeze(0)
        torch.testing.assert_close(actual, expected)
        actual.sum().backward()
        self.assertGreater(float(model.weight.grad.abs().sum()), 0)

    def test_eos_id_remains_an_action_instead_of_being_used_as_padding_mask(self):
        model = self._model()
        actual = completion_logprobs(model, [1, 2], [6, 1, 1])
        self.assertEqual((1, 3), tuple(actual.shape))

    def test_native_cas_roundtrip_preserves_tensor_dtype_shape_and_bfloat16_bits(self):
        import torch
        from types import SimpleNamespace
        from gymts import GymTS
        from gymts_rl.candidate import LocalHFCandidate

        with tempfile.TemporaryDirectory() as root:
            gym = GymTS(root)
            candidate = LocalHFCandidate({"params": {}}, SimpleNamespace(processor=None, family="chatts"))
            candidate.resources, candidate.revision = gym.artifacts, "test-revision"
            tensors = {"input_ids": torch.tensor([[2, 3, 4]]), "attention_mask": torch.ones(1, 3, dtype=torch.long),
                       "timeseries": torch.tensor([[[.125], [-2.5], [3.75]]], dtype=torch.bfloat16)}
            ref = candidate._native_inputs({"tensor_bundle": tensors}, {"sample_id": "test", "series_names": ["series"]})
            restored = load_native_inputs(gym.artifacts, ref)
            for name, value in tensors.items():
                torch.testing.assert_close(value, restored[name], rtol=0, atol=0)
                self.assertEqual(value.dtype, restored[name].dtype)
            gym.records.close()


@unittest.skipUnless(importlib.util.find_spec("torch") and importlib.util.find_spec("transformers"),
                     "Optional local-model transformers dependency is not installed")
class NativeGenerationTests(unittest.TestCase):
    def _policy(self):
        import torch
        from transformers import Qwen2Config, Qwen2ForCausalLM
        from gymts_rl.policy import LocalPolicy

        class Tokenizer:
            pad_token_id = 1
            eos_token_id = 1

            def apply_chat_template(self, messages, **kwargs):
                self.last_messages = messages
                return "\n".join(message["content"] for message in messages)

            def __call__(self, *args, **kwargs):
                return {"input_ids": torch.tensor([[2, 3, 4]]), "attention_mask": torch.ones(1, 3, dtype=torch.long)}

            def decode(self, tokens, **kwargs):
                return ",".join(str(token) for token in tokens if token != self.eos_token_id)

        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(17)
            model = Qwen2ForCausalLM(Qwen2Config(vocab_size=19, hidden_size=16, intermediate_size=32,
                num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=1,
                bos_token_id=0, eos_token_id=1, pad_token_id=1, attention_dropout=0))
        model.eval()
        # HF 4.52 may replace values equal to global defaults with checkpoint
        # defaults unless the adapter explicitly fixes the generation kwargs.
        model.generation_config.temperature = .6
        model.generation_config.top_p = .95
        return LocalPolicy(model, Tokenizer(), family="text", revision="fixed-tiny-qwen")

    def test_real_hf_native_tokens_and_forward_logprobs_agree_and_rng_is_restored(self):
        import torch
        policy = self._policy()
        sample = {"messages": [{"role": "user", "content": "test"}], "timeseries": []}
        before = torch.random.get_rng_state().clone()
        generated = policy.generate(sample, 19, {"max_new_tokens": 6})
        torch.testing.assert_close(before, torch.random.get_rng_state())
        actual = completion_logprobs(policy.model, generated["prompt_ids"], generated["completion_ids"], generated["tensor_bundle"])
        torch.testing.assert_close(actual[0], torch.tensor(generated["raw_model_logprobs"]), rtol=1e-5, atol=1e-5)
        torch.testing.assert_close(torch.tensor(generated["raw_model_logprobs"]), torch.tensor(generated["sampling_logprobs"]))
        self.assertEqual(0.0, generated["effective_params"]["model_sampling_logprobs_max_abs_difference"])

    def test_actual_top_k_sampling_and_greedy_point_mass_are_distinct_from_raw_model(self):
        policy = self._policy()
        sample = {"messages": [{"role": "user", "content": "test"}], "timeseries": []}
        sampled = policy.generate(sample, 3, {"max_new_tokens": 3, "top_k": 1, "temperature": .7})
        self.assertEqual([0.0] * len(sampled["completion_ids"]), sampled["sampling_logprobs"])
        self.assertTrue(all(value < 0 for value in sampled["raw_model_logprobs"]))
        self.assertGreater(sampled["effective_params"]["model_sampling_logprobs_max_abs_difference"], 0)
        greedy = policy.generate(sample, 5, {"max_new_tokens": 3, "do_sample": False})
        self.assertEqual([0.0] * len(greedy["completion_ids"]), greedy["sampling_logprobs"])

    def test_text_policy_renders_every_full_precision_time_series_in_order(self):
        policy = self._policy()
        sample = {"messages": [{"role": "user", "content": "A <ts><ts/> B <ts><ts/>"}],
                  "timeseries": [[0.12345678901234568, -7.25], [3.5, 0.0]]}
        prompt, tensors = policy._inputs(sample, False)
        self.assertEqual("A [0.12345678901234568,-7.25] B [3.5,0.0]", prompt)
        self.assertEqual("A <ts><ts/> B <ts><ts/>", sample["messages"][0]["content"])
        self.assertEqual(["attention_mask", "input_ids"], sorted(tensors))


if __name__ == "__main__":
    unittest.main()
