"""A tiny native transition backend used to verify the action/observation contract."""

import copy

from gymts.contracts import utc_now
from ._common import clock, component, empty_update, end_info, fail, identifier, payload, unpack

PROTOCOL = "gymts.task/counter-control/1"
STATE = "gymts.builtin/counter-state/1"
ARGS = "gymts.builtin/increment-arguments/1"
INPUT = "gymts.builtin/counter-input/1"
OUTPUT = "gymts.builtin/counter-output/1"
RESULT = "gymts.builtin/counter-result/1"
ALIGNMENT = "gymts.builtin/counter-alignment/1"


class CounterTransition:
    def __init__(self, spec, services):
        self.spec, self.state, self.session = spec, "created", None
        self.value, self.step = 0, 0
        self._pending = True
        self._summary = None
        self._terminal = None
        self._counts = {"batches": 0, "points": 0, "operations": 0, "late_points": 0, "dropped_points": 0}

    def describe(self):
        return {"environment_id": "counter-transition", "adapter_ref": component("counter-transition"),
                "clock_domain": "step", "observation_granularity": "transition", "advance_mode": "on_action",
                "variables": {"counter": {"dtype": "float64", "shape": [], "unit": "count",
                    "time_semantics": "instant", "schema_ref": "gymts.builtin/scalar/1"}},
                "operations": {"increment": {"arguments_schema_ref": ARGS, "receipt_schema_ref": STATE,
                    "changes_state": True, "idempotent": False}},
                "capabilities": {"range": False, "query": False, "history": False, "reinitialize": True,
                    "attach": False, "seed": True, "operation_idempotency": False},
                "context_schema_ref": STATE, "native_schema_ref": STATE,
                "default_command": {"name": "increment", "arguments": payload(ARGS, {"amount": 1})}}

    def start(self, spec):
        if self.state != "created":
            fail("invalid_state", "Counter start may be called only once", "start")
        if spec["mode"] != "reinitialize" or spec["scope"]["start"] != 0:
            fail("unsupported_capability", "The demonstration counter starts at step zero", "start")
        if set(spec["permitted_variables"]) - {"counter"} or set(spec["permitted_operations"]) - {"increment"}:
            fail("permission_denied", "Counter selection contains an unknown variable or operation", "start")
        self._spec = copy.deepcopy(spec)
        self._max = self.spec["options"]["max_steps"]
        self._cursor = identifier("cursor")
        self.state = "active"
        self.session = {"session_id": identifier("session"), "run_id": spec["run_id"],
            "environment_id": "counter-transition", "source_revision": self.spec["source"]["revision"],
            "actual_mode": "reinitialize", "actual_scope": copy.deepcopy(spec["scope"]),
            "read_scope": copy.deepcopy(spec["read_scope"]), "clock": clock(0, "step"),
            "initial_cursor": self._cursor, "seed_used": spec["seed"], "ownership": "created",
            "public_context": payload(STATE, {"step": 0, "value": 0})}
        return copy.deepcopy(self.session)

    def observe(self, request):
        if self.state not in ("active", "exhausted"):
            fail("invalid_state", "Counter observe requires an active session", "observe")
        if request["kind"] != "next":
            fail("unsupported_capability", "Counter supports only transition next", "observe")
        if request["cursor"] != self._cursor:
            fail("cursor_mismatch", "Counter cursor does not match current state", "observe")
        if set(request["variables"]) - set(self._spec["permitted_variables"]):
            fail("permission_denied", "Counter variable is not permitted", "observe")
        if self._terminal is not None:
            result = copy.deepcopy(self._terminal)
            result["request_id"] = request["request_id"]
            return result
        if not self._pending:
            return {"batch_id": identifier("batch"), "request_id": request["request_id"],
                "session_id": self.session["session_id"], "status": "waiting", "cursor": self._cursor,
                "clock": clock(self.step, "step"), "coverage": None, "snapshot_time": None,
                "data": None, "context": None, "feedback": [], "end": None}
        self._pending = False
        self._cursor = identifier("cursor")
        self._counts["batches"] += 1
        selected = "counter" in request["variables"] and "counter" in request["entities"]
        self._counts["points"] += int(selected)
        terminal = self.step >= self._max
        native = payload(STATE, {"step": self.step, "value": self.value})
        feedback = []
        if self.step:
            feedback.append({"feedback_id": identifier("feedback"), "operation_id": self._operation_id,
                "kind": "reward", "event_time": self.step, "available_at": self.step,
                "source_ref": component("counter-transition"), "payload": native,
                "reward": {"name": "increment_reward", "value": 1, "unit": "count"}})
        series = []
        if selected:
            series = [{"entity": "counter", "variable": "counter", "unit": "count",
                "timestamps": [self.step], "values": [self.value], "valid_mask": [True], "available_at": [self.step]}]
        batch = {"batch_id": identifier("batch"), "request_id": request["request_id"],
            "session_id": self.session["session_id"], "status": "end" if terminal else "data",
            "cursor": self._cursor, "clock": clock(self.step, "step"), "coverage": None,
            "snapshot_time": self.step, "data": {"time_series": {"series": series}, "native": native if selected else None},
            "context": None, "feedback": feedback,
            "end": end_info("backend_terminated", terminated=True) if terminal else None}
        if terminal:
            self.state = "exhausted"
            self._terminal = copy.deepcopy(batch)
            self._terminal.update(data=None, feedback=[], snapshot_time=None)
        return batch

    def act(self, command):
        if self.state != "active" or self._pending:
            fail("invalid_state", "Consume the pending transition before issuing another action", "act")
        if command["name"] != "increment" or "increment" not in self._spec["permitted_operations"]:
            fail("permission_denied", "Counter action is not permitted", "act")
        if command.get("idempotency_key") is not None:
            fail("unsupported_capability", "The counter does not promise action idempotency", "act")
        amount = unpack(command["arguments"])["amount"]
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 1:
            fail("invalid_request", "Increment amount must be a positive integer", "act")
        self.value += amount
        self.step += 1
        self._pending = True
        self._operation_id = command["operation_id"]
        self._counts["operations"] += 1
        return {"receipt_id": identifier("receipt"), "operation_id": command["operation_id"],
                "request_id": command["request_id"], "status": "completed", "received_at": utc_now(),
                "payload": payload(STATE, {"step": self.step, "value": self.value}), "feedback": []}

    def finish(self):
        if self._summary is None:
            self._summary = {"session_id": self.session["session_id"] if self.session else None,
                "actual_scope": self.session["actual_scope"] if self.session else None,
                "last_cursor": self._cursor if self.session else None,
                "final_clock": clock(self.step, "step") if self.session else None,
                "end": self._terminal["end"] if self._terminal else None, "counts": self._counts.copy(),
                "pending_operations": [], "artifact_refs": [],
                "backend_disposition": "closed" if self.session else "not_started"}
        self.state = "closed"
        return copy.deepcopy(self._summary)


