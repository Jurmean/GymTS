"""Decode ChatTS-Bench source facts without constructing a model or TaskInput.

The profile's original task identity remains a benchmark compatibility fact.
Gold is preserved in a distinct private artifact and validated by the Scorer,
not by importing Task interpretation into the source reader.
"""
import copy
import math
import re

from gymts_timeseries.contracts import SNAPSHOT, validate_sample, validate_snapshot

from .data import _checked_profile, _error, _hash, _json, _source_identity

PROMPT_POLICY = {
    "policy_ref": "gymts.chatts/canonical-task-question/1",
    "question_source": "gymts_timeseries.task.make_task_input",
    "original_source_messages_used": False,
    "source_messages_preserved_in_raw_artifacts": True,
    "equivalent_to_original_benchmark_prompt": False,
}


def _sample(instance, artifact, meta, token):
    task = instance.get("task", {})
    if (not isinstance(task.get("task_id"), str) or not isinstance(task.get("version"), str)
            or meta.get("task_id") != task["task_id"] or meta.get("task_version") != task["version"]):
        raise _error("Source task identities disagree")
    modalities = instance.get("input", {}).get("modalities", {})
    generated = artifact.get("series", [])
    if not isinstance(modalities, dict) or not modalities or len(modalities) != len(generated):
        raise _error("Source modalities and generated series differ")
    by_id = {item.get("series_id"): item for item in generated}
    if len(by_id) != len(generated):
        raise _error("Generated source contains duplicate series identities")
    series = []
    for name, modality in modalities.items():
        if not isinstance(modality, dict) or set(modality) != {"type", "content"} or modality["type"] != "timeseries":
            raise _error("Only numerical time-series source modalities are supported")
        values = modality["content"]
        if (not isinstance(values, list) or not values or
                any(type(value) not in (int, float) or not math.isfinite(value) for value in values)):
            raise _error("Source observations must be nonempty and finite")
        original = by_id.get("series_0" if name == "series" else name)
        if original is None or original.get("values") != values:
            raise _error("Public observations differ from their source generation artifact")
        series.append({"name": original.get("name"), "values": copy.deepcopy(values)})
    context = copy.deepcopy(instance.get("context", {}))
    if not isinstance(context, dict) or set(context) - {"horizon"}:
        raise _error("Unreviewed source context cannot be exposed publicly")
    # Decode a public request parameter from the source format. No gold length,
    # answer or generator metadata is used to infer this visible horizon.
    if "horizon" not in context:
        messages = instance.get("instruction", {}).get("messages", [])
        horizons = {int(number) for message in messages for number in
                    re.findall(r"Forecast the next (\d+) values", message.get("content", ""))}
        if len(horizons) == 1:
            context["horizon"] = horizons.pop()
    return validate_sample({"sample_token": token, "series": series, "context": context,
        "annotations": {"benchmark_task_id": task["task_id"], "benchmark_task_version": task["version"]}})


def import_profiles(gym, profile_dirs, source_repo=None):
    profiles = [_checked_profile(path) for path in profile_dirs]
    if not profiles:
        raise _error("At least one source profile is required")
    profiles.sort(key=lambda item: (item["manifest"]["profile_id"], _hash(item["manifest_bytes"])))
    revisions = [{"manifest_sha256": _hash(item["manifest_bytes"]), "files": item["manifest"]["files"]} for item in profiles]
    revision = _hash({"schema_version": "gymts.chatts.numeric-import/1", "profiles": revisions})
    public, private, seen, records = [], [], set(), []
    current_source = _source_identity(source_repo)
    for profile in profiles:
        manifest = profile["manifest"]
        manifest_hash = _hash(profile["manifest_bytes"])
        sidecar = profile["directory"].parent / "source_provenance.json"
        records.append({"manifest_sha256": manifest_hash, "source_manifest": manifest,
            "source_directory": str(profile["directory"]), "import_checkout_identity": current_source,
            "generation_provenance": _json(sidecar.read_bytes()) if sidecar.is_file() else None})
        for instance, artifact, meta in profile["rows"]:
            identity = instance["instance_id"]
            if identity in seen:
                raise _error("Duplicate source instance across profiles")
            seen.add(identity)
            token = _hash({"dataset_revision": revision, "source_instance_id": identity})
            public.append(_sample(instance, artifact, meta, token))
            bundle = meta.get("bundle_id")
            if not isinstance(bundle, str) or not bundle:
                raise _error("Source bundle identity is required for explicit split grouping")
            private.append({"sample_token": token,
                "bundle_token": _hash({"profile_id": manifest["profile_id"], "bundle_id": bundle}),
                "alignment_key": {"dataset_revision": revision, "sample_token": token},
                "task_id": instance["task"]["task_id"], "task_version": instance["task"]["version"],
                "expected_output": copy.deepcopy(instance.get("expected_output")),
                "parser": copy.deepcopy(instance.get("evaluation", {}).get("parser")),
                "metrics": copy.deepcopy(instance.get("evaluation", {}).get("metrics")),
                "provenance": {"profile_manifest_sha256": manifest_hash, "source_instance_id": identity,
                    "source_metadata": meta, "generation_artifact_sha256": _hash(artifact),
                    "instance_sha256": _hash(instance), "answer_source": "synthetic_gold"}})
    snapshot = validate_snapshot({"schema_version": SNAPSHOT, "dataset_revision": revision, "samples": public})
    raw_refs = []
    for profile in profiles:
        refs = {name: gym.artifacts.save_artifact(raw, {"media_type": "application/x-ndjson",
            "schema_ref": "gymts.chatts.source-jsonl/1"}) for name, raw in profile["files"].items()}
        raw_refs.append({"manifest_sha256": _hash(profile["manifest_bytes"]), "files": refs})
    snapshot_ref = gym.artifacts.save_json(snapshot, SNAPSHOT)
    private_ref = gym.artifacts.save_json({"schema_version": "gymts.chatts.numeric-private/1",
        "dataset_revision": revision, "samples": private, "raw_source_refs": raw_refs}, "gymts.chatts.numeric-private/1")
    manifest_ref = gym.artifacts.save_json({"schema_version": "gymts.chatts.numeric-import-manifest/1",
        "dataset_revision": revision, "sample_count": len(public), "profiles": records,
        "snapshot_ref": snapshot_ref, "private_ref": private_ref,
        "prompt_policy": copy.deepcopy(PROMPT_POLICY)}, "gymts.chatts.numeric-import-manifest/1")
    return {"dataset_revision": revision, "snapshot_ref": snapshot_ref, "samples": private,
            "private_ref": private_ref, "manifest_ref": manifest_ref, "prompt_policy": copy.deepcopy(PROMPT_POLICY)}
