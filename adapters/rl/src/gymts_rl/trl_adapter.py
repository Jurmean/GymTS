"""TRL 0.18.2 GRPO with GymTS as the native, durable rollout boundary.

Only sampling, evidence ingestion and native multimodal likelihood alignment
are adapted. TRL owns the clipped GRPO loss, backward pass, optimizer and
checkpoint lifecycle. Import this module only inside an RL runtime.
"""
import hashlib
from importlib.metadata import version
from pathlib import Path

import torch
from trl import GRPOTrainer

from gymts.contracts import GymTSError, digest
from .policy import completion_logprobs, load_native_inputs
from .exporter import read_native_dataset_rows


def _published_native_rewards(completions, **kwargs):
    """Fail closed if upstream bypasses the fixed-manifest ingestion override."""
    raise GymTSError("invalid_state", "Native GRPO consumes rewards only from published dataset shards")


def trainable_state_digest(model):
    """Hash actual trainable bytes, including dtype and shape, without RNG use."""
    checksum = hashlib.sha256()
    count = 0
    for name, parameter in sorted(model.named_parameters()):
        if parameter.requires_grad:
            tensor = parameter.detach().cpu().contiguous()
            checksum.update(name.encode())
            checksum.update(str(tensor.dtype).encode())
            checksum.update(str(tuple(tensor.shape)).encode())
            checksum.update(tensor.view(torch.uint8).numpy().tobytes())
            count += tensor.numel()
    if not count:
        raise GymTSError("invalid_config", "GRPO requires trainable policy parameters")
    return "sha256:" + checksum.hexdigest(), count


def collate_native_rows(rows, pad_id, device):
    """Pad exact native sequences; EOS always keeps its real action mask."""
    if not rows:
        raise GymTSError("invalid_dataset", "The fixed rollout dataset has no accepted rows")
    prompt_length = max(len(row["prompt_ids"]) for row in rows)
    completion_length = max(len(row["completion_ids"]) for row in rows)
    prompts, completions, prompt_masks, completion_masks, old_logps = [], [], [], [], []
    for row in rows:
        p, c = row["prompt_ids"], row["completion_ids"]
        logps = row["old_per_token_logps"]
        loss_mask = row.get("completion_mask", [1] * len(c))
        if not p or not c or len(c) != len(logps) or len(c) != len(loss_mask):
            raise GymTSError("schema_mismatch", "Native action/logprob/mask lengths do not match")
        if not all(value in (0, 1) for value in loss_mask):
            raise GymTSError("schema_mismatch", "Native completion masks must be binary")
        prompts.append([pad_id] * (prompt_length - len(p)) + p)
        prompt_masks.append([0] * (prompt_length - len(p)) + [1] * len(p))
        completions.append(c + [pad_id] * (completion_length - len(c)))
        completion_masks.append(loss_mask + [0] * (completion_length - len(c)))
        old_logps.append(logps + [0.0] * (completion_length - len(c)))
    return {
        "prompt_ids": torch.tensor(prompts, dtype=torch.long, device=device),
        "prompt_mask": torch.tensor(prompt_masks, dtype=torch.long, device=device),
        "completion_ids": torch.tensor(completions, dtype=torch.long, device=device),
        "completion_mask": torch.tensor(completion_masks, dtype=torch.long, device=device),
        "old_per_token_logps": torch.tensor(old_logps, dtype=torch.float32, device=device),
        "row_indices": torch.arange(len(rows), device=device),
    }


def validate_behavior_policy(rows):
    """The optimized target is raw model p; reject any other sampling law."""
    for row in rows:
        params = row["effective_params"]
        if (not params.get("do_sample") or params.get("temperature") != 1
                or params.get("top_p") != 1 or params.get("top_k") != 0
                or row["logprob_distribution"] != "sampling"):
            raise GymTSError("unsupported_capability", "GRPO requires captured unwarped sampling probabilities")
        config = params.get("resolved_generation_config", {})
        forbidden = ("bad_words_ids", "force_words_ids", "suppress_tokens", "begin_suppress_tokens",
                     "forced_bos_token_id", "forced_eos_token_id", "sequence_bias", "watermarking_config",
                     "exponential_decay_length_penalty", "constraints", "penalty_alpha", "min_p",
                     "dola_layers", "guidance_scale")
        if any(config.get(key) is not None for key in forbidden):
            raise GymTSError("unsupported_capability", "Checkpoint generation config contains an unsupported probability processor")
        if (any(config.get(key, 0) not in (0, None) for key in
                ("min_length", "min_new_tokens", "no_repeat_ngram_size", "encoder_no_repeat_ngram_size"))
                or config.get("encoder_repetition_penalty", 1) != 1
                or config.get("repetition_penalty", 1) != 1 or config.get("token_healing", False)
                or config.get("typical_p", 1) != 1 or config.get("epsilon_cutoff", 0) != 0
                or config.get("eta_cutoff", 0) != 0):
            raise GymTSError("unsupported_capability", "Checkpoint generation config changes the training distribution")
        if params.get("model_sampling_logprobs_max_abs_difference", 0) > 1e-6:
            raise GymTSError("unsupported_capability", "Captured model and behavior sampling distributions differ")


