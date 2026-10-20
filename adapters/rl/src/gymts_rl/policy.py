"""A resident local Hugging Face policy and exact native-token likelihoods.

Scientific dependencies are deliberately imported inside methods. Importing or
registering the integration therefore does not import torch or transformers.
"""
import copy
import hashlib
import json
import math
from pathlib import Path
import struct

from gymts.contracts import GymTSError, digest


_ACTIVE_POLICY = None


def configure_active_policy(policy):
    """Bind the policy shared by GymTS Runs and the caller's TRL trainer."""
    global _ACTIVE_POLICY
    previous, _ACTIVE_POLICY = _ACTIVE_POLICY, policy
    return previous


def active_policy():
    if _ACTIVE_POLICY is None:
        raise GymTSError("invalid_config", "Load and configure a resident LocalPolicy before running the local RL Candidate")
    return _ACTIVE_POLICY


def _component(name, version="1.0.0"):
    return {"name": name, "version": version, "origin_ref": None}


def validate_safetensors(path):
    """Check a shard's declared byte layout before allocating a model on GPU."""
    path = Path(path)
    try:
        size = path.stat().st_size
        with path.open("rb") as stream:
            prefix = stream.read(8)
            if len(prefix) != 8:
                raise ValueError("missing eight-byte header length")
            length = struct.unpack("<Q", prefix)[0]
            if not 2 <= length <= min(100_000_000, size - 8):
                raise ValueError("header length is outside the complete file")
            header = json.loads(stream.read(length))
        if not isinstance(header, dict):
            raise ValueError("header must be an object")
        offsets = []
        widths = {"F64": 8, "F32": 4, "F16": 2, "BF16": 2, "I64": 8, "I32": 4,
                  "I16": 2, "I8": 1, "U64": 8, "U32": 4, "U16": 2, "U8": 1,
                  "BOOL": 1, "F8_E4M3": 1, "F8_E5M2": 1, "F8_E4M3FN": 1}
        for name, tensor in header.items():
            if name == "__metadata__":
                continue
            start, end = tensor["data_offsets"]
            shape = tensor["shape"]
            if (type(start) is not int or type(end) is not int or start < 0 or end < start
                    or not isinstance(shape, list) or any(type(v) is not int or v < 0 for v in shape)):
                raise ValueError("invalid tensor shape or byte offsets")
            width = widths.get(tensor["dtype"])
            if width is not None and math.prod(shape) * width != end - start:
                raise ValueError("tensor shape/dtype does not match its byte span")
            offsets.append((start, end))
        cursor = 0
        for start, end in sorted(offsets):
            if start != cursor:
                raise ValueError("tensor byte spans contain a gap or overlap")
            cursor = end
        expected = 8 + length + cursor
        if size != expected:
            raise GymTSError("invalid_config", "Local safetensors shard is incomplete or has unexpected trailing bytes",
                details={"path": str(path), "size_bytes": size, "expected_size_bytes": expected,
                         "missing_bytes": max(0, expected - size)})
        return {"path": path.name, "size_bytes": size, "tensor_count": len(offsets)}
    except GymTSError:
        raise
    except (OSError, ValueError, KeyError, TypeError, struct.error) as error:
        raise GymTSError("invalid_config", "Local safetensors shard has an invalid header or tensor layout",
                         details={"path": str(path), "reason": str(error)}) from error


def checkpoint_identity(model_path):
    """Hash the exact local checkpoint and custom code, without modifying it."""
    root = Path(model_path).expanduser().resolve()
    if not root.is_dir():
        raise GymTSError("invalid_config", "Local model directory does not exist")
    for index in root.glob("*.index.json"):
        values = set(json.loads(index.read_text())["weight_map"].values())
        if any(not (root / value).is_file() for value in values):
            raise GymTSError("invalid_config", "Local checkpoint is missing a declared weight shard")
    for shard in root.glob("*.safetensors"):
        validate_safetensors(shard)
    files = []
    for path in sorted(root.iterdir()):
        if path.is_file() and (path.suffix in {".json", ".jinja", ".py", ".model", ".safetensors", ".bin"}
                               or path.name in {"tokenizer.model", "merges.txt", "vocab.txt"}):
            before = path.stat()
            checksum = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(16 * 1024 * 1024), b""):
                    checksum.update(block)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise GymTSError("conflict", "Local checkpoint changed while hashing")
            files.append({"path": path.name, "sha256": checksum.hexdigest(), "size_bytes": after.st_size})
    if not any(item["path"].endswith((".safetensors", ".bin")) for item in files):
        raise GymTSError("invalid_config", "Local model directory has no checkpoint weights")
    return {"revision": digest(files), "files": files}


