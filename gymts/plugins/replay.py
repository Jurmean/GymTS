"""Read-only local replay with separate event-time and availability-time evidence."""

import copy

from ._common import (clock, component, duration, end_info, fail, identifier,
                      parse_time, payload, timestamp)

PUBLIC = "gymts.builtin/replay-context/1"


class TimeSeriesReplay:
    """Finite in-memory source; the registry validates its explicitly versioned config."""

    def __init__(self, spec, services):
        self.spec = copy.deepcopy(spec)
        self.services = services
        self.state = "created"
        self.session = None
        self._summary = None
        self._terminal = None
        self._counts = {"batches": 0, "points": 0, "operations": 0,
                        "late_points": 0, "dropped_points": 0}
        connection = spec["source"]["connection"]
        if bool("points" in connection) == bool("generator" in connection):
            fail("invalid_config", "Source connection needs exactly one of points or generator")
        self.entity = spec["options"].get("entity", "demo")
        self.variables = spec["mapping"]["variables"]
        self.points = []
        if "generator" in connection:
            g = connection["generator"]
            start, period = parse_time(g["start"]), duration(g["period"])
            raw = [{"timestamp": timestamp(start + period * i),
                    "available_at": timestamp(start + period * i),
                    "entity": self.entity,
                    "values": {item["field"]: g["start_value"] + i * g["delta"] for item in self.variables.values()}}
                   for i in range(g["length"])]
            self.source_end = start + period * g["length"]
        else:
            raw = copy.deepcopy(connection["points"])
            self.source_end = max((parse_time(p.get("available_at", p["timestamp"]))
                                   for p in raw), default=None)
            if self.source_end is not None:
                self.source_end += duration(spec["options"].get("source_period", "1s"))
        for index, p in enumerate(raw):
            if spec["options"]["availability"] == "explicit" and "available_at" not in p:
                fail("invalid_config", "Explicit availability requires available_at for every point")
            event_time = parse_time(p["timestamp"])
            available = parse_time(p.get("available_at", p["timestamp"]))
            if available < event_time:
                fail("invalid_config", "Point availability cannot precede its event time")
            unknown = set(p["values"]) - {item["field"] for item in self.variables.values()}
            if unknown:
                fail("invalid_config", "Point contains an unmapped variable")
            self.points.append({"index": index, "time": event_time, "available": available,
                                "entity": p.get("entity", self.entity),
                                "values": {name: p["values"][item["field"]] for name, item in self.variables.items()
                                           if item["field"] in p["values"]}})
        self.points.sort(key=lambda p: (p["available"], p["index"]))

    @staticmethod
    def describe_spec(spec):
        connection = spec["source"]["connection"]
        if ("points" in connection) == ("generator" in connection):
            fail("invalid_config", "Source connection needs exactly one of points or generator")
        return {"environment_id": "local-timeseries-replay", "adapter_ref": component("local-timeseries-replay"),
                "clock_domain": "event_time", "observation_granularity": "time_window",
                "advance_mode": "on_observe",
                "variables": {name: {"dtype": item["dtype"], "shape": [], "unit": item["unit"],
                                       "time_semantics": "instant", "schema_ref": "gymts.builtin/scalar/1"}
                              for name, item in spec["mapping"]["variables"].items()},
                "operations": {}, "capabilities": {"range": True, "query": True, "history": True,
                "reinitialize": True, "attach": False, "seed": True, "operation_idempotency": False},
                "context_schema_ref": PUBLIC, "native_schema_ref": None, "default_command": None}

    def describe(self):
        return self.describe_spec(self.spec)

    def start(self, spec):
        if self.state != "created":
            fail("invalid_state", "Replay start may be called only once", "start")
        if spec["mode"] != "reinitialize":
            fail("unsupported_capability", "Local replay supports only reinitialize", "start")
        unknown = set(spec["permitted_variables"]) - set(self.variables)
        if unknown or spec["permitted_operations"]:
            fail("permission_denied", "The requested replay variables or operations are unavailable", "start")
        self._start_spec = copy.deepcopy(spec)
        self._start = parse_time(spec["read_scope"]["start"])
        requested_end = spec["read_scope"]["end"]
        self._end = parse_time(requested_end) if requested_end is not None else self.source_end
        self._p = self._start
        self._visible = self._start
        self._cursor = identifier("cursor")
        self._delivered = set()
        self.state = "active"
        self.session = {"session_id": identifier("session"), "run_id": spec["run_id"],
                        "environment_id": "local-timeseries-replay",
                        "source_revision": self.spec["source"]["revision"],
                        "actual_mode": "reinitialize", "actual_scope": copy.deepcopy(spec["scope"]),
                        "read_scope": copy.deepcopy(spec["read_scope"]),
                        "clock": clock(timestamp(self._p)), "initial_cursor": self._cursor,
                        "seed_used": spec.get("seed"), "ownership": "created",
                        "public_context": payload(PUBLIC, {"availability": self.spec["options"]["availability"],
                                                            "entity": self.entity})}
        return copy.deepcopy(self.session)

    def _selection(self, request):
        if self.state not in ("active", "exhausted"):
            fail("invalid_state", "Replay reads need an active session", "observe")
        variables = request["variables"]
        if set(variables) - set(self._start_spec["permitted_variables"]):
            fail("permission_denied", "Requested variable is outside the session permission", "observe")
        return variables, request["entities"]

    def _data(self, selected, variables, entities):
        result = []
        # Empty lists select nothing, including when the underlying source is nonempty.
        for entity in entities:
            for variable in variables:
                points = [p for p in selected if p["entity"] == entity and variable in p["values"]]
                if points:
                    values = [p["values"][variable] for p in points]
                    result.append({"entity": entity, "variable": variable,
                                   "unit": self.variables[variable]["unit"],
                                   "timestamps": [timestamp(p["time"]) for p in points],
                                   "values": values, "valid_mask": [v is not None for v in values],
                                   "available_at": [timestamp(p["available"]) for p in points]})
        return {"time_series": {"series": result}, "native": None}

    def _batch(self, request, selected, variables, entities, coverage=None, end=None):
        self._counts["batches"] += 1
        data = self._data(selected, variables, entities)
        self._counts["points"] += sum(len(s["timestamps"]) for s in data["time_series"]["series"])
        return {"batch_id": identifier("batch"), "request_id": request["request_id"],
                "session_id": self.session["session_id"], "status": "end" if end else "data",
                "cursor": self._cursor, "clock": clock(timestamp(self._p), visible=timestamp(self._visible)),
                "coverage": coverage, "snapshot_time": None, "data": data, "context": None,
                "feedback": [], "end": end}

    def observe(self, request):
        variables, entities = self._selection(request)
        kind = request["kind"]
        if kind in ("range", "query"):
            start, end = parse_time(request["scope"]["start"]), request["scope"]["end"]
            if end is None:
                fail("invalid_request", "A read query needs a finite end", "observe")
            end = parse_time(end)
            if start < self._start or end > self._visible or end < start:
                fail("permission_denied", "Query exceeds the authorized scope or current visibility", "observe")
            if self._end is not None and end > self._end:
                fail("permission_denied", "Query exceeds read_scope", "observe")
            query = request.get("query")
            if kind == "query" and query is not None:
                # The minimal backend advertises read queries, not a private arbitrary query language.
                fail("unsupported_capability", "Replay supports only a null query payload", "observe")
            selected = [p for p in self.points if start <= p["time"] < end and p["available"] < self._visible]
            return self._batch(request, selected, variables, entities, copy.deepcopy(request["scope"]))
        if kind != "next":
            fail("invalid_request", "Unknown observation kind", "observe")
        if request["cursor"] != self._cursor:
            fail("cursor_mismatch", "Replay cursor does not match its current delivery position", "observe")
        if self._terminal is not None:
            # Preserve terminal reason and cursor without delivering the terminal values a second time.
            reply = copy.deepcopy(self._terminal)
            reply["request_id"] = request["request_id"]
            return reply
        if not isinstance(request["max_wait_ms"], int) or request["max_wait_ms"] < 0:
            fail("invalid_request", "max_wait_ms must be a nonnegative integer", "observe")
        q = self._p + duration(request["advance_by"])
        if self._end is not None:
            q = min(q, self._end)
        if self.source_end is not None:
            q = min(q, max(self._p, self.source_end))
        p = self._p
        selected = [point for point in self.points if point["index"] not in self._delivered
                    and self._start <= point["time"] and (self._end is None or point["time"] < self._end)
                    and point["available"] < q]
        self._counts["late_points"] += sum(point["time"] < p for point in selected)
        self._delivered.update(point["index"] for point in selected)
        self._p = q
        self._visible = q
        self._cursor = identifier("cursor")
        ended = None
        if self._end is not None and q >= self._end:
            ended = end_info("read_scope_end")
        elif self.source_end is None or q >= self.source_end:
            ended = end_info("source_exhausted")
        batch = self._batch(request, selected, variables, entities,
                            {"start": timestamp(p), "end": timestamp(q)}, ended)
        if ended:
            self.state = "exhausted"
            self._terminal = copy.deepcopy(batch)
            self._terminal["data"] = None
            self._terminal["coverage"] = None
        return batch

    def act(self, command):
        fail("unsupported_capability", "The replay environment is read only", "act")

    def finish(self):
        if self._summary is not None:
            return copy.deepcopy(self._summary)
        self._summary = {"session_id": self.session["session_id"] if self.session else None,
                         "actual_scope": self.session["actual_scope"] if self.session else None,
                         "last_cursor": self._cursor if self.session else None,
                         "final_clock": clock(timestamp(self._p), visible=timestamp(self._visible)) if self.session else None,
                         "end": self._terminal["end"] if self._terminal else None,
                         "counts": self._counts.copy(), "pending_operations": [], "artifact_refs": [],
                         "backend_disposition": "closed" if self.session else "not_started"}
        self.state = "closed"
        return copy.deepcopy(self._summary)
