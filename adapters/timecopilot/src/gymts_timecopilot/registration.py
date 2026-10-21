"""Only a Candidate is added; neutral environments/tasks/scorers stay external."""
from gymts.contracts.schema import OBJECT, STRING, array, obj
from gymts.plugin_support import component
from gymts_timeseries.contracts import INPUT, OUTPUT, PROTOCOL, domain_schemas
from .source import FORECASTERS, TOOLS, implementation_ref

PARAMS = "gymts.timecopilot/params/1"
IDENTITY = "gymts.timecopilot/identity/1"
EVENT = "gymts.timecopilot/native-event/1"
SESSION = "gymts.timecopilot/session/1"


def register_timecopilot_plugins(registries, schemas):
    from .candidate import TimeCopilotCandidate
    for ref, definition in domain_schemas().items():
        schemas.register(ref, definition)
    positive = {"type": "integer", "minimum": 1}
    schemas.register(PARAMS, obj({
        "implementation": obj({"repository": STRING, "python": STRING, "revision": STRING},
                              required=["repository", "python"]),
        "model": obj({"base_url": STRING, "name": STRING, "revision": STRING,
                      "credential_env": STRING, "tool_choice_mode": {"enum": ["required", "auto"]}}, required=["base_url", "name", "revision"]),
        "forecasters": array({"enum": list(FORECASTERS)}, minItems=1, uniqueItems=True),
        "limits": obj({"max_requests": positive, "max_total_tokens": positive,
                       "max_response_tokens": positive, "max_tool_calls": positive,
                       "max_wall_time_s": {"type": "number", "exclusiveMinimum": 0}},
                      required=["max_requests", "max_total_tokens", "max_response_tokens", "max_tool_calls", "max_wall_time_s"]),
        "temperature": {"type": "number", "minimum": 0, "maximum": 2},
        "retries": {"type": "integer", "minimum": 0, "maximum": 8}},
        required=["implementation", "model", "limits"]))
    for schema in (IDENTITY, EVENT, SESSION):
        schemas.register(schema, OBJECT)
    item = {"component_ref": component("timecopilot-agent"),
        "protocol_versions": ["gymts.candidate/1", PROTOCOL], "params_schema_ref": PARAMS,
        "origin_ref": None, "implementation_ref": implementation_ref(),
        "component_refs": [{"name": "timecopilot." + name, "version": implementation_ref()["version"], "origin_ref": None}
                           for name in TOOLS],
        "supported_task_protocols": [PROTOCOL], "input_schema_refs": [INPUT], "output_schema_refs": [OUTPUT],
        "supports_fit": False, "fit_requires_targets": False, "supports_update": False,
        "model_revision_mode": "fixed", "capture_profiles": ["io"],
        "execution_semantics": {"prepare": "verify_local_native_runtime_and_fixed_llm_configuration",
            "infer": "native_TimeCopilot_analyze_agent_with_current_input_tools",
            "persistent_training": False, "cross_call_state": False,
            "tool_scope": "current_authorized_history_only",
            "tool_order": "upstream_system_prompt", "allowed_forecasters": list(FORECASTERS)}}
    registries.candidates.register(item, TimeCopilotCandidate)
