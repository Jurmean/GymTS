"""Transactional local run evidence, outcomes and immutable snapshots."""

from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, List, Optional

from gymts.contracts import canonical_json, digest, utc_now
from gymts.storage.artifacts import ArtifactStore, storage_error


def _text(value: Any) -> str:
    try:
        return canonical_json(value).decode("utf-8")
    except (TypeError, ValueError) as error:
        raise storage_error("invalid_record", "Record must contain finite JSON", reason=str(error)) from error


def _storage_operation(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except (sqlite3.Error, OSError) as error:
            candidate = args[0] if args else kwargs.get("run_id")
            run_id = candidate if isinstance(candidate, str) else candidate.get("run_id") if isinstance(candidate, dict) else None
            raise storage_error("persistence_failed", "Local records operation failed before confirmed completion", run_id=run_id, method=method.__name__, reason=str(error)) from error
    return guarded


def _time(value: str) -> datetime:
    if not isinstance(value, str):
        raise storage_error("invalid_time", "Outcome timestamps must be UTC RFC3339 strings")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise storage_error("invalid_time", "Timestamp is not RFC3339", value=value) from error
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise storage_error("invalid_time", "Outcome/system timestamp must include UTC offset", value=value)
    return parsed


class LocalExperimentRecords:
    """SQLite WAL index plus immutable JSON artifacts.

    A confirmed append is a SQLite FULL-synchronous transaction. Artifacts are
    fsynced before their references enter SQLite. Interrupted writes can leave
    unreferenced CAS blobs but cannot publish a partial run or snapshot.
    """

    def __init__(self, root: Any, artifacts: Optional[ArtifactStore] = None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts = artifacts or ArtifactStore(self.root / "artifacts")
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(self.root / "records.sqlite3"), timeout=30, isolation_level=None, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                metadata TEXT NOT NULL,
                finalization TEXT,
                result TEXT,
                result_ref TEXT,
                trace_ref TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                seq INTEGER NOT NULL,
                draft TEXT NOT NULL,
                event TEXT NOT NULL,
                event_ref TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                UNIQUE(run_id, seq)
            );
            CREATE TABLE IF NOT EXISTS outcomes (
                outcome_id TEXT NOT NULL,
                revision TEXT NOT NULL,
                draft TEXT NOT NULL,
                outcome TEXT NOT NULL,
                artifact_ref TEXT NOT NULL,
                PRIMARY KEY(outcome_id, revision)
            );
            CREATE TABLE IF NOT EXISTS run_outcomes (
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                outcome_id TEXT NOT NULL,
                revision TEXT NOT NULL,
                PRIMARY KEY(run_id, outcome_id, revision),
                FOREIGN KEY(outcome_id, revision) REFERENCES outcomes(outcome_id, revision)
            );
            CREATE TABLE IF NOT EXISTS outcome_snapshots (
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                artifact_ref TEXT NOT NULL,
                PRIMARY KEY(run_id, artifact_ref)
            );
        """)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    @contextmanager
    def _transaction(self):
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
                self._connection.execute("COMMIT")
            except BaseException:
                self._connection.execute("ROLLBACK")
                raise

    @staticmethod
    def _require_run(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise storage_error("run_not_found", "Run is not present in this store", run_id=run_id)
        return row

    def _validate_payload(self, payload: Any) -> None:
        """Do not confirm evidence that only points at an uncommitted object."""
        if not isinstance(payload, dict) or not isinstance(payload.get("schema_ref"), str) or not payload["schema_ref"]:
            raise storage_error("invalid_record", "Payload requires a nonempty schema_ref")
        if payload.get("storage") == "inline" and set(payload) == {"schema_ref", "storage", "value"}:
            return
        if payload.get("storage") != "artifact" or set(payload) != {"schema_ref", "storage", "artifact_ref"}:
            raise storage_error("invalid_record", "Payload must use exactly one storage form")
        ref = payload["artifact_ref"]
        if not isinstance(ref, dict) or ref.get("schema_ref") != payload["schema_ref"]:
            raise storage_error("invalid_record", "Payload and artifact schemas differ")
        self.artifacts.resolve(ref)

    @_storage_operation
    def begin_run(self, meta: Any, resolved_spec_ref: Optional[dict] = None, metadata: Optional[dict] = None) -> Dict[str, Any]:
        if isinstance(meta, str):
            meta = dict(metadata or {}, run_id=meta, resolved_spec_ref=resolved_spec_ref)
        if not isinstance(meta, dict) or not isinstance(meta.get("run_id"), str) or not meta["run_id"]:
            raise storage_error("invalid_record", "RunMetadata requires a nonempty run_id")
        meta = json.loads(_text(meta))
        run_id = meta["run_id"]
        if not isinstance(meta.get("resolved_spec_ref"), dict):
            raise storage_error("invalid_record", "RunMetadata requires resolved_spec_ref", run_id=run_id)
        self.artifacts.resolve(meta["resolved_spec_ref"])
        with self._transaction() as connection:
            existing = connection.execute("SELECT metadata FROM runs WHERE run_id=?", (run_id,)).fetchone()
            previous = json.loads(existing["metadata"]) if existing else {}
            meta.setdefault("created_at", previous.get("created_at", utc_now()))
            meta.setdefault("component_refs", [])
            meta.setdefault("origin", "executed")
            meta.setdefault("source_refs", [])
            meta.setdefault("usage_policy_ref", None)
            _time(meta["created_at"])
            encoded = _text(meta)
            if existing:
                if existing["metadata"] != encoded:
                    raise storage_error("conflict", "RunMetadata identity already has different content", run_id=run_id)
            else:
                connection.execute("INSERT INTO runs(run_id,metadata) VALUES(?,?)", (run_id, encoded))
        return {"run_id": run_id, "record_uri": "gymts-run://" + run_id}

    def _append(self, connection: sqlite3.Connection, run_id: str, drafts: List[dict], allow_sealed: bool = False) -> Dict[str, Any]:
        run = self._require_run(connection, run_id)
        positions = {}
        timestamps = []
        sequence = connection.execute("SELECT COALESCE(MAX(seq),0) FROM events WHERE run_id=?", (run_id,)).fetchone()[0]
        for draft in drafts:
            required = {"event_id", "run_id", "kind", "producer_ref", "source_event_time", "caused_by", "links", "payload"}
            if not isinstance(draft, dict) or not required.issubset(draft) or {"seq", "recorded_at"}.intersection(draft):
                raise storage_error("invalid_record", "EventDraft is missing fields or contains storage-assigned fields", run_id=run_id)
            event_id = draft["event_id"]
            if not isinstance(event_id, str) or not event_id or draft["run_id"] != run_id:
                raise storage_error("invalid_record", "Event identity/run identity is invalid", run_id=run_id)
            self._validate_payload(draft["payload"])
            encoded = _text(draft)
            existing = connection.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
            if existing:
                if existing["draft"] != encoded:
                    raise storage_error("conflict", "event_id already has different canonical content", event_id=event_id, run_id=run_id)
                positions[event_id] = existing["seq"]
                timestamps.append(existing["recorded_at"])
                continue
            if run["result"] is not None and not allow_sealed:
                raise storage_error("run_sealed", "A sealed Run rejects new execution events", run_id=run_id, event_id=event_id)
            if not isinstance(draft["caused_by"], list):
                raise storage_error("invalid_record", "caused_by must be a list", event_id=event_id)
            for predecessor in draft["caused_by"]:
                known = connection.execute("SELECT run_id FROM events WHERE event_id=?", (predecessor,)).fetchone()
                if known is None or known["run_id"] != run_id:
                    raise storage_error("invalid_record", "caused_by must name an already committed preceding event in this Run", event_id=event_id, caused_by=predecessor)
            sequence += 1
            recorded_at = utc_now()
            event = dict(draft, seq=sequence, recorded_at=recorded_at)
            ref = self.artifacts.save_json(event, "gymts.trace-event/1")
            connection.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?)", (event_id, run_id, sequence, encoded, _text(event), _text(ref), recorded_at))
            positions[event_id] = sequence
            timestamps.append(recorded_at)
        return {"positions": positions, "committed_at": max(timestamps) if timestamps else utc_now()}

    @_storage_operation
    def append(self, run_id: str, events: List[dict]) -> Dict[str, Any]:
        if not isinstance(events, list):
            raise storage_error("invalid_record", "append requires a list of EventDrafts")
        with self._transaction() as connection:
            return self._append(connection, run_id, events)

    @_storage_operation
    def end_run(self, run_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
        required = {"protocol_version", "run_id", "purpose", "status", "completion", "started_at", "ended_at", "resolved_spec_ref", "result_ref", "artifact_refs", "evidence_status", "errors", "summary"}
        if not isinstance(result, dict) or not required.issubset(result) or "trace_ref" in result or result.get("run_id") != run_id:
            raise storage_error("invalid_record", "RunFinalization must contain RunResult fields except trace_ref", run_id=run_id)
        if result["protocol_version"] != "gymts.run-result/1" or result["status"] not in {"succeeded", "failed", "cancelled"}:
            raise storage_error("invalid_record", "Invalid RunResult protocol/status", run_id=run_id)
        _time(result["started_at"])
        _time(result["ended_at"])
        self.artifacts.resolve(result["resolved_spec_ref"])
        self.artifacts.resolve(result["result_ref"])
        for ref in result["artifact_refs"]:
            self.artifacts.resolve(ref)
        encoded = _text(result)
        with self._transaction() as connection:
            row = self._require_run(connection, run_id)
            if row["finalization"] is not None:
                if row["finalization"] != encoded:
                    raise storage_error("conflict", "Run was sealed with a different finalization", run_id=run_id)
                return json.loads(row["result"])
            metadata = json.loads(row["metadata"])
            if result["resolved_spec_ref"] != metadata["resolved_spec_ref"]:
                raise storage_error("conflict", "Finalization resolved config differs from begin_run", run_id=run_id)
            summary = {key: result[key] for key in ("status", "completion", "ended_at", "summary", "errors")}
            last = connection.execute("SELECT event_id FROM events WHERE run_id=? ORDER BY seq DESC LIMIT 1", (run_id,)).fetchone()
            draft = {
                "event_id": "run_end_" + digest({"run_id": run_id, "finalization": result}),
                "run_id": run_id, "kind": "run_end",
                "producer_ref": {"name": "gymts.local-records", "version": "1.0.0", "origin_ref": None},
                "source_event_time": None, "caused_by": [last["event_id"]] if last else [], "links": {},
                "payload": {"schema_ref": "gymts.run-end/1", "storage": "inline", "value": summary},
            }
            self._append(connection, run_id, [draft])
            events = [json.loads(item[0]) for item in connection.execute("SELECT event FROM events WHERE run_id=? ORDER BY seq", (run_id,))]
            trace_ref = self.artifacts.save_json({"protocol_version": "gymts.execution-trace/1", "run_id": run_id, "events": events}, "gymts.execution-trace/1")
            completed = dict(result, trace_ref=trace_ref)
            result_ref = self.artifacts.save_json(completed, "gymts.run-result/1")
            connection.execute("UPDATE runs SET finalization=?,result=?,result_ref=?,trace_ref=? WHERE run_id=?", (encoded, _text(completed), _text(result_ref), _text(trace_ref), run_id))
            return completed

    @_storage_operation
    def get_run(self, run_id: str) -> Dict[str, Any]:
        with self._lock:
            row = self._require_run(self._connection, run_id)
            metadata = json.loads(row["metadata"])
            event_rows = self._connection.execute("SELECT event,event_ref FROM events WHERE run_id=? ORDER BY seq", (run_id,)).fetchall()
            events = [json.loads(item["event"]) for item in event_rows]
            def last_payload(kind):
                candidates = [event["payload"] for event in events if event["kind"] == kind]
                if not candidates:
                    return None
                payload = candidates[-1]
                return payload.get("value") if payload.get("storage") == "inline" else self.artifacts.read_json(payload["artifact_ref"])
            session = None
            for event in events:
                if event["kind"] != "artifact":
                    continue
                payload = event["payload"]
                value = payload.get("value") if payload.get("storage") == "inline" else self.artifacts.read_json(payload["artifact_ref"])
                if isinstance(value, dict) and value.get("role") == "session":
                    session = value.get("value")
            return {
                "run_id": run_id, "metadata": metadata,
                "session": session, "preparation": last_payload("candidate_prepare"),
                "result": json.loads(row["result"]) if row["result"] else None,
                "execution_snapshot_ref": json.loads(row["trace_ref"]) if row["trace_ref"] else None,
                "outcome_snapshot_refs": [json.loads(item[0]) for item in self._connection.execute("SELECT artifact_ref FROM outcome_snapshots WHERE run_id=? ORDER BY rowid", (run_id,))],
                "resolved_spec_ref": metadata["resolved_spec_ref"],
                "result_ref": json.loads(row["result_ref"]) if row["result_ref"] else None,
                "events": events, "event_refs": [json.loads(item["event_ref"]) for item in event_rows],
            }

    @_storage_operation
    def read_events(self, run_id: str, query: Optional[dict] = None) -> Dict[str, Any]:
        query = query or {}
        if set(query) - {"after_seq", "limit", "kinds", "snapshot_ref"}:
            raise storage_error("invalid_query", "Unknown EventQuery fields")
        after, limit = query.get("after_seq", 0), query.get("limit", 100)
        if isinstance(after, bool) or not isinstance(after, int) or after < 0 or isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise storage_error("invalid_query", "after_seq must be nonnegative and limit 1..1000")
        kinds = query.get("kinds")
        if kinds is not None and (not isinstance(kinds, list) or not all(isinstance(kind, str) for kind in kinds)):
            raise storage_error("invalid_query", "kinds must be null or a list of strings")
        boundary = None
        if query.get("snapshot_ref"):
            snapshot = self.get_snapshot(query["snapshot_ref"])
            entries = [item for item in snapshot["runs"] if item["run_id"] == run_id]
            if not entries:
                raise storage_error("invalid_query", "Run is outside selected snapshot", run_id=run_id)
            boundary = entries[0]["through_seq"]
        events = self.get_run(run_id)["events"]
        events = [event for event in events if event["seq"] > after and (boundary is None or event["seq"] <= boundary) and (kinds is None or event["kind"] in kinds)]
        page = events[:limit]
        return {"events": page, "next_after_seq": page[-1]["seq"] if len(events) > limit else None}

    @_storage_operation
    def attach_outcomes(self, run_id: str, outcomes: List[dict]) -> Dict[str, Any]:
        if not isinstance(outcomes, list):
            raise storage_error("invalid_record", "outcomes must be a list")
        references = []
        with self._transaction() as connection:
            self._require_run(connection, run_id)
            for item in outcomes:
                required = {"outcome_id", "revision", "alignment_key", "payload", "event_time", "available_at", "source_ref", "supersedes_ref", "allowed_uses"}
                if not isinstance(item, dict) or not required.issubset(item) or not all(isinstance(item.get(key), str) and item[key] for key in ("outcome_id", "revision")):
                    raise storage_error("invalid_record", "OutcomeRecord is missing required fields")
                if item.get("recorded_at") is not None:
                    raise storage_error("invalid_record", "recorded_at is storage-assigned; pass null or omit it")
                _time(item["available_at"])
                self.artifacts.resolve(item["source_ref"])
                self._validate_payload(item["payload"])
                uses = item["allowed_uses"]
                if not isinstance(uses, list) or any(not isinstance(use, str) or use not in {"evaluation", "training_export", "online_feedback"} for use in uses) or len(set(uses)) != len(uses):
                    raise storage_error("invalid_record", "allowed_uses must list unique supported purposes")
                draft = dict(item)
                draft.pop("recorded_at", None)
                encoded = _text(draft)
                outcome_id, revision = item["outcome_id"], item["revision"]
                existing = connection.execute("SELECT * FROM outcomes WHERE outcome_id=? AND revision=?", (outcome_id, revision)).fetchone()
                if existing:
                    if existing["draft"] != encoded:
                        raise storage_error("conflict", "Outcome revision already has different content", outcome_id=outcome_id, revision=revision)
                else:
                    supersedes = item["supersedes_ref"]
                    if supersedes is not None:
                        if not isinstance(supersedes, dict) or set(supersedes) != {"outcome_id", "revision"} or supersedes["outcome_id"] != outcome_id or connection.execute("SELECT 1 FROM outcomes WHERE outcome_id=? AND revision=?", (supersedes["outcome_id"], supersedes["revision"])).fetchone() is None:
                            raise storage_error("invalid_record", "supersedes_ref must identify a committed revision of the same outcome", outcome_id=outcome_id)
                    outcome = dict(draft, recorded_at=utc_now())
                    artifact = self.artifacts.save_json(outcome, "gymts.outcome/1")
                    connection.execute("INSERT INTO outcomes VALUES(?,?,?,?,?)", (outcome_id, revision, encoded, _text(outcome), _text(artifact)))
                connection.execute("INSERT OR IGNORE INTO run_outcomes VALUES(?,?,?)", (run_id, outcome_id, revision))
                references.append({"outcome_id": outcome_id, "revision": revision})
            ref = self.artifacts.save_json(references, "gymts.outcome-snapshot/1")
            connection.execute("INSERT OR IGNORE INTO outcome_snapshots VALUES(?,?)", (run_id, _text(ref)))
            return ref

    def _select_outcomes(self, connection: sqlite3.Connection, run_ids: Optional[List[str]], as_of: Optional[str], refs: Optional[List[dict]], purpose: Optional[str] = None) -> List[dict]:
        if as_of is not None and refs is not None:
            raise storage_error("invalid_query", "outcomes_as_of and explicit outcome_refs are mutually exclusive")
        if run_ids is not None and (not isinstance(run_ids, list) or not all(isinstance(run_id, str) for run_id in run_ids)):
            raise storage_error("invalid_query", "run_ids must be a list of Run identities")
        if run_ids is not None:
            for run_id in run_ids:
                self._require_run(connection, run_id)
        cutoff = _time(as_of) if as_of is not None else datetime.now(timezone.utc)
        if run_ids is None:
            rows = connection.execute("SELECT outcome_id,revision,outcome FROM outcomes ORDER BY outcome_id,revision").fetchall()
        elif not run_ids:
            rows = []
        else:
            placeholders = ",".join("?" for _ in run_ids)
            rows = connection.execute("SELECT DISTINCT o.outcome_id,o.revision,o.outcome FROM outcomes o JOIN run_outcomes r ON o.outcome_id=r.outcome_id AND o.revision=r.revision WHERE r.run_id IN (" + placeholders + ") ORDER BY o.outcome_id,o.revision", run_ids).fetchall()
        selected = []
        requested = None
        if refs is not None:
            if not isinstance(refs, list) or any(not isinstance(ref, dict) or set(ref) != {"outcome_id", "revision"} for ref in refs):
                raise storage_error("invalid_query", "outcome_refs must be OutcomeRef objects")
            requested = {(ref["outcome_id"], ref["revision"]) for ref in refs}
        for row in rows:
            outcome = json.loads(row["outcome"])
            if requested is not None:
                if (row["outcome_id"], row["revision"]) not in requested:
                    continue
            elif _time(outcome["available_at"]) > cutoff or _time(outcome["recorded_at"]) > cutoff:
                continue
            if purpose is not None and purpose not in outcome["allowed_uses"]:
                raise storage_error("purpose_denied", "Outcome is not authorized for requested purpose", outcome_id=outcome["outcome_id"], purpose=purpose)
            selected.append(outcome)
        if requested is not None and {(item["outcome_id"], item["revision"]) for item in selected} != requested:
            raise storage_error("outcome_unavailable", "Selected outcome revision is not committed or is outside selected Runs")
        return selected

    @_storage_operation
    def read_outcomes(self, query: Optional[dict] = None) -> List[dict]:
        query = query or {}
        if set(query) - {"run_ids", "outcomes_as_of", "as_of", "outcome_refs", "purpose", "snapshot_ref"}:
            raise storage_error("invalid_query", "Unknown outcome query fields")
        if "outcomes_as_of" in query and "as_of" in query:
            raise storage_error("invalid_query", "Use only one outcome cutoff field")
        refs = query.get("outcome_refs")
        run_ids = query.get("run_ids")
        if query.get("snapshot_ref"):
            if refs is not None or query.get("outcomes_as_of") is not None or query.get("as_of") is not None:
                raise storage_error("invalid_query", "Snapshot already fixes outcome revisions")
            snapshot = self.get_snapshot(query["snapshot_ref"])
            refs = snapshot["outcome_refs"]
            run_ids = [item["run_id"] for item in snapshot["runs"]]
        with self._lock:
            return self._select_outcomes(self._connection, run_ids, query.get("outcomes_as_of", query.get("as_of")), refs, query.get("purpose"))

    @_storage_operation
    def snapshot(self, run_ids: Any, query: Optional[dict] = None) -> Dict[str, Any]:
        if isinstance(run_ids, dict) and query is None:
            query = dict(run_ids)
            run_ids = query.pop("run_ids", [])
        query = query or {}
        if set(query) - {"through_seq", "outcomes_as_of", "outcome_refs"}:
            raise storage_error("invalid_query", "Unknown SnapshotQuery fields")
        if not isinstance(run_ids, list) or not all(isinstance(run_id, str) for run_id in run_ids) or len(set(run_ids)) != len(run_ids):
            raise storage_error("invalid_query", "snapshot requires unique run_ids")
        through = query.get("through_seq")
        if through is not None and (not isinstance(through, dict) or set(through) - set(run_ids)):
            raise storage_error("invalid_query", "through_seq contains an unselected Run")
        with self._transaction() as connection:
            runs = []
            for run_id in run_ids:
                row = self._require_run(connection, run_id)
                maximum = connection.execute("SELECT COALESCE(MAX(seq),0) FROM events WHERE run_id=?", (run_id,)).fetchone()[0]
                boundary = through.get(run_id, maximum) if through is not None else maximum
                if isinstance(boundary, bool) or not isinstance(boundary, int) or not 0 <= boundary <= maximum:
                    raise storage_error("invalid_query", "through_seq is outside committed event boundary", run_id=run_id)
                # A prefix snapshot must not expose a later final RunResult.
                sealed_visible = row["result"] is not None and boundary == maximum
                runs.append({"run_id": run_id, "through_seq": boundary, "result_ref": json.loads(row["result_ref"]) if sealed_visible else None, "status": json.loads(row["result"])["status"] if sealed_visible else "running"})
            outcomes = self._select_outcomes(connection, run_ids, query.get("outcomes_as_of"), query.get("outcome_refs"))
            body = {"captured_at": utc_now(), "runs": runs, "outcome_refs": [{"outcome_id": item["outcome_id"], "revision": item["revision"]} for item in outcomes]}
            ref = self.artifacts.save_json(body, "gymts.record-snapshot/1")
            return dict(body, snapshot_ref=ref)

    @_storage_operation
    def get_snapshot(self, ref: Dict[str, Any]) -> Dict[str, Any]:
        if ref.get("schema_ref") != "gymts.record-snapshot/1":
            raise storage_error("invalid_query", "Expected a gymts.record-snapshot/1 artifact")
        body = self.artifacts.read_json(ref)
        return dict(body, snapshot_ref=ref)

    def list_outcome_refs(self, run_id: str) -> List[dict]:
        return [{"outcome_id": item["outcome_id"], "revision": item["revision"]} for item in self.read_outcomes({"run_ids": [run_id]})]
