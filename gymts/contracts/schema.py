"""Small, explicit JSON Schema subset for a dependency-free core.

Unknown schema keywords fail registration rather than silently bypassing a rule.
Plugins requiring the full JSON Schema vocabulary can inject another registry.
"""
from __future__ import annotations

import copy
import math
import re
from typing import Any
from .common import GymTSError, canonical_json


class SchemaRegistry:
    KEYWORDS = {"type", "properties", "required", "additionalProperties", "items",
                "enum", "const", "minimum", "maximum", "exclusiveMinimum",
                "exclusiveMaximum", "minItems", "maxItems", "uniqueItems",
                "minLength", "maxLength", "pattern", "anyOf", "oneOf", "allOf",
                "description", "title", "default", "minProperties", "maxProperties"}

    def __init__(self):
        self._schemas = {}
        self.register("gymts.json/1", {})

    def register(self, ref: str, schema: dict) -> None:
        if not isinstance(ref, str) or not ref or not isinstance(schema, dict):
            raise GymTSError("invalid_config", "Schema needs a stable ref and object definition")
        try:
            canonical_json(schema)
        except (TypeError, ValueError) as exc:
            raise GymTSError("invalid_config", "Schema must contain finite JSON") from exc
        self._check_definition(schema)
        if ref in self._schemas and self._schemas[ref] != schema:
            raise GymTSError("conflict", f"Schema already registered: {ref}")
        self._schemas[ref] = copy.deepcopy(schema)

    def resolve(self, ref: str) -> dict:
        if not isinstance(ref, str) or not ref:
            raise GymTSError("schema_mismatch", "Schema reference must be a nonempty string")
        if ref not in self._schemas:
            raise GymTSError("schema_mismatch", f"Schema is not registered: {ref}")
        return copy.deepcopy(self._schemas[ref])

    def validate(self, ref: str, value: Any, path: str = "$") -> None:
        try:
            canonical_json(value)
        except (TypeError, ValueError) as exc:
            raise GymTSError("schema_mismatch", f"{path}: value is not finite JSON") from exc
        self._validate(self.resolve(ref), value, path)

    def _check_definition(self, schema: dict) -> None:
        if not isinstance(schema, dict):
            raise GymTSError("invalid_config", "Schema nodes must be objects")
        unsupported = set(schema) - self.KEYWORDS
        if unsupported:
            raise GymTSError("unsupported_capability", f"Unsupported schema keywords: {sorted(unsupported)}")
        def check(condition, message):
            if not condition:
                raise GymTSError("invalid_config", "Malformed schema: " + message)
        if "type" in schema:
            names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
            check(bool(names) and all(isinstance(t, str) and t in
                  {"object", "array", "string", "number", "integer", "boolean", "null"} for t in names), "type")
        check(isinstance(schema.get("properties", {}), dict), "properties")
        required = schema.get("required", [])
        check(isinstance(required, list) and all(isinstance(k, str) for k in required), "required")
        check(isinstance(schema.get("additionalProperties", True), (bool, dict)), "additionalProperties")
        if "items" in schema:
            check(isinstance(schema["items"], dict), "items must be a schema object")
        check(len(required) == len(set(required)), "required fields must be unique")
        if "type" in schema:
            check(len(names) == len(set(names)), "types must be unique")
        for key in ("enum", "anyOf", "oneOf", "allOf"):
            if key in schema:
                check(isinstance(schema[key], list) and bool(schema[key]), key)
        if "enum" in schema:
            check(len({canonical_json(value) for value in schema["enum"]}) == len(schema["enum"]),
                  "enum values must be unique")
        for key in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
            if key in schema:
                check(type(schema[key]) in (int, float) and
                      (type(schema[key]) is int or math.isfinite(schema[key])), key)
        for key in ("minItems", "maxItems", "minLength", "maxLength", "minProperties", "maxProperties"):
            if key in schema:
                check(type(schema[key]) is int and schema[key] >= 0, key)
        if "uniqueItems" in schema:
            check(type(schema["uniqueItems"]) is bool, "uniqueItems")
        if "pattern" in schema:
            check(isinstance(schema["pattern"], str), "pattern")
            try:
                re.compile(schema["pattern"])
            except re.error as exc:
                raise GymTSError("invalid_config", "Malformed schema pattern") from exc
        for child in schema.get("properties", {}).values():
            self._check_definition(child)
        for key in ("items", "additionalProperties"):
            if isinstance(schema.get(key), dict):
                self._check_definition(schema[key])
        for key in ("allOf", "oneOf", "anyOf"):
            for child in schema.get(key, []):
                self._check_definition(child)

    def _validate(self, schema: dict, value: Any, path: str) -> None:
        def fail(message):
            raise GymTSError("schema_mismatch", f"{path}: {message}", links={"path": path})
        types = schema.get("type")
        valid_types = {
            "object": isinstance(value, dict), "array": isinstance(value, list),
            "string": isinstance(value, str), "boolean": isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "null": value is None,
        }
        if types is not None:
            names = types if isinstance(types, list) else [types]
            if not any(valid_types.get(t, False) for t in names):
                fail(f"expected {types}")
        if "enum" in schema and not any(type(value) is type(v) and value == v for v in schema["enum"]):
            fail("value not in enum")
        if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
            fail("unexpected constant")
        for key in ("allOf", "anyOf", "oneOf"):
            if key in schema:
                count = 0
                for child in schema[key]:
                    try:
                        self._validate(child, value, path)
                        count += 1
                    except GymTSError:
                        pass
                if ((key == "allOf" and count != len(schema[key])) or
                    (key == "anyOf" and not count) or (key == "oneOf" and count != 1)):
                    fail(f"does not satisfy {key}")
        if isinstance(value, dict):
            missing = set(schema.get("required", [])) - set(value)
            if missing:
                fail(f"missing fields {sorted(missing)}")
            props = schema.get("properties", {})
            additional = schema.get("additionalProperties", True)
            for key, item in value.items():
                if key in props:
                    self._validate(props[key], item, f"{path}.{key}")
                elif additional is False:
                    fail(f"unknown field {key}")
                elif isinstance(additional, dict):
                    self._validate(additional, item, f"{path}.{key}")
            for key, compare in (("minProperties", lambda n: len(value) >= n),
                                 ("maxProperties", lambda n: len(value) <= n)):
                if key in schema and not compare(schema[key]):
                    fail(key)
        if isinstance(value, list):
            for key, compare in (("minItems", lambda n: len(value) >= n),
                                 ("maxItems", lambda n: len(value) <= n)):
                if key in schema and not compare(schema[key]):
                    fail(key)
            if schema.get("uniqueItems") and len({canonical_json(v) for v in value}) != len(value):
                fail("array contains duplicate items")
            if "items" in schema:
                for i, item in enumerate(value):
                    self._validate(schema["items"], item, f"{path}[{i}]")
        if isinstance(value, str):
            for key, compare in (("minLength", lambda n: len(value) >= n),
                                 ("maxLength", lambda n: len(value) <= n)):
                if key in schema and not compare(schema[key]):
                    fail(key)
            if "pattern" in schema and not re.search(schema["pattern"], value):
                fail("pattern")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if isinstance(value, float) and not math.isfinite(value):
                fail("number is not finite")
            for key, compare in (("minimum", lambda n: value >= n), ("maximum", lambda n: value <= n),
                                 ("exclusiveMinimum", lambda n: value > n),
                                 ("exclusiveMaximum", lambda n: value < n)):
                if key in schema and not compare(schema[key]):
                    fail(key)


