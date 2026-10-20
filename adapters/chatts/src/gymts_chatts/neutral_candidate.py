"""Model-owned codecs from the shared numerical task to native model requests.

Only this adapter constructs messages and ChatTS placeholders. The public task
and all numerical source providers remain independent of those wire formats.
"""
import copy

from gymts.contracts import canonical_json, utc_now
from gymts.plugin_support import fail, payload, unpack
from gymts_timeseries.contracts import INPUT, OUTPUT, PROTOCOL, validate_input

from .candidate import ChatTSHTTPCandidate, ChatTSSignalBaseline
from .text_candidate import TextLLMHTTPCandidate

CODEC_REF = "gymts.chatts/model-neutral-qa-codec/1"


def encode_input(value, *, native=False):
    """Construct the model's request representation after public task delivery."""
    value = validate_input(value)
    text = value["question"] + "\nResponse JSON schema: " + canonical_json(value["response_schema"]).decode("utf-8")
    if native:
        for item in value["series"]:
            text += "\n" + item["name"] + ": <ts><ts/>"
    return {"messages": [{"role": "user", "content": text}],
        "timeseries": [copy.deepcopy(item["values"]) for item in value["series"]],
        "series_names": [item["name"] for item in value["series"]],
        "output_schema": copy.deepcopy(value["response_schema"]), "context": copy.deepcopy(value["context"])}


def _load(task_input, resources):
    if task_input.get("task_protocol_ref") != PROTOCOL or task_input["payload"]["schema_ref"] != INPUT:
        fail("schema_mismatch", "Candidate requires the model-neutral time-series QA contract")
    return validate_input(unpack(task_input["payload"], resources))


class NeutralChatTSHTTPCandidate(ChatTSHTTPCandidate):
    TASK_PROTOCOL_REF, OUTPUT_SCHEMA_REF = PROTOCOL, OUTPUT

    def _load_input(self, task_input):
        return encode_input(_load(task_input, self.resources), native=True)

    def _representation_metadata(self):
        return {"codec_ref": CODEC_REF, "task_protocol_ref": PROTOCOL}


class NeutralTextLLMHTTPCandidate(TextLLMHTTPCandidate):
    TASK_PROTOCOL_REF, OUTPUT_SCHEMA_REF = PROTOCOL, OUTPUT

    def _load_input(self, task_input):
        return encode_input(_load(task_input, self.resources))

    def _representation_metadata(self):
        return dict(super()._representation_metadata(), codec_ref=CODEC_REF, task_protocol_ref=PROTOCOL)


class NeutralSignalBaseline(ChatTSSignalBaseline):
    REVISION = "timeseries-signal-baseline/1.0.0"

    def infer(self, task_input):
        if self.state != "prepared":
            fail("invalid_state", "Candidate infer requires prepared state")
        value = _load(task_input, self.resources)
        if value["task_id"] != self.task_id:
            fail("schema_mismatch", "Configured baseline task differs from the public task")
        answer = self._predict(encode_input(value))
        return {"input_id": task_input["input_id"], "task_protocol_ref": PROTOCOL,
            "produced_at": utc_now(), "model_revision": self.REVISION,
            "payload": payload(OUTPUT, {"raw_text": canonical_json(answer).decode("utf-8"),
                "evidence": {"kind": "signal_algorithm_baseline", "algorithm_revision": self.REVISION,
                    "task_id": self.task_id, "codec_ref": CODEC_REF, "gold_access": False}})}
