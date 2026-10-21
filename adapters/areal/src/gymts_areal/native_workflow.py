"""Fixed-upstream TIR subclass and transparent native Backend instrumentation.

Import only in the explicitly selected AReaL runtime. The only source path
added is the declared, hash-checked upstream examples/tir directory.
"""
import asyncio
import copy
from dataclasses import asdict
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import torch
import areal
from areal import workflow_context

from .codec import native_messages
from .contracts import PINNED_REVISION, PROMPT_PROJECTION, CODEC
from .tensors import decode_tensors, encode_tensors
from .wire import Client, now, sha


def file_hash(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def verify_runtime():
    root = Path(os.environ["GYMTS_AREAL_REPOSITORY"]).resolve(strict=True)
    actual = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if actual != PINNED_REVISION:
        raise ValueError("Native AReaL checkout has the wrong fixed revision")
    if subprocess.check_output(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"], text=True).strip():
        raise ValueError("Native AReaL checkout has modified tracked files")
    if not Path(areal.__file__).resolve().is_relative_to(root):
        raise ValueError("Loaded AReaL is outside the declared native source checkout")
    import gymts
    frozen = json.loads(Path(os.environ["GYMTS_FROZEN_CORE_IDENTITY"]).read_text())
    base = Path(gymts.__file__).resolve().parent.parent
    for name, expected in frozen["installed_files"].items():
        if file_hash(base / name) != expected:
            raise ValueError("Native worker did not load the frozen installed GymTS core")
    files = list((root / "examples/tir").rglob("*.py")) + [root / name for name in
        ("areal/infra/remote_inf_engine.py", "areal/trainer/rl_trainer.py", "areal/engine/fsdp_engine.py",
         "areal/trainer/ppo/actor.py", "areal/api/io_struct.py", "areal/api/reward_api.py")]
    identity = {"native_revision": actual, "native_root": str(root), "areal_path": str(Path(areal.__file__).resolve()),
        "source_files_sha256": {str(path.relative_to(root)): file_hash(path) for path in files},
        "core_path": str(Path(gymts.__file__).resolve()), "core_wheel_sha256": frozen["wheel_sha256"],
        "core_verified_files": len(frozen["installed_files"])}
    return root, identity


ROOT, RUNTIME_IDENTITY = verify_runtime()
sys.path.insert(0, str(ROOT / "examples/tir"))
native_tir = importlib.import_module("tir_workflow")
if Path(native_tir.__file__).resolve() != ROOT / "examples/tir/tir_workflow.py":
    raise ValueError("Loaded TIR workflow is outside the verified upstream source")


def unused_reward(*args, **kwargs):
    raise RuntimeError("The native process-pool reward wrapper is replaced by the explicit trusted async bridge")


class CapturedBackend:
    def __init__(self, wrapped, workflow):
        self.wrapped, self.workflow = wrapped, workflow
        self.active, self.last_call_id, self.requested = None, None, None

    def __getattr__(self, name):
        return getattr(self.wrapped, name)

    def build_generation_request(self, req, with_lora, version):
        workflow = self.workflow
        if version != workflow.native_version:
            raise ValueError("Native policy version changed inside a frozen TIR Run")
        workflow.model_requests += 1
        if workflow.model_requests > workflow.max_model_requests:
            raise ValueError("Fixed native TIR model-request budget exhausted")
        native = self.wrapped.build_generation_request(req, with_lora=with_lora, version=version)
        call_id = "areal-http-" + uuid.uuid4().hex
        self.active, self.last_call_id = call_id, call_id
        workflow.client.event("model_start", call_id=call_id, attempt_id=uuid.uuid4().hex,
            request={"rid": req.rid, "input_ids": list(req.input_ids), "native_http": asdict(native),
                "requested_generation": self.requested, "effective_generation": asdict(req.gconfig),
                "native_policy_version": version, "with_lora": with_lora})
        return native

    def parse_generation_response(self, response):
        call_id = self.active
        try:
            parsed = self.wrapped.parse_generation_response(response)
        except Exception as error:
            self.workflow.client.event("model_end", call_id=call_id, status="failed",
                response={"native_http_response": response}, error=type(error).__name__ + ": " + str(error))
            self.active = None
            raise
        status = "cancelled" if parsed.stop_reason == "abort" else "succeeded"
        self.workflow.client.event("model_end", call_id=call_id, status=status,
            response={"native_http_response": response, "output_tokens": parsed.output_tokens,
                "output_logprobs": parsed.output_logprobs, "stop_reason": parsed.stop_reason})
        self.active = None
        return parsed


class CapturedEngine:
    def __init__(self, wrapped, backend, workflow):
        self.wrapped, self.backend, self.workflow = wrapped, backend, workflow

    def __getattr__(self, name):
        return getattr(self.wrapped, name)

    async def agenerate(self, request):
        expected = list(request.input_ids)
        self.backend.requested = asdict(request.gconfig)
        if self.wrapped.get_version() != self.workflow.native_version:
            raise ValueError("Native policy version changed before generation")
        try:
            response = await asyncio.wait_for(self.wrapped.agenerate(request), timeout=180)
        except Exception as error:
            if self.backend.active:
                self.workflow.client.event("model_end", call_id=self.backend.active, status="failed",
                    error=type(error).__name__ + ": " + str(error))
                self.backend.active = None
            raise
        self.workflow.client.event("model_aggregate", response={"input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens, "output_logprobs": response.output_logprobs,
            "output_versions": response.output_versions, "stop_reason": response.stop_reason})
        if response.input_tokens != expected or not response.output_tokens:
            raise ValueError("Native inference response has changed inputs or no generated tokens")
        if (self.wrapped.get_version() != self.workflow.native_version or
                any(version != self.workflow.native_version for version in response.output_versions)):
            raise ValueError("Native model response belongs to a changed policy version")
        self.workflow.last_stop_reason = response.stop_reason
        return response


class SealedTIRWorkflow(native_tir.TIRWorkflow):
    def __init__(self, *, gconfig, tokenizer, tir_config, bridge_socket, bridge_id,
                 policy_revision, model_ref, policy_identity, native_version=0,
                 max_model_requests=16, max_wall_time_s=600, seed=1):
        if isinstance(tir_config, dict):
            tir_config = native_tir.TIRConfig(**tir_config)
        if tir_config.enable_tools != "calculator":
            raise ValueError("This fixed TIR adapter permits the native calculator tool only")
        # At T=1, top_p=1 and top_k covering the vocabulary, model and sampling logprobs coincide.
        if gconfig.temperature != 1 or gconfig.top_p != 1 or gconfig.greedy or gconfig.frequency_penalty != 0:
            raise ValueError("This native probability profile requires unfiltered temperature-one sampling")
        super().__init__(reward_fn=unused_reward, gconfig=gconfig, tokenizer=tokenizer,
                         tir_config=tir_config, enable_thinking=False)
        if gconfig.top_k < len(self.tokenizer):
            raise ValueError("Native probability profile requires top_k covering the complete vocabulary")
        self.async_reward_fn = self.trusted_async_reward
        self._serial = asyncio.Lock()
        self.bridge_socket, self.bridge_id = bridge_socket, bridge_id
        self.policy_revision, self.model_ref = policy_revision, model_ref
        self.policy_identity, self.native_version = policy_identity, native_version
        self.max_model_requests, self.seed = max_model_requests, seed
        self.max_wall_time_s = max_wall_time_s

    def tokenizer_identity(self):
        directory = Path(self.tokenizer.name_or_path).resolve(strict=True)
        names = ("tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "added_tokens.json",
                 "vocab.json", "merges.txt", "tokenizer.model", "chat_template.jinja")
        return {"directory": str(directory), "class": type(self.tokenizer).__name__,
            "files": {name: file_hash(directory / name) for name in names if (directory / name).is_file()},
            "chat_template": self.tokenizer.get_chat_template(), "eos_token": self.tokenizer.eos_token,
            "pad_token": self.tokenizer.pad_token, "eos_token_id": self.tokenizer.eos_token_id,
            "pad_token_id": self.tokenizer.pad_token_id}

    async def trusted_async_reward(self, prompt, completions, prompt_ids, completion_ids, **data):
        self.native_completion = completions
        self.client.sequence += 1
        reply = self.client.request({"kind": "reward_request", "sequence": self.client.sequence,
            "at": now(),
            "completion": completions, "prompt_ids": prompt_ids, "completion_ids": completion_ids,
            "sample_id": data["sample_id"], "tool_using": data.get("tool_using"), "tool_count": data.get("tool_status")})
        if reply.get("kind") != "reward_result" or reply.get("sequence") != self.client.sequence:
            raise ValueError("Trusted reward did not return the matching captured request")
        return float(reply["value"])

    async def _execute_tools(self, response, tool_manager=None):
        call_id = "areal-tool-" + uuid.uuid4().hex
        self.tool_call_id = call_id
        self.client.event("tool_start", call_id=call_id, attempt_id=uuid.uuid4().hex,
            parent_call_id=self.backend.last_call_id, request={"native_tool_text": response, "allowed_tools": "calculator"})
        try:
            result, status = await super()._execute_tools(response, tool_manager)
            success = status == native_tir.ToolCallStatus.SUCCESS
            self.client.event("tool_end", call_id=call_id, status="succeeded" if success else "failed",
                response={"native_result": result, "native_tool_status": str(status)},
                **({} if success else {"error": "Native calculator dispatch returned " + str(status)}))
            return result, status
        except Exception as error:
            self.client.event("tool_end", call_id=call_id, status="failed", error=type(error).__name__ + ": " + str(error))
            raise

    def _process_tool_result(self, result):
        formatted = native_tir.TIRWorkflow._process_tool_result(result)
        self.client.event("tool_projection", call_id=self.tool_call_id, text=formatted,
            token_ids=self.tokenizer.encode(formatted, add_special_tokens=False), loss_mask=0, native_version=-1)
        return formatted

    async def arun_episode(self, engine, data):
        # Native v1 grouped workflow uses gather; this adapter lock makes the entire native episode serial.
        async with self._serial:
            native_engine = getattr(engine, "_engine", engine)
            if not hasattr(native_engine, "backend") or native_engine.config.request_retries != 1:
                raise ValueError("Native backend must expose the fixed one-attempt v1 generation boundary")
            if engine.get_version() != self.native_version:
                raise ValueError("Native rollout started with an unexpected policy version")
            sample = copy.deepcopy(data)
            if {"answer", "reward_spec", "ground_truth", "gold", "target", "labels"}.intersection(sample):
                raise ValueError("Private reference fields must not enter native workflow data")
            client = Client(self.bridge_socket)
            self.client, self.model_requests, self.native_completion = client, 0, None
            self.last_stop_reason = None
            self.backend = CapturedBackend(native_engine.backend, self)
            context = workflow_context.get()
            episode_seed = self.seed + (context.sample_idx or 0)
            self.gconfig = self.gconfig.new(seed=episode_seed)
            try:
                response = client.request({"kind": "episode", "bridge_id": self.bridge_id,
                    "sample_id": sample["sample_id"], "sample_sha256": sha(sample),
                    "native_revision": PINNED_REVISION, "native_policy_version": self.native_version,
                    "policy_revision": self.policy_revision, "model_ref": self.model_ref,
                    "identity": {"runtime": RUNTIME_IDENTITY, "policy": self.policy_identity,
                        "prompt_projection_ref": PROMPT_PROJECTION, "answer_codec_ref": CODEC,
                        "individual_generation_deadline_s": 180,
                        "max_physical_model_requests": self.max_model_requests,
                        "episode_wall_seconds": self.max_wall_time_s, "native_max_turns": self.max_turns,
                        "native_group_size": context.group_size, "native_sample_idx": context.sample_idx,
                        "native_task_id": context.task_id, "sampling_seed": episode_seed,
                        "serialization": "adapter asyncio.Lock; native v1 group tasks queued"},
                    "tokenizer": self.tokenizer_identity(), "max_length": self.max_length,
                    "seed": episode_seed})
                if response.get("kind") != "execute" or response["sample"] != sample or response["policy_revision"] != self.policy_revision:
                    raise ValueError("Host did not authorize the identical public native TIR input")
                native_engine.backend = self.backend
                public_data = copy.deepcopy(sample)
                public_data["messages"] = native_messages(sample)
                tensors = await asyncio.wait_for(super().arun_episode(CapturedEngine(engine, self.backend, self), public_data),
                                                 timeout=self.max_wall_time_s)
                tensors["is_truncated"] = torch.tensor([self.last_stop_reason in ("length", "abort")], dtype=torch.bool)
                encoded = encode_tensors(tensors)
                client.sequence += 1
                sealed = client.request({"kind": "native_result", "sequence": client.sequence,
                    "at": now(), "tensors": encoded, "completion": self.native_completion})
                if sealed.get("kind") != "sealed" or sealed["native_tensor_sha256"] != sha(encoded):
                    raise ValueError("Native trainer did not receive the identical sealed TIR tensor identity")
                restored = decode_tensors(sealed["native_tensors"])
                if set(restored) != set(tensors) or any(not torch.equal(restored[name], tensors[name].cpu()) for name in tensors):
                    raise ValueError("Sealed CAS tensors differ from the exact native TIR result")
                return restored
            except Exception as error:
                try:
                    client.event("native_failure", error=type(error).__name__ + ": " + str(error))
                except Exception:
                    pass
                raise
            finally:
                native_engine.backend = self.backend.wrapped
                client.close()
