"""One-step time-scaled drift; no data reader, Task or Scorer implementation."""

import copy

from gymts.contracts import utc_now
from gymts.plugin_support import fail, parse_time, payload, unpack
from . import OUTPUT, PROTOCOL


class DriftCandidate:
    def __init__(self, spec):
        self.spec = copy.deepcopy(spec)
        self.state = "created"

    @staticmethod
    def check_compatibility_spec(context):
        candidate = context["experiment"]["candidate"]
        if candidate["artifact"] is not None or candidate["inherited_state"]:
            fail("unsupported_capability", "The tutorial Candidate accepts no model or inherited state")

    def prepare(self, context, training):
        if self.state != "created":
            fail("invalid_state", "prepare must be called once")
        if training is not None or context["learning"]["prepare"] != "load_only":
            fail("unsupported_capability", "The tutorial Candidate does not fit")
        self.resources = context["resources"]
        self.state = "prepared"
        return {"model_revision": None, "state_refs": [], "training_provenance_ref": None}

    def infer(self, task_input):
        if self.state != "prepared":
            fail("invalid_state", "infer requires prepare")
        values = unpack(task_input["payload"], self.resources)
        points = [(parse_time(time), value) for time, value, valid in zip(
            values["timestamps"], values["values"], values["valid_mask"])
            if valid and value is not None]
        prediction = points[-1][1] if points else None
        if len(points) >= 2:
            first, last = points[-2:]
            elapsed = (last[0] - first[0]).total_seconds()
            if elapsed <= 0:
                fail("invalid_request", "Drift requires increasing valid sample timestamps")
            horizon = (parse_time(values["target_time"]) - last[0]).total_seconds()
            prediction += self.spec["params"].get("damping", 1.0) * (last[1] - first[1]) * horizon / elapsed
        return {"input_id": task_input["input_id"], "task_protocol_ref": PROTOCOL,
                "produced_at": utc_now(), "model_revision": None,
                "payload": payload(OUTPUT, {"prediction": prediction,
                    "reason": None if points else "no_valid_observation"})}

    def update(self, feedback):
        fail("unsupported_capability", "The tutorial Candidate does not update")

    def finish(self):
        self.state = "closed"
        return []
