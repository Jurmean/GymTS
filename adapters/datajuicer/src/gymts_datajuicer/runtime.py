"""Single frozen source view; one native pipeline is one experiment case.

The static observation lifecycle follows the public GymTS environment contract.
No model or dataset publication is performed by this environment or Task.
"""
import copy
import math

from gymts.contracts import canonical_json, in_scope, intersect_scope, utc_now
from gymts.plugin_support import clock, component, empty_update, end_info, fail, identifier, payload, unpack
from .contracts import ALIGNMENT, CONTEXT, OUTCOME, OUTPUT, PROTOCOL, PUBLIC, RESULT, SNAPSHOT
from .common import validate_source
TOKEN = "gymts.json/1"


class SourceEnvironment:
    @staticmethod
    def describe_spec(spec):
        return {"environment_id": "datajuicer-source", "adapter_ref": component("datajuicer-source"),
            "clock_domain": "step", "observation_granularity": "transition", "advance_mode": "on_observe",
            "variables": {"sample": {"dtype": "string", "shape": [], "unit": "sample",
                                      "time_semantics": "sample_index", "schema_ref": TOKEN}},
            "operations": {}, "capabilities": {"range": False, "query": False, "history": False,
                "reinitialize": True, "attach": False, "seed": True, "operation_idempotency": False},
            "context_schema_ref": CONTEXT, "native_schema_ref": PUBLIC, "default_command": None}

    def __init__(self, spec, services):
        self.spec, self.state = copy.deepcopy(spec), "created"
        reference = spec["source"]["connection"]["artifact_refs"][0]
        if reference["schema_ref"] != SNAPSHOT:
            fail("schema_mismatch", "Data-Juicer environment requires one public snapshot")
        snapshot = services.read_json(reference)
        if snapshot["dataset_revision"] != spec["source"]["revision"]:
            fail("conflict", "Data-Juicer snapshot differs from its fixed dataset revision")
        self.sample, self.revision = snapshot["sample"], snapshot["dataset_revision"]
        if self.sample["source_revision"] != self.revision:
            fail("conflict", "Public source identity differs from its fixed snapshot revision")
        validate_source(self.sample["rows"])
        self.session = self._summary = self._terminal = None
        self._counts = {key: 0 for key in ("batches", "points", "operations", "late_points", "dropped_points")}

    def describe(self):
        return self.describe_spec(self.spec)

    def start(self, spec):
        if self.state != "created":
            fail("invalid_state", "Static source can only start once")
        if spec["mode"] != "reinitialize":
            fail("unsupported_capability", "Static source requires reinitialize")
        if set(spec["permitted_variables"]) - {"sample"} or spec["permitted_operations"]:
            fail("permission_denied", "Static source has no requested variable or operation")
        scope = intersect_scope(spec["scope"], {"start": 0, "end": 1})
        self._scope = intersect_scope(spec["read_scope"], {"start": 0, "end": 1})
        if scope["start"] != 0 or scope["end"] != 1 or self._scope != {"start": 0, "end": 1}:
            fail("invalid_config", "A frozen sample requires the step scope [0,1)")
        self._start = copy.deepcopy(spec)
        self.cursor = identifier("cursor")
        self.session = {"session_id": identifier("session"), "run_id": spec["run_id"],
            "environment_id": "datajuicer-source", "source_revision": self.revision,
            "actual_mode": "reinitialize", "actual_scope": scope, "read_scope": copy.deepcopy(self._scope),
            "clock": clock(0, "step"), "initial_cursor": self.cursor, "seed_used": spec["seed"],
            "ownership": "created", "public_context": payload(CONTEXT, {"dataset_revision": self.revision})}
        self.state = "active"
        return copy.deepcopy(self.session)

    def observe(self, request):
        if self.state not in ("active", "exhausted"):
            fail("invalid_state", "Static source is not active")
        if request["kind"] != "next":
            fail("unsupported_capability", "Static source supports next only")
        if request["cursor"] != self.cursor:
            fail("cursor_mismatch", "Static source cursor does not match")
        if set(request["variables"]) - set(self._start["permitted_variables"]):
            fail("permission_denied", "Static sample read is not permitted")
        if self._terminal is not None:
            batch = copy.deepcopy(self._terminal)
            batch["request_id"] = request["request_id"]
            return batch
        selected = "sample" in request["variables"] and "samples" in request["entities"]
        self._counts["batches"] += 1
        self._counts["points"] += int(selected)
        self.cursor = identifier("cursor")
        batch = {"batch_id": identifier("batch"), "request_id": request["request_id"],
            "session_id": self.session["session_id"], "status": "end", "cursor": self.cursor,
            "clock": clock(0, "step"), "coverage": None, "snapshot_time": 0,
            "data": {"time_series": None, "native": payload(PUBLIC, copy.deepcopy(self.sample))} if selected else None,
            "context": None, "feedback": [], "end": end_info()}
        self.state = "exhausted"
        self._terminal = copy.deepcopy(batch)
        self._terminal.update(data=None, snapshot_time=None)
        return batch

    def act(self, command):
        fail("unsupported_capability", "Static datasets expose no external actions")

    def finish(self):
        if self._summary is None:
            self._summary = {"session_id": self.session["session_id"] if self.session else None,
                "actual_scope": self.session["actual_scope"] if self.session else None,
                "last_cursor": self.cursor if self.session else None,
                "final_clock": clock(0, "step") if self.session else None,
                "end": self._terminal["end"] if self._terminal else None, "counts": copy.deepcopy(self._counts),
                "pending_operations": [], "artifact_refs": [],
                "backend_disposition": "closed" if self.session else "not_started"}
        self.state = "closed"
        return copy.deepcopy(self._summary)


