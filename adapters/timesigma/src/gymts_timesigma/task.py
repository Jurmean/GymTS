"""One complete Schema planning unit to one lossless multiseries score result."""
import copy

from gymts.contracts import in_scope
from gymts.plugin_support import component, empty_update, fail, identifier, payload, unpack
from .contracts import (ALIGNMENT, CONTEXT, IDENTITY_FIELDS, INPUT, OUTCOME, OUTPUT,
                        PROTOCOL, RESULT, TASK_PARAMS, validate, validate_answer, validate_unit)


class TimeSigmaTask:
    def __init__(self, spec):
        validate(TASK_PARAMS, spec.get("params"))
        self.params = copy.deepcopy(spec["params"])

    @staticmethod
    def describe_spec(spec):
        validate(TASK_PARAMS, spec.get("params"))
        return {"plugin_ref": component("timesigma-tsad"), "task_protocol_ref": PROTOCOL,
            "input_schema_ref": INPUT, "output_schema_ref": OUTPUT, "result_schema_ref": RESULT,
            "outcome_schema_ref": OUTCOME, "alignment_schema_ref": ALIGNMENT,
            "required_variables": {"planning_unit": {"dtype": "string", "shape": [], "unit": "planning_unit"}},
            "required_operations": {}, "required_capabilities": [], "use_default_command": False,
            "warmup": {"duration": None, "min_points": 0}}

    def describe(self):
        return self.describe_spec({"params": self.params})

    @staticmethod
    def check_compatibility_spec(context):
        environment = context["environment"]
        if (environment["clock_domain"] != "step" or environment["observation_granularity"] != "transition" or
                environment["advance_mode"] != "on_observe" or environment["native_schema_ref"] != INPUT or
                environment["context_schema_ref"] != CONTEXT):
            fail("unsupported_capability", "TimeSigma Task requires native planning-unit snapshots and public context")

    def bind(self, spec, binding, environment, execution):
        if (environment["clock_domain"] != "step" or environment["observation_granularity"] != "transition" or
                environment["advance_mode"] != "on_observe" or environment["native_schema_ref"] != INPUT):
            fail("unsupported_capability", "TimeSigma Task requires native planning-unit snapshots", "bind")
        return TimeSigmaTaskSession(self.params, binding, execution)


class TimeSigmaTaskSession:
    def __init__(self, params, binding, execution):
        self.params, self.binding, self.execution = copy.deepcopy(params), copy.deepcopy(binding), execution
        self.cursor = execution["session"]["initial_cursor"]
        self.public = unpack(execution["session"]["public_context"], execution["data"])
        validate(CONTEXT, self.public)
        if self.public["planning_unit_id"] != params["planning_unit_id"]:
            fail("schema_mismatch", "Task planning unit differs from the fixed environment")
        self.done, self.seen, self.completed, self._summary = False, None, set(), None
        self.counts = {key: 0 for key in ("cases_started", "cases_completed", "cases_incomplete", "results_valid", "results_invalid")}

    def next_observation(self):
        if self._summary is not None:
            fail("invalid_state", "TimeSigma task has already finished", "next_observation")
        return {"request_id": identifier("request"), "kind": "next", "entities": ["planning_units"],
            "variables": [self.binding["variables"]["planning_unit"]["source"]], "cursor": self.cursor, "max_wait_ms": 0}

    def consume(self, batch):
        if self._summary is not None:
            fail("invalid_state", "TimeSigma task has already finished", "consume")
        self.cursor = batch["cursor"]
        update = empty_update(self.done)
        if batch["data"] is not None and batch["data"].get("native") is not None:
            native_payload = batch["data"]["native"]
            if native_payload["schema_ref"] != INPUT:
                fail("schema_mismatch", "Observation does not use TimeSigma input schema", "consume")
            native = unpack(native_payload, self.execution["data"])
            validate_unit(native)
            if any(native[key] != self.public[key] for key in IDENTITY_FIELDS):
                fail("schema_mismatch", "Observed native Schema membership differs from session context", "consume")
            if {row["curve_id"]: len(row["values"]) for row in native["curves"]} != self.public["evaluation_lengths"]:
                fail("schema_mismatch", "Observed curve lengths differ from the frozen snapshot", "consume")
            if type(batch["snapshot_time"]) is not int or batch["snapshot_time"] != 0:
                fail("schema_mismatch", "A complete planning unit exists only at step zero", "consume")
            if self.seen is not None:
                if self.seen != native:
                    fail("conflict", "A planning unit cannot change within one session", "consume")
            elif not self.done and in_scope(0, self.execution["effective_scope"]):
                self.seen = copy.deepcopy(native)
                update["inputs"].append({"run_id": self.execution["run_id"], "case_id": identifier("case"),
                    "turn_id": 0, "input_id": identifier("input"), "task_protocol_ref": PROTOCOL,
                    "decision_time": 0, "alignment_key": {key: native[key] for key in ("dataset_revision", "planning_unit_id")},
                    "observation_refs": [self.execution["data"].observation_ref(batch["batch_id"])],
                    "payload": payload(INPUT, copy.deepcopy(native))})
                self.counts["cases_started"] += 1
        self.done = self.done or batch["status"] == "end"
        update["done"] = self.done
        return update

    def on_action(self, receipt):
        fail("unsupported_capability", "TimeSigma snapshots have no actions", "on_action")

    def interpret(self, task_input, output, output_id):
        if self._summary is not None or task_input["input_id"] in self.completed:
            fail("conflict", "TimeSigma input is finished or already interpreted", "interpret")
        model_input = unpack(task_input["payload"], self.execution["data"])
        if output["payload"]["schema_ref"] != OUTPUT:
            fail("schema_mismatch", "Candidate output uses the wrong TimeSigma schema", "interpret")
        result = unpack(output["payload"], self.execution["data"])
        validate_answer(result, model_input)
        record = {key: copy.deepcopy(task_input[key]) for key in
            ("run_id", "case_id", "turn_id", "input_id", "task_protocol_ref", "decision_time", "alignment_key")}
        record.update(result_id=identifier("result"), output_id=output_id, status="valid", payload=payload(RESULT, result))
        self.completed.add(task_input["input_id"])
        self.counts["cases_completed"] += 1
        self.counts["results_valid"] += 1
        return {"results": [record], "requests": [], "complete": True}

    def finish(self, reason):
        if self._summary is None:
            self.counts["cases_incomplete"] = self.counts["cases_started"] - self.counts["cases_completed"]
            self._summary = dict(self.counts, pending_requests=[], artifact_refs=[])
        return copy.deepcopy(self._summary)
