"""Reusable time-series domain contracts; no model or project implementation."""
__version__ = "0.1.0"


def register_timeseries_plugins(registries, schemas):
    from .registration import register_timeseries_plugins as register
    return register(registries, schemas)


__all__ = ["register_timeseries_plugins"]
