"""Reference forecast task and deterministic, dependency-free Candidate adapters."""

import copy
import math

from gymts.contracts import utc_now
from ._common import (component, duration, empty_update, fail, identifier, parse_time,
                      payload, timestamp, unpack)

PROTOCOL = "gymts.task/forecast/1"
INPUT = "gymts.builtin/forecast-input/1"
OUTPUT = "gymts.builtin/forecast-output/1"
RESULT = "gymts.builtin/forecast-result/1"
OUTCOME = "gymts.builtin/forecast-outcome/1"
ALIGNMENT = "gymts.builtin/forecast-alignment/1"


class WindowForecastTask:
    def __init__(self, spec):
        self.params = copy.deepcopy(spec["params"])
        duration(self.params["horizon"])
        duration(self.params["advance_by"])
        if self.params.get("warmup_duration") is not None:
            duration(self.params["warmup_duration"])

    def describe(self):
        p = self.params
        return {"plugin_ref": component("window_forecast"), "task_protocol_ref": PROTOCOL,
                "input_schema_ref": INPUT, "output_schema_ref": OUTPUT,
                "result_schema_ref": RESULT, "outcome_schema_ref": OUTCOME,
                "alignment_schema_ref": ALIGNMENT,
                "required_variables": {p["variable"]: {"dtype": "float64", "shape": [], "unit": p["unit"]}},
                "required_operations": {}, "required_capabilities": [], "use_default_command": False,
                "warmup": {"duration": p.get("warmup_duration"), "min_points": p["window_points"]}}

    def bind(self, spec, binding, environment, execution):
        return ForecastSession(self.params, binding, execution)


class ForecastSession:
    def __init__(self, params, binding, execution):
        self.params, self.binding, self.execution = copy.deepcopy(params), copy.deepcopy(binding), execution
        self.window = []
        self.seen = set()
        self._cursor = execution["session"]["initial_cursor"]
        self._done = False
        self._summary = None
        self._counts = {"cases_started": 0, "cases_completed": 0, "cases_incomplete": 0,
                        "results_valid": 0, "results_invalid": 0}

    def next_observation(self):
        return {"request_id": identifier("request"), "kind": "next",
                "entities": [self.params["entity"]],
                "variables": [self.binding["variables"][self.params["variable"]]["source"]],
                "cursor": self._cursor, "advance_by": self.params["advance_by"], "max_wait_ms": 0}

    def consume(self, batch):
        self._cursor = batch["cursor"]
        update = empty_update()
        if batch["data"] and batch["data"].get("time_series"):
            source = self.binding["variables"][self.params["variable"]]["source"]
            binding = self.binding["variables"][self.params["variable"]]
            for series in batch["data"]["time_series"]["series"]:
                if series["entity"] != self.params["entity"] or series["variable"] != source:
                    continue
                for time, value, valid in zip(series["timestamps"], series["values"], series["valid_mask"]):
                    # The simple example explicitly drops late corrections rather than silently revising a forecast.
                    if time in self.seen or (self.window and parse_time(time) <= parse_time(self.window[-1][0])):
                        continue
                    self.seen.add(time)
                    if valid and binding.get("transform"):
                        value = self.execution["data"].apply_transform(binding["transform"], value)
                    self.window.append((time, value if valid else None, valid))
                    self.window = self.window[-self.params["window_points"]:]
                    scope = self.execution["effective_scope"]
                    decision = parse_time(time)
                    if len(self.window) < self.params["window_points"] or self._done:
                        continue
                    if decision < parse_time(scope["start"]) or (scope["end"] is not None and decision >= parse_time(scope["end"])):
                        continue
                    target = timestamp(decision + duration(self.params["horizon"]))
                    alignment = {"entity": self.params["entity"], "variable": self.params["variable"],
                                 "issued_at": time, "target_time": target}
                    update["inputs"].append({"run_id": self.execution["run_id"], "case_id": identifier("case"),
                        "turn_id": 0, "input_id": identifier("input"), "task_protocol_ref": PROTOCOL,
                        "decision_time": time, "alignment_key": alignment,
                        "observation_refs": [self.execution["data"].observation_ref(batch["batch_id"])],
                        "payload": payload(INPUT, {"entity": self.params["entity"], "variable": self.params["variable"],
                            "unit": self.params["unit"], "timestamps": [p[0] for p in self.window],
                            "values": [p[1] for p in self.window], "valid_mask": [p[2] for p in self.window],
                            "target_time": target})})
                    self._counts["cases_started"] += 1
        self._done = self._done or batch["status"] == "end"
        update["done"] = self._done
        return update

    def on_action(self, receipt):
        fail("invalid_request", "Forecast task has no environment actions", "on_action")

    def interpret(self, task_input, output, output_id):
        result = unpack(output["payload"], self.execution["data"])
        prediction = result["prediction"]
        valid = (prediction is not None and isinstance(prediction, (int, float))
                 and not isinstance(prediction, bool) and math.isfinite(prediction))
        if not valid:
            result = {"prediction": None, "reason": result.get("reason") or "non_finite_or_missing_prediction"}
        self._counts["results_valid" if valid else "results_invalid"] += 1
        self._counts["cases_completed"] += 1
        record = {key: copy.deepcopy(task_input[key]) for key in (
            "run_id", "case_id", "turn_id", "input_id", "task_protocol_ref", "decision_time", "alignment_key")}
        record.update({"result_id": identifier("result"), "output_id": output_id,
                       "status": "valid" if valid else "invalid", "payload": payload(RESULT, result)})
        return {"results": [record], "requests": [], "complete": True}

    def finish(self, reason):
        if self._summary is None:
            self._counts["cases_incomplete"] = self._counts["cases_started"] - self._counts["cases_completed"]
            self._summary = dict(self._counts, pending_requests=[], artifact_refs=[])
        return copy.deepcopy(self._summary)


class ForecastCandidate:
    def __init__(self, spec, method="last"):
        self.spec, self.method, self.state = copy.deepcopy(spec), method, "created"

    def prepare(self, context, training):
        if self.state != "created":
            fail("invalid_state", "Candidate prepare may be called only once", "prepare")
        if training is not None or context["learning"]["prepare"] != "load_only":
            fail("unsupported_capability", "Reference forecast candidates do not fit", "prepare")
        if self.spec.get("inherited_state") or self.spec.get("artifact") is not None:
            fail("unsupported_capability", "Reference forecast candidates have no inherited/model state", "prepare")
        self.resources = context["resources"]
        self.state = "prepared"
        return {"model_revision": None, "state_refs": [], "training_provenance_ref": None}

    def infer(self, task_input):
        if self.state != "prepared":
            fail("invalid_state", "Candidate infer requires prepared state", "infer")
        values = unpack(task_input["payload"], self.resources)
        valid = [value for value, mask in zip(values["values"], values["valid_mask"]) if mask and value is not None]
        prediction = (valid[-1] if self.method == "last" else sum(valid) / len(valid)) if valid else None
        return {"input_id": task_input["input_id"], "task_protocol_ref": PROTOCOL, "produced_at": utc_now(),
                "model_revision": None, "payload": payload(OUTPUT, {
                    "prediction": prediction, "reason": None if valid else "no_valid_observation"})}

    def update(self, feedback):
        fail("unsupported_capability", "Reference forecast candidates do not support online update", "update")

    def finish(self):
        self.state = "closed"
        return []