def completion_logprobs(model, prompt_ids, completion_ids, model_inputs=None):
    """Differentiable log p(response | prompt), including ChatTS patch expansion.

    This deliberately receives the exact generated IDs rather than re-tokenizing
    a decoded answer. Batch size one avoids hidden padding/EOS assumptions; a
    trainer may concatenate these differentiable rows for its padded minibatch.
    """
    import torch

    device = next(model.parameters()).device
    prompt = torch.as_tensor(prompt_ids, dtype=torch.long, device=device).reshape(1, -1)
    completion = torch.as_tensor(completion_ids, dtype=torch.long, device=device).reshape(1, -1)
    if not prompt.numel() or not completion.numel():
        raise GymTSError("invalid_request", "Likelihood computation requires nonempty exact prompt and completion tokens")
    ids = torch.cat((prompt, completion), dim=1)
    extra = {}
    for key, value in (model_inputs or {}).items():
        if key in {"input_ids", "attention_mask", "position_ids", "token_type_ids"}:
            continue
        if hasattr(value, "to"):
            extra[key] = value.to(device)
        elif isinstance(value, dict) and "values" in value and "dtype" in value:
            dtype = getattr(torch, value["dtype"].removeprefix("torch."))
            extra[key] = torch.tensor(value["values"], dtype=dtype, device=device)
        else:
            extra[key] = value
    output = model(input_ids=ids, attention_mask=torch.ones_like(ids),
                   use_cache=False, return_dict=True, **extra)
    positions = getattr(output, "new_token_positions", None)
    if positions is None:
        indices = torch.arange(prompt.shape[1] - 1, ids.shape[1] - 1, device=device)
    else:
        indices = positions[0, prompt.shape[1]:] - 1
        if indices.numel() != completion.shape[1] or bool((indices < 0).any()):
            raise GymTSError("schema_mismatch", "ChatTS completion positions could not be aligned with the expanded forward sequence")
    logits = output.logits[0, indices].float()
    return (logits.gather(-1, completion[0, :, None]).squeeze(-1)
            - torch.logsumexp(logits, dim=-1)).unsqueeze(0)


def load_native_inputs(artifacts, native_inputs_ref):
    """Restore the exact captured CPU tensors; never recreate a TS from text."""
    import numpy as np
    import torch

    manifest = artifacts.read_json(native_inputs_ref)
    if manifest.get("format") != "npy" or not isinstance(manifest.get("tensors"), dict):
        raise GymTSError("schema_mismatch", "Native policy inputs require the captured tensor manifest")
    result = {}
    for name, entry in manifest["tensors"].items():
        path = artifacts.resolve(entry["artifact_ref"])
        array = np.load(path, allow_pickle=False)
        tensor = torch.from_numpy(array.copy())
        if entry["dtype"] == "bfloat16":
            if tensor.dtype != torch.uint16:
                raise GymTSError("schema_mismatch", "bfloat16 tensor storage must preserve its uint16 bits")
            tensor = tensor.view(torch.bfloat16)
        if list(tensor.shape) != entry["shape"] or str(tensor.dtype).removeprefix("torch.") != entry["dtype"]:
            raise GymTSError("schema_mismatch", "Captured tensor shape or dtype differs from its bytes")
        result[name] = tensor
    return result