def obj(properties: dict, required=None, *, additional=False) -> dict:
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required,
            "additionalProperties": additional}


def array(items: dict, **kwargs) -> dict:
    return {"type": "array", "items": items, **kwargs}


def nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


STRING = {"type": "string", "minLength": 1}
OBJECT = {"type": "object"}
TIME = {"anyOf": [STRING, {"type": "integer", "minimum": 0}]}
ARTIFACT = obj({"artifact_id": STRING, "revision": STRING, "uri": STRING,
                "content_hash": nullable(STRING), "media_type": STRING,
                "schema_ref": nullable(STRING),
                "size_bytes": nullable({"type": "integer", "minimum": 0})})
COMPONENT = obj({"name": STRING, "version": STRING, "origin_ref": nullable(STRING)})
PAYLOAD = {"oneOf": [
    obj({"schema_ref": STRING, "storage": {"const": "inline"}, "value": {}}),
    obj({"schema_ref": STRING, "storage": {"const": "artifact"}, "artifact_ref": ARTIFACT})]}
SCOPE = obj({"start": TIME, "end": nullable(TIME)})
VIEW = obj({"view_id": STRING, "revision": STRING, "source_refs": array(ARTIFACT),
            "selection": PAYLOAD, "as_of": nullable(TIME),
            "purpose": {"enum": ["prepare", "runtime", "evaluation", "dataset_build"]}})


