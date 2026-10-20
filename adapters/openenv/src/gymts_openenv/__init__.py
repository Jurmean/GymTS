"""Opt-in adapter; importing GymTS or this package opens no connection."""
__version__ = '0.1.0'


def register_openenv_plugins(registries, schemas):
    from .registration import register_openenv_plugins as register
    return register(registries, schemas)
