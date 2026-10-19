"""Versioned schemas and manifests for the ChatTS integration."""

import copy

from gymts.contracts.schema import ARTIFACT, OBJECT, STRING, array, nullable, obj
from gymts.plugin_support import component

TASK_IDS = ["pattern.trend_direction", "anomaly.point_indices", "forecast.numeric",
            "pattern.seasonality_profile", "process.stationarity_type",
            "relation.lagged_dependence", "similarity.shape_retrieval"]


def chatts_schemas():
    token = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    model_input = obj({
        "messages": array(obj({"role": {"enum": ["system", "user", "assistant"]}, "content": STRING}), minItems=1),
        "timeseries": array(array({"type": "number"}, minItems=1), minItems=1),
        "series_names": array(STRING, minItems=1), "output_schema": OBJECT, "context": OBJECT})
    sample = obj({"sample_token": token, "task_id": {"enum": TASK_IDS}, "task_version": STRING,
                  "model_input": model_input})
    task_params = obj({"task_id": {"enum": TASK_IDS}, "task_version": {"enum": ["0.1.0", "0.2.0"]}})
    http_params = obj({"base_url": {"type": "string", "minLength": 1},
        "model": {"type": "string", "minLength": 1}, "model_revision": {"type": "string", "minLength": 1},
        "dialect": {"enum": ["chatts-timeseries/v1", "chatts-vllm-text-envelope/v1"]},
        "timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
        "max_tokens": {"type": "integer", "minimum": 1}, "temperature": {"type": "number", "minimum": 0},
        "top_p": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
        "api_key_env": nullable(STRING), "expected_system_fingerprint": nullable(STRING),
        "enable_thinking": nullable({"type": "boolean"}), "json_object": {"type": "boolean"}},
        required=["base_url", "model", "model_revision"])
    text_http_params = copy.deepcopy(http_params)
    text_http_params["properties"].pop("enable_thinking")
    text_http_params["properties"]["dialect"] = {"const": "openai-chat-timeseries-text/v1"}
    text_http_params["properties"]["thinking_mode"] = {"enum": [None, "disabled", "enabled"]}
    return {
        "gymts.chatts/sample-token/1": token,
        "gymts.chatts/input/1": model_input,
        "gymts.chatts/native/1": sample,
        "gymts.chatts/context/1": obj({"dataset_revision": STRING, "sample_count": {"type": "integer", "minimum": 1}}),
        "gymts.chatts.snapshot/1": obj({"schema_version": {"const": "gymts.chatts.snapshot/1"},
            "dataset_revision": STRING, "samples": array(sample, minItems=1)}),
        "gymts.chatts/source/1": obj({"kind": {"const": "dataset"}, "locator": STRING, "revision": STRING,
            "connection": obj({"artifact_refs": array(ARTIFACT, minItems=1, maxItems=1)}),
            "credential_ref": {"type": "null"}}),
        "gymts.chatts/empty/1": obj({}),
        "gymts.chatts/options/1": obj({"sample_tokens": array(token, minItems=1, uniqueItems=True)}),
        "gymts.chatts/task-params/1": task_params,
        "gymts.chatts/http-params/1": http_params,
        "gymts.chatts/text-http-params/1": text_http_params,
        "gymts.chatts/baseline-params/1": obj({"task_id": {"enum": TASK_IDS}}),
        "gymts.chatts/output/1": obj({"raw_text": {"type": "string"}, "evidence": OBJECT}),
        "gymts.chatts/result/1": obj({"raw_text": {"type": "string"}, "parsed": nullable(OBJECT),
            "reason": nullable(STRING), "parser_ref": {"const": "chatts.structured-json/1"}}),
        "gymts.chatts/outcome/1": obj({"task_id": {"enum": TASK_IDS}, "task_version": STRING, "expected_output": OBJECT}),
        "gymts.chatts/alignment/1": obj({"dataset_revision": STRING, "sample_token": token}),
    }


def _manifest(name, protocols, params):
    return {"component_ref": component(name), "protocol_versions": protocols,
            "params_schema_ref": params, "origin_ref": None}


def register_chatts_plugins(registries, schemas):
    from .environment import ChatTSSnapshotEnvironment
    from .task import ChatTSSyntheticQATask
    from .scoring import ChatTSQAScorer
    from .candidate import ChatTSHTTPCandidate, ChatTSSignalBaseline
    from .text_candidate import TextLLMHTTPCandidate
    protocol = "gymts.task/chatts-qa/1"
    for ref, definition in chatts_schemas().items():
        schemas.register(ref, definition)
    item = _manifest("chatts-synthetic-snapshot", ["gymts.environment/1"], None)
    item.update(source_schema_ref="gymts.chatts/source/1", mapping_schema_ref="gymts.chatts/empty/1",
                options_schema_ref="gymts.chatts/options/1")
    registries.environments.register(item, ChatTSSnapshotEnvironment)
    item = _manifest("chatts-synthetic-qa", ["gymts.task/1", protocol], "gymts.chatts/task-params/1")
    item.update(task_protocol_ref=protocol, input_schema_ref="gymts.chatts/input/1",
        output_schema_ref="gymts.chatts/output/1", result_schema_ref="gymts.chatts/result/1",
        outcome_schema_ref="gymts.chatts/outcome/1", alignment_schema_ref="gymts.chatts/alignment/1")
    registries.tasks.register(item, ChatTSSyntheticQATask)
    for name, params, factory in (
            ("chatts-http", "gymts.chatts/http-params/1", ChatTSHTTPCandidate),
            ("chatts-text-http", "gymts.chatts/text-http-params/1", TextLLMHTTPCandidate),
            ("chatts-signal-baseline", "gymts.chatts/baseline-params/1", ChatTSSignalBaseline)):
        item = _manifest(name, ["gymts.candidate/1", protocol], params)
        item.update(implementation_ref=component(name), component_refs=[], supported_task_protocols=[protocol],
            input_schema_refs=["gymts.chatts/input/1"], output_schema_refs=["gymts.chatts/output/1"],
            supports_fit=False, fit_requires_targets=False, supports_update=False,
            model_revision_mode="fixed", capture_profiles=[])
        registries.candidates.register(item, factory)
    item = _manifest("chatts-qa-scorer", ["gymts.scorer/1"], "gymts.chatts/task-params/1")
    item.update(supported_task_protocols=[protocol], supported_alignment_matchings=["exact"],
        result_schema_refs=["gymts.chatts/result/1"], outcome_schema_refs=["gymts.chatts/outcome/1"],
        metrics={metric: {"direction": "lower_better" if metric in ("mae", "rmse") else "higher_better",
            "unit": "value" if metric in ("mae", "rmse") else "ratio", "requires_outcome": True,
            "eligibility_ref": component("one-planned-chatts-sample"),
            "eligibility_schema_ref": "gymts.chatts/alignment/1"}
            for metric in ("accuracy", "exact_match", "event_f1", "mae", "rmse")})
    registries.scorers.register(item, ChatTSQAScorer)
