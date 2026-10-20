"""Optional static data provider. Importing this package does not import HF."""
__version__ = "0.1.0"


def register_hf_datasets_plugins(registries, schemas):
    from .registration import register
    return register(registries, schemas)