def register_core_schemas(schemas: SchemaRegistry) -> None:
    from .resources import PROVENANCE, register_resource_schemas, resource_schemas
    register_resource_schemas(schemas)
    source = obj({"kind": {"enum": ["dataset", "generator", "simulator", "live"]},
                  "locator": STRING, "revision": nullable(STRING), "connection": OBJECT,
                  "credential_ref": nullable(STRING)})
    env = obj({"protocol_version": {"const": "gymts.environment/1"}, "adapter": STRING,
               "version": STRING, "source": source, "mapping": OBJECT, "options": OBJECT})
    task = obj({"plugin": STRING, "version": STRING, "params": OBJECT})
    binding = obj({"variables": {"type": "object", "additionalProperties": obj({
        "source": STRING, "unit": STRING, "transform": nullable(COMPONENT)})},
        "operations": {"type": "object", "additionalProperties": obj({
            "source": STRING, "arguments_schema_ref": STRING, "transform": nullable(COMPONENT)})}})
    learning = obj({"prepare": {"enum": ["load_only", "fit"]},
                    "online": {"enum": ["frozen", "update"]}, "training_view": nullable(VIEW),
                    "training_targets": nullable(VIEW), "alignment_schema_ref": nullable(STRING),
                    "allowed_feedback_sources": array(STRING, uniqueItems=True)})
    limits = obj({"max_inputs": nullable({"type": "integer", "minimum": 1}),
                  "max_operations": nullable({"type": "integer", "minimum": 1}),
                  "max_turns_per_case": {"type": "integer", "minimum": 1},
                  "max_wall_time_s": nullable({"type": "number", "exclusiveMinimum": 0})})
    execution = obj({"mode": {"enum": ["batch", "stream", "interactive"]},
                     "start": obj({"mode": {"enum": ["reinitialize", "attach"]}}),
                     "scope": SCOPE, "feedback_until": nullable(TIME), "seed": nullable({"type": "integer"}),
                     "learning": learning, "limits": limits})
    candidate = obj({"adapter": STRING, "version": STRING, "artifact": nullable(ARTIFACT),
                     "params": OBJECT, "inherited_state": array(ARTIFACT)})
    recording = obj({"store_ref": STRING, "inputs": {"enum": ["full", "reference"]},
                     "outputs": {"enum": ["full", "reference"]}, "artifacts": {"const": "reference"},
                     "model_calls": {"enum": ["none", "io", "native_rollout"]},
                     "on_capture_failure": {"enum": ["fail_run", "mark_incomplete"]},
                     "redaction_policy_ref": nullable(ARTIFACT), "extra_event_kinds": array(STRING)})
    schemas.register("gymts.artifact/1", ARTIFACT)
    schemas.register("gymts.payload/1", PAYLOAD)
    schemas.register("gymts.component/1", COMPONENT)
    schemas.register("gymts.view/1", VIEW)
    schemas.register("gymts.extensions/1", obj({}))
    schemas.register("gymts.experiment/1", obj({
        "protocol_version": {"const": "gymts.experiment/1"}, "name": nullable(STRING),
        "purpose": {"enum": ["development", "regression", "acceptance", "training_collection"]},
        "scene": obj({"environment": env, "task": task, "binding": binding}),
        "candidate": candidate, "execution": execution, "recording": recording, "extensions": OBJECT,
        "provenance": resource_schemas()[PROVENANCE]},
        required=["protocol_version", "name", "purpose", "scene", "candidate", "execution", "recording", "extensions"]))
    schemas.register("gymts.assembly-plan/1", obj({
        "protocol_version": {"const": "gymts.assembly-plan/1"},
        "resolved_spec": schemas.resolve("gymts.experiment/1"),
        "manifests": obj({"environment": OBJECT, "task": OBJECT, "candidate": OBJECT}),
        "descriptions": obj({"environment": OBJECT, "task": OBJECT}),
        "variables": array(STRING, uniqueItems=True), "operations": array(STRING, uniqueItems=True),
        "read_scope": SCOPE, "resource_checks": {"const": "deferred_to_open"}}))
    schemas.register("gymts.selection/1", obj({
        "kind": {"enum": ["all", "rows", "json_pointer"]},
        "source_index": {"type": "integer", "minimum": 0}, "pointer": {"type": "string"},
        "start": {"type": "integer", "minimum": 0}, "stop": nullable({"type": "integer", "minimum": 0})},
        required=["kind"]))
    register_capture_schemas(schemas)