class CounterControlTask:
    def __init__(self, spec):
        self.spec = spec

    def describe(self):
        return {"plugin_ref": component("counter_control"), "task_protocol_ref": PROTOCOL,
            "input_schema_ref": INPUT, "output_schema_ref": OUTPUT, "result_schema_ref": RESULT,
            "outcome_schema_ref": None, "alignment_schema_ref": ALIGNMENT,
            "required_variables": {"counter": {"dtype": "float64", "shape": [], "unit": "count"}},
            "required_operations": {"increment": {"arguments_schema_ref": ARGS}},
            "required_capabilities": [], "use_default_command": False,
            "warmup": {"duration": None, "min_points": 0}}

    def bind(self, spec, binding, environment, execution):
        return CounterControlSession(execution, binding)


class CounterControlSession:
    def __init__(self, execution, binding):
        self.execution, self.binding = execution, binding
        self.cursor = execution["session"]["initial_cursor"]
        self.done = False
        self.started = self.completed = 0
        self._summary = None

    def next_observation(self):
        return {"request_id": identifier("request"), "kind": "next", "entities": ["counter"],
            "variables": ["counter"], "cursor": self.cursor, "max_wait_ms": 0}

    def consume(self, batch):
        self.cursor = batch["cursor"]
        update = empty_update(self.done)
        if batch["status"] == "end":
            self.done = True
            update["done"] = True
            return update
        if batch["data"] is not None:
            native = unpack(batch["data"]["native"], self.execution["data"])
            scope = self.execution["effective_scope"]
            if native["step"] < scope["start"]:
                return update
            if scope["end"] is not None and native["step"] >= scope["end"]:
                self.done = True
                update["done"] = True
                return update
            self.started += 1
            update["inputs"].append({"run_id": self.execution["run_id"], "case_id": identifier("case"),
                "turn_id": 0, "input_id": identifier("input"), "task_protocol_ref": PROTOCOL,
                "decision_time": native["step"], "alignment_key": {"step": native["step"]},
                "observation_refs": [self.execution["data"].observation_ref(batch["batch_id"])],
                "payload": payload(INPUT, native)})
        return update

    def on_action(self, receipt):
        return empty_update(self.done)

    def interpret(self, task_input, output, output_id):
        arguments = unpack(output["payload"], self.execution["data"])
        result = {key: copy.deepcopy(task_input[key]) for key in (
            "run_id", "case_id", "turn_id", "input_id", "task_protocol_ref", "decision_time", "alignment_key")}
        result.update(result_id=identifier("result"), output_id=output_id, status="valid",
                      payload=payload(RESULT, {"requested_amount": arguments["amount"]}))
        self.completed += 1
        return {"results": [result], "requests": [{"kind": "command", "request_id": identifier("request"),
            "case_id": task_input["case_id"], "output_id": output_id, "operation": "increment",
            "arguments": payload(ARGS, arguments)}], "complete": True}

    def finish(self, reason):
        if self._summary is None:
            self._summary = {"cases_started": self.started, "cases_completed": self.completed,
                "cases_incomplete": self.started - self.completed, "results_valid": self.completed,
                "results_invalid": 0, "pending_requests": [], "artifact_refs": []}
        return copy.deepcopy(self._summary)


class IncrementPolicy:
    def __init__(self, spec):
        self.spec, self.state = spec, "created"

    def prepare(self, context, training):
        if self.state != "created":
            fail("invalid_state", "Increment policy prepare may be called only once", "prepare")
        if training is not None or context["learning"]["prepare"] != "load_only":
            fail("unsupported_capability", "Increment policy has no fit capability", "prepare")
        self.state = "prepared"
        return {"model_revision": None, "state_refs": [], "training_provenance_ref": None}

    def infer(self, task_input):
        if self.state != "prepared":
            fail("invalid_state", "Increment policy infer requires prepared state", "infer")
        return {"input_id": task_input["input_id"], "task_protocol_ref": PROTOCOL, "produced_at": utc_now(),
            "model_revision": None, "payload": payload(OUTPUT, {"amount": self.spec["params"]["amount"]})}

    def update(self, feedback):
        fail("unsupported_capability", "Increment policy has no online update capability", "update")

    def finish(self):
        self.state = "closed"
        return []
