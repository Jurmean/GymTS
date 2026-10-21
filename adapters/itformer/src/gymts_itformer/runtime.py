"""Lazy native runtime. No source, model or CUDA access during discovery/plan."""
import contextlib
import importlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

from .contracts import UPSTREAM_SHA
from .data import file_identity

PREFIXES = ("ts_encoder.", "itformer.", "ts_project.", "query_project.", "fusion_project.")


def safetensor_headers(directory):
    directory = Path(directory)
    index_path = directory / "model.safetensors.index.json"
    expected = json.loads(index_path.read_text())["weight_map"] if index_path.exists() else None
    files = sorted(directory.glob("model*.safetensors"))
    if not files:
        raise ValueError("Safetensors model weights are required; pickle fallback is disabled")
    headers, locations = {}, {}
    for path in files:
        with path.open("rb") as stream:
            length_bytes = stream.read(8)
            if len(length_bytes) != 8:
                raise ValueError("Incomplete safetensors header")
            length = struct.unpack("<Q", length_bytes)[0]
            if length > 32 * 1024 * 1024:
                raise ValueError("Invalid safetensors header length")
            values = json.loads(stream.read(length))
        for key, value in values.items():
            if key == "__metadata__":
                continue
            if key in headers:
                raise ValueError("Duplicate tensor key across checkpoint shards")
            if value["data_offsets"][1] + 8 + length > path.stat().st_size:
                raise ValueError("Incomplete safetensors payload")
            headers[key], locations[key] = value, path.name
    if expected is not None and expected != locations:
        raise ValueError("Checkpoint index and actual tensor shards differ")
    return headers, files


def validate_source(directory):
    root = Path(directory).resolve()
    sha = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if sha != UPSTREAM_SHA:
        raise ValueError("ITFormer native source differs from the supported frozen commit")
    subprocess.run(["git", "-C", str(root), "diff", "--exit-code", "HEAD", "--"], check=True, capture_output=True)
    tracked = subprocess.check_output(["git", "-C", str(root), "ls-files", "*.py"], text=True).splitlines()
    actual = {str(p.relative_to(root)) for p in root.rglob("*.py") if ".git" not in p.parts}
    if actual != set(tracked):
        raise ValueError("Native checkout contains missing or untracked Python source")
    return {"commit": sha, "files": [file_identity(root / p) | {"path": p} for p in tracked]}


def preflight(source, checkpoint, base_model, *, hash_weights=True):
    # The fixed TLM loader prefers this filename over safetensors. Reject it
    # before loading so an unrecorded pickle cannot override hashed shards.
    if (Path(checkpoint) / "pytorch_model.bin").exists():
        raise ValueError("pytorch_model.bin would override native safetensors; pickle fallback is disabled")
    native = validate_source(source)
    headers, files = safetensor_headers(checkpoint)
    base_headers, base_files = safetensor_headers(base_model)
    counts = {prefix: sum(k.startswith(prefix) for k in headers) for prefix in PREFIXES}
    if any(count == 0 for count in counts.values()):
        raise ValueError("Checkpoint is missing encoder, ITFormer or projector weights")
    if not any(k.startswith("model.layers.") for k in base_headers) or "model.embed_tokens.weight" not in base_headers:
        raise ValueError("Complete native base causal-LM checkpoint is required")
    def identity(root, tensor_files):
        paths = tensor_files + [Path(root) / "config.json"]
        for name in ("tokenizer.json", "tokenizer_config.json", "generation_config.json", "vocab.json", "merges.txt"):
            if (Path(root) / name).exists():
                paths.append(Path(root) / name)
        return [file_identity(p) if hash_weights or p.suffix != ".safetensors"
                else {"name": p.name, "bytes": p.stat().st_size, "sha256": None} for p in paths]
    config = json.loads((Path(checkpoint) / "config.json").read_text())
    base_config = json.loads((Path(base_model) / "config.json").read_text())
    if config.get("ts_pad_num") != 25 or base_config.get("model_type") != "qwen2":
        raise ValueError("Unsupported native prefix/base architecture")
    return {"native_source": native, "checkpoint_files": identity(checkpoint, files),
        "base_model_files": identity(base_model, base_files), "non_llm_prefix_counts": counts,
        "checkpoint_tensor_count": len(headers), "base_tensor_count": len(base_headers),
        "checkpoint_llm_weights": "intentionally ignored by the fixed upstream loader",
        "base_model_loading": "external local Qwen; all native loading keys checked",
        "weight_hashing": "sha256" if hash_weights else "headers-only-not-a-model-identity"}


@contextlib.contextmanager
def source_imports(source):
    root = str(Path(source).resolve())
    for name in ("models", "dataset", "utils"):
        module = sys.modules.get(name)
        if module is not None and not str(getattr(module, "__file__", "")).startswith(root + "/"):
            raise RuntimeError("Native top-level module collision: " + name)
    sys.path.insert(0, root)
    try:
        yield
    finally:
        sys.path.remove(root)