class LocalPolicy:
    """One resident model, usable by both native GymTS rollout and TRL training."""

    completion_logprobs = staticmethod(completion_logprobs)

    def __init__(self, model, tokenizer, processor=None, *, model_path=None,
                 revision=None, family="text", identity=None):
        if family not in {"text", "chatts"}:
            raise GymTSError("invalid_config", "LocalPolicy family must be text or chatts")
        if family == "chatts" and processor is None:
            raise GymTSError("invalid_config", "ChatTS policy requires its native processor")
        self.model, self.tokenizer, self.processor = model, tokenizer, processor
        self.family, self.model_path = family, str(model_path) if model_path else None
        self.identity = copy.deepcopy(identity or {})
        self.revision = revision or self.identity.get("revision")
        if not isinstance(self.revision, str) or not self.revision:
            raise GymTSError("invalid_config", "LocalPolicy requires an actual fixed policy revision")
        self.model_ref = _component("local-hf-" + family)
        self.adapter_ref = _component("gymts-rl-hf-native")

    @classmethod
    def from_pretrained(cls, model_path, *, family="text", device="cuda:0",
                        dtype="bfloat16", trust_remote_code=False,
                        adapter_path=None, tokenizer_path=None, processor_path=None, **kwargs):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        if family == "chatts" and not trust_remote_code:
            raise GymTSError("invalid_config", "Native ChatTS requires explicitly trusted local model code")
        identity = checkpoint_identity(model_path)
        tokenizer = AutoTokenizer.from_pretrained(tokenizer_path or model_path, local_files_only=True,
                                                  trust_remote_code=trust_remote_code)
        processor = None
        if family == "chatts":
            from transformers import AutoProcessor
            processor = AutoProcessor.from_pretrained(processor_path or model_path, local_files_only=True,
                                                       trust_remote_code=True)
        torch_dtype = getattr(torch, dtype)
        model = AutoModelForCausalLM.from_pretrained(model_path, local_files_only=True,
            trust_remote_code=trust_remote_code, torch_dtype=torch_dtype,
            device_map={"": device}, attn_implementation="sdpa", **kwargs)
        if adapter_path:
            from peft import PeftModel
            adapter_identity = checkpoint_identity(adapter_path)
            model = PeftModel.from_pretrained(model, adapter_path, is_trainable=False)
            identity = {"base": identity, "adapter": adapter_identity,
                        "revision": digest({"base": identity["revision"], "adapter": adapter_identity["revision"]})}
        model.eval()
        policy = cls(model, tokenizer, processor, model_path=model_path, family=family, identity=identity)
        policy.tokenizer_path = str(tokenizer_path or model_path)
        policy.processor_path = str(processor_path or model_path)
        return policy

    def set_revision(self, revision, *, identity=None):
        """Advance identity only after the owning trainer fixes new model state."""
        if not isinstance(revision, str) or not revision:
            raise GymTSError("invalid_config", "Policy revision must be a nonempty fixed identifier")
        self.revision = revision
        if identity is not None:
            self.identity = copy.deepcopy(identity)

    def tokenizer_manifest(self):
        return {"class": type(self.tokenizer).__name__,
                "name_or_path": str(getattr(self.tokenizer, "name_or_path", self.model_path)),
                "vocab_size": len(self.tokenizer), "special_tokens_map": self.tokenizer.special_tokens_map,
                "init_kwargs": {key: (str(value) if key.endswith("_token") and value is not None else value)
                                for key, value in getattr(self.tokenizer, "init_kwargs", {}).items()
                                if key in {"bos_token", "eos_token", "pad_token", "unk_token", "clean_up_tokenization_spaces"}},
                "checkpoint_identity": self.identity}

    def _inputs(self, sample, enable_thinking):
        import numpy as np

        messages = copy.deepcopy(sample["messages"])
        timeseries = sample.get("timeseries", [])
        if self.family == "text" and timeseries:
            count = sum(message["content"].count("<ts><ts/>") for message in messages)
            if count != len(timeseries):
                raise GymTSError("schema_mismatch", "Text time-series placeholder count differs from the attached arrays")
            arrays = iter(timeseries)
            for message in messages:
                parts = message["content"].split("<ts><ts/>")
                rendered = parts[0]
                for tail in parts[1:]:
                    rendered += json.dumps(next(arrays), allow_nan=False, separators=(",", ":")) + tail
                message["content"] = rendered
        prompt = self.tokenizer.apply_chat_template(messages, tokenize=False,
            add_generation_prompt=True, enable_thinking=enable_thinking)
        if self.family == "chatts":
            count = prompt.count("<ts><ts/>")
            if count != len(timeseries):
                raise GymTSError("schema_mismatch", "ChatTS prompt placeholder count differs from attached time-series count")
            encoded = self.processor(text=[prompt], timeseries=[np.asarray(ts, dtype=np.float64) for ts in timeseries],
                                     return_tensors="pt", padding=False)
        else:
            encoded = self.tokenizer([prompt], return_tensors="pt", padding=False,
                                     add_special_tokens=False)
        parameter = next(self.model.parameters())
        return prompt, {key: value.to(device=parameter.device,
                                      dtype=parameter.dtype if value.is_floating_point() else value.dtype)
                        for key, value in encoded.items()}

    def generate(self, public_sample, seed, generation_params=None):
        import torch

        params = {"max_new_tokens": 256, "temperature": 1.0, "top_p": 1.0,
                  "top_k": 0, "do_sample": True, "enable_thinking": False,
                  **(generation_params or {})}
        if set(params) - {"max_new_tokens", "temperature", "top_p", "top_k", "do_sample", "enable_thinking"}:
            raise GymTSError("invalid_config", "Unsupported local generation parameter")
        if type(params["max_new_tokens"]) is not int or params["max_new_tokens"] < 1:
            raise GymTSError("invalid_config", "max_new_tokens must be a positive integer")
        if (not math.isfinite(params["temperature"]) or params["temperature"] <= 0
                or not 0 < params["top_p"] <= 1 or type(params["top_k"]) is not int or params["top_k"] < 0):
            raise GymTSError("invalid_config", "Sampling temperature/top_p/top_k are invalid")
        if type(seed) is not int or seed < 0:
            raise GymTSError("invalid_config", "Generation seed must be a nonnegative integer")
        if type(params["do_sample"]) is not bool or type(params["enable_thinking"]) is not bool:
            raise GymTSError("invalid_config", "do_sample and enable_thinking must be booleans")
        prompt, model_inputs = self._inputs(public_sample, params["enable_thinking"])
        was_training = self.model.training
        self.model.eval()
        inputs = {key: value.detach().cpu().contiguous() for key, value in model_inputs.items()}
        effective = {key: value for key, value in params.items() if key != "enable_thinking"}
        effective.update(use_cache=True, num_beams=1, num_return_sequences=1,
                         repetition_penalty=1.0, min_new_tokens=0)
        eos_id = getattr(self.model.generation_config, "eos_token_id", None)
        pad_id = self.tokenizer.pad_token_id
        if pad_id is None:
            pad_id = self.tokenizer.eos_token_id
        if pad_id is None:
            raise GymTSError("invalid_config", "Local policy requires an explicit padding or EOS token ID")
        effective.update(pad_token_id=pad_id, eos_token_id=eos_id)
        from transformers import GenerationConfig

        generation = dict(effective)
        if not params["do_sample"]:
            for key in ("temperature", "top_p", "top_k"):
                generation.pop(key)
        config = GenerationConfig(**self.model.generation_config.to_dict())
        for key, value in generation.items():
            setattr(config, key, value)
        if not params["do_sample"]:
            config.temperature, config.top_p, config.top_k = 1.0, 1.0, 0
        effective["resolved_generation_config"] = config.to_dict()
        devices = [next(self.model.parameters()).device] if next(self.model.parameters()).is_cuda else []
        try:
            with torch.random.fork_rng(devices=devices), torch.inference_mode():
                torch.random.default_generator.manual_seed(seed)
                if devices:
                    with torch.cuda.device(devices[0]):
                        torch.cuda.manual_seed(seed)
                result = self.model.generate(**model_inputs, generation_config=config, **generation,
                    use_model_defaults=False,
                    return_dict_in_generate=True, output_scores=True, output_logits=True)
            prompt_ids = model_inputs["input_ids"][0].tolist()
            completion = result.sequences[0, len(prompt_ids):].tolist()
            if not completion or len(result.scores) != len(completion) or len(result.logits) != len(completion):
                raise GymTSError("candidate_failure", "Native generation returned inconsistent token evidence")
            raw, sampling = [], []
            for index, token in enumerate(completion):
                logits = result.logits[index][0].float()
                raw.append(float(logits[token] - torch.logsumexp(logits, dim=-1)))
                if params["do_sample"]:
                    processed = result.scores[index][0].float()
                    sampling.append(float(processed[token] - torch.logsumexp(processed, dim=-1)))
                else:
                    sampling.append(0.0)
            if not all(math.isfinite(value) and value <= 1e-6 for value in raw + sampling):
                raise GymTSError("candidate_failure", "Native generation returned invalid log probabilities")
            eos = eos_id if isinstance(eos_id, list) else [eos_id]
            return {"prompt_ids": prompt_ids, "completion_ids": completion,
                    "raw_model_logprobs": raw, "sampling_logprobs": sampling,
                    "tensor_bundle": inputs, "response": self.tokenizer.decode(completion, skip_special_tokens=True),
                    "rendered_prompt": prompt, "effective_params": {**effective, "seed": seed,
                        "use_model_defaults": False,
                        "enable_thinking": params["enable_thinking"],
                        "timeseries_encoding": "native_processor" if self.family == "chatts" else "full_precision_json_in_prompt",
                        "floating_input_dtype": str(next(self.model.parameters()).dtype).removeprefix("torch."),
                        "model_sampling_logprobs_max_abs_difference": (
                            max(abs(left - right) for left, right in zip(raw, sampling))
                            if params["do_sample"] else None),
                        "sampling_distribution": "temperature_top_k_top_p" if params["do_sample"] else "greedy_point_mass"},
                    "policy_revision": self.revision,
                    "finish_reason": ("eos" if completion[-1] in eos else
                                      "length" if len(completion) >= params["max_new_tokens"] else "stopping_criteria")}
        finally:
            self.model.train(was_training)


__all__ = ["LocalPolicy", "active_policy", "configure_active_policy", "checkpoint_identity", "completion_logprobs", "load_native_inputs", "validate_safetensors"]
