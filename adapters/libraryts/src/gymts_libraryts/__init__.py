"""Opt-in LibraryTS adapter; discovery imports no scientific dependencies."""


def register_libraryts_plugins(registries, schemas):
    from .registration import register_libraryts_plugins as register
    return register(registries, schemas)


__all__ = ["register_libraryts_plugins"]
