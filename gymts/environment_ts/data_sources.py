"""Core source identity, recipe, policy and portable dataset organization."""
import copy

from gymts.contracts import canonical_json
from gymts.contracts.resources import DATA_SOURCE, DATASET, DATASET_V2, POLICY
from gymts.storage.resources import resource_error


def intersect_policies(policies):
    allowed = set(policies[0]["allowed_uses"])
    training = all(item["training_allowed"] for item in policies)
    for item in policies[1:]:
        allowed.intersection_update(item["allowed_uses"])
    if not training:
        allowed.difference_update(("training", "prepare", "dataset_build"))
    if not allowed:
        raise resource_error("Source and parent policies have no common authorized use", "permission_denied")
    return {"allowed_uses": sorted(allowed), "training_allowed": training}


class DataOrganization:
    """Shared by DatasetCatalog; providers remain existing Environment adapters."""

    def load_manifest(self, dataset_id, *, revision, config="default"):
        return self.store.load_definition("dataset", dataset_id, revision, (DATASET, DATASET_V2), config=config)

    def _parents(self, references):
        fixed, manifests = [], []
        for reference in references:
            item = self.load_manifest(reference["dataset_id"], config=reference["config"], revision=reference["revision"])
            if reference["split"] not in item["splits"]:
                raise resource_error("Parent dataset does not provide the selected split")
            ref = dict(reference, revision=item["revision"])
            if ref not in fixed:
                fixed.append(ref)
                manifests.append(item)
        return fixed, manifests

    def register_source(self, definition, *, aliases=()):
        item = copy.deepcopy(definition)
        item["parent_datasets"], parents = self._parents(item["parent_datasets"])
        item["usage_policy"] = intersect_policies([item["usage_policy"]] + [p["usage_policy"] for p in parents])
        kind, reproduction = item["kind"], item["reproducibility"]
        if item["provider_ref"]["version"] in {"latest", "main", "master"}:
            raise resource_error("Source providers require a fixed implementation version")
        if reproduction["mode"] == "seeded" and reproduction["seed"] is None:
            raise resource_error("A seeded source requires its actual seed")
        if kind == "synthetic" and not item["recipe"]:
            raise resource_error("Synthetic sources require a fixed generation recipe")
        if kind == "static" and reproduction["mode"] != "snapshot":
            raise resource_error("Static sources require snapshot reproduction")
        if kind == "live_testbed" and reproduction["mode"] != "recorded":
            raise resource_error("Live testbeds require recorded reproduction")
        if item["card_ref"] is not None:
            self.store.read_asset(item["card_ref"])
        return self.store.publish_definition("source", item, DATA_SOURCE, aliases=aliases)

    def load_source(self, source_id, *, revision, config="default"):
        return self.store.load_definition("source", source_id, revision, DATA_SOURCE, config=config)

    def list_sources(self):
        return self.store.definitions("source", DATA_SOURCE)

    def register_snapshot(self, rows, *, dataset_id, source_ref, split="test", config="default",
                          schema_ref="gymts.json/1", targets=None, parents=(), usage_policy=None,
                          features=None, split_origin="explicit", attachments=(), capture=None,
                          aliases=(), kind=None):
        from .datasets import JSONL_READER
        source = self.load_source(source_ref["source_id"], config=source_ref["config"], revision=source_ref["revision"])
        if kind is not None and kind != source["kind"]:
            raise resource_error("Snapshot kind differs from its registered source", "conflict")
        fixed_parents, parent_manifests = self._parents(list(source["parent_datasets"]) + list(parents))
        policy = intersect_policies([source["usage_policy"], usage_policy or source["usage_policy"]] +
                                    [item["usage_policy"] for item in parent_manifests])
        public = list(rows)
        for row in public:
            self.schemas.validate(schema_ref, row)
        hidden = None if targets is None else list(targets)
        if hidden is not None and len(hidden) != len(public):
            raise resource_error("Private targets must align with the complete public split")
        def shard(values):
            return self.publish_asset(b"".join(canonical_json(row) + b"\n" for row in values), media_type="application/jsonl")
        source_asset = self.publish_asset(canonical_json(source), media_type="application/json")
        parent_assets = [self.publish_asset(canonical_json(item), media_type="application/json") for item in parent_manifests]
        manifest = {"protocol_version": DATASET_V2, "dataset_id": dataset_id, "config": config, "revision": None,
            "schema_ref": schema_ref, "reader_ref": copy.deepcopy(JSONL_READER), "features": copy.deepcopy(features or {}),
            "splits": {split: {"row_count": len(public), "split_origin": split_origin,
                "input_indices": [0], "target_indices": [] if hidden is None else [0]}},
            "usage_policy": policy, "source_files": [],
            "importer_ref": {"name": "gymts.snapshot", "version": "2.0.0", "origin_ref": None},
            "inputs": [shard(public)], "series": [], "targets": [] if hidden is None else [shard(hidden)],
            "quality_report_ref": None, "card_ref": None, "kind": source["kind"],
            "origin": {"source_ref": {key: source[key] for key in ("source_id", "config", "revision")},
                "source_definition": source_asset},
            "lineage": {"parents": fixed_parents, "parent_manifests": parent_assets, "capture": capture},
            "attachments": list(copy.deepcopy(attachments))}
        return self.register_dataset(manifest, aliases=aliases)

    def bind_source(self, spec, source_id, *, revision, config="default"):
        """Bind fixed source/parent identities and their policy to an ExperimentSpec."""
        if self.artifacts is None:
            raise resource_error("Source binding needs a Run artifact service", "unsupported_capability")
        source = self.load_source(source_id, revision=revision, config=config)
        result = copy.deepcopy(spec)
        environment = result["scene"]["environment"]
        if (environment["adapter"], environment["version"]) != (source["provider_ref"]["name"], source["provider_ref"]["version"]):
            raise resource_error("Experiment Environment differs from the registered source provider", "conflict")
        if source["reproducibility"]["mode"] == "seeded" and result["execution"]["seed"] != source["reproducibility"]["seed"]:
            raise resource_error("Experiment seed differs from the registered source", "conflict")
        for key in ("source", "mapping", "options"):
            if key in source["configuration"] and environment[key] != source["configuration"][key]:
                raise resource_error("Experiment configuration differs from its fixed source", "conflict")
        _, parents = self._parents(source["parent_datasets"])
        provenance = result.setdefault("provenance", {"source_refs": [], "usage_policy_ref": None, "benchmark_definition_ref": None})
        policies = [source["usage_policy"]] + [item["usage_policy"] for item in parents]
        if provenance["usage_policy_ref"] is not None:
            policies.append(self.artifacts.read_json(provenance["usage_policy_ref"]))
        provenance["usage_policy_ref"] = self.artifacts.save_json(intersect_policies(policies), POLICY)
        for item in [source] + parents:
            ref = self.artifacts.save_json(item, item["protocol_version"])
            if ref not in provenance["source_refs"]:
                provenance["source_refs"].append(ref)
        return result

    def capture_run(self, run_id, *, source_id, revision, dataset_id, config="default", source_config="default",
                    split="recorded", event_kinds=None, usage_policy=None, aliases=()):
        from .data_capture import capture_run
        return capture_run(self, run_id, source_id=source_id, revision=revision, dataset_id=dataset_id,
            config=config, source_config=source_config, split=split, event_kinds=event_kinds,
            usage_policy=usage_policy, aliases=aliases)
