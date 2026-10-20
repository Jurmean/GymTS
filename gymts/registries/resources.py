"""Project-independent, fixed-version resource readers and benchmark resolvers."""
import copy

from gymts.contracts import GymTSError, canonical_json


class ResourceProviderRegistry:
    def __init__(self, kind):
        self.kind, self._entries = kind, {}

    def register(self, reference, provider):
        if (not isinstance(reference, dict) or set(reference) != {"name", "version", "origin_ref"}
                or not all(isinstance(reference.get(key), str) and reference[key] for key in ("name", "version"))
                or reference["version"] in {"latest", "main", "master"}):
            raise GymTSError("invalid_config", "Resource providers require a fixed ComponentRef")
        method = "read" if self.kind == "dataset" else "resolve"
        if not callable(getattr(provider, method, None)):
            raise GymTSError("invalid_config", "Resource provider must implement " + method)
        key = canonical_json(reference)
        if key in self._entries and self._entries[key] is not provider:
            raise GymTSError("conflict", "Resource provider is already registered")
        self._entries[key] = provider

    def resolve(self, reference):
        key = canonical_json(reference)
        if key not in self._entries:
            raise GymTSError("unsupported_capability", "No installed " + self.kind + " provider for this fixed reference")
        return self._entries[key]

    def manifests(self):
        import json
        return [copy.deepcopy(json.loads(key)) for key in sorted(self._entries)]


class DatasetRegistry(ResourceProviderRegistry):
    def __init__(self):
        super().__init__("dataset")


class BenchmarkRegistry(ResourceProviderRegistry):
    def __init__(self):
        super().__init__("benchmark")
