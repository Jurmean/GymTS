"""Publish native AReaL lineage into the reusable RL deployment archive format."""
import hashlib
import io
import json
from pathlib import Path
import zipfile
from collections import Counter

from gymts.contracts import canonical_json, digest
from gymts_rl.checkpoint import BUNDLE, MANIFEST, PROVENANCE, MEDIA_TYPE, adapter_state_hash
from .identity import model_identity


def archive_bytes(payloads):
    """Deterministic original/deployment bytes without touching native files."""
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(payloads.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type, info.external_attr = zipfile.ZIP_DEFLATED, 0o100600 << 16
            archive.writestr(info, content)
    return stream.getvalue()


def deployment_projection(state):
    """Exactly promote exported low-precision values; never reconstruct masters."""
    import torch
    projected, audit = {}, []
    for name, source in sorted(state.items()):
        source = source.detach().cpu().contiguous()
        if source.is_floating_point() and not bool(torch.isfinite(source).all()):
            raise ValueError("Native checkpoint contains nonfinite adapter tensors")
        target = source.float() if source.dtype in (torch.bfloat16, torch.float16) else source.clone()
        round_trip = bool(torch.equal(target.to(source.dtype), source))
        exact_promotion = bool(torch.equal(target, source.float())) if source.dtype in (torch.bfloat16, torch.float16) else bool(torch.equal(target, source))
        if source.shape != target.shape or not round_trip or not exact_promotion:
            raise ValueError("Deployment adapter projection changed native exported tensor values")
        projected[name] = target
        audit.append({"name": name, "shape": list(source.shape), "native_dtype": str(source.dtype),
            "deployment_dtype": str(target.dtype), "round_trip_exact": round_trip,
            "exact_exported_value_promotion": exact_promotion,
            "native_tensor_hash": adapter_state_hash({name: source}),
            "deployment_tensor_hash": adapter_state_hash({name: target})})
    return projected, audit


TOKENIZER_PROJECTION = "areal.hf5-special-token-list-to-hf4/1"


def tokenizer_metadata_projection(payloads, target):
    """Explicit metadata-only HF compatibility; token bytes/IDs stay untouched."""
    if target not in ("native", "hf4"):
        raise ValueError("Choose native or hf4 tokenizer compatibility explicitly")
    result = dict(payloads)
    name = "assets/tokenizer_config.json"
    source = result[name]
    audit = {"version": TOKENIZER_PROJECTION, "target": target, "applied": False,
        "source_config_sha256": hashlib.sha256(source).hexdigest(),
        "untouched_asset_sha256": {key: hashlib.sha256(value).hexdigest() for key, value in sorted(payloads.items())
            if key.startswith("assets/") and key != name}}
    if target == "hf4":
        original = json.loads(source)
        extra = original.get("extra_special_tokens", {})
        if isinstance(extra, list):
            if any(not isinstance(token, str) for token in extra) or len(set(extra)) != len(extra):
                raise ValueError("HF5 special-token list must contain unique token strings")
            if original.get("additional_special_tokens", extra) != extra:
                raise ValueError("Conflicting special-token lists cannot be projected implicitly")
            converted = dict(original, extra_special_tokens={}, additional_special_tokens=list(extra))
            if {key: value for key, value in converted.items() if key not in ("extra_special_tokens", "additional_special_tokens")} != {
                    key: value for key, value in original.items() if key not in ("extra_special_tokens", "additional_special_tokens")}:
                raise AssertionError("Tokenizer projection modified unrelated configuration")
            result[name] = canonical_json(converted)
            audit.update(applied=True, rule="Move the complete ordered HF5 extra_special_tokens list to HF4 additional_special_tokens; use an empty named-token map",
                ordered_special_tokens=list(extra), special_token_count=len(extra),
                other_config_fields_unchanged=True, token_assets_unchanged=True,
                semantics="Declared metadata compatibility projection; runtime vocab/ID/template/encoding equality requires independent CPU validation")
        elif not isinstance(extra, dict):
            raise ValueError("Unsupported extra_special_tokens representation")
    audit["deployment_config_sha256"] = hashlib.sha256(result[name]).hexdigest()
    return result, audit


def publish_native_checkpoint(gym, prepared, native, bridge, base_path, *, tokenizer_compatibility="native"):
    from safetensors.torch import load_file
    adapter = Path(native["checkpoint"]).resolve(strict=True)
    state = load_file(str(adapter / "adapter_model.safetensors"), device="cpu")
    native_saved_hash = adapter_state_hash(state)
    if model_identity(adapter) != native["checkpoint_identity"]:
        raise ValueError("Native final checkpoint files changed after original training saved them")
    events = bridge["training_events"]
    saves = [row for row in events if row["event"]["kind"] == "native_hf_save" and
             Path(row["event"]["path"]).resolve() == adapter]
    updates = [row for row in events if row["event"]["kind"] == "native_optimizer_step"]
    advantages = [row for row in events if row["event"]["kind"] == "native_advantages"]
    consumes = [row for row in events if row["event"]["kind"] == "consume_batch"]
    episodes = [row for row in bridge["episodes"] if row["split"] == "train"]
    if (not saves or any(row["event"]["adapter_state_hash"] != native_saved_hash for row in saves) or not updates or
            any(row["event"]["changed_parameters"] <= 0 or row["event"]["delta_l2"] <= 0 for row in updates) or
            not advantages or any(not row["event"]["finite"] or not row["event"]["nonzero"] for row in advantages) or
            not consumes or not episodes or any(row["status"] != "succeeded" or not row["manifest_ref"] for row in episodes)):
        raise ValueError("Native checkpoint lacks verified sealed-rollout, advantage, gradient/update or saved-tensor evidence")
    initial_saves = [row["event"] for row in events if row["event"]["kind"] == "native_hf_save" and
        Path(row["event"]["path"]).name == "initial_lora"]
    if (len(initial_saves) != 1 or initial_saves[0]["adapter_state_hash"] == native_saved_hash or
            not all(row["event"]["exact_native_cast_tensor_match"] for row in saves)):
        raise ValueError("Native exported HF tensors must differ between the verified initial and final saves")
    expected = Counter(row["native_tensor_sha256"] for row in episodes)
    consumed = Counter(item for row in consumes for item in row["event"]["row_hashes"])
    if consumed != expected:
        raise ValueError("Native optimizer consumption does not cover the identical sealed training batch")
    native_tools = 0
    for entry in episodes:
        run = gym.records.get_run(entry["run_id"])
        for event in run["events"]:
            if event["kind"] == "tool_call":
                from gymts.plugin_support import unpack
                call = unpack(event["payload"], gym.artifacts)
                native_tools += call["status"] == "succeeded"
    if not native_tools:
        raise ValueError("Original TIR completed without a successful native calculator decision; multi-turn tool acceptance is not met")
    base_identity = model_identity(base_path)
    versions = bridge["policy_versions"]
    if (len(versions) != 1 or versions[0]["native_policy_version"] != 0 or
            versions[0]["policy_revision"] != native["initial_policy_revision"] or
            versions[0]["identity"]["base"] != base_identity or
            versions[0]["identity"]["initial_lora"] != native["initial_lora_identity"]):
        raise ValueError("Deployment base or initial rollout policy differs from the sealed native version map")
    original_payloads = {}
    for path in sorted(adapter.iterdir()):
        if path.is_symlink():
            raise ValueError("Native checkpoint assets must be regular files")
        if path.is_file():
            original_payloads[path.name] = path.read_bytes()
    original_bytes = archive_bytes(original_payloads)
    original_ref = gym.artifacts.save_artifact(original_bytes, {"media_type": "application/zip"})
    projected, tensor_audit = deployment_projection(state)
    saved_hash = adapter_state_hash(projected)
    from safetensors.torch import save
    payloads = {"adapter/adapter_config.json": original_payloads["adapter_config.json"],
        "adapter/adapter_model.safetensors": save(projected, metadata={"format": "pt"})}
    for name, content in original_payloads.items():
        if name not in ("adapter_config.json", "adapter_model.safetensors") and Path(name).suffix in (".json", ".jinja", ".model", ".txt"):
            payloads["assets/" + name] = content
    if "assets/tokenizer_config.json" not in payloads:
        raise ValueError("Native checkpoint lacks loadable tokenizer assets")
    payloads, tokenizer_audit = tokenizer_metadata_projection(payloads, tokenizer_compatibility)
    tokenizer_audit["source_checkpoint_ref"] = original_ref
    tokenizer_projection_ref = gym.artifacts.save_json(tokenizer_audit, "gymts.json/1")
    final_identity = {"phase": "after_native_optimizer_and_original_hf_save", "base": base_identity,
        "native_checkpoint_identity": native["checkpoint_identity"], "native_saved_adapter_state_hash": native_saved_hash,
        "native_revision": native["runtime"]["native_revision"], "observed_native_version": native["native_final_version"]}
    final_revision = digest(final_identity)
    projection = {"version": "areal.exported-low-precision-to-fp32/1", "source_checkpoint_ref": original_ref,
        "source_archive_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "native_checkpoint_identity": native["checkpoint_identity"], "native_saved_adapter_state_hash": native_saved_hash,
        "initial_native_saved_adapter_state_hash": initial_saves[0]["adapter_state_hash"],
        "deployment_adapter_state_hash": saved_hash, "tensors": tensor_audit,
        "semantics": "Exact FP32 promotion of original exported BF16/FP16 values; not optimizer master recovery or bitwise logits equivalence"}
    projection_ref = gym.artifacts.save_json(projection, "gymts.json/1")
    provenance = {"schema_version": PROVENANCE, "backend": "areal.native_PPOTrainer", "native_revision": native["runtime"]["native_revision"],
        "source_dataset_manifest_ref": prepared["manifest_ref"], "builds": [{key: row[key] for key in
            ("run_id", "snapshot_ref", "manifest_ref", "sample_id", "native_tensor_sha256")} for row in episodes],
        "training_policy_revision": final_revision, "adapter_state_hash": saved_hash,
        "rollout_policy_revision": native["initial_policy_revision"], "rollout_native_version": 0,
        "native_final_version": native["native_final_version"], "final_training_identity": final_identity,
        "training_events": events, "initial_lora_identity": native["initial_lora_identity"],
        "steps_completed": len(updates), "weights_changed": True, "successful_native_tool_calls": native_tools,
        "trained_checkpoint_identity": native["checkpoint_identity"], "native_saved_adapter_state_hash": native_saved_hash,
        "native_checkpoint_ref": original_ref, "deployment_projection_ref": projection_ref,
        "tokenizer_projection_ref": tokenizer_projection_ref,
        "native_result_ref": gym.artifacts.save_json(native, "gymts.json/1")}
    provenance_ref = gym.artifacts.save_json(provenance, PROVENANCE)
    files = [{"path": name, "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content)} for name, content in sorted(payloads.items())]
    identity = {"family": "text", "base_revision": base_identity["revision"], "adapter_state_hash": saved_hash,
        "adapter_files": [row for row in files if row["path"].startswith("adapter/")],
        "asset_files": [row for row in files if row["path"].startswith("assets/")]}
    manifest = {"schema_version": MANIFEST, "policy_revision": digest(identity), "policy_identity": identity,
        "family": "text", "base": {"identity": base_identity, "source_path": str(Path(base_path).resolve()), "embedded": False},
        "adapter_state_hash": saved_hash, "training_policy_revision": final_revision,
        "training_provenance": provenance, "training_provenance_ref": provenance_ref, "files": files}
    reference = gym.artifacts.save_artifact(archive_bytes({"manifest.json": canonical_json(manifest), **payloads}),
        {"media_type": MEDIA_TYPE, "schema_ref": BUNDLE})
    return {"bundle_ref": reference, "policy_revision": manifest["policy_revision"],
            "training_provenance_ref": provenance_ref, "adapter_state_hash": saved_hash,
            "training_policy_revision": final_revision, "rollout_policy_revision": native["initial_policy_revision"],
            "native_checkpoint_ref": original_ref, "deployment_projection_ref": projection_ref,
            "tokenizer_projection_ref": tokenizer_projection_ref}