class GymTSGRPOTrainer(GRPOTrainer):
    """Single-process LoRA GRPO consuming sealed native GymTS datasets.

    The narrow supported configuration is intentional: changing the sampling
    temperature or enabling top-k/p requires a different target likelihood.
    Such configurations are rejected instead of silently applying a wrong ratio.
    """

    def __init__(self, *, policy, args, train_dataset, artifacts=None, rollout_provider=None,
                 gym=None, prepared_dataset=None, peft_config=None, progress_callback=None, **kwargs):
        if version("trl") != "0.18.2":
            raise GymTSError("unsupported_capability", "GymTS native GRPO adapter requires trl==0.18.2")
        if next(policy.model.parameters()).is_cuda and torch.cuda.device_count() != 1:
            raise GymTSError("unsupported_capability", "Expose one GPU with CUDA_VISIBLE_DEVICES before importing torch; native multimodal GRPO does not use DataParallel")
        if (args.beta != 0 or args.temperature != 1 or args.top_p != 1
                or args.top_k not in (None, 0) or args.min_p is not None
                or args.repetition_penalty != 1 or args.use_vllm
                or args.use_liger_loss or args.num_iterations != 1
                or args.steps_per_generation != 1 or args.loss_type != "grpo"):
            raise GymTSError("unsupported_capability", "Native GRPO requires beta=0, unwarped sampling, one iteration and one generation step")
        if args.max_prompt_length is not None:
            raise GymTSError("unsupported_capability", "Native prompts cannot be silently truncated")
        self.artifacts = artifacts if artifacts is not None else getattr(gym, "artifacts", None)
        if self.artifacts is None:
            raise GymTSError("invalid_config", "Native GRPO requires artifact services")
        if rollout_provider is None:
            if gym is None or prepared_dataset is None:
                raise GymTSError("invalid_config", "Provide a rollout provider, or the legacy QA gym/dataset pair")
            from .pipeline import qa_rollout_provider
            rollout_provider = qa_rollout_provider(gym, prepared_dataset)
        if not callable(rollout_provider):
            raise GymTSError("invalid_config", "rollout_provider must be callable")
        self.rollout_provider, self.policy = rollout_provider, policy
        self._base_identity = policy.identity
        self._rollout_rows, self._loss_rows = [], None
        self.rollout_batches, self.policy_checkpoints = [], []
        self.progress_callback = progress_callback
        super().__init__(model=policy.model, reward_funcs=_published_native_rewards, args=args,
                         train_dataset=train_dataset, processing_class=policy.tokenizer,
                         peft_config=peft_config, **kwargs)
        if self.accelerator.num_processes != 1:
            raise GymTSError("unsupported_capability", "This native multimodal adapter currently supports one training process")
        self.policy.model = self.model
        self.initial_trainable_digest, self.trainable_count = trainable_state_digest(self.model)
        self._fix_policy_revision()

    def _fix_policy_revision(self):
        """Publish actual adapter weights before a frozen rollout batch starts."""
        state_hash, _ = trainable_state_digest(self.model)
        revision = digest({"base": self._base_identity, "trainable_state": state_hash})
        if self.policy_checkpoints and self.policy_checkpoints[-1]["policy_revision"] == revision:
            return
        directory = Path(self.args.output_dir) / "rollout-policies" / revision.removeprefix("sha256:")
        directory.mkdir(parents=True, exist_ok=True)
        # PEFT saves the actual adapter, keeping the immutable base external.
        self.accelerator.unwrap_model(self.model).save_pretrained(directory, safe_serialization=True)
        files = []
        for path in sorted(directory.iterdir()):
            if path.is_file():
                files.append({"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                              "size_bytes": path.stat().st_size})
        identity = {"base": self._base_identity, "adapter_state_hash": state_hash,
                    "adapter_path": str(directory), "files": files, "revision": revision}
        self.policy.set_revision(revision, identity=identity)
        self.policy_checkpoints.append({"policy_revision": revision, "trainable_state": state_hash,
                                        "adapter_path": str(directory), "files": files})

    def _generate_and_score_completions(self, inputs):
        if not self.model.training:
            raise GymTSError("unsupported_capability", "Run held-out evaluation through the separate GymTS rollout command")
        self._fix_policy_revision()
        ids = [row["sample_id"] for row in inputs]
        if len(ids) % self.num_generations:
            raise GymTSError("invalid_dataset", "A GRPO generation batch must contain complete groups")
        for start in range(0, len(ids), self.num_generations):
            if len(set(ids[start:start + self.num_generations])) != 1:
                raise GymTSError("invalid_dataset", "TRL repeated prompt groups do not align with stable sample IDs")
        batch = self.rollout_provider(inputs, self.policy,
                         generation={"max_new_tokens": self.max_completion_length,
                                     "temperature": 1.0, "top_p": 1.0, "top_k": 0,
                                     "do_sample": True, "enable_thinking": False},
                         seed_start=self.args.seed + len(self.rollout_batches) * 1_000_000)
        self.rollout_batches.append({key: value for key, value in batch.items() if key != "rows"})
        # Publish the parent link before a group validation failure can abort
        # training. Child Runs and rejected/truncated actions stay discoverable.
        if self.progress_callback is not None:
            self.progress_callback(batch)
        # Consume only published, integrity-checked native shards. A provider's
        # in-memory rows are never the optimizer's source of truth.
        rows = read_native_dataset_rows(batch["manifest_ref"], self.artifacts)
        if "rows" in batch and batch["rows"] != rows:
            raise GymTSError("conflict", "Rollout provider rows differ from their published dataset")
        if len(rows) != len(ids) or [row["source_sample_id"] for row in rows] != ids:
            raise GymTSError("invalid_dataset", "The sealed dataset must preserve every native GRPO action in input order")
        if any(row["policy_revision"] != self.policy.revision for row in rows):
            raise GymTSError("conflict", "A GRPO batch mixed behavior policy revisions")
        validate_behavior_policy(rows)
        self._rollout_rows = rows
        result = collate_native_rows(rows, self.processing_class.pad_token_id, self.accelerator.device)
        rewards = torch.tensor([row["reward"] for row in rows], device=self.accelerator.device)
        grouped = rewards.view(-1, self.num_generations)
        means, stds = grouped.mean(dim=1), grouped.std(dim=1)
        advantages = rewards - means.repeat_interleave(self.num_generations)
        if self.scale_rewards:
            advantages = advantages / (stds.repeat_interleave(self.num_generations) + 1e-4)
        result["advantages"] = advantages
        self._metrics["train"]["reward"].append(rewards.mean().item())
        self._metrics["train"]["reward_std"].append(stds.mean().item())
        self._metrics["train"]["frac_reward_zero_std"].append((stds == 0).float().mean().item())
        self._metrics["train"]["completions/mean_length"].append(
            result["completion_mask"].sum(1).float().mean().item())
        return result

    def _compute_loss(self, model, inputs):
        self._loss_rows = [self._rollout_rows[index] for index in inputs["row_indices"].tolist()]
        try:
            # The optimization objective and all clipping remain upstream TRL.
            return super()._compute_loss(model, inputs)
        finally:
            self._loss_rows = None

    def _get_per_token_logps(self, model, input_ids, attention_mask, logits_to_keep, batch_size=None):
        if self._loss_rows is None or len(self._loss_rows) != input_ids.shape[0]:
            raise GymTSError("invalid_state", "Native likelihood computation requires the corresponding sealed dataset rows")
        values = []
        for index, row in enumerate(self._loss_rows):
            actual_ids = input_ids[index][attention_mask[index].bool()].tolist()
            if actual_ids != row["prompt_ids"] + row["completion_ids"]:
                raise GymTSError("schema_mismatch", "Trainer tokens differ from their captured native rollout")
            bundle = load_native_inputs(self.artifacts, row["native_inputs_ref"])
            if "input_ids" in bundle and (list(bundle["input_ids"].shape) != [1, len(row["prompt_ids"])]
                    or bundle["input_ids"][0].tolist() != row["prompt_ids"]):
                raise GymTSError("schema_mismatch", "Captured native input tensor differs from its prompt token artifact")
            if "attention_mask" in bundle and (list(bundle["attention_mask"].shape) != [1, len(row["prompt_ids"])]
                    or not bool((bundle["attention_mask"] == 1).all())):
                raise GymTSError("unsupported_capability", "Native GRPO currently requires one unpadded prompt per captured model call")
            if {"position_ids", "token_type_ids"}.intersection(bundle):
                raise GymTSError("unsupported_capability", "Explicit native position or token-type tensors require a dedicated likelihood adapter")
            logps = completion_logprobs(model, row["prompt_ids"], row["completion_ids"], bundle)[0]
            values.append(torch.nn.functional.pad(logps, (0, logits_to_keep - logps.numel())))
        return torch.stack(values)


__all__ = ["GymTSGRPOTrainer", "collate_native_rows", "trainable_state_digest", "validate_behavior_policy"]
