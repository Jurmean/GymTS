"""Ordinary text LLM transport for lossless named numeric time-series input.

This is a separate Candidate from native ChatTS. The model receives JSON text,
and a configured service alias does not identify or pin its underlying weights.
"""
import copy

from gymts.contracts import canonical_json
from gymts.http_candidate import FrozenJSONHTTPCandidate
from gymts.plugin_support import fail as _fail
from .qa_contract import OUTPUT, PLACEHOLDER, PROTOCOL, load_qa_input


class TextLLMHTTPCandidate(FrozenJSONHTTPCandidate):
    DIALECTS = ("openai-chat-timeseries-text/v1",)
    SEED_DIALECTS = DIALECTS
    DEFAULTS = {"dialect": DIALECTS[0], "timeout_seconds": 120.0,
                "max_tokens": 512, "temperature": 0.0, "top_p": 1.0,
                "api_key_env": None, "expected_system_fingerprint": None,
                "json_object": False, "thinking_mode": None}
    KIND = "text_llm_http"
    NORMALIZATION = "none"
    REVISION_PROVENANCE = "configured_alias"
    TASK_PROTOCOL_REF = PROTOCOL
    OUTPUT_SCHEMA_REF = OUTPUT
    INPUT_REPRESENTATION = "named_numeric_json/v1"

    def _load_input(self, task_input):
        return load_qa_input(task_input, self.resources)

    def _request_metadata(self, model_input):
        return {"native_timeseries": model_input["timeseries"],
                "series_names": model_input["series_names"]}

    def _validate_controls(self):
        if type(self.params["json_object"]) is not bool:
            _fail("invalid_config", "json_object must be a boolean", "configure")
        if self.params["thinking_mode"] not in (None, "disabled", "enabled"):
            _fail("invalid_config", "thinking_mode must be disabled, enabled, or null", "configure")

    def _representation_metadata(self):
        return {"input_representation": self.INPUT_REPRESENTATION,
                "model_revision_semantics": "configured_service_alias",
                "weights_pinned": False}

    def _numeric_json(self, names, arrays):
        return canonical_json({"representation": self.INPUT_REPRESENTATION,
                               "series": [{"name": name, "values": values}
                                          for name, values in zip(names, arrays)]}).decode("utf-8")

    def _wire(self, model_input):
        messages = copy.deepcopy(model_input["messages"])
        final_user = next((i for i in range(len(messages) - 1, -1, -1) if messages[i]["role"] == "user"), None)
        if final_user is None:
            _fail("schema_mismatch", "Numeric text input requires a user message", "infer")
        text = messages[final_user]["content"]
        count = sum(message["content"].count(PLACEHOLDER) for message in messages)
        if count and count != text.count(PLACEHOLDER):
            _fail("schema_mismatch", "Numeric time-series placeholders must belong to the final user message", "infer")
        if count:
            chunks = text.split(PLACEHOLDER)
            inserted = []
            for i, chunk in enumerate(chunks[:-1]):
                inserted.extend((chunk, self._numeric_json([model_input["series_names"][i]], [model_input["timeseries"][i]])))
            inserted.append(chunks[-1])
            messages[final_user]["content"] = "".join(inserted)
        else:
            messages[final_user]["content"] = text + "\n\nTime series data (named_numeric_json/v1; original numerical values and order):\n" + self._numeric_json(
                model_input["series_names"], model_input["timeseries"])
        wire = {"model": self.model, "messages": messages, "stream": False,
                "temperature": self.params["temperature"], "top_p": self.params["top_p"],
                "max_tokens": self.params["max_tokens"]}
        if self.params["json_object"]:
            wire["response_format"] = {"type": "json_object"}
        if self.params["thinking_mode"] is not None:
            wire["thinking"] = {"type": self.params["thinking_mode"]}
        return wire
