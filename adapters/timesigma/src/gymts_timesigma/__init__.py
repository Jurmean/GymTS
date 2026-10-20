"""Explicit, optional native TimeSigma integration; importing it trains nothing."""


def register_timesigma_plugins(registries, schemas):
    from .registration import register_timesigma_plugins as register
    return register(registries, schemas)


__all__ = ["register_timesigma_plugins"]
