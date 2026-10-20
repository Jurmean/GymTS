"""One immutable native planning unit at step zero; no private gold access."""
import copy

from gymts.contracts import intersect_scope
from gymts.plugin_support import clock, component, end_info, fail, identifier, payload
from .contracts import (CONTEXT, INPUT, PLANNING_UNIT_ID, SNAPSHOT, identity,
                        validate_unit)


class TimeSigmaSnapshotEnvironment:
    def __init__(self, spec, services):
        self.spec, self.state = copy.deepcopy(spec), "created"
        references = spec["source"]["connection"]["artifact_refs"]
        if len(references) != 1 or references[0].get("schema_ref") != SNAPSHOT:
            fail("schema_mismatch", "TimeSigma source requires exactly one public test snapshot")
        self.snapshot = services.read_json(references[0])
        validate_unit(self.snapshot)
        if self.snapshot["dataset_revision"] != spec["source"]["revision"]:
            fail("conflict", "TimeSigma snapshot/source revisions differ")
        self.public = {**identity(self.snapshot), "evaluation_lengths": {
            row["curve_id"]: len(row["values"]) for row in self.snapshot["curves"]}}
        self.session = self._terminal = self._summary = None
        self._counts = {key: 0 for key in ("batches", "points", "operations", "late_points", "dropped_points")}

    @staticmethod
    def describe_spec(spec):
        references = spec["source"]["connection"]["artifact_refs"]
        if len(references) != 1 or references[0].get("schema_ref") != SNAPSHOT:
            fail("schema_mismatch", "TimeSigma source requires exactly one public test snapshot")
        return {"environment_id": "timesigma-snapshot", "adapter_ref": component("timesigma-snapshot"),
            "clock_domain": "step", "observation_granularity": "transition", "advance_mode": "on_observe",
            "variables": {"planning_unit": {"dtype": "string", "shape": [], "unit": "planning_unit",
                "time_semantics": "complete_native_planning_unit", "schema_ref": PLANNING_UNIT_ID}},
            "operations": {}, "capabilities": {"range": False, "query": False, "history": False,
                "reinitialize": True, "attach": False, "seed": True, "operation_idempotency": False},
            "context_schema_ref": CONTEXT, "native_schema_ref": INPUT, "default_command": None}

    def describe(self):
        return self.describe_spec(self.spec)

    def start(self, spec):
        if self.state != "created":
            fail("invalid_state", "TimeSigma snapshot can be started only once", "start")
        if spec["mode"] != "reinitialize":
            fail("unsupported_capability", "TimeSigma snapshot supports reinitialize only", "start")
        if set(spec["permitted_variables"]) - {"planning_unit"} or spec["permitted_operations"]:
            fail("permission_denied", "TimeSigma snapshot has no requested variable or operation", "start")
        for scope in (spec["scope"], spec["read_scope"]):
            if type(scope["start"]) is not int or (scope["end"] is not None and type(scope["end"]) is not int):
                fail("invalid_config", "TimeSigma planning units use integer step scope", "start")
        actual = intersect_scope(spec["scope"], {"start": 0, "end": 1})
        readable = intersect_scope(spec["read_scope"], {"start": 0, "end": 1})
        if actual["start"] >= actual["end"] or readable["start"] >= readable["end"]:
            fail("invalid_config", "TimeSigma execution must include planning-unit step zero", "start")
        self._start, self.cursor = copy.deepcopy(spec), identifier("cursor")
        self.session = {"session_id": identifier("session"), "run_id": spec["run_id"],
            "environment_id": "timesigma-snapshot", "source_revision": self.snapshot["dataset_revision"],
            "actual_mode": "reinitialize", "actual_scope": actual, "read_scope": readable,
            "clock": clock(0, "step"), "initial_cursor": self.cursor, "seed_used": spec["seed"],
            "ownership": "created", "public_context": payload(CONTEXT, copy.deepcopy(self.public))}
        self.state = "active"
        return copy.deepcopy(self.session)

    def observe(self, request):
        if self.state not in ("active", "exhausted"):
            fail("invalid_state", "TimeSigma snapshot is not active", "observe")
        if request["kind"] != "next":
            fail("unsupported_capability", "TimeSigma snapshot supports next only", "observe")
        if request["cursor"] != self.cursor:
            fail("cursor_mismatch", "TimeSigma snapshot cursor does not match", "observe")
        if set(request["variables"]) - set(self._start["permitted_variables"]):
            fail("permission_denied", "TimeSigma planning-unit read is not permitted", "observe")
        if self._terminal is not None:
            batch = copy.deepcopy(self._terminal)
            batch["request_id"] = request["request_id"]
            return batch
        selected = "planning_unit" in request["variables"] and "planning_units" in request["entities"]
        self.cursor = identifier("cursor")
        self._counts["batches"] += 1
        self._counts["points"] += int(selected)
        batch = {"batch_id": identifier("batch"), "request_id": request["request_id"],
            "session_id": self.session["session_id"], "status": "end", "cursor": self.cursor,
            "clock": clock(0, "step"), "coverage": None, "snapshot_time": 0,
            "data": {"time_series": None, "native": payload(INPUT, copy.deepcopy(self.snapshot))} if selected else None,
            "context": None, "feedback": [], "end": end_info()}
        self.state = "exhausted"
        self._terminal = copy.deepcopy(batch)
        self._terminal.update(data=None, snapshot_time=None)
        return batch

    def act(self, command):
        fail("unsupported_capability", "TimeSigma dataset snapshots have no actions", "act")

    def finish(self):
        if self._summary is None:
            self._summary = {"session_id": self.session["session_id"] if self.session else None,
                "actual_scope": self.session["actual_scope"] if self.session else None,
                "last_cursor": self.cursor if self.session else None,
                "final_clock": clock(0, "step") if self.session else None,
                "end": self._terminal["end"] if self._terminal else None, "counts": copy.deepcopy(self._counts),
                "pending_operations": [], "artifact_refs": [], "backend_disposition": "closed" if self.session else "not_started"}
        self.state = "closed"
        return copy.deepcopy(self._summary)
