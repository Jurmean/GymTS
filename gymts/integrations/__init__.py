"""Explicit optional integrations; discovery reads metadata without loading code.

Third-party distributions can publish a ``gymts.integrations`` entry point whose
callable accepts ``(registries, schemas)``. Installing an integration does not
enable it: users select its name in ``GymTS(integrations=(... ,))``.
"""
import copy
import importlib
from importlib.metadata import entry_points

from gymts.contracts import GymTSError


_SHIPPED = {
    "chatts": {
        "name": "chatts",
        "description": "ChatTS synthetic QA data, tasks, HTTP adapters and scoring",
        "registration": "gymts.integrations.chatts:register_chatts_plugins",
        "distribution": "gymts",
    }
}


def _catalog():
    items = {name: [(copy.deepcopy(info), None)] for name, info in _SHIPPED.items()}
    discovered = entry_points()
    entries = (discovered.select(group="gymts.integrations") if hasattr(discovered, "select")
               else discovered.get("gymts.integrations", ()))
    for entry in entries:
        distribution = getattr(entry, "dist", None)
        items.setdefault(entry.name, []).append(({"name": entry.name, "description": None,
            "registration": entry.value,
            "distribution": distribution.name if distribution else None}, entry))
    return items


def available_integrations():
    """Return fresh metadata, including conflicts, without loading integration code."""
    result = []
    for name, providers in sorted(_catalog().items()):
        if len(providers) == 1:
            result.append(dict(providers[0][0], status="available"))
        else:
            result.append({"name": name, "description": None, "registration": None,
                           "distribution": None, "status": "conflict",
                           "providers": [info for info, _ in providers]})
    return result


def _snapshot_registration(registries, schemas):
    # Host-side registration transactions preserve callable identities; copying
    # callable factory instances can silently change idempotent registrations.
    entries = []
    for kind in ("environments", "tasks", "candidates", "scorers"):
        registry = getattr(registries, kind)
        entries.append((registry, {key: (copy.deepcopy(manifest), factory)
                                  for key, (manifest, factory) in registry._entries.items()}))
    return copy.deepcopy(schemas._schemas), entries


def _restore_registration(snapshot, schemas):
    definitions, entries = snapshot
    schemas._schemas.clear()
    schemas._schemas.update(definitions)
    for registry, prior in entries:
        registry._entries.clear()
        registry._entries.update(prior)


def register_integration(name, registries, schemas):
    """Load and register one explicitly selected trusted integration."""
    if not isinstance(name, str) or not name:
        raise GymTSError("invalid_config", "An integration name must be a nonempty string")
    catalog = _catalog()
    if name not in catalog:
        raise GymTSError("unsupported_capability", "Unknown optional integration: " + name)
    if len(catalog[name]) != 1:
        raise GymTSError("conflict", "Duplicate optional integration: " + name)
    info, entry = catalog[name][0]
    snapshot = _snapshot_registration(registries, schemas)
    try:
        if entry is not None:
            register = entry.load()
        else:
            module, attribute = info["registration"].split(":", 1)
            register = getattr(importlib.import_module(module), attribute)
        if not callable(register):
            raise GymTSError("invalid_config", "Integration entry point must be callable")
        register(registries, schemas)
    except BaseException as error:
        _restore_registration(snapshot, schemas)
        if not isinstance(error, Exception):
            raise
        code = "unsupported_capability" if isinstance(error, (ImportError, AttributeError)) else "invalid_config"
        if isinstance(error, GymTSError) and error.code in {
                "unsupported_capability", "invalid_config", "schema_mismatch", "conflict"}:
            code = error.code
        raise GymTSError(code, "Optional integration registration failed: " + name,
                         stage="plugin", method="register") from None


__all__ = ["available_integrations", "register_integration"]
