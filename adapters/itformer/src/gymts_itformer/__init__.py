"""Optional, explicitly activated integration; importing never loads a model."""
__version__ = "0.1.0"


def register_itformer_plugins(registries, schemas):
    from .registration import register
    register(registries, schemas)
