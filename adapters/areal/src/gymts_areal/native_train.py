"""One original AReaL PPO update with a public-only native map dataset."""
import copy
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import signal
import subprocess

from torch.utils.data import Dataset
from omegaconf import OmegaConf
from areal.api.cli_args import load_expr_config
from areal.utils.saver import Saver

from .native_workflow import ROOT, RUNTIME_IDENTITY, native_tir
from .native_actor import ObservedPPOTrainer
from .identity import model_identity
from .wire import Client, sha


class PublicDataset(Dataset):
    """Preserve public JSON identity; Arrow must not inject nullable gold columns."""
    def __init__(self, rows):
        self.rows = copy.deepcopy(rows)
        for row in self.rows:
            if row["split"] != "train" or {"answer", "reward_spec", "target", "labels", "gold", "ground_truth"}.intersection(row):
                raise ValueError("The native trainer only accepts public training samples")

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        return copy.deepcopy(self.rows[index])


def make_config(settings, destination):
    """Amend upstream's actual LoRA recipe; loss and optimizer stay native."""
    cfg = OmegaConf.load(ROOT / "examples/math/gsm8k_grpo_lora.yaml")
    root = str(Path(settings["output"]).resolve())
    count = len(settings["public_train"])
    updates = {
        "experiment_name": "gymts-sealed-tir", "trial_name": settings["trial"], "seed": settings["seed"],
        "total_train_epochs": 1, "total_train_steps": 1, "tokenizer_path": settings["model"],
        "cluster.n_gpus_per_node": 2, "cluster.fileroot": root + "/native", "cluster.name_resolve.nfs_record_root": root + "/names",
        "scheduler.type": "local", "actor.path": settings["model"], "actor.backend": "fsdp:d1",
        "rollout.backend": "sglang:d1", "rollout.max_head_offpolicyness": 0,
        "rollout.max_concurrent_rollouts": 1, "rollout.consumer_batch_size": count, "rollout.request_retries": 1,
        "rollout.request_timeout": settings["group_size"] * settings["episode_seconds"] + 120,
        "rollout.workers_ready_timeout": 900, "rollout.setup_timeout": 900,
        "rollout.dump_to_file": False, "rollout.serialize_group_samples": True,
        "gconfig.n_samples": settings["group_size"], "gconfig.max_new_tokens": settings["max_new_tokens"],
        "gconfig.max_tokens": settings["max_length"], "gconfig.temperature": 1.0,
        "gconfig.top_p": 1.0, "gconfig.top_k": 100000000, "gconfig.frequency_penalty": 0.0,
        "gconfig.greedy": False, "gconfig.reward_normalization": False, "gconfig.lora_name": "gymts-tir-lora",
        "actor.temperature": 1.0, "actor.optimizer.weight_decay": 0.0, "actor.optimizer.lr": settings["learning_rate"],
        "actor.optimizer.warmup_steps_proportion": 0.0, "actor.reward_scaling": 1.0, "actor.reward_bias": 0.0,
        "actor.recompute_logprob": False, "actor.use_decoupled_loss": False,
        "actor.mb_spec.max_tokens_per_mb": settings["max_length"], "actor.mask_no_eos_with_zero": False,
        "actor.mb_spec.n_mbs": count * settings["group_size"], "actor.mb_spec.granularity": 1,
        "actor.lora_rank": 16, "actor.lora_alpha": 16,
        "actor.attn_impl": "sdpa",
        "train_dataset.batch_size": count, "train_dataset.num_workers": 0, "train_dataset.shuffle": False,
        "train_dataset.path": "public-cas-snapshot-only", "train_dataset.max_length": settings["max_length"],
        "valid_dataset": None, "ref": None,
        "sglang.context_length": settings["max_length"], "sglang.mem_fraction_static": 0.65,
        "sglang.max_running_requests": 1, "sglang.attention_backend": "torch_native",
        "sglang.sampling_backend": "pytorch", "sglang.disable_cuda_graph": True,
        "sglang.lora_backend": "torch_native",
        "sglang.disable_radix_cache": True, "sglang.skip_tokenizer_init": False,
        "saver.freq_steps": 1, "saver.freq_epochs": None,
        "evaluator.freq_epochs": None, "evaluator.freq_steps": None,
    }
    env_keys = ("GYMTS_AREAL_REPOSITORY", "GYMTS_FROZEN_CORE_IDENTITY", "GYMTS_AREAL_BRIDGE_SOCKET", "GYMTS_AREAL_BRIDGE_ID",
                "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "TOKENIZERS_PARALLELISM", "CUDA_DEVICE_ORDER")
    worker_env = {key: os.environ[key] for key in env_keys if key in os.environ}
    # Exact same isolated Python for RPC subprocesses. Scheduler appends only native arguments.
    updates["actor.scheduling_spec"] = [{"task_type": "worker", "port_count": 2, "gpu": 1, "cpu": 4, "mem": 48,
        "cmd": str(Path(sys.executable).absolute()) + " -m areal.infra.rpc.rpc_server", "env_vars": worker_env}]
    for name, value in updates.items():
        OmegaConf.update(cfg, name, value, merge=False, force_add=True)
    OmegaConf.save(cfg, destination)
    config, _ = load_expr_config(["--config", str(destination)], native_tir.TIRGRPOConfig)
    return config


def main(path):
    def terminated(_signal, _frame):
        raise TimeoutError("Owned native training worker received its bounded coordinator stop")
    signal.signal(signal.SIGTERM, terminated)
    settings = json.loads(Path(path).read_text())
    output = Path(settings["output"])
    config = make_config(settings, output / "native-config.yaml")
    (output / "resolved-native-config.json").write_text(json.dumps(asdict(config), indent=2) + "\n")
    if settings.get("cpu_preflight_only"):
        # Instantiate map data and dataloader without a Trainer, CUDA context or server.
        from areal.utils.dataloader import create_dataloader
        dataset = PublicDataset(settings["public_train"])
        batch = next(iter(create_dataloader(dataset, 0, 1, config.train_dataset)))
        if batch != settings["public_train"]:
            raise ValueError("Native dataloader changed public sample identity")
        if settings["max_model_requests"] < 8:
            raise ValueError("Physical HTTP request budget must allow native marker-split tool calls and a final response")
        from .codec import native_messages, CALCULATOR_INSTRUCTION
        from .contracts import PROMPT_PROJECTION, CODEC
        if any(CALCULATOR_INSTRUCTION not in native_messages(row)[-1]["content"] for row in batch):
            raise ValueError("Versioned public calculator instruction is missing from the native projection")
        if config.rollout.request_timeout < settings["group_size"] * settings["episode_seconds"] + 120:
            raise ValueError("Native group callback deadline cannot cover serialized member episodes")
        from areal.utils.data import split_padded_tensor_dict_into_mb_list
        import torch
        rows = len(batch) * settings["group_size"]
        microbatches = split_padded_tensor_dict_into_mb_list({"input_ids": torch.ones((rows, 8), dtype=torch.int64),
            "attention_mask": torch.ones((rows, 8), dtype=torch.bool)}, config.actor.mb_spec, sync_mbs=False)
        sequence_counts = [mb["input_ids"].shape[0] for mb in microbatches.mbs]
        if sequence_counts != [1] * rows:
            raise ValueError("Native SDPA microbatches must contain exactly one independent episode")
        # Match the upstream launcher's bare python3 command under its actual worker environment.
        from areal.api.cli_args import get_py_cmd
        from areal.infra.utils.launcher import get_env_vars
        from areal.engine.sglang_remote import SGLangBackend
        command = get_py_cmd("sglang.launch_server", {})
        code = ("import json,sys; import sglang; from sglang.srt.server_args import ServerArgs;"
                "print(json.dumps({'prefix':sys.prefix,'version':list(sys.version_info[:2]),'sglang':sglang.__version__}))")
        executable = json.loads(subprocess.check_output([command[0], "-c", code], text=True,
            env=SGLangBackend.build_server_env({**os.environ, **get_env_vars({})})))
        if executable["prefix"] != sys.prefix or executable["version"] != list(sys.version_info[:2]):
            raise ValueError("Upstream SGLang launcher selected a different Python environment")
        (output / "native-api-preflight.json").write_text(json.dumps({"status": "passed", "runtime": RUNTIME_IDENTITY,
            "public_samples": len(batch), "private_fields_absent": True, "effective_serialization": "adapter_lock_v1",
            "native_single_episode_microbatches": len(sequence_counts), "native_sequences_per_microbatch": sequence_counts,
            "native_sublaunch_interpreter": executable,
            "prompt_projection_ref": PROMPT_PROJECTION, "answer_codec_ref": CODEC,
            "group_callback_deadline_s": config.rollout.request_timeout,
            "individual_generation_deadline_s": 180,
            "max_physical_model_requests": settings["max_model_requests"],
            "core_changes": 0, "cuda_context_created": False}, indent=2) + "\n")
        return
    import torch
    if torch.cuda.device_count() != 2:
        raise ValueError("Native actor/rollout require exactly the two explicitly allocated visible GPUs")
    actual_uuids = [str(torch.cuda.get_device_properties(index).uuid) for index in range(2)]
    if [value.removeprefix("GPU-").lower() for value in actual_uuids] != [value.removeprefix("GPU-").lower() for value in settings["gpu_uuids"]]:
        raise ValueError("Native visible GPU UUIDs differ from the user's explicit allocation")
    if model_identity(settings["model"]) != settings["model_identity"]:
        raise ValueError("Base model bytes changed between coordinator and native training process")
    with ObservedPPOTrainer(config, PublicDataset(settings["public_train"]), None) as trainer:
        initial = Path(Saver.get_model_save_root(config.experiment_name, config.trial_name, config.cluster.fileroot, "actor")) / "initial_lora"
        identity = {"base": settings["model_identity"], "initial_lora": model_identity(initial),
                    "native_revision": RUNTIME_IDENTITY["native_revision"]}
        revision = sha(identity)
        policy = {"kind": "policy_version", "bridge_id": os.environ["GYMTS_AREAL_BRIDGE_ID"],
            "native_policy_version": 0, "policy_revision": revision, "identity": identity}
        client = Client(os.environ["GYMTS_AREAL_BRIDGE_SOCKET"])
        try:
            if client.request(policy) != {"kind": "ack"}:
                raise ValueError("Policy version map was not committed")
        finally:
            client.close()
        trainer.train(workflow="gymts_areal.native_workflow.SealedTIRWorkflow", workflow_kwargs={
            "gconfig": config.gconfig, "tokenizer": config.tokenizer_path,
            "tir_config": {"max_turns": 2, "max_length": settings["max_length"], "tool_timeout": 30,
                           "enable_tools": "calculator", "is_chat_model": True},
            "bridge_socket": os.environ["GYMTS_AREAL_BRIDGE_SOCKET"], "bridge_id": os.environ["GYMTS_AREAL_BRIDGE_ID"],
            "policy_revision": revision, "model_ref": {"name": "local-qwen-policy", "version": revision, "origin_ref": None},
            "policy_identity": identity, "native_version": 0, "max_model_requests": settings["max_model_requests"],
            "max_wall_time_s": settings["episode_seconds"], "seed": settings["seed"]})
        checkpoint = Path(Saver.get_model_save_path(config.experiment_name, config.trial_name,
            config.cluster.fileroot, 0, 0, 0))
        if not (checkpoint / "adapter_model.safetensors").is_file():
            raise ValueError("Original native Saver did not produce the final HF LoRA checkpoint")
        trainer.tokenizer.save_pretrained(checkpoint)
        report = {"status": "checkpointed", "checkpoint": str(checkpoint), "checkpoint_identity": model_identity(checkpoint),
                  "initial_policy_revision": revision, "initial_lora_identity": identity["initial_lora"],
                  "native_final_version": trainer.actor.get_version(), "runtime": RUNTIME_IDENTITY}
        (output / "native-training-result.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
