"""Immutable public RL prompts, delivered through native GymTS observations."""

import copy

from gymts.contracts import intersect_scope
from gymts.plugin_support import clock, component, end_info, fail, identifier, payload
from .contracts import CONTEXT, NATIVE, SNAPSHOT


class RLQASnapshotEnvironment:
    def __init__(self, spec, services):
        self.spec, self.state = copy.deepcopy(spec), "created"
        refs = spec["source"]["connection"]["artifact_refs"]
        if len(refs) != 1 or refs[0]["schema_ref"] != SNAPSHOT:
            fail("schema_mismatch", "RL source requires one public snapshot artifact")
        self.snapshot = services.read_json(refs[0])
        services.schemas.validate(SNAPSHOT, self.snapshot)
        if self.snapshot["dataset_revision"] != spec["source"]["revision"]:
            fail("conflict", "RL source revision differs from its fixed public snapshot")
        rows = {row["sample_id"]: row for row in self.snapshot["samples"]}
        selected = spec["options"]["sample_ids"]
        if len(rows) != len(self.snapshot["samples"]) or len(selected) != len(set(selected)):
            fail("conflict", "RL snapshots require unique sample identities")
        if not selected or set(selected) - set(rows):
            fail("invalid_config", "RL sample selection is empty or unknown")
        self.samples = [rows[key] for key in selected]
        self.session = self._summary = self._terminal = None
        self._counts = {key: 0 for key in ("batches", "points", "operations", "late_points", "dropped_points")}

    @staticmethod
    def describe_spec(spec):
        refs = spec["source"]["connection"]["artifact_refs"]
        if len(refs) != 1 or refs[0]["schema_ref"] != SNAPSHOT:
            fail("schema_mismatch", "RL source requires one public snapshot artifact")
        return {"environment_id": "rl-qa-snapshot", "adapter_ref": component("rl-qa-snapshot"),
            "clock_domain": "step", "observation_granularity": "transition", "advance_mode": "on_observe",
            "variables": {"sample": {"dtype": "string", "shape": [], "unit": "sample", "time_semantics": "sample_index",
                "schema_ref": "gymts.rl/sample-id/1"}}, "operations": {},
            "capabilities": {"range": False, "query": False, "history": False, "reinitialize": True,
                "attach": False, "seed": True, "operation_idempotency": False},
            "context_schema_ref": CONTEXT, "native_schema_ref": NATIVE, "default_command": None}

    def describe(self):
        return self.describe_spec(self.spec)

    def start(self, spec):
        if self.state != "created":
            fail("invalid_state", "RL snapshot can be started only once", "start")
        if spec["mode"] != "reinitialize":
            fail("unsupported_capability", "RL snapshot requires reinitialize", "start")
        if set(spec["permitted_variables"]) - {"sample"} or spec["permitted_operations"]:
            fail("permission_denied", "RL snapshot has no requested variable or operation", "start")
        scope = intersect_scope(spec["scope"], {"start": 0, "end": len(self.samples)})
        if scope["end"] is None or scope["start"] >= scope["end"]:
            fail("invalid_config", "RL selection and execution scope do not overlap", "start")
        self._start = copy.deepcopy(spec)
        self._scope = intersect_scope(spec["read_scope"], {"start": 0, "end": len(self.samples)})
        self.position = self.now = self._scope["start"]
        self.cursor = identifier("cursor")
        self.session = {"session_id": identifier("session"), "run_id": spec["run_id"], "environment_id": "rl-qa-snapshot",
            "source_revision": self.snapshot["dataset_revision"], "actual_mode": "reinitialize", "actual_scope": scope,
            "read_scope": copy.deepcopy(self._scope), "clock": clock(self.now, "step"), "initial_cursor": self.cursor,
            "seed_used": spec["seed"], "ownership": "created", "public_context": payload(CONTEXT, {
                "dataset_revision": self.snapshot["dataset_revision"], "sample_count": len(self.samples)})}
        self.state = "active"
        return copy.deepcopy(self.session)

    def observe(self, request):
        if self.state not in ("active", "exhausted"):
            fail("invalid_state", "RL snapshot is not active", "observe")
        if request["kind"] != "next":
            fail("unsupported_capability", "RL snapshot supports next only", "observe")
        if request["cursor"] != self.cursor:
            fail("cursor_mismatch", "RL snapshot cursor does not match", "observe")
        if set(request["variables"]) - set(self._start["permitted_variables"]):
            fail("permission_denied", "RL sample read is not permitted", "observe")
        if self._terminal is not None:
            result = copy.deepcopy(self._terminal)
            result["request_id"] = request["request_id"]
            return result
        row, self.now = self.samples[self.position], self.position
        self.position += 1
        self.cursor = identifier("cursor")
        terminal = self.position >= self._scope["end"]
        selected = "sample" in request["variables"] and "samples" in request["entities"]
        self._counts["batches"] += 1
        self._counts["points"] += int(selected)
        result = {"batch_id": identifier("batch"), "request_id": request["request_id"], "session_id": self.session["session_id"],
            "status": "end" if terminal else "data", "cursor": self.cursor, "clock": clock(self.now, "step"), "coverage": None,
            "snapshot_time": self.now, "data": {"time_series": None, "native": payload(NATIVE, copy.deepcopy(row))} if selected else None,
            "context": None, "feedback": [], "end": end_info() if terminal else None}
        if terminal:
            self.state = "exhausted"
            self._terminal = copy.deepcopy(result)
            self._terminal.update(data=None, snapshot_time=None)
        return result

    def act(self, command):
        fail("unsupported_capability", "RL prompt snapshots do not provide environment actions", "act")

    def finish(self):
        if self._summary is None:
            self._summary = {"session_id": self.session["session_id"] if self.session else None,
                "actual_scope": self.session["actual_scope"] if self.session else None, "last_cursor": self.cursor if self.session else None,
                "final_clock": clock(self.now, "step") if self.session else None, "end": self._terminal["end"] if self._terminal else None,
                "counts": copy.deepcopy(self._counts), "pending_operations": [], "artifact_refs": [],
                "backend_disposition": "closed" if self.session else "not_started"}
        self.state = "closed"
        return copy.deepcopy(self._summary)
