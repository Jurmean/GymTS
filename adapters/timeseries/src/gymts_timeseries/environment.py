"""Immutable, model-visible Numeric QA snapshots, one native sample per step."""

import copy

from gymts.contracts import intersect_scope
from gymts.plugin_support import clock, component, end_info, fail, identifier, payload

from .contracts import SNAPSHOT, NATIVE, CONTEXT, CSV, validate_snapshot


class NumericSnapshotEnvironment:
    ADAPTER = "numeric-snapshot"
    SOURCE_SCHEMA = SNAPSHOT

    def _load_snapshot(self, services, ref):
        if ref["schema_ref"] != SNAPSHOT:
            fail("schema_mismatch", "Numeric JSON source requires the public snapshot contract")
        return services.read_json(ref)

    def __init__(self, spec, services):
        self.spec, self.state = copy.deepcopy(spec), "created"
        refs = spec["source"]["connection"]["artifact_refs"]
        if len(refs) != 1:
            fail("schema_mismatch", "Numeric source requires one public snapshot artifact")
        self.snapshot = self._load_snapshot(services, refs[0])
        validate_snapshot(self.snapshot)
        if self.snapshot["dataset_revision"] != spec["source"]["revision"]:
            fail("conflict", "Numeric snapshot differs from the fixed source revision")
        tokens = spec["options"]["sample_tokens"]
        rows = {row["sample_token"]: row for row in self.snapshot["samples"]}
        if len(rows) != len(self.snapshot["samples"]) or len(tokens) != len(set(tokens)):
            fail("conflict", "Numeric snapshot and selection must have unique sample tokens")
        if set(tokens) - set(rows):
            fail("invalid_config", "Numeric selection contains an unknown sample token")
        self.samples = [rows[token] for token in tokens]
        self.session = self._summary = self._terminal = None
        self._counts = {key: 0 for key in ("batches", "points", "operations", "late_points", "dropped_points")}

    @classmethod
    def describe_spec(cls, spec):
        refs = spec["source"]["connection"]["artifact_refs"]
        if len(refs) != 1 or refs[0]["schema_ref"] != cls.SOURCE_SCHEMA:
            fail("schema_mismatch", "Numeric source requires one artifact with its declared source schema")
        return {"environment_id": cls.ADAPTER, "adapter_ref": component(cls.ADAPTER),
            "clock_domain": "step", "observation_granularity": "transition", "advance_mode": "on_observe",
            "variables": {"sample": {"dtype": "string", "shape": [], "unit": "sample",
                "time_semantics": "sample_index", "schema_ref": "gymts.timeseries/sample-token/1"}},
            "operations": {}, "capabilities": {"range": False, "query": False, "history": False,
                "reinitialize": True, "attach": False, "seed": True, "operation_idempotency": False},
            "context_schema_ref": CONTEXT, "native_schema_ref": NATIVE, "default_command": None}

    def describe(self):
        return self.describe_spec(self.spec)

    def start(self, spec):
        if self.state != "created":
            fail("invalid_state", "Numeric snapshot can be started only once", "start")
        if spec["mode"] != "reinitialize":
            fail("unsupported_capability", "Numeric snapshot requires reinitialize", "start")
        if set(spec["permitted_variables"]) - {"sample"} or spec["permitted_operations"]:
            fail("permission_denied", "Numeric snapshot has no requested variable or operation", "start")
        scope = intersect_scope(spec["scope"], {"start": 0, "end": len(self.samples)})
        if scope["end"] is None or scope["start"] >= scope["end"]:
            fail("invalid_config", "Numeric selection and execution scope do not overlap", "start")
        self._start = copy.deepcopy(spec)
        self._scope = intersect_scope(spec["read_scope"], {"start": 0, "end": len(self.samples)})
        self.position, self.now = self._scope["start"], self._scope["start"]
        self.cursor = identifier("cursor")
        self.session = {"session_id": identifier("session"), "run_id": spec["run_id"],
            "environment_id": self.ADAPTER, "source_revision": self.snapshot["dataset_revision"],
            "actual_mode": "reinitialize", "actual_scope": scope, "read_scope": copy.deepcopy(self._scope),
            "clock": clock(self.now, "step"), "initial_cursor": self.cursor, "seed_used": spec["seed"],
            "ownership": "created", "public_context": payload(CONTEXT, {
                "dataset_revision": self.snapshot["dataset_revision"], "sample_count": len(self.samples)})}
        self.state = "active"
        return copy.deepcopy(self.session)

    def observe(self, request):
        if self.state not in ("active", "exhausted"):
            fail("invalid_state", "Numeric snapshot is not active", "observe")
        if request["kind"] != "next":
            fail("unsupported_capability", "Numeric snapshot supports next only", "observe")
        if request["cursor"] != self.cursor:
            fail("cursor_mismatch", "Numeric snapshot cursor does not match", "observe")
        if set(request["variables"]) - set(self._start["permitted_variables"]):
            fail("permission_denied", "Numeric sample read is not permitted", "observe")
        if self._terminal is not None:
            batch = copy.deepcopy(self._terminal)
            batch["request_id"] = request["request_id"]
            return batch
        row = self.samples[self.position]
        self.now = self.position
        self.position += 1
        self.cursor = identifier("cursor")
        terminal = self.position >= self._scope["end"]
        selected = "sample" in request["variables"] and "samples" in request["entities"]
        self._counts["batches"] += 1
        self._counts["points"] += int(selected)
        batch = {"batch_id": identifier("batch"), "request_id": request["request_id"],
            "session_id": self.session["session_id"], "status": "end" if terminal else "data", "cursor": self.cursor,
            "clock": clock(self.now, "step"), "coverage": None, "snapshot_time": self.now,
            "data": {"time_series": None, "native": payload(NATIVE, copy.deepcopy(row))} if selected else None,
            "context": None, "feedback": [], "end": end_info() if terminal else None}
        if terminal:
            self.state = "exhausted"
            self._terminal = copy.deepcopy(batch)
            self._terminal.update(data=None, snapshot_time=None)
        return batch

    def act(self, command):
        fail("unsupported_capability", "Numeric snapshots have no environment actions", "act")

    def finish(self):
        if self._summary is None:
            self._summary = {"session_id": self.session["session_id"] if self.session else None,
                "actual_scope": self.session["actual_scope"] if self.session else None,
                "last_cursor": self.cursor if self.session else None,
                "final_clock": clock(self.now, "step") if self.session else None,
                "end": self._terminal["end"] if self._terminal else None, "counts": copy.deepcopy(self._counts),
                "pending_operations": [], "artifact_refs": [], "backend_disposition": "closed" if self.session else "not_started"}
        self.state = "closed"
        return copy.deepcopy(self._summary)


