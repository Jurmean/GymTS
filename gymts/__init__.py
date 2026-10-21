"""GymTS: synchronous experiments and independent, versioned evaluation."""
from .contracts import GymTSError
from .environment_ts import EnvironmentTS
from .autobench_ts import AutoBenchTS

__version__ = "0.6.0"


class GymTS:
    def __init__(self, root=".gymts", *, register_builtins=True, integrations=(), data_home=None, cache_home=None):
        import os
        from pathlib import Path
        from .contracts.schema import SchemaRegistry, register_core_schemas
        from .registries import Registries
        from .storage import ArtifactStore, LocalExperimentRecords
        from .environment_ts import EnvironmentTS
        from .autobench_ts import AutoBenchTS
        self.root = Path(root)
        self.schemas = SchemaRegistry()
        register_core_schemas(self.schemas)
        self.registries = Registries(self.schemas)
        if register_builtins:
            from .plugins import register_builtin_plugins
            register_builtin_plugins(self.registries, self.schemas)
        if isinstance(integrations, str):
            raise GymTSError("invalid_config", "integrations must be a sequence of names, not a string")
        try:
            integrations = tuple(integrations)
        except TypeError as error:
            raise GymTSError("invalid_config", "integrations must be a sequence of names") from error
        self.enabled_integrations = ()
        for integration in integrations:
            self.enable_integration(integration)
        self.artifacts = ArtifactStore(self.root / "artifacts")
        self.records = LocalExperimentRecords(self.root, self.artifacts)
        self.environment_ts = EnvironmentTS(self.registries, self.schemas, self.records, self.artifacts)
        from .storage.resources import ResourceStore
        from .environment_ts.datasets import DatasetCatalog
        data_home = data_home or os.environ.get("GYMTS_DATA_HOME") or str(
            Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser() / "gymts")
        cache_home = cache_home or os.environ.get("GYMTS_CACHE_HOME") or str(
            Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")).expanduser() / "gymts")
        self.environment_ts.datasets = DatasetCatalog(
            ResourceStore(data_home, cache_home, self.schemas), self.registries.datasets, self.schemas,
            artifacts=self.artifacts, records=self.records)
        self.autobench = AutoBenchTS(self.environment_ts, self.registries.scorers, self.schemas,
                                     self.records, self.artifacts)
        self.autobench_ts = self.autobench
        from .environment_ts.experiments import ExperimentOrganization
        self.experiments = ExperimentOrganization(self)
        self.environment_ts.experiments = self.experiments

    @staticmethod
    def available_integrations():
        """Discover optional registration metadata without importing integrations."""
        from .integrations import available_integrations
        return available_integrations()

    def enable_integration(self, name):
        """Register a selected trusted integration; repeated enables are harmless."""
        if name in self.enabled_integrations:
            return
        from .integrations import register_integration
        register_integration(name, self.registries, self.schemas)
        self.enabled_integrations += (name,)

    def validate(self, spec):
        return self.environment_ts.validate(spec)

    def plan(self, spec):
        return self.environment_ts.plan(spec)

    def run(self, spec):
        return self.environment_ts.run(spec)

    def run_data(self, spec, *, source_id, revision, dataset_id, source_config="default",
                 config="default", split="recorded"):
        """Execute an experiment and persist its environment data in the catalog."""
        return self.environment_ts.run_data(spec, source_id=source_id, revision=revision,
            dataset_id=dataset_id, source_config=source_config, config=config, split=split)

    def close(self):
        self.records.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


__all__ = ["GymTS", "EnvironmentTS", "AutoBenchTS", "GymTSError", "__version__"]
