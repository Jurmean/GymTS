"""Bounded read-only attached telemetry. HTTP and PromQL remain provider logic."""
import copy
from datetime import datetime, timedelta, timezone
import json
import math
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from gymts.contracts import GymTSError, digest, new_id, utc_now
from gymts.plugin_support import clock, component, duration, end_info, parse_time, payload, timestamp
from .registration import CONTEXT, HTTP


def _deny(message, code="invalid_request"):
    raise GymTSError(code, message, stage="prometheus")


def _endpoint(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment):
        _deny("Prometheus base_url must be HTTP(S), without credentials/query/fragment", "invalid_config")
    return value.rstrip("/")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


class PrometheusEnvironment:
    def __init__(self, spec, services):
        self.spec, self.services = copy.deepcopy(spec), services
        self.describe_spec(spec)
        self.connection, self.options = self.spec["source"]["connection"], self.spec["options"]
        self.endpoint = _endpoint(self.connection["base_url"])
        self.entity = self.options.get("entity", "prometheus")
        self.variables = self.spec["mapping"]["variables"]
        self.state, self.session, self._summary = "created", None, None
        self._terminal, self._refs, self._cache = None, [], []
        self._cached_ranges, self._last_clock = [], None
        self._counts = {"batches": 0, "points": 0, "operations": 0, "late_points": 0, "dropped_points": 0}
        self._warnings, self._http_calls = [], 0

    @staticmethod
    def describe_spec(spec):
        connection, variables = spec["source"]["connection"], spec["mapping"]["variables"]
        _endpoint(connection["base_url"])
        if set(connection["queries"]) != set(variables):
            _deny("Prometheus queries and mapped variables must match exactly", "invalid_config")
        for query in connection["queries"].values():
            if not query["expression"].strip():
                _deny("Empty configured PromQL expression", "invalid_config")
        return {"environment_id": "prometheus-live", "adapter_ref": component("prometheus-live"),
            "clock_domain": "wall_time", "observation_granularity": "time_window", "advance_mode": "on_observe",
            "variables": {name: {"dtype": "float64", "shape": [], "unit": value["unit"],
                "time_semantics": "instant", "schema_ref": "gymts.builtin/scalar/1"} for name, value in variables.items()},
            "operations": {}, "capabilities": {"range": True, "query": True, "history": True,
                "reinitialize": False, "attach": True, "seed": False, "operation_idempotency": False},
            "context_schema_ref": CONTEXT, "native_schema_ref": None, "default_command": None}

    @staticmethod
    def check_compatibility_spec(context):
        execution = context["experiment"]["execution"]
        if execution["start"]["mode"] != "attach" or execution["seed"] is not None:
            _deny("Live telemetry attaches without a reset or simulated seed", "unsupported_capability")

    def describe(self):
        return self.describe_spec(self.spec)

    def _save(self, value):
        ref = self.services.save_json(value, HTTP)
        self._refs.append(ref)
        return ref

    def _get(self, path, params=None):
        url = self.endpoint + path + ("?" + urlencode(params) if params else "")
        call_id, started = new_id("prometheus-http"), utc_now()
        request_ref = self._save({"call_id": call_id, "phase": "request", "method": "GET",
            "url": url, "started_at": started, "credential_env_ref": self.connection.get("token_env")})
        headers = {"Accept": "application/json", "User-Agent": "gymts-prometheus/0.1.0"}
        token_env = self.connection.get("token_env")
        if token_env:
            token = os.environ.get(token_env)
            if not token:
                self._save({"call_id": call_id, "phase": "failed", "request_ref": request_ref,
                    "error": "credential_unavailable", "ended_at": utc_now()})
                _deny("Configured credential environment variable is unavailable", "permission_denied")
            headers["Authorization"] = "Bearer " + token
        response_ref, response_truncated = None, False
        limit = self.options.get("max_response_bytes", 8 * 1024 * 1024)
        self._http_calls += 1
        try:
            # Redirects are rejected, so a server cannot forward a bearer header.
            with build_opener(_NoRedirect).open(Request(url, headers=headers),
                    timeout=self.connection.get("timeout_seconds", 5)) as response:
                raw = response.read(limit + 1)
                status = response.status
            response_truncated = len(raw) > limit
            response_ref = self.services.save_artifact(raw[:limit], {"media_type": "application/json", "schema_ref": None})
            self._refs.append(response_ref)
            if response_truncated:
                _deny("Prometheus response exceeds configured bound; captured prefix retained", "resource_exhausted")
            result = json.loads(raw)
            if result.get("status") != "success":
                _deny("Prometheus rejected the configured query", "execution_failure")
            if result.get("warnings"):
                self._warnings.extend(result["warnings"])
            self._save({"call_id": call_id, "phase": "response", "request_ref": request_ref,
                "response_ref": response_ref, "status_code": status, "ended_at": utc_now()})
            return result["data"]
        except HTTPError as error:
            raw = error.read(limit + 1)
            response_truncated = len(raw) > limit
            response_ref = self.services.save_artifact(raw[:limit], {"media_type": "application/octet-stream", "schema_ref": None})
            self._refs.append(response_ref)
            self._save({"call_id": call_id, "phase": "failed", "request_ref": request_ref,
                "response_ref": response_ref, "status_code": error.code, "error": "http_error",
                "ended_at": utc_now(), "retried": False, "response_truncated": response_truncated})
            raise GymTSError("execution_failure", "Prometheus rejected HTTP request; inspect retained response",
                stage="prometheus.http", links={"request_ref": request_ref, "response_ref": response_ref}) from error
        except (OSError, URLError, ValueError, KeyError, GymTSError) as error:
            code = error.code if isinstance(error, GymTSError) else "execution_failure"
            self._save({"call_id": call_id, "phase": "failed", "request_ref": request_ref,
                "response_ref": response_ref, "error": code, "ended_at": utc_now(), "retried": False,
                "response_truncated": response_truncated})
            raise GymTSError(code, "Prometheus read failed; inspect retained request/response",
                stage="prometheus.http", links={"request_ref": request_ref, "response_ref": response_ref}) from error

    def start(self, spec):
        if self.state != "created":
            _deny("Telemetry session starts once", "invalid_state")
        if spec["mode"] != "attach" or spec["seed"] is not None or spec["permitted_operations"]:
            _deny("Telemetry is attached, read-only and has no simulation seed", "unsupported_capability")
        if set(spec["permitted_variables"]) - set(self.variables):
            _deny("Unknown telemetry variable", "permission_denied")
        self._start_spec = copy.deepcopy(spec)
        self._p, self._end = parse_time(spec["read_scope"]["start"]), spec["read_scope"]["end"]
        self._end = parse_time(self._end) if self._end is not None else None
        now = datetime.now(timezone.utc)
        if self._p > now or self._end is not None and self._end <= now:
            _deny("Live attach requires a started, still-open time scope; freeze past telemetry for replay", "invalid_config")
        build = self._get("/api/v1/status/buildinfo")
        self._visible, self._cursor = self._p, new_id("cursor")
        self._last_clock = clock(utc_now(), "wall_time", visible=timestamp(self._visible))
        self.state = "active"
        context = {"endpoint": self.endpoint, "build_info": build,
            "queries": copy.deepcopy(self.connection["queries"]), "availability": "actual_response_receipt",
            "query_semantics": "half-open source timestamps; exact configured selectors; cached history only"}
        self.session = {"session_id": new_id("session"), "run_id": spec["run_id"], "environment_id": "prometheus-live",
            "source_revision": digest({"declared_revision": self.spec["source"]["revision"], "deployment": context}),
            "actual_mode": "attach", "actual_scope": copy.deepcopy(spec["scope"]),
            "read_scope": copy.deepcopy(spec["read_scope"]), "clock": copy.deepcopy(self._last_clock),
            "initial_cursor": self._cursor, "seed_used": None, "ownership": "attached",
            "public_context": payload(CONTEXT, context)}
        return copy.deepcopy(self.session)

    def _batch(self, request, *, data=None, coverage=None, waiting=False, end=None, now=None):
        self._last_clock = clock(timestamp(now or datetime.now(timezone.utc)),
            "wall_time", visible=timestamp(self._visible))
        return {"batch_id": new_id("batch"), "request_id": request["request_id"],
            "session_id": self.session["session_id"], "status": "waiting" if waiting else "end" if end else "data",
            "cursor": self._cursor, "clock": copy.deepcopy(self._last_clock), "coverage": coverage, "snapshot_time": None,
            "data": data, "context": None, "feedback": [], "end": end}

    def _select(self, request):
        if self.state not in ("active", "exhausted"):
            _deny("Telemetry read needs an active attached session", "invalid_state")
        if set(request["variables"]) - set(self._start_spec["permitted_variables"]):
            _deny("Telemetry variable is outside the session grant", "permission_denied")
        if set(request["entities"]) - {self.entity}:
            _deny("Telemetry entity is outside the configured selector", "permission_denied")

    def _matrix(self, variable, result, start, end, received):
        if result.get("resultType") != "matrix":
            _deny("Telemetry range query requires a float matrix", "schema_mismatch")
        selector = self.connection["queries"][variable].get("labels", {})
        matches = [row for row in result["result"]
            if all(row.get("metric", {}).get(key) == value for key, value in selector.items())]
        if len(matches) > 1:
            _deny("Configured labels match multiple series; choose an explicit selector", "schema_mismatch")
        if not matches:
            return []
        row = matches[0]
        if row.get("histograms"):
            _deny("Native histogram telemetry needs a separate representation adapter", "unsupported_capability")
        points, seen = [], set()
        for raw_time, raw_value in row.get("values", []):
            at = datetime.fromtimestamp(float(raw_time), timezone.utc)
            if not start <= at < end:
                continue  # Prometheus includes end; GymTS windows are half-open.
            if at in seen:
                _deny("Duplicate timestamp in a Prometheus series", "schema_mismatch")
            seen.add(at)
            value = float(raw_value)
            valid = math.isfinite(value)
            points.append({"variable": variable, "time": at, "value": value if valid else None,
                "valid": valid, "available": received})
        return sorted(points, key=lambda point: point["time"])

    def _data(self, points, request):
        series = []
        if self.entity in request["entities"]:
            for name in request["variables"]:
                values = [p for p in points if p["variable"] == name]
                if values:
                    series.append({"entity": self.entity, "variable": name, "unit": self.variables[name]["unit"],
                        "timestamps": [timestamp(p["time"]) for p in values], "values": [p["value"] for p in values],
                        "valid_mask": [p["valid"] for p in values], "available_at": [timestamp(p["available"]) for p in values]})
        return {"time_series": {"series": series}, "native": None}

    def _has_cached_range(self, variable, start, end):
        frontier = start
        for left, right, variables in sorted(self._cached_ranges, key=lambda item: item[0]):
            if variable not in variables or right <= frontier:
                continue
            if left > frontier:
                break
            frontier = max(frontier, right)
            if frontier >= end:
                return True
        return start == end

    def observe(self, request):
        self._select(request)
        kind = request["kind"]
        if kind in ("query", "range"):
            start, end = parse_time(request["scope"]["start"]), request["scope"]["end"]
            if end is None or request.get("query") is not None:
                _deny("History only supports a finite cached range, not arbitrary PromQL", "unsupported_capability")
            end = parse_time(end)
            if start < parse_time(self._start_spec["read_scope"]["start"]) or end > self._p or end < start:
                _deny("History exceeds the already delivered time windows", "permission_denied")
            if self.entity in request["entities"] and any(
                    not self._has_cached_range(variable, start, end) for variable in request["variables"]):
                _deny("History includes a variable/window that was not captured", "unsupported_capability")
            points = [p for p in self._cache if start <= p["time"] < end]
            self._counts["batches"] += 1
            return self._batch(request, data=self._data(points, request), coverage=copy.deepcopy(request["scope"]))
        if kind != "next":
            _deny("Unknown telemetry read kind")
        if request["cursor"] != self._cursor:
            _deny("Telemetry cursor differs from the delivered frontier", "cursor_mismatch")
        if self._terminal is not None:
            result = copy.deepcopy(self._terminal)
            result["request_id"] = request["request_id"]
            return result
        q = self._p + duration(request["advance_by"])
        if self._end is not None:
            q = min(q, self._end)
        now = datetime.now(timezone.utc)
        if now < q:
            wait = min(max(0, request["max_wait_ms"]) / 1000, (q - now).total_seconds())
            if wait:
                time.sleep(wait)
            if datetime.now(timezone.utc) < q:
                return self._batch(request, waiting=True)
        points = []
        if self.entity in request["entities"]:
            for name in request["variables"]:
                query = self.connection["queries"][name]
                result = self._get("/api/v1/query_range", {"query": query["expression"],
                    "start": str(self._p.timestamp()), "end": str(q.timestamp()),
                    "step": str(self.options["step_seconds"])})
                received = datetime.now(timezone.utc)
                points.extend(self._matrix(name, result, self._p, q, received))
        received = datetime.now(timezone.utc)
        self._visible = max(self._visible, received, q)
        coverage = {"start": timestamp(self._p), "end": timestamp(q)}
        self._cached_ranges.append((self._p, q,
            frozenset(request["variables"]) if self.entity in request["entities"] else frozenset()))
        self._p, self._cursor = q, new_id("cursor")
        self._cache.extend(points)
        self._counts["batches"] += 1
        self._counts["points"] += len(points)
        terminal = end_info() if self._end is not None and q >= self._end else None
        batch = self._batch(request, data=self._data(points, request), coverage=coverage, end=terminal, now=received)
        if terminal:
            self.state = "exhausted"
            self._terminal = copy.deepcopy(batch)
            self._terminal.update(data=None, coverage=None)
        return batch

    def act(self, command):
        _deny("Prometheus is read-only; testbed control requires a separate operation adapter", "permission_denied")

    def finish(self):
        if self._summary is None:
            summary = {"provider": "prometheus", "http_calls": self._http_calls, "warnings": self._warnings,
                "coverage_frontier": timestamp(self._p) if hasattr(self, "_p") else None,
                "ownership": "attached", "server_stopped": False, "history": "delivered immutable snapshots"}
            self._save(summary)
            self._summary = {"session_id": self.session["session_id"] if self.session else None,
                "actual_scope": copy.deepcopy(self.session["actual_scope"]) if self.session else None,
                "last_cursor": self._cursor if self.session else None,
                "final_clock": copy.deepcopy(self._last_clock),
                "end": copy.deepcopy(self._terminal["end"]) if self._terminal else None,
                "counts": copy.deepcopy(self._counts), "pending_operations": [], "artifact_refs": list(self._refs),
                "backend_disposition": "detached" if self.session else "not_started"}
            self.state = "closed"
        return copy.deepcopy(self._summary)
