"""Independent ChatTS adapter; registration is explicit and dependency free."""

__version__ = "0.1.0"


def register_chatts_plugins(registries, schemas):
    from .registration import register_chatts_plugins as register
    return register(registries, schemas)


__all__ = ["register_chatts_plugins"]
