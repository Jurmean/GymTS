"""Import genuine ChatTS-Bench profiles without crossing the model/gold boundary.

The source generator is an external, separately versioned project. This bridge
executes that project explicitly; it does not reimplement its synthetic recipe.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import tempfile
from typing import Any

from gymts.contracts import GymTSError, canonical_json
from gymts.contracts.schema import SchemaRegistry


def _classification(field, labels):
    return {"type": "object", "additionalProperties": False, "required": [field],
            "properties": {field: {"type": "string", "enum": list(labels)}}}


TASKS = {
    "pattern.trend_direction": {
        "version": "0.2.0", "metrics": ["metric.classification.accuracy"],
        "metric_ids": ["accuracy"], "main_metric": "accuracy",
        "modality_keys": ["series"], "label_field": "trend_direction",
        "labels": ["increasing", "decreasing", "stable"],
        "output_schema": _classification("trend_direction", ["increasing", "decreasing", "stable"])},
    "anomaly.point_indices": {
        "version": "0.2.0", "metrics": ["metric.anomaly.event_f1"],
        "metric_ids": ["event_f1"], "main_metric": "event_f1", "modality_keys": ["series"],
        "output_schema": {"type": "object", "additionalProperties": False, "required": ["indices"],
                          "properties": {"indices": {"type": "array", "uniqueItems": True,
                                                     "items": {"type": "integer", "minimum": 0}}}}},
    "forecast.numeric": {
        "version": "0.2.0", "metrics": ["metric.forecast.mae", "metric.forecast.rmse"],
        "metric_ids": ["mae", "rmse"], "main_metric": "mae", "modality_keys": ["series"],
        "output_schema": {"type": "object", "additionalProperties": False, "required": ["forecast"],
                          "properties": {"forecast": {"type": "array", "minItems": 1,
                                                      "items": {"type": "number"}}}}},
    "pattern.seasonality_profile": {
        "version": "0.1.0", "metrics": ["metric.classification.accuracy"],
        "metric_ids": ["accuracy"], "main_metric": "accuracy", "modality_keys": ["series"],
        "label_field": "profile", "labels": ["none", "single_period", "multiple_periods"],
        "output_schema": _classification("profile", ["none", "single_period", "multiple_periods"])},
    "process.stationarity_type": {
        "version": "0.1.0", "metrics": ["metric.classification.accuracy"],
        "metric_ids": ["accuracy"], "main_metric": "accuracy", "modality_keys": ["series"],
        "label_field": "type", "labels": ["stationary", "deterministic_trend", "unit_root", "variance_regime"],
        "output_schema": _classification("type", ["stationary", "deterministic_trend", "unit_root", "variance_regime"])},
    "relation.lagged_dependence": {
        "version": "0.1.0", "metrics": ["metric.exact_match"],
        "metric_ids": ["exact_match"], "main_metric": "exact_match",
        "modality_keys": ["series_x", "series_y"],
        "output_schema": {"type": "object", "additionalProperties": False, "required": ["direction", "lag"],
                          "properties": {"direction": {"type": "string", "enum": ["x_to_y", "y_to_x", "neither"]},
                                         "lag": {"type": "integer", "minimum": 0, "maximum": 16}}}},
    "similarity.shape_retrieval": {
        "version": "0.1.0", "metrics": ["metric.classification.accuracy"],
        "metric_ids": ["accuracy"], "main_metric": "accuracy",
        "modality_keys": ["query", "candidate_a", "candidate_b", "candidate_c", "candidate_d"],
        "label_field": "candidate_id", "labels": ["candidate_a", "candidate_b", "candidate_c", "candidate_d"],
        "output_schema": _classification("candidate_id", ["candidate_a", "candidate_b", "candidate_c", "candidate_d"])},
}

_PROFILES = {
    "native": {"module": "plugins.generators.synthetic.native_task_profile.builder",
               "config": "configs/generators/native_task_profile_v0_2.yaml",
               "schema": "chatts-bench/native-task-profile-artifact/v0.2",
               "tasks": list(TASKS)[:3]},
    "classical": {"module": "plugins.generators.synthetic.classical_concepts_profile.builder",
                  "config": "configs/generators/classical_concepts_profile_v0_1.yaml",
                  "schema": "chatts-bench/classical-concepts-profile-artifact/v0.1",
                  "tasks": list(TASKS)[3:]},
}
_HEX = re.compile(r"^[0-9a-f]{64}$")


def _error(message, **details):
    return GymTSError("invalid_dataset", message, stage="dataset_import", details=details)


def _hash(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical_json(value)).hexdigest()


def _json(data):
    def reject_duplicate(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=reject_duplicate,
                          parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except (ValueError, UnicodeError) as exc:
        raise _error("Source must be strict, finite JSON", reason=str(exc)) from exc


def _rows(data):
    result = []
    for line in data.splitlines():
        if line.strip():
            row = _json(line)
            if not isinstance(row, dict):
                raise _error("JSONL rows must be objects")
            result.append(row)
    return result


def _source_identity(source_repo):
    if source_repo is None:
        return None
    root = Path(source_repo).resolve()
    if not root.is_dir():
        raise _error("Source repository does not exist", path=str(root))
    def git(*args):
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else None
    # Both tracked edits and untracked implementations affect reproducibility.
    hashes = {}
    for prefix in ("core", "plugins", "configs"):
        for path in sorted((root / prefix).rglob("*")):
            if path.is_file() and path.suffix in {".py", ".yaml", ".yml", ".json"}:
                hashes[str(path.relative_to(root))] = _hash(path.read_bytes())
    status = git("status", "--porcelain", "--untracked-files=all")
    return {"source_repo": str(root), "git_revision": git("rev-parse", "HEAD"),
            "worktree_dirty": None if status is None else bool(status),
            "code_sha256": hashes, "code_tree_digest": _hash(hashes)}


def generate_profiles(source_repo, output_dir, python=None, profiles=("native", "classical")):
    """Run the external recipes and retain the exact source identity alongside them.

    Existing output is never overwritten. The source environment is reused, and
    Python bytecode writes are disabled so the source checkout remains untouched.
    """
    root, output = Path(source_repo).resolve(), Path(output_dir).resolve()
    names = tuple(profiles)
    if not names or len(set(names)) != len(names) or any(name not in _PROFILES for name in names):
        raise _error("profiles must contain distinct native/classical names")
    executable = Path(python) if python is not None else root / ".conda/task-system/bin/python"
    if not executable.is_file():
        raise _error("Source Python is unavailable; supply python explicitly", python=str(executable))
    if output.exists():
        raise _error("Generation output already exists", path=str(output))
    before = _source_identity(root)
    output.mkdir(parents=True)
    paths, commands = [], []
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        for name in names:
            profile = _PROFILES[name]
            target = output / name
            command = [str(executable.resolve()), "-m", profile["module"],
                       "--project-root", str(root), "--config", str(root / profile["config"]),
                       "--output", str(target)]
            result = subprocess.run(command, cwd=str(root), env=environment,
                                    capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                raise _error("ChatTS source generator failed", profile=name,
                             stdout=result.stdout[-4000:], stderr=result.stderr[-4000:])
            _checked_profile(target)
            paths.append(target)
            commands.append({"profile": name, "argv": command, "stdout": result.stdout.strip()})
        after = _source_identity(root)
        if before != after:
            raise _error("Source identity changed while generation was running")
        provenance = {"schema_version": "gymts.chatts.generation-provenance/1",
                      "source": before, "commands": commands, "profiles": list(names)}
        _write_file(output / "source_provenance.json", canonical_json(provenance) + b"\n")
        return paths
    except BaseException:
        # Leave partial generation available for diagnosis. Never call it complete.
        _write_file(output / "generation_failed.json", canonical_json({"status": "failed"}) + b"\n")
        raise


def _checked_profile(path):
    directory = Path(path).resolve()
    manifest_bytes = (directory / "manifest.json").read_bytes()
    manifest = _json(manifest_bytes)
    if not isinstance(manifest, dict):
        raise _error("Source profile manifest must be an object")
    profile = next((p for p in _PROFILES.values() if p["schema"] == manifest.get("schema")), None)
    if profile is None or manifest.get("formal_benchmark") is not False:
        raise _error("Unsupported or relabeled ChatTS profile")
    expected_tasks = {task_id: TASKS[task_id]["version"] for task_id in profile["tasks"]}
    if manifest.get("tasks") != expected_tasks:
        raise _error("Profile Task versions differ from the supported source contract")
    records = manifest.get("files")
    if not isinstance(records, dict) or not {"generation.jsonl", "instances.jsonl", "metadata.jsonl"} <= set(records):
        raise _error("Profile file manifest is incomplete")
    payloads = {}
    for name, record in records.items():
        # A source manifest cannot reach arbitrary host files through path traversal.
        if not isinstance(name, str) or Path(name).name != name or name in {".", ".."}:
            raise _error("Profile manifest paths must be local filenames")
        file_path = directory / name
        if file_path.is_symlink() or not file_path.is_file():
            raise _error("Manifest files must be regular local files", filename=name)
        payload = file_path.read_bytes()
        if not isinstance(record, dict) or record.get("sha256") != _hash(payload) or record.get("size_bytes") != len(payload):
            raise _error("Profile file hash/size mismatch", filename=name)
        payloads[name] = payload
    instances, generation, metadata = (_rows(payloads[n]) for n in ("instances.jsonl", "generation.jsonl", "metadata.jsonl"))
    if not len(instances) == len(generation) == len(metadata) == manifest.get("row_count") or not instances:
        raise _error("Profile row counts differ from its manifest")
    indexed = []
    seen = set()
    for instance, artifact, meta in zip(instances, generation, metadata):
        identity = instance.get("instance_id")
        sample_id = meta.get("sample_id")
        if not isinstance(identity, str) or not isinstance(sample_id, str) or identity.rsplit("::", 1)[0] != sample_id or artifact.get("artifact_id") != sample_id:
            raise _error("Profile row identity alignment failed")
        if identity in seen:
            raise _error("Duplicate source instance", instance_id=identity)
        seen.add(identity)
        if artifact.get("validation", {}).get("valid") is not True or meta.get("task_oracle", {}).get("passed") is not True:
            raise _error("Source task oracle did not pass", instance_id=identity)
        indexed.append((instance, artifact, meta))
    return {"directory": directory, "manifest": manifest, "manifest_bytes": manifest_bytes,
            "files": payloads, "rows": indexed}


def _model_input(instance, artifact, meta):
    task = instance.get("task", {})
    task_id = task.get("task_id")
    definition = TASKS.get(task_id)
    if definition is None or task.get("version") != definition["version"]:
        raise _error("Unknown Task or unsupported version", task=task)
    if meta.get("task_id") != task_id or meta.get("task_version") != task["version"]:
        raise _error("Instance and private metadata Task identities differ")
    parser = instance.get("evaluation", {}).get("parser", {})
    schema = parser.get("parameters", {}).get("schema")
    if parser.get("id") != "parser.structured_json" or parser.get("version") != "0.1.0" or parser.get("parameters", {}).get("mode") != "strict" or schema != definition["output_schema"]:
        raise _error("Output parser/schema differs from the fixed Task contract", task_id=task_id)
    metrics = instance.get("evaluation", {}).get("metrics")
    if not isinstance(metrics, list) or [m.get("id") for m in metrics] != definition["metrics"]:
        raise _error("Metric identities differ from the Task contract", task_id=task_id)
    for metric in metrics:
        if metric.get("version") != "0.1.0":
            raise _error("Unsupported source metric version")
        if metric["id"] == "metric.anomaly.event_f1" and metric.get("parameters", {}).get("tolerance") != 0:
            raise _error("Source event F1 tolerance must be zero")
    expected_metrics = []
    field = definition.get("label_field", "forecast" if task_id == "forecast.numeric" else "indices")
    for index, metric_id in enumerate(definition["metrics"]):
        parameters = {} if metric_id == "metric.exact_match" else {"prediction_path": "/" + field, "expected_path": "/" + field}
        if metric_id == "metric.anomaly.event_f1":
            parameters["tolerance"] = 0
        expected_metrics.append({"id": metric_id, "version": "0.1.0", "parameters": parameters,
                                 "role": "primary" if index == 0 else "secondary", "aggregation": "point"})
    if metrics != expected_metrics:
        raise _error("Source metric parameters/roles differ from the fixed Task contract")
    validator = SchemaRegistry()
    validator.register("chatts.answer/1", schema)
    validator.validate("chatts.answer/1", instance.get("expected_output"))
    modalities = instance.get("input", {}).get("modalities", {})
    if not isinstance(modalities, dict) or set(modalities) != set(definition["modality_keys"]):
        raise _error("Source modalities differ from the Task input contract")
    source_series = artifact.get("series", [])
    if not isinstance(source_series, list) or len(source_series) != len(modalities):
        raise _error("Source generation/input series count mismatch")
    by_id = {series.get("series_id"): series for series in source_series}
    if len(by_id) != len(source_series):
        raise _error("Duplicate source series IDs")
    values, names = [], []
    for modality_id, modality in modalities.items():
        if not isinstance(modality, dict) or set(modality) != {"type", "content"} or modality["type"] != "timeseries":
            raise _error("Only native timeseries modalities are supported")
        content = modality["content"]
        if not isinstance(content, list) or len(content) < 8 or any(type(v) not in (int, float) or not math.isfinite(v) for v in content):
            raise _error("Timeseries must contain finite numeric observations")
        series = by_id.get("series_0" if modality_id == "series" else modality_id)
        if series is None or series.get("values") != content:
            raise _error("Input values differ from the preserved generation artifact")
        name = series.get("name")
        if not isinstance(name, str) or not name or re.search(r"[\u3400-\u9fff]", name):
            raise _error("Source series names must be nonempty English text")
        names.append(name)
        values.append([float(value) for value in content])
    messages = instance.get("instruction", {}).get("messages")
    if not isinstance(messages, list) or not messages or messages[-1].get("role") != "user":
        raise _error("Source chat messages must end with a user message")
    for message in messages:
        if not isinstance(message, dict) or set(message) != {"role", "content"} or message["role"] not in {"system", "user", "assistant"} or not isinstance(message["content"], str) or not message["content"].strip() or re.search(r"[\u3400-\u9fff]", message["content"]):
            raise _error("Source model-visible messages violate the English chat contract")
    # These seven frozen source tasks currently expose no arbitrary context. A
    # future context requires a new whitelist instead of copying private fields.
    source_context = instance.get("context", {})
    if not isinstance(source_context, dict) or set(source_context) - {"horizon"} or (source_context and task_id != "forecast.numeric"):
        raise _error("Unsupported public context keys")
    context = copy.deepcopy(source_context)
    expected = instance["expected_output"]
    if task_id == "forecast.numeric":
        horizons = set(int(n) for message in messages for n in re.findall(r"Forecast the next (\d+) values", message["content"]))
        if len(horizons) != 1:
            raise _error("Forecast horizon must be explicitly stated in the public prompt")
        horizon = horizons.pop()
        if horizon < 1 or len(expected["forecast"]) != horizon or ("horizon" in context and context["horizon"] != horizon):
            raise _error("Public forecast horizon and private target shape disagree")
        context["horizon"] = horizon
        if artifact.get("ground_truth", {}).get("future", {}).get("series_0") != expected["forecast"]:
            raise _error("Forecast gold differs from source holdout")
    elif task_id == "anomaly.point_indices":
        indices = expected["indices"]
        if indices != sorted(indices) or any(i >= len(values[0]) for i in indices):
            raise _error("Event gold must contain ordered, in-bounds indices")
        if artifact.get("ground_truth", {}).get("series", {}).get("series_0", {}).get("spike_indices") != indices:
            raise _error("Event gold differs from source generation")
    elif task_id == "pattern.trend_direction":
        if artifact.get("ground_truth", {}).get("series", {}).get("series_0", {}).get("trend_direction") != expected["trend_direction"]:
            raise _error("Trend gold differs from source generation")
    elif artifact.get("ground_truth", {}).get("answer") != expected:
        raise _error("Classical gold differs from source generation")
    model_input = {"messages": copy.deepcopy(messages), "timeseries": values, "series_names": names,
                   "output_schema": copy.deepcopy(schema), "context": context}
    # Reuse the same semantic contract as live Candidate outputs so source gold
    # cannot bypass shape/index/lag rules accepted by the runnable Task.
    from .task import parse_answer
    _, reason = parse_answer(canonical_json(expected).decode("utf-8"), schema, task_id, model_input)
    if reason:
        raise _error("Source gold violates Task answer semantics", task_id=task_id, reason=reason)
    return model_input


def import_profiles(gym, profile_dirs, source_repo=None):
    """Publish a public snapshot and distinct private gold/provenance artifacts."""
    paths = list(profile_dirs)
    if not paths:
        raise _error("At least one source profile is required")
    profiles = [_checked_profile(path) for path in paths]
    profiles.sort(key=lambda p: (p["manifest"]["profile_id"], _hash(p["manifest_bytes"])))
    revisions = [{"manifest_sha256": _hash(p["manifest_bytes"]), "files": p["manifest"]["files"]} for p in profiles]
    revision = _hash({"schema_version": "gymts.chatts.import/1", "profiles": revisions})
    public, private, identities = [], [], set()
    current_source = _source_identity(source_repo)
    profile_records = []
    for profile in profiles:
        manifest = profile["manifest"]
        sidecar = profile["directory"].parent / "source_provenance.json"
        generated_source = _json(sidecar.read_bytes()) if sidecar.is_file() else None
        manifest_hash = _hash(profile["manifest_bytes"])
        profile_record = {"manifest_sha256": manifest_hash, "source_manifest": manifest,
                          "source_directory": str(profile["directory"]),
                          "generation_provenance": generated_source,
                          "import_checkout_identity": current_source}
        profile_records.append(profile_record)
        for instance, artifact, meta in profile["rows"]:
            identity = instance["instance_id"]
            if identity in identities:
                raise _error("Duplicate instance across profiles", instance_id=identity)
            identities.add(identity)
            model_input = _model_input(instance, artifact, meta)
            token = _hash({"dataset_revision": revision, "source_instance_id": identity})
            bundle_id = meta.get("bundle_id")
            if not isinstance(bundle_id, str) or not bundle_id:
                raise _error("Source bundle identity is required for leakage-safe splits")
            bundle_token = _hash({"profile_id": manifest["profile_id"], "bundle_id": bundle_id})
            task = instance["task"]
            public.append({"sample_token": token, "task_id": task["task_id"],
                           "task_version": task["version"], "model_input": model_input})
            private.append({"sample_token": token, "bundle_token": bundle_token,
                            "alignment_key": {"dataset_revision": revision, "sample_token": token},
                            "task_id": task["task_id"], "task_version": task["version"],
                            "expected_output": copy.deepcopy(instance["expected_output"]),
                            "parser": copy.deepcopy(instance["evaluation"]["parser"]),
                            "metrics": copy.deepcopy(instance["evaluation"]["metrics"]),
                            "provenance": {"profile_manifest_sha256": manifest_hash,
                                           "source_instance_id": identity, "source_metadata": meta,
                                           "generation_artifact_sha256": _hash(artifact),
                                           "instance_sha256": _hash(instance),
                                           "answer_source": "synthetic_gold"}})
    # Validate all rows before publishing any dataset artifact.
    raw_refs = []
    for profile in profiles:
        refs = {name: gym.artifacts.save_artifact(payload, {"media_type": "application/x-ndjson",
                "schema_ref": "gymts.chatts.source-jsonl/1"}) for name, payload in profile["files"].items()}
        raw_refs.append({"manifest_sha256": _hash(profile["manifest_bytes"]), "files": refs})
    snapshot = {"schema_version": "gymts.chatts.snapshot/1", "dataset_revision": revision, "samples": public}
    snapshot_ref = gym.artifacts.save_json(snapshot, "gymts.chatts.snapshot/1")
    private_ref = gym.artifacts.save_json({"schema_version": "gymts.chatts.private/1",
        "dataset_revision": revision, "samples": private, "raw_source_refs": raw_refs}, "gymts.chatts.private/1")
    manifest_ref = gym.artifacts.save_json({"schema_version": "gymts.chatts.import-manifest/1",
        "dataset_revision": revision, "sample_count": len(public), "profiles": profile_records,
        "snapshot_ref": snapshot_ref, "private_ref": private_ref}, "gymts.chatts.import-manifest/1")
    return {"dataset_revision": revision, "snapshot_ref": snapshot_ref, "samples": private,
            "private_ref": private_ref, "manifest_ref": manifest_ref}


def _write_file(path, content):
    with Path(path).open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def export_sft(gym, imported, output_dir, eval_fraction=0.2, seed=7):
    """Export native multimodal gold-supervised JSONL with bundle-disjoint splits.

    This is an SFT source dataset, not policy-rollout data or a completed training
    run. Answers are explicitly marked synthetic_gold and stay out of the prompt.
    """
    if type(eval_fraction) not in (int, float) or not math.isfinite(eval_fraction) or not 0 <= eval_fraction < 1 or type(seed) is not int:
        raise _error("eval_fraction must be finite in [0,1); seed must be integer")
    output = Path(output_dir).resolve()
    if output.exists():
        raise _error("SFT export output already exists", path=str(output))
    snapshot = gym.artifacts.read_json(imported["snapshot_ref"])
    private = gym.artifacts.read_json(imported["private_ref"])
    if snapshot.get("dataset_revision") != imported["dataset_revision"] or private.get("dataset_revision") != imported["dataset_revision"]:
        raise _error("SFT sources have different dataset revisions")
    gold = {row["sample_token"]: row for row in private["samples"]}
    if len(gold) != len(private["samples"]) or set(gold) != {r["sample_token"] for r in snapshot["samples"]}:
        raise _error("SFT public and private sample identities differ")
    task_bundles = {}
    for row in private["samples"]:
        task_bundles.setdefault(row["task_id"], set()).add(row["bundle_token"])
    # Stratify at Task level, then split complete bundles; ordering is deterministic.
    evaluation_bundles = set()
    for task_id, bundle_set in sorted(task_bundles.items()):
        bundles = sorted(bundle_set)
        random.Random(_hash({"seed": seed, "task_id": task_id})).shuffle(bundles)
        count = min(len(bundles) - 1, max(1, round(len(bundles) * eval_fraction))) if eval_fraction and len(bundles) > 1 else 0
        evaluation_bundles.update(bundles[:count])
    rows = {"train": [], "eval": []}
    for sample in snapshot["samples"]:
        truth = gold[sample["sample_token"]]
        split = "eval" if truth["bundle_token"] in evaluation_bundles else "train"
        model_input = copy.deepcopy(sample["model_input"])
        rows[split].append({"schema_version": "gymts.chatts.sft-sample/1",
            "sample_id": sample["sample_token"], "task_id": sample["task_id"],
            "dataset_revision": imported["dataset_revision"], "bundle_token": truth["bundle_token"],
            "model_input": model_input, "answer": copy.deepcopy(truth["expected_output"]),
            "answer_source": "synthetic_gold", "lineage": {"alignment_key": truth["alignment_key"],
                "source_instance_sha256": truth["provenance"]["instance_sha256"],
                "source_snapshot_ref": imported["snapshot_ref"], "source_private_ref": imported["private_ref"]}})
    bundles = {split: {r["bundle_token"] for r in records} for split, records in rows.items()}
    if bundles["train"] & bundles["eval"]:
        raise _error("Bundle split contamination")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="." + output.name + "-", dir=str(output.parent)))
    try:
        files = {}
        for split, records in rows.items():
            payload = b"".join(canonical_json(row) + b"\n" for row in records)
            name = split + ".jsonl"
            _write_file(staging / name, payload)
            files[name] = {"sha256": _hash(payload), "size_bytes": len(payload), "row_count": len(records)}
        manifest = {"schema_version": "gymts.chatts.sft-manifest/1", "dataset_revision": imported["dataset_revision"],
            "answer_source": "synthetic_gold", "status": "supervised_source_export", "seed": seed,
            "eval_fraction": eval_fraction, "counts": {k: len(v) for k, v in rows.items()},
            "bundle_counts": {k: len(v) for k, v in bundles.items()}, "bundle_disjoint": True,
            "files": files, "source_manifest_ref": imported["manifest_ref"],
            "splits": {split: {"sample_tokens": [r["sample_id"] for r in records],
                               "bundle_tokens": sorted(bundles[split])}
                       for split, records in rows.items()}}
        _write_file(staging / "manifest.json", canonical_json(manifest) + b"\n")
        if output.exists():
            raise _error("SFT output appeared during export")
        os.rename(staging, output)
        manifest_ref = gym.artifacts.save_json(manifest, "gymts.chatts.sft-manifest/1")
        return dict(manifest, output_dir=str(output), manifest_ref=manifest_ref,
                    manifest_path=str(output / "manifest.json"),
                    train_sample_tokens=manifest["splits"]["train"]["sample_tokens"],
                    eval_sample_tokens=manifest["splits"]["eval"]["sample_tokens"])
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


__all__ = ["TASKS", "generate_profiles", "import_profiles", "export_sft"]
