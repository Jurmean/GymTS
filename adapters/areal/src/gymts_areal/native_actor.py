"""Observe original FSDP/PPO methods without replacing loss or optimizer math."""
import hashlib
import math
import os

import torch
from areal import PPOTrainer
from areal.engine.fsdp_engine import FSDPPPOActor
from areal.utils.environ import is_single_controller

from .tensors import FIELDS, encode_tensors
from .wire import Client, finite_evidence, sha
from .native_workflow import RUNTIME_IDENTITY  # Verify the same native/F0 bytes in each actor RPC process.


def report(event):
    client = Client(os.environ["GYMTS_AREAL_BRIDGE_SOCKET"])
    try:
        reply = client.request({"kind": "training_event", "bridge_id": os.environ["GYMTS_AREAL_BRIDGE_ID"], "event": finite_evidence(event)})
        if reply != {"kind": "ack"}:
            raise ValueError("Native training evidence was not committed")
    finally:
        client.close()


def row_hashes(batch):
    hashes = []
    for record in batch:
        for index in range(record["input_ids"].shape[0]):
            valid = record["attention_mask"][index].bool()
            row = {name: record[name][index:index+1][:, valid] for name in FIELDS[:-1]}
            row["rewards"] = record["rewards"][index:index+1]
            row["is_truncated"] = record["is_truncated"][index:index+1]
            hashes.append(sha(encode_tensors(row)))
    return hashes


def trainable_state(model):
    result = {}
    for name, parameter in model.named_parameters():
        if not parameter.requires_grad:
            continue
        if "lora_" not in name:
            raise ValueError("The bounded native acceptance supports LoRA-only trainable parameters")
        tensor = parameter.detach()
        if hasattr(tensor, "to_local"):
            tensor = tensor.to_local()
        result[name] = tensor.cpu().contiguous().clone()
    if not result:
        raise ValueError("Native actor exposes no trainable LoRA parameters")
    return result


def state_hash(state):
    value = hashlib.sha256()
    for name, tensor in sorted(state.items()):
        value.update(name.encode())
        value.update(str(tensor.dtype).encode())
        value.update(str(tuple(tensor.shape)).encode())
        value.update(tensor.view(torch.uint8).numpy().tobytes())
    return "sha256:" + value.hexdigest()


def optimizer_steps(optimizer):
    steps = []
    for value in optimizer.state.values():
        if "step" in value:
            step = value["step"]
            steps.append(int(step.item() if hasattr(step, "item") else step))
    return {"min": min(steps, default=0), "max": max(steps, default=0), "states_with_step": len(steps)}


class ObservedFSDPActor(FSDPPPOActor):
    def _prepare_mb_list(self, *args, **kwargs):
        result = super()._prepare_mb_list(*args, **kwargs)
        sequence_counts = [mb["cu_seqlens"].numel() - 1 for mb in result.mbs]
        if self.config.attn_impl != "sdpa" or any(count != 1 for count in sequence_counts):
            raise ValueError("The bounded SDPA profile requires exactly one episode per native microbatch")
        report({"kind": "native_microbatch_isolation", "episodes_per_microbatch": sequence_counts,
                "attention": "original_native_sdpa; no cross-episode packing"})
        return result

    def _save_lora_to_hf(self, path):
        # Preserve the original saver and explicitly verify its documented dtype/key conversion.
        super()._save_lora_to_hf(path)
        import re
        from safetensors.torch import load_file
        from gymts_rl.checkpoint import adapter_state_hash
        if torch.distributed.get_rank() != 0:
            return
        saved = load_file(os.path.join(path, "adapter_model.safetensors"), device="cpu")
        actual = {}
        for name, parameter in self.model.named_parameters():
            if parameter.requires_grad and "lora_" in name:
                value = parameter.detach()
                if hasattr(value, "full_tensor"):
                    value = value.full_tensor()
                actual[re.sub(r"\.default\.(weight|bias)$", r".\1", name)] = self._cast_to_compute_dtype(value.cpu())
        if set(saved) != set(actual) or any(not torch.equal(saved[name], actual[name]) for name in actual):
            raise ValueError("Native HF saver did not persist the actual LoRA tensors with its declared dtype conversion")
        report({"kind": "native_hf_save", "path": str(path), "adapter_state_hash": adapter_state_hash(saved),
                "saved_tensor_count": len(saved), "exact_native_cast_tensor_match": True,
                "serialization": "original_FSDPEngine._save_lora_to_hf; native key cleanup and compute dtype"})

    @torch.no_grad()
    def compute_advantages(self, batch, *args, **kwargs):
        report({"kind": "consume_batch", "row_hashes": row_hashes(batch)})
        result = super().compute_advantages(batch, *args, **kwargs)
        stats = {"tokens": 0, "nonzero": 0, "finite": True, "abs_max": 0.0}
        for record in result:
            values = record["advantages"][record["loss_mask"].bool()]
            stats["tokens"] += values.numel()
            stats["nonzero"] += int(torch.count_nonzero(values).item())
            stats["finite"] = stats["finite"] and bool(torch.isfinite(values).all().item())
            if values.numel(): stats["abs_max"] = max(stats["abs_max"], float(values.abs().max().item()))
        report({"kind": "native_advantages", **stats})
        if not stats["finite"] or not stats["nonzero"]:
            raise ValueError("Native batch has no finite nonzero trainable advantage; no optimizer update is accepted")
        return result

    def optimizer_step(self):
        if any(group["weight_decay"] != 0 for group in self.optimizer.param_groups):
            raise ValueError("Acceptance requires zero weight decay to attribute parameter changes to gradients")
        before = trainable_state(self.model)
        previous_steps = optimizer_steps(self.optimizer)
        native_stats = super().optimizer_step()
        after = trainable_state(self.model)
        next_steps = optimizer_steps(self.optimizer)
        deltas = {name: float(torch.linalg.vector_norm(after[name].float() - before[name].float()).item()) for name in before}
        stats = {"kind": "native_optimizer_step", "native_stats": native_stats,
            "before_steps": previous_steps, "after_steps": next_steps,
            "before_trainable_sha256": state_hash(before), "after_trainable_sha256": state_hash(after),
            "changed_parameters": sum(delta > 0 for delta in deltas.values()),
            "delta_l2": math.sqrt(math.fsum(delta * delta for delta in deltas.values())),
            "trainable_parameter_count": sum(t.numel() for t in before.values()), "weight_decay": 0,
            "gradient_source": "original_areal_FSDPEngine.optimizer_step", "parameter_delta_by_name": deltas}
        report(stats)
        if (native_stats["update_successful"] != 1 or not math.isfinite(native_stats["grad_norm"]) or
                native_stats["grad_norm"] <= 0 or stats["changed_parameters"] == 0 or
                next_steps["max"] <= previous_steps["max"]):
            raise ValueError("Native optimizer did not produce a verified finite-gradient parameter update")
        return native_stats


class ObservedPPOTrainer(PPOTrainer):
    def _create_train_engine(self, actor_config, alloc):
        # Fixed-version native factory hook. Native FSDP/PPO and optimizer methods still execute via super.
        if alloc.backend != "fsdp" or actor_config.optimizer is None or not actor_config.use_lora:
            raise ValueError("This bounded trainer bridge supports one native FSDP LoRA actor without auxiliary models")
        actor = (ObservedFSDPActor.as_controller(actor_config, self.scheduler) if is_single_controller()
                 else ObservedFSDPActor(config=actor_config))
        actor.create_process_group(parallel_strategy=alloc.parallel)
        return actor
