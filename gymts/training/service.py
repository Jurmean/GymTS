"""Public, project-independent dispatch for fixed-evidence dataset builders.

Builders are trusted external providers. Discovery reads metadata; only the
provider selected by the fixed ComponentRef is loaded when building a dataset.
"""
from __future__ import annotations

import copy
from importlib.metadata import entry_points
from typing import Protocol, Sequence

from gymts.contracts import GymTSError, canonical_json
from gymts.contracts.schema import SchemaRegistry, register_core_schemas
from .builder import register_training_schemas


def _error(message, code="invalid_dataset"):
    return GymTSError(code, message, stage="dataset_build")


def _fixed_ref(reference):
    schemas = SchemaRegistry()
    register_core_schemas(schemas)
    schemas.validate("gymts.component/1", reference)
    if reference["version"] in {"latest", "main", "master"}:
        raise _error("Training components require a fixed version", "invalid_config")
    return canonical_json(reference)


class DatasetBuilderProvider(Protocol):
    """Structural exporter contract; implementations need no framework base."""
    builder_ref: dict
    target_formats: Sequence[str]
    output_schema_refs: Sequence[str]

    def build(self, spec: dict, records, artifacts) -> dict: ...


class DatasetBuilderRegistry:
    """Register provider instances without importing any project implementation.

    Providers declare ``builder_ref``, ``target_formats``, ``output_schema_refs``
    and ``build(spec, records, artifacts)``. These Python declarations do not
    add fields to the formal DatasetBuildSpec or DatasetManifest protocols.
    """

    def __init__(self, *, discover=True):
        self._providers = {}
        self.discover = discover

    def register(self, builder_ref: dict, provider: DatasetBuilderProvider):
        key = _fixed_ref(builder_ref)
        if getattr(provider, "builder_ref", None) != builder_ref or not callable(getattr(provider, "build", None)):
            raise _error("Builder provider declaration differs from its registration", "invalid_config")
        for attribute in ("target_formats", "output_schema_refs"):
            values = getattr(provider, attribute, None)
            if not isinstance(values, (tuple, list)) or not values or any(not isinstance(item, str) or not item for item in values):
                raise _error("Builder must declare " + attribute, "invalid_config")
        if key in self._providers and self._providers[key] is not provider:
            raise _error("Dataset builder is already registered", "conflict")
        self._providers[key] = provider

    def resolve(self, builder_ref):
        key = _fixed_ref(builder_ref)
        if key in self._providers:
            return self._providers[key]
        if not self.discover:
            raise _error("No provider for the selected dataset builder", "unsupported_capability")
        discovered = entry_points()
        entries = (discovered.select(group="gymts.dataset_builders") if hasattr(discovered, "select")
                   else discovered.get("gymts.dataset_builders", ()))
        matches = [entry for entry in entries if entry.name == builder_ref["name"]]
        if not matches:
            raise _error("No installed provider for the selected dataset builder", "unsupported_capability")
        if len(matches) != 1:
            raise _error("Multiple providers declare the selected dataset builder", "conflict")
        try:
            selected = matches[0].load()
            provider = selected() if isinstance(selected, type) else selected
        except (ImportError, AttributeError) as error:
            raise _error("The selected dataset builder could not be loaded", "unsupported_capability") from error
        if getattr(provider, "builder_ref", None) != builder_ref:
            raise _error("Installed builder does not provide the requested fixed revision", "unsupported_capability")
        self.register(builder_ref, provider)
        return provider


