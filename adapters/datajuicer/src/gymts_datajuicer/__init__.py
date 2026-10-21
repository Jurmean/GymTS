"""Explicit opt-in; discovering the package never imports a native ML runtime."""
__version__ = "0.1.0"
UPSTREAM_TREE_SHA256 = '6ee32fcab30625d654349e470dec70362691d0f9d3531d83128b87dd518a1014'
UPSTREAM_SHA = "abb9e49897bdd0e0e2f44ce3272cc1ea5c5a6111"


def register_datajuicer_plugins(registries, schemas):
    from .registration import register
    register(registries, schemas)
