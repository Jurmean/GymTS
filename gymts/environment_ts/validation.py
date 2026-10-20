"""Static assembly checks. No environment start/reset/act or Candidate fitting."""
from __future__ import annotations

import copy
from gymts.contracts import (GymTSError, duration_seconds, parse_time, shift_time,
                             time_compare)
from gymts.contracts.schema import (ARTIFACT, COMPONENT, OBJECT, PAYLOAD, STRING,
                                    array, nullable, obj)


def check_descriptions(env, task, schemas):
    variable = obj({"dtype": {"enum": ["float32", "float64", "int32", "int64", "bool", "string"]},
                    "shape": array(nullable({"type": "integer", "minimum": 0})),
                    "unit": STRING, "time_semantics": STRING, "schema_ref": STRING})
    operation = obj({"arguments_schema_ref": STRING, "receipt_schema_ref": STRING,
                     "changes_state": {"type": "boolean"}, "idempotent": {"type": "boolean"}})
    env_schema = obj({"environment_id": STRING, "adapter_ref": COMPONENT,
        "clock_domain": {"enum": ["event_time", "wall_time", "step"]},
        "observation_granularity": {"enum": ["time_window", "transition"]},
        "advance_mode": {"enum": ["on_observe", "on_action", "external"]},
        "variables": {"type": "object", "additionalProperties": variable},
        "operations": {"type": "object", "additionalProperties": operation},
        "capabilities": obj({k: {"type": "boolean"} for k in
            ("range", "query", "history", "reinitialize", "attach", "seed", "operation_idempotency")}),
        "context_schema_ref": nullable(STRING), "native_schema_ref": nullable(STRING),
        "default_command": nullable(obj({"name": STRING, "arguments": PAYLOAD}))})
    task_schema = obj({"plugin_ref": COMPONENT, "task_protocol_ref": STRING,
        "input_schema_ref": STRING, "output_schema_ref": STRING, "result_schema_ref": STRING,
        "outcome_schema_ref": nullable(STRING), "alignment_schema_ref": STRING,
        "required_variables": {"type": "object", "additionalProperties": obj({
            "dtype": STRING, "shape": array(nullable({"type": "integer", "minimum": 0})), "unit": STRING})},
        "required_operations": {"type": "object", "additionalProperties": obj({"arguments_schema_ref": STRING})},
        "required_capabilities": array(STRING, uniqueItems=True), "use_default_command": {"type": "boolean"},
        "warmup": obj({"duration": nullable(STRING), "min_points": {"type": "integer", "minimum": 0}})})
    schemas._validate(env_schema, env, "$.environment.describe")
    schemas._validate(task_schema, task, "$.task.describe")
    for definition in env["variables"].values():
        schemas.resolve(definition["schema_ref"])
    for definition in env["operations"].values():
        schemas.resolve(definition["arguments_schema_ref"])
        schemas.resolve(definition["receipt_schema_ref"])
    for key in ("context_schema_ref", "native_schema_ref"):
        if env[key] is not None:
            schemas.resolve(env[key])


def resolved_defaults(spec: dict, artifacts=None) -> dict:
    value = copy.deepcopy(spec)
    if not isinstance(value, dict):
        raise GymTSError("invalid_config", "ExperimentSpec must be an object")
    if "scene_ref" in value:
        if "scene" in value:
            raise GymTSError("invalid_config", "scene and scene_ref are mutually exclusive")
        if artifacts is None:
            raise GymTSError("unsupported_capability", "Offline planning requires an inline scene; scene_ref is resolved only for execution")
        value["scene"] = artifacts.read_json(value.pop("scene_ref"))
    value.setdefault("name", None)
    value.setdefault("purpose", "development")
    value.setdefault("extensions", {})
    value.setdefault("provenance", {})
    if isinstance(value["provenance"], dict):
        for key, default in (("source_refs", []), ("usage_policy_ref", None), ("benchmark_definition_ref", None)):
            value["provenance"].setdefault(key, default)
    if isinstance(value.get("candidate"), dict):
        value["candidate"].setdefault("inherited_state", [])
    execution = value.get("execution", {})
    if isinstance(execution, dict):
        execution.setdefault("feedback_until", None)
        execution.setdefault("seed", None)
        limits = execution.get("limits", {})
        if isinstance(limits, dict):
            for key, default in {"max_inputs": None, "max_operations": None,
                                 "max_turns_per_case": 32, "max_wall_time_s": None}.items():
                limits.setdefault(key, default)
    recording = value.get("recording", {})
    if isinstance(recording, dict):
        for key, default in {"model_calls": "none", "on_capture_failure": "fail_run",
                             "redaction_policy_ref": None, "extra_event_kinds": []}.items():
            recording.setdefault(key, default)
    return value