def build_dataset(spec, records, artifacts, *, builders=None):
    """Build from fixed evidence using a selected external provider.

    The framework validates the public envelopes and published identity; the
    provider owns its task-specific selection, authorization, rows and masks.
    No Candidate, environment or GymTS orchestrator is passed to the provider.
    """
    schemas = SchemaRegistry()
    register_core_schemas(schemas)
    register_training_schemas(schemas)
    if not isinstance(spec, dict):
        raise _error("DatasetBuildSpec must be an object", "schema_mismatch")
    fixed = copy.deepcopy(spec)
    fixed.setdefault("require_sealed_runs", True)
    schemas.validate("gymts.dataset-build/1", fixed)
    components = [item["component_ref"] for item in fixed["transforms"]]
    if fixed["target"]["backend_ref"] is not None:
        components.append(fixed["target"]["backend_ref"])
    if fixed["reward_mapping"] is not None:
        components.append(fixed["reward_mapping"]["mapper_ref"])
    tokenization = fixed["tokenization"]
    if tokenization is not None:
        components.append(tokenization["mask_builder_ref"])
        if tokenization["reconstructor_ref"] is not None:
            components.append(tokenization["reconstructor_ref"])
        components.extend(item["computation_ref"] for item in tokenization["recompute_policies"])
    for reference in components:
        _fixed_ref(reference)
    # Source policy is independent of a domain exporter. A provider may choose
    # its own rows and rewards, but cannot turn evaluation-only evidence into
    # training data merely by choosing a different output profile.
    for reference in fixed["input_snapshots"]:
        snapshot = records.get_snapshot(reference)
        for frozen in snapshot["runs"]:
            run = records.get_run(frozen["run_id"])
            policy_ref = run["metadata"].get("usage_policy_ref")
            if policy_ref is not None:
                if policy_ref["schema_ref"] != "gymts.source-usage-policy/1":
                    raise _error("Source usage policy has an unsupported schema", "unsupported_capability")
                policy = artifacts.read_json(policy_ref)
                schemas.validate("gymts.source-usage-policy/1", policy)
                if not policy["training_allowed"] or not set(policy["allowed_uses"]) & {"training", "prepare", "dataset_build"}:
                    raise _error("Source policy forbids training export from this evidence", "permission_denied")
    provider = (builders if builders is not None else DatasetBuilderRegistry()).resolve(fixed["builder_ref"])
    target = fixed["target"]
    if target["format"] not in provider.target_formats or target["schema_ref"] not in provider.output_schema_refs:
        raise _error("The selected builder does not support this target format/schema", "unsupported_capability")
    returned = provider.build(copy.deepcopy(fixed), records, artifacts)
    if not isinstance(returned, dict):
        raise _error("Dataset builder must return a Manifest", "schema_mismatch")
    manifest = {key: value for key, value in returned.items() if key != "manifest_ref"}
    schemas.validate("gymts.dataset/1", manifest)
    if (manifest["builder_ref"] != fixed["builder_ref"] or manifest["build_id"] != fixed["build_id"]
            or manifest["input_snapshot_refs"] != fixed["input_snapshots"]
            or manifest["output_schema_ref"] != target["schema_ref"]):
        raise _error("Dataset Manifest differs from the requested build identity")
    if manifest["build_spec_ref"]["schema_ref"] != "gymts.dataset-build/1":
        raise _error("Manifest must reference its formal DatasetBuildSpec")
    if canonical_json(artifacts.read_json(manifest["build_spec_ref"])) != canonical_json(fixed):
        raise _error("Manifest references a different DatasetBuildSpec")
    if sum(shard["sample_count"] for shard in manifest["shards"]) != manifest["counts"]["accepted_samples"]:
        raise _error("Manifest shard counts differ from accepted_samples")
    references = [manifest["lineage_ref"], manifest["exclusion_summary_ref"]]
    references += manifest["input_snapshot_refs"] + manifest["reward_refs"]
    references += [shard["artifact_ref"] for shard in manifest["shards"]]
    if manifest["tokenization_ref"] is not None:
        references.append(manifest["tokenization_ref"])
    for reference in references:
        artifacts.resolve(reference)
    reference = returned.get("manifest_ref")
    if reference is not None:
        schemas.validate("gymts.artifact/1", reference)
        if reference["schema_ref"] != "gymts.dataset/1" or canonical_json(artifacts.read_json(reference)) != canonical_json(manifest):
            raise _error("Published Manifest differs from the returned Manifest")
    else:
        reference = artifacts.save_json(manifest, "gymts.dataset/1")
    return dict(copy.deepcopy(manifest), manifest_ref=reference)


__all__ = ["DatasetBuilderProvider", "DatasetBuilderRegistry", "build_dataset"]
