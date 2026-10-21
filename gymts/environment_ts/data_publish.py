"""Publish fixed training exports as durable, codec-neutral source datasets."""
import copy
import json
from pathlib import Path

from gymts.contracts import canonical_json
from gymts.contracts.resources import DATASET, DATASET_V2, DATA_SOURCE, POLICY
from gymts.contracts.schema import SchemaRegistry, register_core_schemas
from gymts.storage.resources import content_revision, resource_error
from gymts.training.builder import register_training_schemas
from .data_capture import PortablePayloads
from .data_sources import intersect_policies


TRAINING = {"allowed_uses": ["training", "prepare", "dataset_build"], "training_allowed": True}


def publish_build(catalog, build, *, reader_ref, dataset_id=None, config="default",
                  usage_policy=None, parents=(), aliases=()):
    """Persist an existing ``gymts.dataset/1`` export without executing its builder.

    Shard bytes and their external reader/schema are preserved. Source files
    contain private portable build/Run evidence and an original-to-portable
    artifact index; they are not public dataset inputs. Publication can narrow
    source permissions, but never adds runtime/evaluation uses to training data.
    """
    if catalog.artifacts is None or catalog.records is None:
        raise resource_error("Build publication needs records and artifact services", "unsupported_capability")
    if not isinstance(build, dict):
        raise resource_error("Build publication expects a manifest or ArtifactRef", "schema_mismatch")
    schemas = SchemaRegistry()
    register_core_schemas(schemas)
    register_training_schemas(schemas)
    reference = build if "artifact_id" in build else build.get("manifest_ref")
    manifest = catalog.artifacts.read_json(reference) if reference is not None else copy.deepcopy(build)
    if reference is not None and reference["schema_ref"] != "gymts.dataset/1":
        raise resource_error("Expected a gymts.dataset/1 build manifest", "schema_mismatch")
    if "protocol_version" in build:
        supplied = {key: value for key, value in build.items() if key != "manifest_ref"}
        if supplied != manifest:
            raise resource_error("Build manifest differs from its published artifact", "conflict")
    schemas.validate("gymts.dataset/1", manifest)
    spec = catalog.artifacts.read_json(manifest["build_spec_ref"])
    schemas.validate("gymts.dataset-build/1", spec)
    if (spec["build_id"] != manifest["build_id"] or spec["builder_ref"] != manifest["builder_ref"]
            or spec["input_snapshots"] != manifest["input_snapshot_refs"]
            or spec["target"]["schema_ref"] != manifest["output_schema_ref"]):
        raise resource_error("Build manifest differs from its fixed DatasetBuildSpec", "conflict")
    if sum(shard["sample_count"] for shard in manifest["shards"]) != manifest["counts"]["accepted_samples"]:
        raise resource_error("Build shard counts differ from accepted_samples")

    policies, sources, parent_refs, runs, snapshots = [TRAINING], [], [], [], []
    seen_sources, seen_runs = set(), set()
    source_assets, source_documents = [], []

    def retain_assets(value):
        if isinstance(value, list):
            for child in value:
                retain_assets(child)
        elif isinstance(value, dict):
            if set(value) == {"uri", "sha256", "size_bytes", "media_type"}:
                if value not in source_assets:
                    content = catalog.store.read_asset(value)
                    source_assets.append(value)
                    if value["media_type"] == "application/json" or value["media_type"].endswith("+json"):
                        source_documents.append({"asset_ref": value, "value": json.loads(content)})
            else:
                for child in value.values():
                    retain_assets(child)

    def inherit(item):
        protocol = item.get("protocol_version")
        if protocol not in (DATASET, DATASET_V2, DATA_SOURCE):
            return
        schemas.validate(protocol, item)
        if item["revision"] != content_revision(item):
            raise resource_error("Source evidence has a conflicting content revision", "artifact_integrity")
        identity = (protocol, item.get("dataset_id", item.get("source_id")), item["config"], item["revision"])
        if identity in seen_sources:
            return
        seen_sources.add(identity)
        sources.append(item)
        retain_assets(item)
        policies.append(item["usage_policy"])
        if protocol in (DATASET, DATASET_V2):
            for split in item["splits"]:
                ref = {"dataset_id": item["dataset_id"], "config": item["config"], "revision": item["revision"], "split": split}
                if ref not in parent_refs:
                    parent_refs.append(ref)
        if protocol == DATASET_V2:
            origin = item["origin"]["source_ref"]
            inherit(catalog.load_source(origin["source_id"], revision=origin["revision"], config=origin["config"]))
        references = item.get("parent_datasets", item.get("lineage", {}).get("parents", []))
        if protocol == DATASET and "dataset_build" in item["features"]:
            references = item["features"].get("parent_datasets", [])
        for ref in references:
            inherit(catalog.load_manifest(ref["dataset_id"], revision=ref["revision"], config=ref["config"]))

    fixed_parents, parent_manifests = catalog._parents(parents)
    for item in parent_manifests:
        inherit(item)
    # These are declared dataset ancestors. Exact consumed rows/Run boundaries
    # remain in the original build selection and frozen evidence.
    for parent in fixed_parents:
        if parent not in parent_refs:
            parent_refs.append(parent)
    for snapshot_ref in manifest["input_snapshot_refs"]:
        snapshot = catalog.records.get_snapshot(snapshot_ref)
        schemas.validate("gymts.record-snapshot/1", {key: value for key, value in snapshot.items() if key != "snapshot_ref"})
        snapshots.append({"snapshot_ref": snapshot_ref,
            "outcomes": catalog.records.read_outcomes({"snapshot_ref": snapshot_ref})})
        for frozen in snapshot["runs"]:
            if spec["require_sealed_runs"] and frozen["status"] == "running":
                raise resource_error("Build publication requires the selected sealed Run snapshot", "invalid_state")
            identity = (frozen["run_id"], frozen["through_seq"])
            if identity in seen_runs:
                continue
            seen_runs.add(identity)
            run = catalog.records.get_run(frozen["run_id"])
            metadata = run["metadata"]
            if metadata.get("usage_policy_ref") is not None:
                policy = catalog.artifacts.read_json(metadata["usage_policy_ref"])
                schemas.validate(POLICY, policy)
                policies.append(policy)
            for ref in metadata.get("source_refs", []):
                inherit(catalog.artifacts.read_json(ref))
            events = [event for event in run["events"] if event["seq"] <= frozen["through_seq"]]
            event_refs = [ref for event, ref in zip(run["events"], run["event_refs"]) if event["seq"] <= frozen["through_seq"]]
            runs.append({"run_id": run["run_id"], "snapshot_entry": frozen, "metadata": metadata,
                "events": events, "event_refs": event_refs, "result_ref": frozen["result_ref"],
                "execution_snapshot_ref": run["execution_snapshot_ref"] if frozen["result_ref"] is not None else None})
    if usage_policy is not None:
        schemas.validate(POLICY, usage_policy)
        policies.append(usage_policy)
    policy = intersect_policies(policies)
    if not policy["training_allowed"]:
        raise resource_error("Source policy forbids publishing a training build", "permission_denied")

    portable = PortablePayloads(catalog)
    evidence = portable.copy({"manifest": manifest, "snapshots": snapshots,
        "runs": runs, "sources": sources, "source_asset_documents": source_documents,
        "parent_datasets": parent_refs, "usage_policy": policy})
    # Preserve original evidence bytes as well as traversable JSON projections.
    # The index lets a codec resolve references embedded in unchanged opaque
    # shards; the core does not rewrite a trainer's row or tensor format.
    artifact_index, originals = [], {}
    for encoded, wrapped in sorted(portable.references.items()):
        ref = json.loads(encoded)
        asset = wrapped["dataset_asset_ref"]
        if asset["sha256"] != ref["content_hash"]:
            asset = catalog.publish_asset(Path(catalog.artifacts.resolve(ref)).read_bytes(), media_type=ref["media_type"])
        originals[encoded] = asset
        artifact_index.append({"source_artifact": ref, "original_asset": asset,
            "portable_asset": wrapped["dataset_asset_ref"]})
    evidence["artifact_index"] = artifact_index
    proof = catalog.publish_asset(canonical_json(evidence), media_type="application/json")
    original = catalog.publish_asset(canonical_json(manifest) if reference is None else
        Path(catalog.artifacts.resolve(reference)).read_bytes(), media_type="application/json")
    source_files = [{"name": "build-manifest.json", "asset_ref": original},
                    {"name": "build-provenance.json", "asset_ref": proof}]
    assets = []
    for asset in portable.attachments + list(originals.values()) + source_assets:
        if asset not in assets:
            assets.append(asset)
            source_files.append({"name": "evidence/" + asset["sha256"], "asset_ref": asset})
    inputs, splits = [], {}
    for shard in manifest["shards"]:
        ref = shard["artifact_ref"]
        inputs.append(originals[canonical_json(ref)])
        selected = splits.setdefault(shard["split"], {"row_count": 0, "split_origin": "fixed-dataset-build",
            "input_indices": [], "target_indices": []})
        selected["row_count"] += shard["sample_count"]
        selected["input_indices"].append(len(inputs) - 1)
    if not splits:
        splits["train"] = {"row_count": 0, "split_origin": "fixed-dataset-build", "input_indices": [], "target_indices": []}
    item = {"protocol_version": DATASET, "dataset_id": dataset_id or manifest["dataset_id"],
        "config": config, "revision": None, "schema_ref": manifest["output_schema_ref"],
        "reader_ref": copy.deepcopy(reader_ref), "features": {"dataset_build": {
            key: copy.deepcopy(manifest[key]) for key in ("dataset_id", "revision", "build_id", "builder_ref", "counts")},
            "parent_datasets": parent_refs, "training_format": spec["target"]["format"]},
        "splits": splits, "usage_policy": policy, "source_files": source_files,
        "importer_ref": copy.deepcopy(manifest["builder_ref"]), "inputs": inputs, "series": [], "targets": [],
        "quality_report_ref": None, "card_ref": None}
    return catalog.register_dataset(item, aliases=aliases)