def ensure(condition: bool, message: str, code="invalid_config") -> None:
    if not condition:
        raise GymTSError(code, message)


def compile_read_scope(execution: dict, description: dict, task: dict) -> dict:
    scope = execution["scope"]
    start, end = scope["start"], scope["end"]
    step = description["clock_domain"] == "step"
    ensure(isinstance(parse_time(start), int) == step, "Scope does not match environment clock domain")
    if end is not None:
        ensure(time_compare(start, end) < 0, "Scope must be nonempty")
    feedback = execution["feedback_until"]
    ensure(end is not None or feedback is None, "feedback_until requires finite scope.end")
    if feedback is not None:
        ensure(time_compare(feedback, end) >= 0, "feedback_until precedes scope.end")
    warmup = task["warmup"]
    if step:
        ensure(description["observation_granularity"] == "transition", "Step clocks require transition")
        ensure(warmup["duration"] is None, "Step clocks do not support warmup durations", "unsupported_capability")
    elif warmup["duration"] is not None:
        seconds = duration_seconds(warmup["duration"])
        if description["capabilities"]["history"]:
            start = shift_time(start, -seconds)
    limits = execution["limits"]
    ensure(end is not None or any(limits[k] is not None for k in
           ("max_inputs", "max_operations", "max_wall_time_s")), "Run needs a finite stopping boundary")
    if description["advance_mode"] == "external":
        ensure((end is not None and description["clock_domain"] == "wall_time") or
               limits["max_wall_time_s"] is not None, "External waits need a wall-clock deadline")
    if description["advance_mode"] != "on_action" and end is None:
        ensure(limits["max_inputs"] is not None or limits["max_wall_time_s"] is not None,
               "Operation-only limit cannot stop a read-only Run")
    return {"start": start, "end": feedback if feedback is not None else end}


