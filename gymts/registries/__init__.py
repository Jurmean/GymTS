"""Version-exact component factories with conflict and schema checks."""
from __future__ import annotations

import copy
from typing import Callable
from gymts.contracts import GymTSError, canonical_json
from gymts.contracts.schema import (ARTIFACT, COMPONENT, STRING, SchemaRegistry,
                                    array, nullable, obj)


class ComponentRegistry:
    def __init__(self, kind: str, schemas: SchemaRegistry):
        self.kind, self.schemas = kind, schemas
        self._entries = {}

    def register(self, manifest: dict, factory: Callable) -> None:
        required = {"component_ref", "protocol_versions", "params_schema_ref", "origin_ref"}
        specific = {
            "environment": {"source_schema_ref", "mapping_schema_ref", "options_schema_ref"},
            "task": {"task_protocol_ref", "input_schema_ref", "output_schema_ref", "result_schema_ref", "outcome_schema_ref", "alignment_schema_ref"},
            "candidate": {"implementation_ref", "component_refs", "supported_task_protocols", "input_schema_refs", "output_schema_refs", "supports_fit", "fit_requires_targets", "supports_update", "model_revision_mode", "capture_profiles"},
            "scorer": {"supported_task_protocols", "result_schema_refs", "outcome_schema_refs", "metrics"},
        }[self.kind]
        if not isinstance(manifest, dict) or not required | specific <= set(manifest) or not (
                callable(factory) or callable(getattr(factory, "create", None))):
            raise GymTSError("invalid_config", f"Incomplete {self.kind} registration")
        # Validate the entire declaration before iterating references or using
        # them as dictionary keys. Malformed plugins must fail at registration.
        fields = {"component_ref": COMPONENT, "protocol_versions": array(STRING, minItems=1, uniqueItems=True),
                  "params_schema_ref": nullable(STRING), "origin_ref": nullable(ARTIFACT)}
        if self.kind == "environment":
            fields.update({name: STRING for name in specific})
        elif self.kind == "task":
            fields.update({name: nullable(STRING) if name == "outcome_schema_ref" else STRING
                           for name in specific})
        elif self.kind == "candidate":
            fields.update(implementation_ref=COMPONENT, component_refs=array(COMPONENT),
                supported_task_protocols=array(STRING, minItems=1, uniqueItems=True),
                input_schema_refs=array(STRING, minItems=1, uniqueItems=True),
                output_schema_refs=array(STRING, minItems=1, uniqueItems=True),
                supports_fit={"type": "boolean"}, fit_requires_targets={"type": "boolean"},
                supports_update={"type": "boolean"}, capture_profiles=array(STRING, uniqueItems=True),
                model_revision_mode={"enum": ["none", "fixed", "tracked", "unknown"]})
        else:
            fields.update(supported_task_protocols=array(STRING, minItems=1, uniqueItems=True),
                result_schema_refs=array(STRING, minItems=1, uniqueItems=True),
                outcome_schema_refs=array(STRING, uniqueItems=True),
                metrics={"type": "object", "minProperties": 1, "additionalProperties": obj({
                    "direction": {"enum": ["higher_better", "lower_better", "descriptive"]},
                    "unit": {"type": "string"}, "requires_outcome": {"type": "boolean"},
                    "eligibility_ref": COMPONENT, "eligibility_schema_ref": STRING})})
            if "supported_alignment_matchings" in manifest:
                fields["supported_alignment_matchings"] = array(
                    {"enum": ["exact", "interval", "tolerance"]}, minItems=1, uniqueItems=True)
        try:
            canonical_json(manifest)
        except (TypeError, ValueError) as exc:
            raise GymTSError("invalid_config", "Manifest must contain finite JSON") from exc
        self.schemas._validate(obj(fields, additional=True), manifest, "$.manifest")
        component_ref = manifest["component_ref"]
        references = [component_ref]
        if self.kind == "candidate":
            references += [manifest["implementation_ref"]] + manifest["component_refs"]
        elif self.kind == "scorer":
            references += [metric["eligibility_ref"] for metric in manifest["metrics"].values()]
        if any(ref["version"] in {"latest", "main", "master"} for ref in references):
            raise GymTSError("invalid_config", "Component versions must be fixed")
        versions = manifest["protocol_versions"]
        expected = f"gymts.{self.kind}/1"
        if not isinstance(versions, list) or expected not in versions or not all(
                isinstance(v, str) and v.endswith("/1") for v in versions):
            raise GymTSError("unsupported_capability", f"Component must declare compatible protocol {expected}")
        if self.kind == "environment" and manifest["params_schema_ref"] is not None:
            raise GymTSError("invalid_config", "Environment does not have a params schema")
        if self.kind != "environment" and manifest["params_schema_ref"] is None:
            raise GymTSError("invalid_config", "Component needs a params schema")
        if self.kind == "candidate":
            self.schemas.validate("gymts.component/1", manifest["implementation_ref"])
            for part_ref in manifest["component_refs"]:
                self.schemas.validate("gymts.component/1", part_ref)
            for key in ("supports_fit", "supports_update", "fit_requires_targets"):
                if type(manifest[key]) is not bool:
                    raise GymTSError("invalid_config", f"Manifest.{key} must be boolean")
            if manifest["model_revision_mode"] not in ("none", "fixed", "tracked", "unknown"):
                raise GymTSError("invalid_config", "Unknown model revision mode")
        for key in ("supported_task_protocols", "input_schema_refs", "output_schema_refs", "result_schema_refs", "outcome_schema_refs", "capture_profiles"):
            if key in manifest and (not isinstance(manifest[key], list) or not all(isinstance(x, str) for x in manifest[key])):
                raise GymTSError("invalid_config", f"Manifest.{key} must be a string list")
        for field, value in manifest.items():
            if field.endswith("schema_ref") and value is not None:
                self.schemas.resolve(value)
            elif field.endswith("schema_refs"):
                for schema in value:
                    self.schemas.resolve(schema)
        if self.kind == "scorer":
            for metric in manifest.get("metrics", {}).values():
                self.schemas.resolve(metric["eligibility_schema_ref"])
                self.schemas.validate("gymts.component/1", metric["eligibility_ref"])
        key = (component_ref["name"], component_ref["version"])
        if key in self._entries:
            old, old_factory = self._entries[key]
            if old != manifest or old_factory is not factory:
                raise GymTSError("conflict", f"Registration already exists: {key}")
            return
        canonical_json(manifest)
        self._entries[key] = (copy.deepcopy(manifest), factory)

    def resolve(self, name: str, version: str) -> dict:
        if not isinstance(name, str) or not name or not isinstance(version, str) or not version:
            raise GymTSError("invalid_config", "Component name and version must be nonempty strings")
        if (name, version) not in self._entries:
            raise GymTSError("unsupported_capability", f"Unregistered {self.kind}: {name}@{version}")
        return copy.deepcopy(self._entries[(name, version)][0])

    def create(self, spec: dict, *args):
        name = spec["plugin"] if self.kind == "task" else spec["adapter"]
        manifest = self.resolve(name, spec["version"])
        if manifest["params_schema_ref"] is not None:
            self.schemas.validate(manifest["params_schema_ref"], spec["params"])
        factory = self._entries[(name, spec["version"])][1]
        if callable(getattr(factory, "create", None)):
            return factory.create(copy.deepcopy(spec), *args)
        return factory(copy.deepcopy(spec), *args)

    def manifests(self) -> list:
        return [copy.deepcopy(v[0]) for _, v in sorted(self._entries.items())]


class EnvironmentRegistry(ComponentRegistry):
    def __init__(self, schemas):
        super().__init__("environment", schemas)


class TaskRegistry(ComponentRegistry):
    def __init__(self, schemas):
        super().__init__("task", schemas)


class CandidateRegistry(ComponentRegistry):
    def __init__(self, schemas):
        super().__init__("candidate", schemas)


class ScorerRegistry(ComponentRegistry):
    def __init__(self, schemas):
        super().__init__("scorer", schemas)


class Registries:
    def __init__(self, schemas: SchemaRegistry):
        self.environments = EnvironmentRegistry(schemas)
        self.tasks = TaskRegistry(schemas)
        self.candidates = CandidateRegistry(schemas)
        self.scorers = ScorerRegistry(schemas)

