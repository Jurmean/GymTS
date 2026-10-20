"""Opt-in live telemetry adapter. Import/discovery opens no network connection."""


def register(registries, schemas):
    from .registration import register_prometheus
    register_prometheus(registries, schemas)
