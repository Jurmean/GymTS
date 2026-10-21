"""Benchmark resources resolved into the existing AutoBenchTS EvaluationSpec."""
import copy

from gymts.contracts import canonical_json
from gymts.contracts.resources import BENCHMARK, POLICY
from gymts.environment_ts.datasets import EvaluationDatasets
from gymts.storage.resources import resource_error


class _SelectedDatasets(EvaluationDatasets):
    def __init__(self, catalog, references):
        super().__init__(catalog)
        self._references = {canonical_json(item) for item in references}

    def load_dataset(self, dataset_id, *, revision, config="default", split="test", purpose="evaluation"):
        reference = {"dataset_id": dataset_id, "config": config, "revision": revision, "split": split}
        if canonical_json(reference) not in self._references:
            raise resource_error("Benchmark resolver requested a dataset outside its fixed definition", "permission_denied")
        return super().load_dataset(dataset_id, revision=revision, config=config, split=split, purpose=purpose)


class BenchmarkResources:
    """Explicit evaluation resources; no Runner or Candidate execution service."""
    def __init__(self, datasets, artifacts, source_refs, definition_ref):
        self.datasets, self.artifacts = datasets, artifacts
        self.source_refs, self.definition_ref = copy.deepcopy(source_refs), copy.deepcopy(definition_ref)


class BenchmarkCatalog:
    def __init__(self, datasets, resolvers, artifacts, schemas):
        self.datasets, self.store, self.resolvers = datasets, datasets.store, resolvers
        self.artifacts, self.schemas = artifacts, schemas

    def register_benchmark(self, definition, *, aliases=()):
        item = copy.deepcopy(definition)
        # Release labels resolve once, before a reusable definition is frozen.
        for reference in item["datasets"]:
            source = self.datasets.load_manifest(reference["dataset_id"], revision=reference["revision"],
                                                 config=reference["config"])
            if reference["split"] not in source["splits"]:
                raise resource_error("Benchmark definition references an absent split")
            if "evaluation" not in source["usage_policy"]["allowed_uses"]:
                raise resource_error("Benchmark source does not authorize evaluation", "permission_denied")
            reference["revision"] = source["revision"]
        if item["resolver_ref"]["version"] in {"latest", "main", "master"}:
            raise resource_error("Benchmark resolvers require a fixed implementation version")
        if item["card_ref"] is not None:
            self.store.read_asset(item["card_ref"])
        return self.store.publish_definition("benchmark", item, BENCHMARK, aliases=aliases)

    def list_benchmarks(self):
        return [{key: copy.deepcopy(item[key]) for key in ("benchmark_id", "revision", "resolver_ref", "datasets")}
                for item in self.store.definitions("benchmark", BENCHMARK)]

    def load_benchmark(self, benchmark_id, *, revision):
        return self.store.load_definition("benchmark", benchmark_id, revision, BENCHMARK)

    def resolve_benchmark(self, benchmark_id, *, revision, candidates, purpose="regression", repetitions=None):
        definition = self.load_benchmark(benchmark_id, revision=revision)
        provider = self.resolvers.resolve(definition["resolver_ref"])
        if purpose not in {"development", "regression", "acceptance"}:
            raise resource_error("Benchmark execution requires an evaluation purpose", "permission_denied")
        definition_ref = self.artifacts.save_json(definition, BENCHMARK)
        sources, policies = [], []
        for reference in definition["datasets"]:
            manifest = self.datasets.load_manifest(reference["dataset_id"], revision=reference["revision"],
                                                   config=reference["config"])
            sources.append(self.artifacts.save_json(manifest, manifest["protocol_version"]))
            policies.append(manifest["usage_policy"])
        resources = BenchmarkResources(_SelectedDatasets(self.datasets, definition["datasets"]),
                                       self.artifacts, sources, definition_ref)
        spec = provider.resolve(copy.deepcopy(definition), resources, copy.deepcopy(candidates), purpose,
                                copy.deepcopy(repetitions))
        if not isinstance(spec, dict) or spec.get("protocol_version") != "gymts.evaluation/1":
            raise resource_error("Benchmark provider must return a native EvaluationSpec", "schema_mismatch")
        if spec.get("candidates") != candidates or spec.get("purpose") != purpose:
            raise resource_error("Benchmark resolver changed the requested candidates or purpose", "conflict")
        if repetitions is not None and spec.get("repetitions") != repetitions:
            raise resource_error("Benchmark resolver changed the requested repetitions", "conflict")
        if "provenance" in spec:
            raise resource_error("Resource provenance is owned by AutoBenchTS, not its resolver", "conflict")
        policy = {"allowed_uses": sorted(set.intersection(*(set(item["allowed_uses"]) for item in policies))),
                  "training_allowed": all(item["training_allowed"] for item in policies)}
        if not policy["allowed_uses"]:
            raise resource_error("Benchmark source policies have no common authorized use", "permission_denied")
        spec["provenance"] = {"source_refs": sources, "usage_policy_ref": self.artifacts.save_json(policy, POLICY),
                              "benchmark_definition_ref": definition_ref}
        return spec
