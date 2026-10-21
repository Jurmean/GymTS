"""Explicit external integration; discovery loads no scientific libraries."""
__version__ = "0.1.0"


def register(registries, schemas):
    from .registration import register as activate
    return activate(registries, schemas)