def register_capture_schemas(schemas: SchemaRegistry) -> None:
    """Formal v1 internal-call evidence, separate from a model's output schema."""
    error = obj({"code": STRING, "stage": STRING, "method": nullable(STRING),
                 "message": {"type": "string"}, "run_id": nullable(STRING), "links": OBJECT,
                 "retryable": {"type": "boolean"},
                 "side_effect": {"enum": ["none", "possible", "confirmed"]}})
    capture = obj({"requested_profile": {"enum": ["io", "native_rollout"]},
                   "acquired_fields": array(STRING, uniqueItems=True),
                   "missing_fields": {"type": "object", "additionalProperties": STRING},
                   "transforms": array(COMPONENT),
                   "completeness": {"enum": ["complete", "partial", "none"]}})
    identity = {"call_id": STRING, "attempt_id": STRING, "parent_call_id": nullable(STRING),
                "run_id": STRING, "input_id": STRING, "output_id": STRING}
    timing = {"started_at": STRING, "ended_at": nullable(STRING),
              "status": {"enum": ["succeeded", "failed", "cancelled", "unknown"]}}
    model = dict(identity, **timing)
    model.update({"protocol_version": {"const": "gymts.model-call/1"},
                  "model_ref": COMPONENT, "adapter_ref": COMPONENT,
                  "policy_revision": nullable(STRING), "request_ref": nullable(ARTIFACT),
                  "response_ref": nullable(ARTIFACT), "requested_params": OBJECT,
                  "effective_params": OBJECT, "tokenizer_ref": nullable(ARTIFACT),
                  "chat_template_ref": nullable(ARTIFACT), "native_inputs_ref": nullable(ARTIFACT),
                  "prompt_token_ids_ref": nullable(ARTIFACT), "response_token_ids_ref": nullable(ARTIFACT),
                  "logprobs_ref": nullable(ARTIFACT), "usage": nullable(OBJECT),
                  "error": nullable(error), "capture": capture})
    schemas.register("gymts.model-call/1", obj(model))
    tool = dict(identity, **timing)
    tool.update({"protocol_version": {"const": "gymts.tool-call/1"}, "tool_ref": COMPONENT,
                 "arguments_ref": nullable(ARTIFACT), "result_ref": nullable(ARTIFACT),
                 "error": nullable(error), "environment_request_id": nullable(STRING),
                 "operation_id": nullable(STRING)})
    schemas.register("gymts.tool-call/1", obj(tool))
    schemas.register("gymts.token-ids/1", array({"type": "integer", "minimum": 0}, minItems=1))
    sequence_hash = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
    schemas.register("gymts.logprobs/1", obj({
        "protocol_version": {"const": "gymts.logprobs/1"},
        "source": {"enum": ["captured", "recomputed"]}, "call_id": STRING, "attempt_id": STRING,
        "prompt_sequence_hash": sequence_hash, "response_sequence_hash": sequence_hash,
        "values": array({"type": "number", "maximum": 0}), "policy_ref": nullable(ARTIFACT),
        "policy_revision": nullable(STRING), "distribution": {"enum": ["model", "sampling"]},
        "effective_params": OBJECT, "computation_ref": nullable(COMPONENT)}))
    # The model adapter owns the tensor/processor layout. A generic collector
    # verifies its immutable reference; a trainer validates the chosen layout.
    schemas.register("gymts.native-inputs/1", OBJECT)