def check_compatibility(spec, env, task, manifests, schemas, artifacts, store_refs):
    em, tm, cm = manifests
    schemas.validate("gymts.experiment/1", spec)
    schemas.validate("gymts.extensions/1", spec["extensions"])
    check_descriptions(env, task, schemas)
    es = spec["scene"]["environment"]
    ensure(es["protocol_version"] in em["protocol_versions"], "Environment protocol unsupported", "unsupported_capability")
    for field, key in (("source_schema_ref", "source"), ("mapping_schema_ref", "mapping"),
                       ("options_schema_ref", "options")):
        schemas.validate(em[field], es[key])
    for manifest, component in ((tm, spec["scene"]["task"]), (cm, spec["candidate"])):
        schemas.validate(manifest["params_schema_ref"], component["params"])
    if es["source"]["kind"] != "live":
        ensure(es["source"]["revision"] not in (None, "latest", "main", "master"),
               "Non-live source needs a fixed revision")
    ensure(env["adapter_ref"] == em["component_ref"], "Environment describe identity differs from manifest")
    ensure(task["plugin_ref"] == tm["component_ref"], "Task describe identity differs from manifest")
    for key in ("task_protocol_ref", "input_schema_ref", "output_schema_ref", "result_schema_ref",
                "outcome_schema_ref", "alignment_schema_ref"):
        ensure(task[key] == tm[key], f"Task description differs from manifest: {key}")
        if key.endswith("schema_ref") and task[key] is not None:
            schemas.resolve(task[key])
    ensure(task["task_protocol_ref"] in cm["supported_task_protocols"], "Candidate task incompatible", "unsupported_capability")
    ensure(task["input_schema_ref"] in cm["input_schema_refs"] and
           task["output_schema_ref"] in cm["output_schema_refs"], "Candidate I/O incompatible", "schema_mismatch")
    caps = env["capabilities"]
    for key in ("range", "query", "history", "reinitialize", "attach", "seed", "operation_idempotency"):
        ensure(isinstance(caps.get(key), bool), f"Environment capability missing: {key}")
    ensure(caps[spec["execution"]["start"]["mode"]], "Environment start mode unsupported", "unsupported_capability")
    if spec["execution"]["seed"] is not None:
        ensure(caps["seed"], "Environment cannot honor seed", "unsupported_capability")
    for cap in task["required_capabilities"]:
        ensure(caps.get(cap, False), f"Task needs capability {cap}", "unsupported_capability")
    binding = spec["scene"]["binding"]
    variables = []
    for name, required in task["required_variables"].items():
        ensure(name in binding["variables"], f"Missing variable binding: {name}")
    for name, item in binding["variables"].items():
        ensure(item["source"] in env["variables"], f"Unknown source variable: {name}")
        actual = env["variables"][item["source"]]
        ensure(item["transform"] is None, "Binding transforms require a registered provider", "unsupported_capability")
        ensure(item["unit"] == actual["unit"], f"Unit mismatch for {name}")
        if name in task["required_variables"]:
            required = task["required_variables"][name]
            ensure(all(actual.get(k) == required.get(k) for k in ("dtype", "shape", "unit")),
                   f"Variable type/shape/unit incompatible: {name}")
        variables.append(item["source"])
    operations = []
    for name in task["required_operations"]:
        ensure(name in binding["operations"], f"Missing operation binding: {name}")
        ensure(task["required_operations"][name]["arguments_schema_ref"] == binding["operations"][name]["arguments_schema_ref"],
               f"Task operation parameter schema mismatch: {name}", "schema_mismatch")
    for name, item in binding["operations"].items():
        ensure(item["source"] in env["operations"], f"Unknown operation: {name}")
        ensure(item["transform"] is None, "Operation transforms unavailable", "unsupported_capability")
        ensure(item["arguments_schema_ref"] == env["operations"][item["source"]]["arguments_schema_ref"],
               f"Operation arguments incompatible: {name}")
        schemas.resolve(item["arguments_schema_ref"])
        operations.append(item["source"])
    if task.get("use_default_command", False):
        ensure(env["default_command"] is not None, "Task asks for an undefined default command")
        name = env["default_command"]["name"]
        ensure(name in env["operations"], "Default command unavailable")
        operations.append(name)
    learning = spec["execution"]["learning"]
    if learning["prepare"] == "fit":
        ensure(cm["supports_fit"] and learning["training_view"] is not None, "Candidate fitting unavailable", "unsupported_capability")
        if cm["fit_requires_targets"]:
            ensure(learning["training_targets"] is not None, "Candidate requires training targets")
    else:
        ensure(learning["training_view"] is None and learning["training_targets"] is None,
               "load_only must not include fitting views")
    if learning["training_targets"] is not None:
        ensure(learning["alignment_schema_ref"] is not None, "Training target pairing schema required")
        schemas.resolve(learning["alignment_schema_ref"])
    if learning["online"] == "update":
        ensure(cm["supports_update"] and learning["allowed_feedback_sources"],
               "Online update needs capability and authorized sources", "unsupported_capability")
    if learning["online"] == "frozen":
        ensure(cm["model_revision_mode"] != "unknown", "Frozen model needs a verifiable revision", "unsupported_capability")
    for key in ("training_view", "training_targets"):
        view = learning[key]
        if view is not None:
            ensure(view["purpose"] == "prepare", "Training view purpose must be prepare", "permission_denied")
            schemas.validate("gymts.view/1", view)
            # Planning checks the view declaration, not the underlying data.
    for ref in [spec["candidate"]["artifact"]] + spec["candidate"]["inherited_state"]:
        if ref is not None:
            schemas.validate("gymts.artifact/1", ref)
    recording = spec["recording"]
    ensure(recording["store_ref"] in store_refs, "Unknown recording store_ref")
    ensure(recording["model_calls"] == "none" or recording["model_calls"] in cm["capture_profiles"],
           "Candidate does not declare the requested model-call capture profile", "unsupported_capability")
    ensure(recording["redaction_policy_ref"] is None, "No redaction adapter installed", "unsupported_capability")
    ensure(not recording["extra_event_kinds"], "No extension event schemas installed", "unsupported_capability")
    return sorted(set(variables)), sorted(set(operations)), compile_read_scope(spec["execution"], env, task)


def check_execution_resources(spec, artifacts, schemas):
    """Resolve actual bytes only after the execution Run has begun."""
    refs = spec["scene"]["environment"]["source"].get("connection", {}).get("artifact_refs", [])
    for ref in refs:
        artifacts.resolve(ref)
    learning = spec["execution"]["learning"]
    for key in ("training_view", "training_targets"):
        if learning[key] is not None:
            artifacts.read_view(learning[key])
    for ref in [spec["candidate"]["artifact"]] + spec["candidate"]["inherited_state"]:
        if ref is not None:
            artifacts.resolve(ref)
    provenance = spec.get("provenance", {})
    for ref in list(provenance.get("source_refs", [])) + [provenance.get("usage_policy_ref"), provenance.get("benchmark_definition_ref")]:
        if ref is not None:
            artifacts.resolve(ref)
    policy_ref = provenance.get("usage_policy_ref")
    if policy_ref is not None:
        ensure(policy_ref["schema_ref"] == "gymts.source-usage-policy/1", "Source usage policy has an unsupported schema", "schema_mismatch")
        policy = artifacts.read_json(policy_ref)
        schemas.validate("gymts.source-usage-policy/1", policy)
        if spec["purpose"] == "training_collection":
            ensure(policy["training_allowed"] and bool(set(policy["allowed_uses"]) & {"training", "prepare", "dataset_build"}), "Source policy does not authorize collection for training", "permission_denied")
