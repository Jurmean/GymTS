"""Optional native AReaL adapter; discovery has no scientific imports."""


def register_areal_plugins(registries, schemas):
    from .registration import register_areal_plugins as register
    return register(registries, schemas)