class DerivationTask:
    def __init__(self, spec):
        self.spec = copy.deepcopy(spec)

    @staticmethod
    def describe_spec(spec):
        return {"plugin_ref": component("datajuicer-derive"), "task_protocol_ref": PROTOCOL,
            "input_schema_ref": PUBLIC, "output_schema_ref": OUTPUT, "result_schema_ref": RESULT,
            "outcome_schema_ref": OUTCOME, "alignment_schema_ref": ALIGNMENT,
            "required_variables": {"sample": {"dtype": "string", "shape": [], "unit": "sample"}},
            "required_operations": {}, "required_capabilities": [], "use_default_command": False,
            "warmup": {"duration": None, "min_points": 0}}

    @staticmethod
    def compatibility(context):
        if context["environment"]["native_schema_ref"] != PUBLIC:
            fail("unsupported_capability", "Static forecast Task needs the declared public series schema")

    def describe(self):
        return self.describe_spec(self.spec)

    def bind(self, spec, binding, environment, execution):
        if environment["native_schema_ref"] != PUBLIC or environment["clock_domain"] != "step":
            fail("unsupported_capability", "Static forecast Task needs a public sample on a step clock")
        return DerivationSession(binding, execution)


class DerivationSession:
    def __init__(self, binding, execution):
        self.binding, self.execution = binding, execution
        self.cursor = execution["session"]["initial_cursor"]
        self.revision = unpack(execution["session"]["public_context"], execution["data"])["dataset_revision"]
        self.done, self.started, self.completed = False, False, set()
        self.counts = {key: 0 for key in ("cases_started", "cases_completed", "results_valid", "results_invalid")}

    def next_observation(self):
        return {"request_id": identifier("request"), "kind": "next", "entities": ["samples"],
            "variables": [self.binding["variables"]["sample"]["source"]], "cursor": self.cursor, "max_wait_ms": 0}

    def consume(self, batch):
        self.cursor = batch["cursor"]
        update = empty_update(self.done)
        if batch["data"] is not None and batch["data"].get("native") is not None:
            point = batch["snapshot_time"]
            if type(point) is not int or point != 0:
                fail("schema_mismatch", "Static sample requires step 0")
            if not self.started and in_scope(point, self.execution["effective_scope"]):
                sample = unpack(batch["data"]["native"], self.execution["data"])
                if sample["source_revision"] != self.revision:
                    fail("conflict", "Observed public source identity changed")
                validate_source(sample["rows"])
                update["inputs"].append({"run_id": self.execution["run_id"], "case_id": identifier("case"),
                    "turn_id": 0, "input_id": identifier("input"), "task_protocol_ref": PROTOCOL,
                    "decision_time": point, "alignment_key": {"source_revision": self.revision},
                    "observation_refs": [self.execution["data"].observation_ref(batch["batch_id"])],
                    "payload": payload(PUBLIC, sample)})
                self.started = True
                self.counts["cases_started"] += 1
        self.done = self.done or batch["status"] == "end"
        update["done"] = self.done
        return update

    def on_action(self, receipt):
        fail("unsupported_capability", "Static Task has no environment actions")

    def interpret(self, task_input, output, output_id):
        if task_input["input_id"] in self.completed:
            fail("conflict", "Static input has already been interpreted")
        sample = unpack(task_input["payload"], self.execution["data"])
        value = unpack(output["payload"], self.execution["data"])
        valid = bool(value["stages"]) and value["identity"].get("native_execution") is True
        record = {key: copy.deepcopy(task_input[key]) for key in (
            "run_id", "case_id", "turn_id", "input_id", "task_protocol_ref", "decision_time", "alignment_key")}
        record.update(result_id=identifier("result"), output_id=output_id,
                      status="valid" if valid else "invalid", payload=payload(RESULT, value))
        self.completed.add(task_input["input_id"])
        self.counts["cases_completed"] += 1
        self.counts["results_valid" if valid else "results_invalid"] += 1
        return {"results": [record], "requests": [], "complete": True}

    def finish(self, reason):
        return dict(self.counts, cases_incomplete=self.counts["cases_started"] - self.counts["cases_completed"],
                    pending_requests=[], artifact_refs=[])
