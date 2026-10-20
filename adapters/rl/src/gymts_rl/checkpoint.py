"""Immutable, loadable RL checkpoint archives and their training lineage.

A single authorized ArtifactRef contains adapter/tokenizer/processor bytes and
provenance. Large base weights may remain at an explicit, hash-verified local
locator; small engineering models can be included for standalone relocation.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import zipfile

from gymts.contracts import GymTSError, canonical_json, digest
from .policy import LocalPolicy, checkpoint_identity

BUNDLE = "gymts.rl/checkpoint-bundle/1"
MANIFEST = "gymts.rl/checkpoint-manifest/1"
PROVENANCE = "gymts.rl/training-provenance/1"
MEDIA_TYPE = "application/vnd.gymts.rl-checkpoint+zip"


def _require(condition, reason, code="invalid_artifact"):
    if not condition:
        raise GymTSError(code, reason, stage="rl_checkpoint")


def adapter_state_hash(state):
    """Hash exact PEFT tensors independently of save-file metadata or RNG."""
    import torch
    checksum = hashlib.sha256()
    _require(bool(state), "Checkpoint contains no adapter tensors")
    for name, value in sorted(state.items()):
        tensor = value.detach().cpu().contiguous()
        _require(not tensor.is_floating_point() or bool(torch.isfinite(tensor).all()), "Nonfinite adapter tensor")
        checksum.update(name.encode())
        checksum.update(str(tensor.dtype).encode())
        checksum.update(str(tuple(tensor.shape)).encode())
        checksum.update(tensor.view(torch.uint8).numpy().tobytes())
    return "sha256:" + checksum.hexdigest()


def _training_provenance(gym, prepared, summary, state_hash):
    from .exporter import read_native_dataset_rows
    builds = []
    _require(summary.get("status") == "checkpointed" and type(summary.get("weights_changed")) is bool,
             "Publish only a checkpointed training attempt with a recorded update status")
    for batch in summary["rollout_batches"]:
        reference = batch.get("manifest_ref")
        _require(reference is not None and batch.get("split") == "train", "Training batch lacks a fixed train dataset")
        manifest = gym.artifacts.read_json(reference)
        rows = read_native_dataset_rows(reference, gym.artifacts)
        snapshot_ref = batch["record_snapshot_ref"]
        snapshot = gym.records.get_snapshot(snapshot_ref)
        _require(manifest["input_snapshot_refs"] == [snapshot_ref] and rows,
                 "Dataset does not describe its recorded training snapshot")
        _require(all(row["split"] == "train" and row["record_snapshot_ref"] == snapshot_ref for row in rows),
                 "Checkpoint lineage contains nontraining or substituted rows")
        _require(set(row["run_id"] for row in rows).issubset({run["run_id"] for run in snapshot["runs"]}),
                 "Training row is outside the fixed snapshot")
        builds.append({"dataset_manifest_ref": reference, "record_snapshot_ref": snapshot_ref,
                       "rollout_batch_ref": batch["batch_ref"], "run_ids": batch["run_ids"],
                       "policy_revision": batch["policy_revision"], "accepted_samples": len(rows)})
    _require(bool(builds), "Checkpoint has no training dataset lineage")
    summary_ref = summary.get("summary_ref")
    _require(summary_ref is not None, "Checkpoint requires a committed training-parent revision")
    committed = gym.artifacts.read_json(summary_ref)
    _require(committed["final_trainable_digest"] == summary["final_trainable_digest"] and
             committed["final_policy_revision"] == summary["final_policy_revision"], "Training summary identity mismatch")
    return {"schema_version": PROVENANCE, "backend": summary["backend"], "backend_versions": summary["versions"],
            "training_summary_ref": summary_ref, "source_dataset_manifest_ref": prepared["manifest_ref"],
            "builds": builds, "training_policy_revision": summary["final_policy_revision"],
            "final_trainable_digest": summary["final_trainable_digest"], "adapter_state_hash": state_hash,
            "steps_completed": summary["steps_completed"], "weights_changed": summary["weights_changed"]}


def publish_checkpoint_bundle(gym, policy, adapter_path, prepared, summary, *, include_base=False):
    """Commit exact trained weights plus portable assets and fixed lineage."""
    adapter = Path(adapter_path).resolve()
    base = Path(policy.model_path).resolve()
    base_identity = checkpoint_identity(base)
    training_base = policy.identity
    # Training checkpoints wrap the original loaded identity; deployment bundles
    # may themselves be a training input. Compare the innermost fixed base.
    for _ in range(8):
        if not isinstance(training_base, dict) or "base" not in training_base:
            break
        training_base = training_base["base"]
    _require(training_base == base_identity,
             "Base files changed since this training policy was loaded", "conflict")
    from peft import get_peft_model_state_dict
    from safetensors.torch import load_file
    from .trl_adapter import trainable_state_digest

    _require(policy.revision == summary["final_policy_revision"] and
             trainable_state_digest(policy.model)[0] == summary["final_trainable_digest"],
             "Actual trained parameters differ from the committed training summary", "conflict")
    _require((adapter / "adapter_config.json").is_file() and (adapter / "adapter_model.safetensors").is_file(),
             "A loadable safetensors PEFT adapter is required")
    disk = load_file(str(adapter / "adapter_model.safetensors"), device="cpu")
    saved_hash = adapter_state_hash(disk)
    _require(saved_hash == adapter_state_hash(get_peft_model_state_dict(policy.model)),
             "Saved adapter differs from the actual trained model", "conflict")
    provenance = _training_provenance(gym, prepared, summary, saved_hash)
    provenance_ref = gym.artifacts.save_json(provenance, PROVENANCE)
    payloads = {}

    def add(path, name):
        _require(path.is_file() and not path.is_symlink(), "Checkpoint payload must be a regular file")
        payloads[name] = path.read_bytes()

    for name in ("adapter_config.json", "adapter_model.safetensors"):
        add(adapter / name, "adapter/" + name)
    if include_base:
        _require(sum(entry["size_bytes"] for entry in base_identity["files"]) <= 128 * 1024 * 1024,
                 "Only small base models may be embedded; use a verified external base locator", "unsupported_capability")
        for entry in base_identity["files"]:
            add(base / entry["path"], "base/" + entry["path"])
    with tempfile.TemporaryDirectory(prefix="gymts-checkpoint-assets-") as temporary:
        assets = Path(temporary)
        policy.tokenizer.save_pretrained(assets)
        if policy.processor is not None:
            policy.processor.save_pretrained(assets)
        # Custom tokenizer/processor implementations stay tied to the same
        # verified source bytes. Loading them still requires explicit trust.
        for source in base.glob("*.py"):
            shutil.copy2(source, assets / source.name)
        for path in sorted(assets.iterdir()):
            if path.is_file():
                add(path, "assets/" + path.name)
    files = [{"path": name, "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content)}
             for name, content in sorted(payloads.items())]
    identity = {"family": policy.family, "base_revision": base_identity["revision"], "adapter_state_hash": saved_hash,
                "adapter_files": [entry for entry in files if entry["path"].startswith("adapter/")],
                "asset_files": [entry for entry in files if entry["path"].startswith("assets/")]}
    manifest = {"schema_version": MANIFEST, "policy_revision": digest(identity), "policy_identity": identity,
                "family": policy.family, "base": {"identity": base_identity, "source_path": str(base), "embedded": include_base},
                "adapter_state_hash": saved_hash, "training_policy_revision": policy.revision,
                "training_provenance": provenance, "training_provenance_ref": provenance_ref, "files": files}
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for name, content in [("manifest.json", canonical_json(manifest)), *sorted(payloads.items())]:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100600 << 16
            output.writestr(info, content)
    reference = gym.artifacts.save_artifact(archive.getvalue(), {"media_type": MEDIA_TYPE, "schema_ref": BUNDLE})
    return {"bundle_ref": reference, "policy_revision": manifest["policy_revision"],
            "training_provenance_ref": provenance_ref, "adapter_state_hash": saved_hash, "manifest": manifest}


def materialize_checkpoint(services, reference):
    """Verify and unpack the one explicitly authorized checkpoint artifact."""
    _require(reference.get("schema_ref") == BUNDLE and reference.get("media_type") == MEDIA_TYPE,
             "Candidate artifact is not an RL checkpoint bundle")
    temporary = tempfile.TemporaryDirectory(prefix="gymts-load-checkpoint-")
    root = Path(temporary.name)
    try:
        with zipfile.ZipFile(services.resolve(reference)) as archive:
            names = archive.namelist()
            _require(len(names) == len(set(names)) and names.count("manifest.json") == 1,
                     "Checkpoint contains duplicate or missing entries")
            manifest = json.loads(archive.read("manifest.json"))
            _require(manifest.get("schema_version") == MANIFEST, "Unsupported checkpoint manifest")
            declared = manifest["files"]
            _require(len(declared) <= 1024 and set(names) == {"manifest.json", *(entry["path"] for entry in declared)},
                     "Checkpoint payload list differs from its manifest")
            for entry in declared:
                relative = PurePosixPath(entry["path"])
                _require(not relative.is_absolute() and len(relative.parts) == 2 and relative.parts[0] in {"base", "adapter", "assets"}
                         and relative.parts[1] not in {"", ".", ".."}, "Unsafe checkpoint entry path")
                info = archive.getinfo(entry["path"])
                _require(info.file_size == entry["size_bytes"] and (info.external_attr >> 16) & 0o170000 != 0o120000,
                         "Checkpoint entry size/type mismatch")
                content = archive.read(entry["path"])
                _require(hashlib.sha256(content).hexdigest() == entry["sha256"], "Checkpoint entry hash mismatch")
                destination = root.joinpath(*relative.parts)
                destination.parent.mkdir(exist_ok=True)
                destination.write_bytes(content)
        expected = {"family": manifest["family"], "base_revision": manifest["base"]["identity"]["revision"],
                    "adapter_state_hash": manifest["adapter_state_hash"],
                    "adapter_files": [entry for entry in declared if entry["path"].startswith("adapter/")],
                    "asset_files": [entry for entry in declared if entry["path"].startswith("assets/")]}
        _require(expected == manifest["policy_identity"] and digest(expected) == manifest["policy_revision"],
                 "Checkpoint policy identity mismatch")
        provenance_bytes = canonical_json(manifest["training_provenance"])
        provenance_hash = hashlib.sha256(provenance_bytes).hexdigest()
        provenance_ref = manifest["training_provenance_ref"]
        _require(manifest["training_provenance"].get("schema_version") == PROVENANCE and
                 provenance_ref["schema_ref"] == PROVENANCE and provenance_ref["media_type"] == "application/json" and
                 provenance_ref["content_hash"] == provenance_hash and provenance_ref["revision"] == provenance_hash and
                 provenance_ref["size_bytes"] == len(provenance_bytes),
                 "Embedded training provenance differs from its fixed source reference")
        _require(manifest["training_provenance"]["adapter_state_hash"] == manifest["adapter_state_hash"] and
                 manifest["training_provenance"]["training_policy_revision"] == manifest["training_policy_revision"],
                 "Checkpoint training lineage identity mismatch")
        return root, manifest, temporary
    except BaseException:
        temporary.cleanup()
        raise


def load_checkpoint_policy(services, reference, *, device="cpu", dtype="float32", base_model_path=None,
                           trust_remote_code=False):
    """Load immutable checkpoint bytes without a resident/global policy."""
    from peft import get_peft_model_state_dict
    root, manifest, temporary = materialize_checkpoint(services, reference)
    try:
        base = root / "base" if manifest["base"]["embedded"] else Path(base_model_path or manifest["base"]["source_path"]).resolve()
        _require(checkpoint_identity(base) == manifest["base"]["identity"], "Base model differs from checkpoint identity", "conflict")
        policy = LocalPolicy.from_pretrained(base, family=manifest["family"], device=device, dtype=dtype,
            trust_remote_code=trust_remote_code, adapter_path=root / "adapter", tokenizer_path=root / "assets",
            processor_path=root / "assets")
        _require(adapter_state_hash(get_peft_model_state_dict(policy.model)) == manifest["adapter_state_hash"],
                 "Loaded adapter tensors differ from the published checkpoint", "conflict")
        policy.set_revision(manifest["policy_revision"], identity={"revision": manifest["policy_revision"],
            "base": manifest["base"]["identity"], "base_embedded": manifest["base"]["embedded"], "adapter_state_hash": manifest["adapter_state_hash"], "bundle_ref": reference})
        provenance = services.save_json(copy.deepcopy(manifest["training_provenance"]), PROVENANCE)
        _require(provenance["content_hash"] == manifest["training_provenance_ref"]["content_hash"],
                 "Relocated training provenance changed content identity", "conflict")
        return policy, provenance, temporary
    except BaseException:
        temporary.cleanup()
        raise


__all__ = ["BUNDLE", "MANIFEST", "PROVENANCE", "MEDIA_TYPE", "publish_checkpoint_bundle",
           "materialize_checkpoint", "load_checkpoint_policy", "adapter_state_hash"]
