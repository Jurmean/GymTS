"""Native masks and TRL's actual loss/backward boundary, without a big model."""
import importlib.util
from pathlib import Path
import tempfile
import unittest


AVAILABLE = all(importlib.util.find_spec(name) for name in ("torch", "trl", "peft"))


@unittest.skipUnless(AVAILABLE, "requires the optional pinned RL runtime")
class RLTrainingTests(unittest.TestCase):
    def test_unwarped_behavior_policy_accepts_captured_matching_distribution(self):
        import copy
        from gymts_rl.trl_adapter import validate_behavior_policy
        rows = [{"logprob_distribution": "sampling", "effective_params": {
            "do_sample": True, "temperature": 1.0, "top_p": 1.0, "top_k": 0,
            "model_sampling_logprobs_max_abs_difference": 0.0,
            "resolved_generation_config": {"min_length": 0, "min_new_tokens": 0,
                "no_repeat_ngram_size": 0, "encoder_no_repeat_ngram_size": 0,
                "encoder_repetition_penalty": 1.0, "repetition_penalty": 1.0,
                "typical_p": 1.0, "epsilon_cutoff": 0.0, "eta_cutoff": 0.0,
                "token_healing": False, "bad_words_ids": None, "min_p": None}}}]
        before = copy.deepcopy(rows)
        self.assertIsNone(validate_behavior_policy(rows))
        self.assertEqual(rows, before, "Validation must not repair or rewrite captured evidence")

    def test_hidden_processors_and_measured_probability_changes_are_rejected(self):
        import copy
        from gymts.contracts import GymTSError
        from gymts_rl.trl_adapter import validate_behavior_policy
        base = {"logprob_distribution": "sampling", "effective_params": {
            "do_sample": True, "temperature": 1.0, "top_p": 1.0, "top_k": 0,
            "model_sampling_logprobs_max_abs_difference": 0.0,
            "resolved_generation_config": {}}}
        for processor, value in (("suppress_tokens", [5]), ("bad_words_ids", [[5, 6]]),
                                 ("forced_eos_token_id", 2), ("typical_p", .9),
                                 ("min_length", 1), ("repetition_penalty", 1.1)):
            with self.subTest(processor=processor):
                row = copy.deepcopy(base)
                row["effective_params"]["resolved_generation_config"][processor] = value
                with self.assertRaises(GymTSError) as error:
                    validate_behavior_policy([row])
                self.assertEqual(error.exception.code, "unsupported_capability")
        row = copy.deepcopy(base)
        # Every declared sampling parameter can look valid while an actual
        # model/HF generation hook changes the distribution seen by the action.
        row["effective_params"]["model_sampling_logprobs_max_abs_difference"] = 2e-6
        with self.assertRaisesRegex(GymTSError, "distributions differ"):
            validate_behavior_policy([row])

    def test_eos_equal_to_pad_is_still_an_action(self):
        from gymts_rl.trl_adapter import collate_native_rows
        rows = [{"prompt_ids": [5, 6], "completion_ids": [3, 2], "old_per_token_logps": [-.2, -.1]},
                {"prompt_ids": [6], "completion_ids": [2], "old_per_token_logps": [-.3]}]
        batch = collate_native_rows(rows, 2, "cpu")
        self.assertEqual(batch["completion_ids"].tolist(), [[3, 2], [2, 2]])
        self.assertEqual(batch["completion_mask"].tolist(), [[1, 1], [1, 0]])
        self.assertEqual(batch["prompt_mask"].tolist(), [[1, 1], [0, 1]])

    def test_upstream_grpo_backward_survives_shuffled_native_rows(self):
        import io
        from collections import defaultdict
        from types import SimpleNamespace
        import numpy as np
        import torch
        from gymts import GymTS
        from gymts.environment_ts.capture import NATIVE_INPUTS
        from gymts_rl.policy import completion_logprobs
        from gymts_rl.trl_adapter import GymTSGRPOTrainer, collate_native_rows

        class NativeModel(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.embedding = torch.nn.Embedding(8, 8)
                self.head = torch.nn.Linear(8, 8)

            def forward(self, input_ids, attention_mask, timeseries, **kwargs):
                return SimpleNamespace(logits=self.head(self.embedding(input_ids) + timeseries.reshape(1, 1, 1)))

        torch.manual_seed(8)
        model = NativeModel()
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym:
            rows = []
            for response, value in (([3, 2], .1), ([4, 5, 2], .8)):
                stream = io.BytesIO()
                np.save(stream, np.array([value], dtype="float32"), allow_pickle=False)
                tensor_ref = gym.artifacts.save_artifact(stream.getvalue(), {"media_type": "application/x-npy"})
                native_ref = gym.artifacts.save_json({"format": "npy", "tensors": {"timeseries": {
                    "artifact_ref": tensor_ref, "dtype": "float32", "shape": [1]}}}, NATIVE_INPUTS)
                row = {"prompt_ids": [6, 7], "completion_ids": response, "native_inputs_ref": native_ref}
                row["old_per_token_logps"] = completion_logprobs(model, row["prompt_ids"], response,
                    {"timeseries": torch.tensor([value])}).detach()[0].tolist()
                rows.append(row)
            trainer = object.__new__(GymTSGRPOTrainer)
            trainer.model, trainer.artifacts, trainer._rollout_rows = model, gym.artifacts, rows
            trainer.beta, trainer.epsilon_low, trainer.epsilon_high, trainer.loss_type = 0, .2, .2, "grpo"
            trainer.args = SimpleNamespace(delta=None)
            trainer.accelerator = SimpleNamespace(gather=lambda x: x)
            trainer._metrics = {"train": defaultdict(list), "eval": defaultdict(list)}
            batch = collate_native_rows(rows, 2, "cpu")
            batch["advantages"] = torch.tensor([1., -1.])
            trainer._compute_loss(model, batch).backward()
            original = torch.cat([p.grad.flatten().clone() for p in model.parameters()])
            self.assertGreater(original.norm().item(), 0)
            model.zero_grad()
            reverse = {key: value.flip(0) for key, value in batch.items()}
            trainer._compute_loss(model, reverse).backward()
            reordered = torch.cat([p.grad.flatten() for p in model.parameters()])
            torch.testing.assert_close(reordered, original)
            # Reuse the upstream TRL loss with a real CPU optimizer update.
            before = torch.cat([p.detach().flatten().clone() for p in model.parameters()])
            optimizer = torch.optim.SGD(model.parameters(), lr=.01)
            optimizer.step()
            after = torch.cat([p.detach().flatten() for p in model.parameters()])
            self.assertFalse(torch.equal(before, after))
            broken = dict(batch, prompt_ids=batch["prompt_ids"].clone())
            broken["prompt_ids"][0, 0] = 1
            with self.assertRaisesRegex(Exception, "Trainer tokens differ"):
                trainer._compute_loss(model, broken)
            # CAS integrity alone cannot establish that a tensor belongs to
            # this prompt: reject a valid NPY file carrying different IDs.
            stream = io.BytesIO()
            np.save(stream, np.array([[6, 0]], dtype="int64"), allow_pickle=False)
            wrong_ids = gym.artifacts.save_artifact(stream.getvalue(), {"media_type": "application/x-npy"})
            native = gym.artifacts.read_json(rows[0]["native_inputs_ref"])
            native["tensors"]["input_ids"] = {"artifact_ref": wrong_ids, "dtype": "int64", "shape": [1, 2]}
            bad_ref = gym.artifacts.save_json(native, NATIVE_INPUTS)
            trainer._rollout_rows = [dict(rows[0], native_inputs_ref=bad_ref), rows[1]]
            with self.assertRaisesRegex(Exception, "native input tensor differs"):
                trainer._compute_loss(model, batch)

    def test_injected_source_is_read_from_published_native_shards(self):
        from collections import defaultdict
        from types import SimpleNamespace
        from unittest.mock import patch
        import torch
        from gymts_rl.trl_adapter import GymTSGRPOTrainer
        trainer = object.__new__(GymTSGRPOTrainer)
        trainer.model = torch.nn.Linear(1, 1)
        trainer._fix_policy_revision = lambda: None
        trainer.policy = SimpleNamespace(revision="fixed")
        trainer.artifacts = object()
        trainer.num_generations, trainer.max_completion_length = 2, 8
        trainer.args = SimpleNamespace(seed=7)
        trainer.rollout_batches, trainer.progress_callback = [], None
        trainer.accelerator = SimpleNamespace(device="cpu")
        trainer.processing_class = SimpleNamespace(pad_token_id=2)
        trainer._metrics = {"train": defaultdict(list)}
        trainer.scale_rewards = True
        rows = [{"source_sample_id": "independent-source", "policy_revision": "fixed",
                 "prompt_ids": [4], "completion_ids": [1, 2], "old_per_token_logps": [-.3, -.2],
                 "reward": float(index), "logprob_distribution": "sampling", "effective_params": {
                     "do_sample": True, "temperature": 1, "top_p": 1, "top_k": 0}}
                for index in range(2)]
        calls = []
        def collect(inputs, policy, **kwargs):
            calls.append((inputs, policy, kwargs))
            return {"manifest_ref": {"fixture": "published"}, "batch_ref": {"fixture": "batch"}}
        trainer.rollout_provider = collect
        inputs = [{"sample_id": "independent-source"}] * 2
        with patch("gymts_rl.trl_adapter.read_native_dataset_rows", return_value=rows) as reader:
            batch = trainer._generate_and_score_completions(inputs)
        reader.assert_called_once_with({"fixture": "published"}, trainer.artifacts)
        self.assertEqual(calls[0][0], inputs)
        self.assertEqual(batch["completion_ids"].tolist(), [[1, 2], [1, 2]])
        self.assertLess(batch["advantages"][0].item(), 0)
        self.assertGreater(batch["advantages"][1].item(), 0)
        self.assertFalse(hasattr(trainer, "gym"))


class PromptBoundaryTests(unittest.TestCase):
    def test_private_rewards_and_eval_are_absent_from_trainer_dataset(self):
        import json
        from gymts_rl.train import training_prompts
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "train.jsonl"
            rows = [{"sample_id": str(i), "group_id": str(i), "task_id": "test", "dataset_id": source,
                     "split": "train", "messages": [{"role": "user", "content": "question"}],
                     "reward_spec": {"ground_truth": "PRIVATE"}} for i, source in enumerate(("gsm", "gsm", "chatts", "chatts"))]
            path.write_text("\n".join(json.dumps(row) for row in rows))
            selected = training_prompts({"train_path": str(path)}, groups_per_step=2)
            self.assertEqual([row["sample_id"] for row in selected], ["2", "0", "3", "1"])
            self.assertNotIn("PRIVATE", json.dumps(selected))
            rows[0]["split"] = "eval"
            path.write_text("\n".join(json.dumps(row) for row in rows))
            with self.assertRaisesRegex(Exception, "Held-out"):
                training_prompts({"train_path": str(path)}, groups_per_step=2)


if __name__ == "__main__":
    unittest.main()
