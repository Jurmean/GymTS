"""Explicit optional TRL training entry point; no model services are used."""
import json
import math
import os
from importlib.metadata import version
from pathlib import Path
import tempfile
import warnings

from gymts.contracts import GymTSError, canonical_json, utc_now


def training_prompts(prepared, *, groups_per_step, sample_ids=None):
    """Round-robin public training identities across the two data sources."""
    rows = [json.loads(line) for line in Path(prepared["train_path"]).read_text().splitlines()]
    if sample_ids is not None:
        if not isinstance(sample_ids, list) or not sample_ids or len(set(sample_ids)) != len(sample_ids):
            raise GymTSError("invalid_config", "Training sample selection must be explicit, nonempty and unique")
        selected = set(sample_ids)
        if selected - {row["sample_id"] for row in rows}:
            raise GymTSError("permission_denied", "Training selection includes unknown or held-out samples")
        rows = [row for row in rows if row["sample_id"] in selected]
    buckets = {}
    for row in rows:
        if row["split"] != "train":
            raise GymTSError("permission_denied", "Held-out rows cannot enter the training sampler")
        buckets.setdefault(row["dataset_id"], []).append(row)
    selected = []
    while any(buckets.values()):
        for key in sorted(buckets):
            if buckets[key]:
                row = buckets[key].pop(0)
                # Keep Arrow columns uniform. Private rewards stay in GymTS's
                # verifier artifact; the trainer dataset has no answer column.
                selected.append({"sample_id": row["sample_id"], "group_id": row["group_id"],
                                 "task_id": row["task_id"], "prompt": row["messages"]})
    if len(selected) < groups_per_step:
        raise GymTSError("invalid_dataset", "Not enough distinct training prompts for one GRPO batch")
    return selected


