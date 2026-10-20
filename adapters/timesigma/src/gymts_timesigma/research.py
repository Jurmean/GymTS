"""Research parent journals reference native child Runs, never create fake Runs.

Provider calls stay under the caller's control. Reservation/settlement records
can capture their requests, responses and reported usage without shipping keys.
The journal is a CAS hash chain; its only mutable file is a durable head pointer.
"""
import copy
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
from uuid import uuid4
import time

from gymts.contracts import GymTSError, canonical_json, digest, utc_now


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SECRET = re.compile(r"\b(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{36})\b")


def redact(value):
    if isinstance(value, dict):
        def sensitive(key):
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            return (normalized in {"authorization", "password", "secret"}
                    or any(part in normalized for part in ("apikey", "accesstoken", "refreshtoken"))
                    or normalized.endswith(("password", "secret")))
        return {key: "[redacted]" if sensitive(key) else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _SECRET.sub("[redacted]", value)
    return value


class ResearchEpisode:
    """Single-writer, resumable parent of actual GymTS experiments and tool IO."""
    def __init__(self, gym, *, budget=None, episode_id=None, scope=None):
        self.gym = gym
        self._closed = False
        self.episode_id = episode_id or "research-" + uuid4().hex
        if not _IDENTIFIER.fullmatch(self.episode_id):
            raise GymTSError("invalid_config", "Invalid research episode identifier")
        self.directory = Path(gym.root) / "timesigma" / "research" / self.episode_id
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = (self.directory / "writer.lock").open("a+b")
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            pointer = self.directory / "head.json"
            if pointer.exists():
                self.head_ref = json.loads(pointer.read_text())["head_ref"]
                previous = gym.artifacts.read_json(self.head_ref)
                self.state = previous["state"]
                if self.state["episode_id"] != self.episode_id or budget is not None and budget != self.state["budget"]:
                    raise GymTSError("conflict", "Resuming an episode cannot replace its frozen budget")
                if scope is not None and redact(scope) != self.state["scope"]:
                    raise GymTSError("conflict", "Resuming an episode cannot replace its frozen scope")
            else:
                required = {"max_experiments", "max_requests", "max_total_tokens", "max_wall_seconds"}
                if (not isinstance(budget, dict) or set(budget) != required or
                        any(type(value) is not int or value < 1 for value in budget.values())):
                    raise GymTSError("invalid_config", "New research episodes require explicit positive experiment/request/token/time budgets")
                self.head_ref = None
                self.state = {"episode_id": self.episode_id, "created_at": utc_now(), "scope": redact(scope or {}),
                    "budget": copy.deepcopy(budget), "experiments": 0, "requests": 0, "tokens_accounted": 0,
                    "seq": 0, "status": "active", "model_pending": {}, "child_experiments": []}
                self._append("episode_start", {"capture": "integration_cas_journal", "native_model_call_events": False})
        except BaseException:
            self._lock.close()
            raise

    def _append(self, kind, payload):
        self._ensure_open()
        self.state["seq"] += 1
        entry = {"schema_version": "gymts.timesigma/research-entry/1", "episode_id": self.episode_id,
            "seq": self.state["seq"], "recorded_at": utc_now(), "kind": kind,
            "payload": redact(payload), "previous_ref": self.head_ref, "state": copy.deepcopy(self.state)}
        temporary = self.directory / (".head-" + uuid4().hex)
        try:
            ref = self.gym.artifacts.save_json(entry, "gymts.timesigma/research-entry/1")
            with temporary.open("xb") as stream:
                stream.write(canonical_json({"head_ref": ref}))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.directory / "head.json")
            descriptor = os.open(str(self.directory), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except (OSError, GymTSError) as error:
            self.state["status"] = "persistence_failed"
            raise GymTSError("persistence_failed", "Research journal head could not be durably published") from error
        finally:
            temporary.unlink(missing_ok=True)
        self.head_ref = ref
        return ref

    def _remaining(self):
        self._ensure_open()
        if self.state["status"] != "active":
            raise GymTSError("invalid_state", "Research episode no longer accepts execution")
        created = datetime.fromisoformat(self.state["created_at"].replace("Z", "+00:00"))
        remaining = self.state["budget"]["max_wall_seconds"] - (datetime.now(timezone.utc) - created).total_seconds()
        if remaining <= 0:
            raise GymTSError("budget_exhausted", "Research wall-time budget has expired")
        return remaining

    def reserve_model_request(self, request, *, max_total_tokens):
        """Call before provider IO; caller must enforce this total-token ceiling.

        Unknown or failed requests keep their full reservation. Restart never
        clears those reservations or resets previously consumed requests.
        """
        self._remaining()
        budget = self.state["budget"]
        if (type(max_total_tokens) is not int or max_total_tokens < 1 or
                self.state["requests"] >= budget["max_requests"] or
                self.state["tokens_accounted"] + max_total_tokens > budget["max_total_tokens"]):
            raise GymTSError("budget_exhausted", "Research provider request/token budget is unavailable")
        ticket = "model-" + uuid4().hex
        self.state["requests"] += 1
        self.state["tokens_accounted"] += max_total_tokens
        self.state["model_pending"][ticket] = max_total_tokens
        self._append("model_request", {"ticket": ticket, "request": request, "reserved_total_tokens": max_total_tokens})
        return ticket

    def settle_model_request(self, ticket, *, response=None, total_tokens=None, error=None):
        self._ensure_open()
        if self.state["status"] != "active" or ticket not in self.state["model_pending"]:
            raise GymTSError("conflict", "Model request is unknown, already settled, or episode is sealed")
        reserved = self.state["model_pending"][ticket]
        if total_tokens is not None and (type(total_tokens) is not int or not 0 <= total_tokens <= reserved):
            if type(total_tokens) is int and total_tokens >= 0:
                self.state["tokens_accounted"] += total_tokens - reserved
                self.state["model_pending"].pop(ticket)
            self.state["status"] = "budget_exceeded"
            self._append("model_usage_rejected", {"ticket": ticket, "reserved_total_tokens": reserved,
                "reported_total_tokens": total_tokens, "reason": "usage_exceeds_reservation_or_invalid",
                "response": response, "error": error})
            raise GymTSError("budget_exhausted", "Provider usage violated its reservation; episode execution has stopped")
        self.state["model_pending"].pop(ticket)
        if total_tokens is not None:
            self.state["tokens_accounted"] -= reserved - total_tokens
        return self._append("model_error" if error is not None else "model_response",
            {"ticket": ticket, "response": response, "error": error,
             "reported_total_tokens": total_tokens, "accounted_total_tokens": total_tokens if total_tokens is not None else reserved})

    def call_tool(self, tools, tool, arguments, *, call_id=None):
        remaining = self._remaining()
        if not isinstance(arguments, dict):
            raise GymTSError("invalid_request", "Research tool arguments must be a JSON object")
        if tool == "experiment.run":
            imported = arguments.get("imported", {})
            for key in ("dataset_revision", "planning_unit_id", "dataset", "schema"):
                if key in self.state["scope"] and imported.get(key) != self.state["scope"][key]:
                    raise GymTSError("conflict", "Experiment differs from the Research episode's frozen scope")
        call_id = call_id or "tool-" + uuid4().hex
        if not _IDENTIFIER.fullmatch(call_id):
            raise GymTSError("invalid_request", "Invalid research tool call identifier")
        # A repeated call ID must never silently trigger a second scientific Run.
        for entry in self.entries():
            if entry["kind"] == "tool_request" and entry["payload"]["call_id"] == call_id:
                raise GymTSError("conflict", "Tool call ID is already recorded; inspect its evidence before retrying")
        is_fit = tool == "experiment.run" and arguments.get("artifact") is None
        if is_fit:
            if self.state["experiments"] >= self.state["budget"]["max_experiments"]:
                raise GymTSError("budget_exhausted", "Research experiment budget is exhausted")
            self.state["experiments"] += 1
        self._append("tool_request", {"call_id": call_id, "tool": tool, "arguments": arguments,
                                      "arguments_digest": digest(arguments)})
        try:
            result = tools.call(tool, arguments, deadline_unix_ms=int((time.time() + remaining) * 1000))
        except BaseException as error:
            if isinstance(error, GymTSError) and error.info["links"].get("run_ids"):
                self.state["child_experiments"].append({"call_id": call_id, **error.info["links"]})
            self._append("tool_error", {"call_id": call_id, "tool": tool,
                "tool_call_ref": getattr(tools, "last_call_ref", None),
                "error": error.to_dict() if isinstance(error, GymTSError) else {"type": type(error).__name__}})
            raise
        if tool == "experiment.run":
            self.state["child_experiments"].append({"call_id": call_id, "run_ids": result["run_ids"],
                "experiment_ref": result["experiment_ref"], "record_snapshot_ref": result["record_snapshot_ref"]})
        self._append("tool_result", {"call_id": call_id, "tool": tool, "result": result,
                                     "tool_call_ref": getattr(tools, "last_call_ref", None)})
        return result

    def entries(self):
        self._ensure_open()
        reverse, reference, expected = [], self.head_ref, self.state["seq"]
        while reference is not None:
            entry = self.gym.artifacts.read_json(reference)
            if entry["episode_id"] != self.episode_id or entry["seq"] != expected:
                raise GymTSError("artifact_integrity", "Research journal sequence or identity changed")
            reverse.append(entry)
            reference, expected = entry["previous_ref"], expected - 1
        if expected:
            raise GymTSError("artifact_integrity", "Research journal is incomplete")
        return list(reversed(reverse))

    def snapshot(self):
        self._ensure_open()
        return self.gym.artifacts.save_json({"schema_version": "gymts.timesigma/research-episode/1",
            "state": copy.deepcopy(self.state), "journal_head_ref": self.head_ref}, "gymts.timesigma/research-episode/1")

    def finish(self, *, reason="completed"):
        self._ensure_open()
        if self.state["status"] not in {"active", "budget_exceeded"}:
            raise GymTSError("invalid_state", "Research episode is already sealed")
        self.state["status"] = "finished"
        self._append("episode_finish", {"reason": reason, "unsettled_model_requests": list(self.state["model_pending"])})
        return self.snapshot()

    def close(self):
        if not self._closed:
            self._closed = True
            self._lock.close()

    def _ensure_open(self):
        if self._closed:
            raise GymTSError("invalid_state", "Research writer is closed; resume using a new locked instance")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
