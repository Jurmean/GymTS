"""Public fixed-evidence dataset building and versioned export contracts.

Concrete layouts and backends are supplied by independently installed providers.
"""
from .builder import REWARD, register_training_schemas
from .service import DatasetBuilderProvider, DatasetBuilderRegistry, build_dataset

__all__ = ["REWARD", "register_training_schemas", "DatasetBuilderProvider", "DatasetBuilderRegistry", "build_dataset"]