def run_training(gym, prepared, policy, output_dir, *, steps=2, generations=4,
                 groups_per_step=2, max_new_tokens=512, learning_rate=1e-5,
                 lora_rank=8, seed=7, eval_per_source=1, train_sample_ids=None,
                 publish_bundle=True, include_base_in_bundle=False):
    """Train actual LoRA parameters and preserve every rollout dataset boundary."""
    for name, value, minimum in (("steps", steps, 1), ("generations", generations, 2),
                                 ("groups_per_step", groups_per_step, 1), ("max_new_tokens", max_new_tokens, 1),
                                 ("lora_rank", lora_rank, 1), ("eval_per_source", eval_per_source, 0)):
        if type(value) is not int or value < minimum:
            raise GymTSError("invalid_config", name + " is below its supported minimum")
    if type(learning_rate) not in (int, float) or not math.isfinite(learning_rate) or learning_rate <= 0:
        raise GymTSError("invalid_config", "learning_rate must be finite and positive")
    if type(seed) is not int or seed < 0:
        raise GymTSError("invalid_config", "seed must be a nonnegative integer")
    destination = Path(output_dir).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise GymTSError("conflict", "Training output must be a new directory; existing evidence is immutable")
    destination.mkdir(parents=True, exist_ok=True)
    trainer, primary_error = None, None
    summary = {"schema_version": "gymts.rl/training/1", "status": "initializing", "started_at": utc_now(),
        "backend": "trl.GRPOTrainer", "versions": {},
        "dataset_manifest_ref": prepared["manifest_ref"], "steps_requested": steps,
        "generations": generations, "groups_per_step": groups_per_step,
        "beta": 0.0, "loss_type": "grpo", "lora_rank": lora_rank, "learning_rate": learning_rate,
        "steps_completed": 0, "rollout_batches": [], "policy_checkpoints": [],
        "model_path": policy.model_path, "family": policy.family, "seed": seed,
        "training_sample_ids": train_sample_ids, "weight_decay": 0.0}

    def persist():
        if trainer is not None:
            summary.update(rollout_batches=trainer.rollout_batches, policy_checkpoints=trainer.policy_checkpoints,
                           steps_completed=trainer.state.global_step)
        _persist_training_summary(gym, destination, summary)

    def on_batch(batch):
        # The adapter invokes this after the native batch is durable and before
        # validating optimizer eligibility, including truncated/failed groups.
        summary["last_batch_ref"] = batch["batch_ref"]
        persist()

    # Publish the experiment parent before importing the runtime or constructing
    # PEFT/TRL objects; failed initialization is a recorded attempt as well.
    persist()
    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, get_peft_model_state_dict, set_peft_model_state_dict
        from safetensors.torch import load_file
        from trl import GRPOConfig
        from transformers import set_seed
        from .pipeline import qa_rollout_provider, rollouts
        from .trl_adapter import GymTSGRPOTrainer, trainable_state_digest

        summary["versions"] = {key: version(key) for key in
            ("torch", "transformers", "trl", "peft", "accelerate", "datasets", "numpy", "pyarrow")}
        prompts = training_prompts(prepared, groups_per_step=groups_per_step, sample_ids=train_sample_ids)
        args = GRPOConfig(output_dir=str(destination), max_steps=steps,
            per_device_train_batch_size=generations * groups_per_step,
            gradient_accumulation_steps=1, steps_per_generation=1,
            num_generations=generations, num_iterations=1, max_prompt_length=None,
            max_completion_length=max_new_tokens, beta=0.0, temperature=1.0,
            top_p=1.0, top_k=0, repetition_penalty=1.0, loss_type="grpo",
            scale_rewards=True, learning_rate=learning_rate, weight_decay=0.0,
            bf16=next(policy.model.parameters()).dtype == torch.bfloat16,
            fp16=next(policy.model.parameters()).dtype == torch.float16,
            gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False},
            disable_dropout=True, remove_unused_columns=False, shuffle_dataset=False,
            report_to="none", save_strategy="no", logging_steps=1,
            dataloader_num_workers=0, seed=seed, data_seed=seed)
        lora = LoraConfig(r=lora_rank, lora_alpha=lora_rank * 2, lora_dropout=0.0,
                          target_modules=["q_proj", "v_proj"], task_type="CAUSAL_LM", bias="none")
        set_seed(seed)
        trainer = GymTSGRPOTrainer(artifacts=gym.artifacts, rollout_provider=qa_rollout_provider(gym, prepared), policy=policy,
            args=args, train_dataset=Dataset.from_list(prompts), peft_config=lora,
            progress_callback=on_batch)
        summary.update(status="running", trainable_parameters=trainer.trainable_count,
                       initial_trainable_digest=trainer.initial_trainable_digest)
        persist()
        result = trainer.train()
        final_digest, _ = trainable_state_digest(trainer.model)
        trainer._fix_policy_revision()
        checkpoint = destination / "final-adapter"
        trainer.save_model(str(checkpoint))
        trainer.save_state()
        policy.tokenizer.save_pretrained(checkpoint)
        # Reload bytes through the same PEFT API used by adapter consumers.
        state = load_file(str(checkpoint / "adapter_model.safetensors"), device="cpu")
        in_memory = get_peft_model_state_dict(trainer.accelerator.unwrap_model(trainer.model))
        if set(state) != set(in_memory) or any(not torch.equal(state[key], in_memory[key].detach().cpu()) for key in state):
            raise GymTSError("conflict", "Saved adapter bytes differ from the trained policy")
        set_peft_model_state_dict(trainer.accelerator.unwrap_model(trainer.model), state)
        reloaded_digest, _ = trainable_state_digest(trainer.model)
        if reloaded_digest != final_digest:
            raise GymTSError("conflict", "Reloading the adapter changed its trainable state")
        summary.update(status="checkpointed", steps_completed=trainer.state.global_step,
            final_trainable_digest=final_digest,
            weights_changed=final_digest != trainer.initial_trainable_digest,
            checkpoint_reload_equal=True, checkpoint=str(checkpoint),
            final_policy_revision=policy.revision, train_metrics=result.metrics,
            log_history=trainer.state.log_history)
        # Preserve the verified checkpoint even if separate evaluation fails.
        persist()
        if publish_bundle:
            from .checkpoint import publish_checkpoint_bundle
            published = publish_checkpoint_bundle(gym, policy, checkpoint, prepared, summary,
                                                  include_base=include_base_in_bundle)
            summary.update(checkpoint_bundle_ref=published["bundle_ref"],
                deployment_policy_revision=published["policy_revision"],
                training_provenance_ref=published["training_provenance_ref"])
            persist()
        if eval_per_source:
            eval_rows = [json.loads(line) for line in Path(prepared["eval_path"]).read_text().splitlines()]
            chosen, counts = [], {}
            for row in eval_rows:
                source = row["dataset_id"]
                if counts.get(source, 0) < eval_per_source:
                    chosen.append(row["sample_id"])
                    counts[source] = counts.get(source, 0) + 1
            if chosen:
                evaluation = rollouts(gym, prepared, chosen, policy,
                    generation={"max_new_tokens": max_new_tokens, "temperature": 1.0,
                                "top_p": 1.0, "top_k": 0, "do_sample": True, "enable_thinking": False},
                    seed_start=seed + 100_000_000, split="eval")
                summary["evaluation"] = {key: value for key, value in evaluation.items() if key != "rows"}
                summary["evaluation_status"] = "succeeded" if all(entry["run_status"] == "succeeded" for entry in evaluation["entries"]) else "failed"
        summary["status"] = "completed"
        return summary
    except BaseException as error:
        primary_error = error
        summary.update(status="failed", error=(error.to_dict() if isinstance(error, GymTSError)
            else {"type": type(error).__name__, "message": str(error)}))
        raise
    finally:
        summary["ended_at"] = utc_now()
        try:
            persist()
        except Exception as recording_error:
            if primary_error is None:
                raise GymTSError("recording_failure", "Training evidence could not be finalized",
                    links={"previous_summary_ref": summary.get("summary_ref"), "output_dir": str(destination)}) from recording_error
            # Keep the original training exception when storage is unavailable.
            # The previous committed journal revision remains identifiable.
            note = "Training summary finalization failed; previous committed revision: " + str(summary.get("summary_ref"))
            if hasattr(primary_error, "add_note"):
                primary_error.add_note(note)
            else:
                warnings.warn(note, RuntimeWarning)


def _persist_training_summary(gym, destination, summary):
    """Commit a hash-linked CAS revision, then atomically advance its JSON index."""
    previous = summary.get("summary_ref")
    body = {key: value for key, value in summary.items() if key != "summary_ref"}
    body["previous_summary_ref"] = previous
    nonfinite = []

    def finite_json(value, path):
        if isinstance(value, float) and not math.isfinite(value):
            nonfinite.append(path)
            return None
        if isinstance(value, dict):
            return {key: finite_json(item, path + "." + key) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [finite_json(item, path + "[" + str(index) + "]") for index, item in enumerate(value)]
        return value

    body = finite_json(body, "$")
    if nonfinite:
        body["non_finite_fields"] = nonfinite
    gym.schemas.register("gymts.rl/training/1", {"type": "object"})
    reference = gym.artifacts.save_json(body, "gymts.rl/training/1")
    document = dict(body, summary_ref=reference)
    descriptor, temporary = tempfile.mkstemp(prefix=".training-summary-", dir=str(destination))
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json(document) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, Path(destination) / "training-summary.json")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    summary.clear()
    summary.update(document)
    return reference


__all__ = ["run_training", "training_prompts"]
