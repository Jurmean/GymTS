"""Capability-limited artifact/view access for plugin contexts.

This is an API boundary, not a sandbox for untrusted Python code. Plugins must
be trusted; execute untrusted code in an external worker/container.
"""
from __future__ import annotations

from gymts.contracts import GymTSError, canonical_json


class RestrictedServices:
    def __init__(self, artifacts, refs=(), views=(), purpose="runtime", schemas=None):
        self._store = artifacts
        self._refs = {canonical_json(ref) for ref in refs if ref is not None}
        self._views = {canonical_json(view) for view in views if view is not None}
        for view in views:
            if view:
                self._refs.update(canonical_json(ref) for ref in view["source_refs"])
        self.purpose, self.schemas = purpose, schemas
        self._observations = {}

    @property
    def artifacts(self):
        return self

    def _allow(self, ref):
        if canonical_json(ref) not in self._refs:
            raise GymTSError("permission_denied", "Artifact is not authorized in this context")

    def resolve(self, ref):
        self._allow(ref)
        return self._store.resolve(ref)

    def read_json(self, ref):
        self._allow(ref)
        return self._store.read_json(ref)

    def save_artifact(self, content, metadata):
        ref = self._store.save_artifact(content, metadata)
        self._refs.add(canonical_json(ref))
        return ref

    def save_json(self, value, schema_ref="gymts.json/1"):
        if self.schemas:
            self.schemas.validate(schema_ref, value)
        ref = self._store.save_json(value, schema_ref)
        self._refs.add(canonical_json(ref))
        return ref

    def read_view(self, ref):
        if canonical_json(ref) not in self._views or ref["purpose"] != self.purpose:
            raise GymTSError("permission_denied", "Data view is not authorized for this purpose")
        return self._store.read_view(ref)

    def credential(self, ref):
        raise GymTSError("unsupported_capability", "No credential provider configured")

    def apply_transform(self, ref, value):
        if ref is None:
            return value
        raise GymTSError("unsupported_capability", "No binding transform provider configured")

    def observation_ref(self, batch_id):
        if batch_id not in self._observations:
            raise GymTSError("invalid_request", "Observation has not been committed")
        return self._observations[batch_id]

    def _grant_payload(self, payload):
        if payload and payload.get("storage") == "artifact":
            self._refs.add(canonical_json(payload["artifact_ref"]))