class CSVNumericEnvironment(NumericSnapshotEnvironment):
    """Read immutable long-form numeric CSV directly, with no task/model imports."""
    ADAPTER = "csv-numeric-snapshot"
    SOURCE_SCHEMA = CSV

    def _load_snapshot(self, services, ref):
        import csv
        import hashlib
        import io
        import math
        from .sources import csv_revision
        if ref["schema_ref"] != CSV or ref["media_type"] != "text/csv":
            fail("schema_mismatch", "CSV source requires a committed text/csv artifact")
        context = self.spec["options"].get("context", {})
        revision = csv_revision(ref, context)
        if revision != self.spec["source"]["revision"]:
            fail("conflict", "CSV source revision differs from its bytes and public context")
        raw = services.resolve(ref).read_bytes()
        if hashlib.sha256(raw).hexdigest() != ref["content_hash"] or len(raw) != ref["size_bytes"]:
            fail("artifact_integrity", "CSV bytes changed after reference resolution")
        try:
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8")))
        except UnicodeError:
            fail("invalid_dataset", "Numeric CSV must use UTF-8 encoding")
        if reader.fieldnames != ["sample_token", "series_name", "index", "value"]:
            fail("invalid_dataset", "CSV columns must be sample_token,series_name,index,value in order")
        samples, series = {}, {}
        for row in reader:
            if set(row) != set(reader.fieldnames) or any(value is None for value in row.values()):
                fail("invalid_dataset", "CSV rows must have exactly the declared columns")
            token, name = row["sample_token"], row["series_name"]
            if token not in samples:
                samples[token] = {"sample_token": token, "series": [], "context": copy.deepcopy(context), "annotations": {}}
            key = token, name
            if key not in series:
                item = {"name": name, "values": []}
                series[key] = item
                samples[token]["series"].append(item)
            try:
                index, value = int(row["index"]), float(row["value"])
            except (ValueError, OverflowError):
                fail("invalid_dataset", "CSV indices and observations must be numeric")
            if str(index) != row["index"] or index != len(series[key]["values"]) or not math.isfinite(value):
                fail("invalid_dataset", "CSV series must have finite values and consecutive zero-based indices")
            series[key]["values"].append(value)
        return {"schema_version": SNAPSHOT, "dataset_revision": revision, "samples": list(samples.values())}
