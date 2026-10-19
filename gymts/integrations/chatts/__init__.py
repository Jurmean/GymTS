"""ChatTS synthetic-data integration. Registration is explicit and dependency free."""


def register_chatts_plugins(registries, schemas):
    from .registration import register_chatts_plugins as register
    return register(registries, schemas)


__all__ = ["register_chatts_plugins"]