def load_native(params):
    """Use native TLM loading, adding strict checks instead of accepting warnings."""
    import torch
    from transformers import AutoModelForCausalLM
    source = params["source_path"]
    provenance = preflight(source, params["checkpoint_path"], params["base_model_path"])
    with source_imports(source):
        native = importlib.import_module("models.TimeLanguageModel")
        dataset = importlib.import_module("dataset.dataset")
    config = native.TLMConfig(llm_model_path=str(Path(params["base_model_path"]).resolve()),
        freeze_ts_model=True, ts_pad_num=25, prefix_num=25, d_model=512, n_heads=8,
        e_layers=4, patch_len=60, stride=60, input_len=600, dropout=0.1,
        it_d_model=896, it_n_heads=16, it_layers=2, it_dropout=0.1)
    original_base = AutoModelForCausalLM.from_pretrained
    original_load = native.TLM.load_state_dict
    checks = {}
    def strict_base(*args, **kwargs):
        if Path(args[0]).resolve() != Path(params["base_model_path"]).resolve():
            raise ValueError("Native loader attempted an undeclared base model")
        model, info = original_base(*args, **kwargs, local_files_only=True,
            output_loading_info=True, torch_dtype=torch.float32, attn_implementation="eager")
        if any(info.get(key) for key in ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs")):
            raise ValueError("Base model loading is incomplete: " + json.dumps(info))
        checks["base_loading_info"] = info
        return model
    def strict_non_llm(model, state, strict=False, **kwargs):
        result = original_load(model, state, strict=strict, **kwargs)
        missing = [k for k in result.missing_keys if not k.startswith("llm_model.")]
        if missing or result.unexpected_keys:
            raise ValueError("Incomplete native non-LLM weights: " + str((missing, result.unexpected_keys)))
        actual = model.state_dict()
        for key, value in state.items():
            if not torch.equal(actual[key].cpu(), value.cpu()):
                raise ValueError("Native loaded tensor differs from checkpoint: " + key)
        checks["non_llm_verified_keys"] = len(state)
        return result
    AutoModelForCausalLM.from_pretrained = strict_base
    native.TLM.load_state_dict = strict_non_llm
    try:
        model = native.TLM.from_pretrained(params["checkpoint_path"], config=config, ts_config=config)
    finally:
        AutoModelForCausalLM.from_pretrained = original_base
        native.TLM.load_state_dict = original_load
    if not checks.get("non_llm_verified_keys") or "base_loading_info" not in checks:
        raise ValueError("Native loader did not verify both base and multimodal weights")
    if "<|image_pad|>" not in model.tokenizer.get_vocab():
        raise ValueError("Existing native placeholder token is required; random embedding extension is disabled")
    model._setup_inference_mode()
    model.to(params["device"])
    provenance["loading_checks"] = checks
    provenance["inference_dtype"] = str(next(model.parameters()).dtype)
    return model, dataset, config, provenance


def preprocess_public(sample, model, dataset_module, config):
    """Run strict native Dataset/Collator with no actual answer available.

    The source already applied native string/list HDF5 selection. A temporary
    one-row HDF5 preserves that exact selected tensor; the native dummy answer
    is empty, and labels/reference never leave this function.
    """
    import h5py
    import numpy as np
    with tempfile.TemporaryDirectory(prefix="gymts-itformer-public-") as tmp:
        root = Path(tmp)
        ts = np.asarray(sample["signal"], dtype=np.float32)
        if list(ts.shape) != sample["signal_shape"] or ts.ndim != 2 or ts.shape[1] != 33 or not np.isfinite(ts).all():
            raise ValueError("Invalid public signal tensor; no fallback allowed")
        with h5py.File(root / "signal.h5", "w") as stream:
            stream.create_dataset("seq_data", data=ts[None, ...])
        public_qa = {"id": "1", "conversations": [
            {"stage": str(sample["stage"]), "attribute": sample["form"], "value": sample["question"]},
            {"value": ""}]}
        (root / "public.jsonl").write_text(json.dumps(public_qa) + "\n", encoding="utf-8")
        tokenizer = model.tokenizer
        # Reject native tokenization/chat-template fallback by checking exact
        # expected tokens and placeholder count against direct tokenization.
        expected_chat = tokenizer.apply_chat_template([
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": sample["question"]}], tokenize=False, add_generation_prompt=True)
        expected_chat = expected_chat.replace("<ts>", "<|image_pad|>" * config.ts_pad_num)
        expected_ids = tokenizer(expected_chat, add_special_tokens=False)["input_ids"]
        expected_query = tokenizer(sample["question"], add_special_tokens=False)["input_ids"]
        data = dataset_module.TsQaDataset(str(root / "signal.h5"), str(root / "public.jsonl"),
            tokenizer, tokenizer, config, strict_preprocessing=True)
        feature = data[0]
        if feature["input_ids"] != expected_ids or feature["query_ids"] != expected_query:
            raise ValueError("Native preprocessing silently replaced or repaired input tokens")
        placeholder_id = tokenizer("<|image_pad|>", add_special_tokens=False)["input_ids"]
        if len(placeholder_id) != 1 or expected_ids.count(placeholder_id[0]) != 25:
            raise ValueError("Expected exactly 25 native time-series placeholder tokens")
        batch = dataset_module.DataCollator(tokenizer)([feature])
        if data.h5_file is not None:
            data.h5_file.close(); data.h5_file = None
        allowed = {"input_ids", "query_ids", "ts_values", "stage", "attention_mask"}
        result = {key: batch[key] for key in allowed}
        if not np.array_equal(result["ts_values"][0].numpy(), ts):
            raise ValueError("Native preprocessed signal differs from public tensor")
        return result
