"""Organization indexes share the Run transaction and immutable artifact store."""
from contextlib import contextmanager
from contextvars import ContextVar
import json

from gymts.contracts import GymTSError, canonical_json, new_id, utc_now
from gymts.contracts.organization import ATTEMPT, EVENT, GROUP, REQUEST


def encoded(value):
    return canonical_json(value).decode("utf-8")


class OrganizationRecords:
    def __init__(self, records):
        self.records, self.artifacts = records, records.artifacts
        self.context = ContextVar("gymts_organization", default=None)
        records._connection.executescript("""
            CREATE TABLE IF NOT EXISTS experiment_groups (
                group_id TEXT NOT NULL, revision TEXT NOT NULL, definition_ref TEXT NOT NULL,
                created_at TEXT NOT NULL, PRIMARY KEY(group_id,revision));
            CREATE TABLE IF NOT EXISTS stage_attempts (
                attempt_id TEXT PRIMARY KEY, group_id TEXT NOT NULL, revision TEXT NOT NULL,
                stage_id TEXT NOT NULL, ordinal INTEGER NOT NULL, status TEXT NOT NULL,
                record_ref TEXT NOT NULL, UNIQUE(group_id,revision,stage_id,ordinal),
                FOREIGN KEY(group_id,revision) REFERENCES experiment_groups(group_id,revision));
            CREATE TABLE IF NOT EXISTS experiment_events (
                event_id TEXT PRIMARY KEY, group_id TEXT NOT NULL, revision TEXT NOT NULL,
                seq INTEGER NOT NULL, event_ref TEXT NOT NULL, UNIQUE(group_id,revision,seq));
            CREATE TABLE IF NOT EXISTS experiment_runs (
                attempt_id TEXT NOT NULL REFERENCES stage_attempts(attempt_id),
                run_id TEXT NOT NULL REFERENCES runs(run_id), PRIMARY KEY(attempt_id,run_id));
        """)

    def _event(self, connection, group_id, revision, kind, record_ref, attempt_id=None):
        seq = connection.execute("SELECT COALESCE(MAX(seq),0)+1 FROM experiment_events WHERE group_id=? AND revision=?",
                                 (group_id, revision)).fetchone()[0]
        event = {"protocol_version": EVENT, "event_id": new_id("experiment_event"),
            "group_id": group_id, "revision": revision, "seq": seq, "recorded_at": utc_now(),
            "kind": kind, "attempt_id": attempt_id, "record_ref": record_ref}
        ref = self.artifacts.save_json(event, EVENT)
        connection.execute("INSERT INTO experiment_events VALUES(?,?,?,?,?)",
                           (event["event_id"], group_id, revision, seq, encoded(ref)))

    def register(self, definition):
        ref = self.artifacts.save_json(definition, GROUP)
        with self.records._transaction() as connection:
            cursor = connection.execute("INSERT OR IGNORE INTO experiment_groups VALUES(?,?,?,?)",
                (definition["group_id"], definition["revision"], encoded(ref), utc_now()))
            if cursor.rowcount:
                self._event(connection, definition["group_id"], definition["revision"], "registered", ref)
        return ref

    def definition_ref(self, group_id, revision):
        with self.records._lock:
            row = self.records._connection.execute("SELECT definition_ref FROM experiment_groups WHERE group_id=? AND revision=?",
                                                   (group_id, revision)).fetchone()
        if row is None:
            raise GymTSError("not_found", "Experiment group revision is not registered")
        return json.loads(row[0])

    def definitions(self):
        with self.records._lock:
            rows = self.records._connection.execute("SELECT definition_ref FROM experiment_groups ORDER BY created_at,group_id,revision").fetchall()
        return [self.artifacts.read_json(json.loads(row[0])) for row in rows]

    def attempts(self, group_id, revision):
        with self.records._lock:
            rows = self.records._connection.execute("SELECT record_ref FROM stage_attempts WHERE group_id=? AND revision=? ORDER BY rowid",
                                                   (group_id, revision)).fetchall()
        return [self.artifacts.read_json(json.loads(row[0])) for row in rows]

    def attempt(self, attempt_id):
        with self.records._lock:
            row = self.records._connection.execute("SELECT record_ref FROM stage_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
        if row is None:
            raise GymTSError("not_found", "Stage attempt is not present")
        return self.artifacts.read_json(json.loads(row[0]))

    def begin(self, group_id, revision, stage_id, request, dependencies, *, expected_previous=...):
        definition_ref = self.definition_ref(group_id, revision)
        with self.records._transaction() as connection:
            if connection.execute("SELECT 1 FROM stage_attempts WHERE group_id=? AND revision=? AND status='running'",
                                  (group_id, revision)).fetchone():
                raise GymTSError("conflict", "An experiment attempt is still running; inspect it before recovery")
            previous = connection.execute("SELECT attempt_id,ordinal FROM stage_attempts WHERE group_id=? AND revision=? AND stage_id=? ORDER BY ordinal DESC LIMIT 1",
                                          (group_id, revision, stage_id)).fetchone()
            if expected_previous is not ... and expected_previous != (previous["attempt_id"] if previous else None):
                raise GymTSError("conflict", "Stage changed while its next attempt was being prepared; inspect before continuing")
            for dependency, selected in dependencies.items():
                latest = connection.execute("SELECT attempt_id,status FROM stage_attempts WHERE group_id=? AND revision=? AND stage_id=? ORDER BY ordinal DESC LIMIT 1",
                                            (group_id, revision, dependency)).fetchone()
                if latest is None or latest["attempt_id"] != selected or latest["status"] != "succeeded":
                    raise GymTSError("conflict", "A dependency changed before stage inputs could be committed")
            ordinal = previous["ordinal"] + 1 if previous else 1
            attempt = {"protocol_version": ATTEMPT, "attempt_id": new_id("attempt"),
                "group_id": group_id, "revision": revision, "stage_id": stage_id, "ordinal": ordinal,
                "status": "running", "started_at": utc_now(), "ended_at": None,
                "definition_ref": definition_ref, "request_ref": self.artifacts.save_json(request, REQUEST),
                "dependencies": dependencies, "result_ref": None, "outputs": {}, "error": None}
            ref = self.artifacts.save_json(attempt, ATTEMPT)
            connection.execute("INSERT INTO stage_attempts VALUES(?,?,?,?,?,?,?)", (attempt["attempt_id"], group_id,
                revision, stage_id, ordinal, "running", encoded(ref)))
            self._event(connection, group_id, revision, "attempt_started", ref, attempt["attempt_id"])
        return attempt

    def finish(self, attempt_id, *, status, result_ref=None, outputs=None, error=None):
        with self.records._transaction() as connection:
            attempt = self.attempt(attempt_id)
            if attempt["status"] != "running":
                raise GymTSError("conflict", "A finished attempt is immutable")
            attempt.update(status=status, ended_at=utc_now(), result_ref=result_ref, outputs=outputs or {}, error=error)
            ref = self.artifacts.save_json(attempt, ATTEMPT)
            connection.execute("UPDATE stage_attempts SET status=?,record_ref=? WHERE attempt_id=?",
                               (status, encoded(ref), attempt_id))
            self._event(connection, attempt["group_id"], attempt["revision"], "attempt_finished", ref, attempt_id)
        return attempt

    @contextmanager
    def scope(self, attempt):
        context = {key: attempt[key] for key in ("group_id", "revision", "stage_id", "attempt_id")}
        token = self.context.set(context)
        try:
            yield
        finally:
            self.context.reset(token)

    def link_run(self, connection, context, run_id):
        row = connection.execute("SELECT status FROM stage_attempts WHERE attempt_id=?", (context["attempt_id"],)).fetchone()
        if row is None or row[0] != "running":
            raise GymTSError("conflict", "Cannot attach a Run to an inactive attempt")
        cursor = connection.execute("INSERT OR IGNORE INTO experiment_runs VALUES(?,?)", (context["attempt_id"], run_id))
        if cursor.rowcount:
            ref = self.artifacts.save_json({**context, "run_id": run_id}, "gymts.json/1")
            self._event(connection, context["group_id"], context["revision"], "run_linked", ref, context["attempt_id"])

    def reference_runs(self, attempt, run_ids):
        """Associate existing execution evidence without changing Run ownership."""
        with self.records._transaction() as connection:
            for run_id in dict.fromkeys(run_ids):
                self.records._require_run(connection, run_id)
                cursor = connection.execute("INSERT OR IGNORE INTO experiment_runs VALUES(?,?)", (attempt["attempt_id"], run_id))
                if cursor.rowcount:
                    ref = self.artifacts.save_json({"run_id": run_id, "attempt_id": attempt["attempt_id"]}, "gymts.json/1")
                    self._event(connection, attempt["group_id"], attempt["revision"], "run_referenced", ref, attempt["attempt_id"])

    def events(self, group_id, revision, *, after_seq=0):
        with self.records._lock:
            rows = self.records._connection.execute("SELECT event_ref FROM experiment_events WHERE group_id=? AND revision=? AND seq>? ORDER BY seq",
                                                   (group_id, revision, after_seq)).fetchall()
        return [self.artifacts.read_json(json.loads(row[0])) for row in rows]

    def runs(self, *, group_id=None, revision=None, attempt_id=None, status=None, dataset_id=None, dataset_revision=None):
        with self.records._lock:
            rows = self.records._connection.execute("SELECT run_id,metadata,result,result_ref,trace_ref FROM runs ORDER BY rowid").fetchall()
            linked = self.records._connection.execute("SELECT r.run_id,a.group_id,a.revision,a.stage_id,a.attempt_id FROM experiment_runs r JOIN stage_attempts a ON a.attempt_id=r.attempt_id").fetchall()
        links = {}
        for row in linked:
            links.setdefault(row["run_id"], []).append({key: row[key] for key in ("group_id", "revision", "stage_id", "attempt_id")})
        selected = []
        for row in rows:
            metadata = json.loads(row["metadata"])
            organization = metadata.get("organization", {})
            result = json.loads(row["result"]) if row["result"] else None
            actual_status = result["status"] if result else "running"
            associations = links.get(row["run_id"], [])
            if (any(value is not None for value in (group_id, revision, attempt_id)) and not any(
                    (group_id is None or item["group_id"] == group_id) and
                    (revision is None or item["revision"] == revision) and
                    (attempt_id is None or item["attempt_id"] == attempt_id) for item in associations)) or \
                    (status is not None and status != actual_status):
                continue
            datasets = []
            for ref in metadata.get("source_refs", []):
                value = self.artifacts.read_json(ref)
                if isinstance(value, dict) and value.get("protocol_version") in ("gymts.source-dataset/1", "gymts.source-dataset/2"):
                    datasets.append({key: value[key] for key in ("dataset_id", "config", "revision")})
            if dataset_id is not None and not any(item["dataset_id"] == dataset_id and
                    (dataset_revision is None or item["revision"] == dataset_revision) for item in datasets):
                continue
            selected.append({"run_id": row["run_id"], "status": actual_status, "organization": organization,
                "associations": associations,
                "datasets": datasets, "created_at": metadata.get("created_at"),
                "resolved_spec_ref": metadata["resolved_spec_ref"],
                "result_ref": json.loads(row["result_ref"]) if row["result_ref"] else None,
                "trace_ref": json.loads(row["trace_ref"]) if row["trace_ref"] else None})
        return selected
