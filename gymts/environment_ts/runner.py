"""Serial synchronous Runner. Domain behavior stays in registered plugins."""
from __future__ import annotations

import copy
import random
import time
from collections import deque

from gymts.contracts import (GymTSError, canonical_json, in_scope, inline,
                             intersect_scope, new_id, parse_time, shift_time,
                             time_compare, utc_now, duration_seconds)
from .services import RestrictedServices
from .capture import RunTraceCollector
from .validation import check_compatibility, check_execution_resources, ensure, resolved_defaults


PRODUCER = {"name": "gymts.runner", "version": "0.5.1", "origin_ref": None}


def keys(value, required, optional=(), label="message"):
    ensure(isinstance(value, dict), f"{label} must be an object", "schema_mismatch")
    ensure(set(required) <= set(value), f"{label} missing {sorted(set(required)-set(value))}", "schema_mismatch")
    ensure(set(value) <= set(required) | set(optional),
           f"{label} unknown fields {sorted(set(value)-set(required)-set(optional))}", "schema_mismatch")
    try:
        canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise GymTSError("schema_mismatch", f"{label} must contain finite JSON") from exc


class EnvironmentTS:
    def __init__(self, registries, schemas, records, artifacts, store_refs=("local", "local://records/default")):
        self.registries, self.schemas = registries, schemas
        self.records, self.artifacts = records, artifacts
        self.tasks, self.candidates = registries.tasks, registries.candidates
        self.store_refs = set(store_refs)

    def _assemble(self, spec):
        resolved = resolved_defaults(spec)
        self.schemas.validate("gymts.experiment/1", resolved)
        scene = resolved["scene"]
        em = self.registries.environments.resolve(scene["environment"]["adapter"], scene["environment"]["version"])
        tm = self.tasks.resolve(scene["task"]["plugin"], scene["task"]["version"])
        cm = self.candidates.resolve(resolved["candidate"]["adapter"], resolved["candidate"]["version"])
        # Validate adapter configuration before its constructor can open anything.
        for name, field in (("source_schema_ref", "source"), ("mapping_schema_ref", "mapping"),
                            ("options_schema_ref", "options")):
            self.schemas.validate(em[name], scene["environment"][field])
        self.schemas.validate(tm["params_schema_ref"], scene["task"]["params"])
        self.schemas.validate(cm["params_schema_ref"], resolved["candidate"]["params"])
        # A source can explicitly grant immutable input artifacts to its adapter.
        # These grants stay in the Environment context; they never reach the
        # Task or Candidate. Nested references are deliberately not traversed.
        connection = scene["environment"]["source"].get("connection", {})
        source_refs = connection.get("artifact_refs", [])
        ensure(isinstance(source_refs, list), "Source artifact_refs must be a list", "schema_mismatch")
        for ref in source_refs:
            self.schemas.validate("gymts.artifact/1", ref)
        description = self.registries.environments.describe(scene["environment"])
        task_description = self.tasks.describe(scene["task"])
        variables, operations, read_scope = check_compatibility(
            resolved, description, task_description, (em, tm, cm), self.schemas, self.artifacts, self.store_refs)
        context = {"experiment": resolved, "environment": description, "task": task_description,
                   "manifests": {"environment": em, "task": tm, "candidate": cm}}
        for registry, selection in ((self.registries.environments, scene["environment"]),
                                    (self.tasks, scene["task"]), (self.candidates, resolved["candidate"])):
            registry.check_compatibility(selection, context)
        return resolved, None, None, description, task_description, cm, variables, operations, read_scope

    def plan(self, spec):
        """Compile declarations only: no plugin instance, data read or CAS write."""
        resolved, _, _, env, task, cm, variables, operations, read_scope = self._assemble(spec)
        scene = resolved["scene"]
        return {"protocol_version": "gymts.assembly-plan/1", "resolved_spec": resolved,
            "manifests": {"environment": self.registries.environments.resolve(scene["environment"]["adapter"], scene["environment"]["version"]),
                          "task": self.tasks.resolve(scene["task"]["plugin"], scene["task"]["version"]), "candidate": cm},
            "descriptions": {"environment": env, "task": task}, "variables": variables,
            "operations": operations, "read_scope": read_scope, "resource_checks": "deferred_to_open"}

    def validate(self, spec):
        try:
            plan = self.plan(spec)
            return {"valid": True, "resolved_spec_ref": None, "resolved_spec": plan["resolved_spec"], "issues": []}
        except GymTSError as error:
            return {"valid": False, "resolved_spec_ref": None, "resolved_spec": None, "issues": [{
                "code": error.code, "path": error.info["links"].get("path", "$"), "message": str(error)}]}
        except (KeyError, TypeError, ValueError) as error:
            return {"valid": False, "resolved_spec_ref": None, "resolved_spec": None, "issues": [{
                "code": "invalid_config", "path": "$", "message": f"Invalid component declaration: {type(error).__name__}"}]}

    def run(self, spec):
        try:
            from .experiments import inherit_organization_inputs
            spec = inherit_organization_inputs(spec, self.records, self.artifacts)
            # A historical scene_ref is configuration and can be expanded for
            # execution. Offline planning deliberately requires its inline form.
            assembled = self._assemble(resolved_defaults(spec, self.artifacts))
        except GymTSError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise GymTSError("invalid_config", "Invalid component declaration") from error
        return Runner(self, assembled).run()

    def run_data(self, spec, *, source_id, revision, dataset_id, source_config="default",
                 config="default", split="recorded"):
        """Run with a fixed data source, then publish a portable environment snapshot.

        The original Run remains sealed, including failures. Dataset publication
        is a separate immutable resource operation and never rewrites that Run.
        """
        bound = self.datasets.bind_source(spec, source_id, revision=revision, config=source_config)
        result = self.run(bound)
        dataset = self.datasets.capture_run(result["run_id"], source_id=source_id,
            revision=revision, dataset_id=dataset_id, source_config=source_config,
            config=config, split=split)
        return {"run": result, "dataset": dataset}


class _Stop(Exception):
    def __init__(self, completion):
        self.completion = completion


class Runner:
    def __init__(self, service, assembled):
        self.service = service
        (self.spec, self.environment, self.task, self.description, self.td,
         self.cm, self.variables, self.operations, self.read_scope) = assembled
        self.records, self.artifacts, self.schemas = service.records, service.artifacts, service.schemas
        self.run_id, self.started_at = new_id("run"), utc_now()
        self.began, self.storage_failed = False, False
        self.session, self.task_session, self.candidate = None, None, None
        self.queue, self.current_case = deque(), None
        self.inputs, self.outputs, self.results, self.cases = {}, {}, [], {}
        self.feedback_seen, self.raw_feedback_seen, self.result_ids = {}, {}, set()
        self.task_done, self.draining, self.env_ended = False, False, False
        self.last_event, self.last_batch, self.clock = None, None, None
        self.cursor, self.pending_transition = None, False
        self.errors, self.artifact_refs = [], []
        self.model_revision = None
        self.counts = {k: 0 for k in ("observations", "inputs", "outputs", "results", "operations",
                                     "feedback", "updates", "cases_completed", "cases_incomplete")}
        self.evidence_status = "complete"
        self.deadline = None
        self.cleanup = {}
        self.traces = None

    def _emit(self, kind, value, links=None, event_time=None, storage="full"):
        if self.storage_failed:
            raise GymTSError("recording_failure", "Execution evidence storage has already failed",
                             stage="recording", run_id=self.run_id)
        event_id = new_id("event")
        # A malformed plugin return is a contract failure, not a broken record
        # backend. Keep the Run sealable and state honestly that raw evidence
        # could not be captured; never stringify an arbitrary object or secret.
        try:
            canonical_json(value)
        except (TypeError, ValueError) as exc:
            self.evidence_status = "incomplete"
            raise GymTSError("schema_mismatch", f"{kind} is not finite JSON",
                             stage=kind, run_id=self.run_id) from exc
        try:
            payload = inline(value)
            if storage == "reference":
                ref = self.artifacts.save_json(value, "gymts.json/1")
                payload = {"schema_ref": "gymts.json/1", "storage": "artifact", "artifact_ref": ref}
            elif storage == "artifact":
                payload = {"schema_ref": value["schema_ref"], "storage": "artifact", "artifact_ref": value}
            event = {"event_id": event_id, "run_id": self.run_id, "kind": kind,
                     "producer_ref": PRODUCER, "source_event_time": event_time,
                     "caused_by": [self.last_event] if self.last_event else [],
                     "links": dict(links or {}), "payload": payload}
            self.records.append(self.run_id, [event])
        except Exception as error:
            self.storage_failed = True
            raise GymTSError("recording_failure", "Could not commit execution evidence", stage="recording",
                             run_id=self.run_id, links={"last_confirmed_event_id": self.last_event}) from error
        self.last_event = event_id
        return event_id

    def _capture_storage_failure(self, error):
        self.storage_failed = True
        raise GymTSError("recording_failure", "Could not commit internal-call evidence", stage="recording",
                         run_id=self.run_id, links={"last_confirmed_event_id": self.last_event}) from error

    def _capture_problem(self, message, evidence_ref, reason):
        self.evidence_status = "incomplete"
        error = GymTSError("capture_incomplete", message, stage="capture", run_id=self.run_id,
                           links={"evidence_ref": evidence_ref, "reason": reason})
        if self.spec["recording"]["on_capture_failure"] == "fail_run":
            raise error
        info = error.to_dict()
        self.errors.append(info)
        self._emit("error", info)

    def _flush_capture(self):
        try:
            return self.traces.flush()
        finally:
            self.artifact_refs.extend(self.traces.artifact_refs)

    def _infer(self, task_input, output_id):
        if self.traces is not None:
            self.traces.bind(self.run_id, task_input, output_id)
        try:
            output = self._invoke("candidate", "infer", self.candidate.infer, copy.deepcopy(task_input))
            # Raw output is core evidence, including returns which later fail
            # schema validation. Optional capture checks must not discard it.
            self._emit("candidate_output", output, {"output_id": output_id, "input_id": task_input["input_id"],
                       "case_id": task_input["case_id"], "turn_id": task_input["turn_id"]},
                       storage=self.spec["recording"]["outputs"])
            self.outputs[output_id] = copy.deepcopy(output)
            self.counts["outputs"] += 1
        except BaseException:
            if self.traces is not None:
                try:
                    self._flush_capture()
                except GymTSError as capture_error:
                    if self.storage_failed:
                        raise
                    # Preserve the invocation/schema failure as the primary
                    # error, and retain any independent capture deficiency.
                    self.errors.append(capture_error.to_dict())
            raise
        if self.traces is not None:
            self._flush_capture()
        return output

    def _invoke(self, role, method, callback, *args):
        try:
            return callback(*args)
        except GymTSError:
            raise
        except Exception as error:
            code = {"candidate": "candidate_failure", "task": "task_failure"}.get(role, "backend_failure")
            raise GymTSError(code, f"{role}.{method} raised {type(error).__name__}",
                             stage=method, method=method, run_id=self.run_id,
                             side_effect="possible" if method == "act" else "none") from error

    def _payload(self, payload, schema_ref=None):
        self.schemas.validate("gymts.payload/1", payload)
        if schema_ref:
            ensure(payload["schema_ref"] == schema_ref, "Payload schema differs from task contract", "schema_mismatch")
        value = payload["value"] if payload["storage"] == "inline" else self.artifacts.read_json(payload["artifact_ref"])
        if payload["storage"] == "artifact":
            ensure(payload["artifact_ref"]["schema_ref"] == payload["schema_ref"],
                   "Payload reference has different schema", "schema_mismatch")
        self.schemas.validate(payload["schema_ref"], value)
        return value

    def _checkpoint(self, kind=None, case_id=None):
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise _Stop("limit_reached")
        limits = self.spec["execution"]["limits"]
        if kind == "infer":
            if limits["max_inputs"] is not None and self.counts["inputs"] >= limits["max_inputs"]:
                raise _Stop("limit_reached")
            if self.cases[case_id]["attempts"] >= limits["max_turns_per_case"]:
                raise _Stop("limit_reached")
        if kind == "act" and limits["max_operations"] is not None and self.counts["operations"] >= limits["max_operations"]:
            raise _Stop("limit_reached")

    def _request(self, request, main=False):
        self._checkpoint()
        kind = request.get("kind")
        base = {"request_id", "kind", "entities", "variables"}
        required = base | ({"cursor", "max_wait_ms"} if kind == "next" else {"scope"})
        optional = {"advance_by"} if kind == "next" else ({"query"} if kind == "query" else set())
        keys(request, required, optional, "ObservationRequest")
        ensure(kind in ("next", "range", "query") and (kind == "next") == main,
               "Unexpected observation kind", "invalid_request")
        ensure(isinstance(request["variables"], list) and isinstance(request["entities"], list),
               "Observation selections must be lists", "invalid_request")
        ensure(not set(request["variables"]) - set(self.variables), "Variable read outside permission", "permission_denied")
        if main:
            ensure(request["cursor"] == self.cursor, "Task provided stale cursor", "cursor_mismatch")
            ensure(type(request["max_wait_ms"]) is int and request["max_wait_ms"] >= 0,
                   "Invalid max_wait_ms", "invalid_request")
            if self.description["observation_granularity"] == "time_window":
                from gymts.contracts import duration_seconds
                duration_seconds(request.get("advance_by"))
            else:
                ensure("advance_by" not in request, "Transitions cannot use advance_by", "invalid_request")
            if self.deadline is not None:
                request = copy.deepcopy(request)
                request["max_wait_ms"] = min(request["max_wait_ms"], max(0, int((self.deadline-time.monotonic())*1000)))
        else:
            ensure(self.description["capabilities"].get(kind), "Read capability unavailable", "unsupported_capability")
            scope = request["scope"]
            keys(scope, {"start", "end"}, label="query scope")
            ensure(scope["end"] is not None and time_compare(scope["start"], scope["end"]) <= 0,
                   "Read query requires a finite nonnegative range", "invalid_request")
            ensure(time_compare(scope["start"], self.read_scope["start"]) >= 0 and
                   time_compare(scope["end"], self.clock["visible_until"]) <= 0 and
                   (self.read_scope["end"] is None or time_compare(scope["end"], self.read_scope["end"]) <= 0),
                   "Query exceeds readable scope or visible frontier", "permission_denied")
        self._emit("environment_request", request, {"request_id": request["request_id"]})
        batch = self._invoke("environment", "observe", self.environment.observe, copy.deepcopy(request))
        self._validate_batch(batch, request, main)
        event_id = self._emit("observation", batch, {"session_id": self.session["session_id"],
                              "request_id": request["request_id"]}, batch["snapshot_time"])
        self.counts["observations"] += 1
        self.data._observations[batch["batch_id"]] = event_id
        if main:
            self.cursor = batch["cursor"]
            if batch["coverage"] is not None:
                self.main_frontier = batch["coverage"]["end"]
            if batch["status"] != "waiting":
                self.pending_transition = False
            self.last_batch = batch
        self.clock = batch["clock"]
        for feedback in batch["feedback"]:
            self._raw_feedback(feedback)
        if batch["status"] == "end":
            self.env_ended = True
        self._apply_update(self._invoke("task", "consume", self.task_session.consume, copy.deepcopy(batch)))
        return batch

    def _validate_batch(self, batch, request, main):
        keys(batch, {"batch_id", "request_id", "session_id", "status", "cursor", "clock", "coverage",
                     "snapshot_time", "data", "context", "feedback", "end"}, label="ObservationBatch")
        ensure(batch["request_id"] == request["request_id"] and batch["session_id"] == self.session["session_id"],
               "Observation identity mismatch", "schema_mismatch")
        ensure(batch["status"] in ("data", "waiting", "end"), "Unknown observation status", "schema_mismatch")
        clock = batch["clock"]
        keys(clock, {"domain", "now", "visible_until"}, label="Clock")
        ensure(clock["domain"] == self.description["clock_domain"], "Clock domain changed", "schema_mismatch")
        ensure(time_compare(clock["now"], self.clock["now"]) >= 0,
               "Environment clock moved backwards", "schema_mismatch")
        ensure(time_compare(clock["visible_until"], self.clock["visible_until"]) >= 0,
               "Visible frontier moved backwards", "schema_mismatch")
        ensure(isinstance(batch["feedback"], list), "Observation feedback must be a list", "schema_mismatch")
        for feedback in batch["feedback"]:
            ensure(isinstance(feedback, dict) and "available_at" in feedback,
                   "Feedback must declare its availability", "schema_mismatch")
            ensure(time_compare(feedback["available_at"], clock["visible_until"]) <= 0,
                   "Backend exposed unavailable feedback", "permission_denied")
        if not main:
            ensure(batch["status"] == "data" and batch["cursor"] == self.cursor and
                   clock["visible_until"] == self.clock["visible_until"], "Query changed main cursor/frontier", "invalid_state")
        if batch["status"] == "waiting":
            ensure(batch["data"] is None and batch["coverage"] is None and batch["snapshot_time"] is None and
                   not batch["feedback"] and batch["cursor"] == self.cursor and
                   clock["visible_until"] == self.clock["visible_until"], "Waiting batch advanced state", "invalid_state")
        ensure((batch["status"] == "end") == (batch["end"] is not None), "Terminal information mismatch", "schema_mismatch")
        if main and self.description["observation_granularity"] == "time_window" and batch["status"] != "waiting":
            coverage = batch["coverage"]
            keys(coverage, {"start", "end"}, label="Window coverage")
            ensure(coverage["end"] is not None and time_compare(coverage["start"], self.main_frontier) == 0,
                   "Window coverage does not begin at the main frontier", "invalid_state")
            progress = time_compare(coverage["end"], coverage["start"])
            ensure(progress > 0 or batch["status"] == "end" and progress == 0,
                   "Empty window must advance coverage; use waiting when unfinished", "invalid_state")
            expected_end = shift_time(self.main_frontier, duration_seconds(request["advance_by"]))
            if self.read_scope["end"] is not None and time_compare(expected_end, self.read_scope["end"]) > 0:
                expected_end = self.read_scope["end"]
            ensure(time_compare(coverage["end"], expected_end) <= 0 and
                   (batch["status"] == "end" or time_compare(coverage["end"], expected_end) == 0),
                   "Window coverage differs from the authorized advance", "invalid_state")
            ensure(progress == 0 or batch["cursor"] != self.cursor, "Data window did not advance its cursor", "invalid_state")
            ensure(time_compare(clock["visible_until"], coverage["end"]) >= 0,
                   "Window has not been completely opened", "invalid_state")
        if batch["context"] is not None:
            self._payload(batch["context"], self.description["context_schema_ref"])
        if batch["data"]:
            keys(batch["data"], {"time_series", "native"}, label="Observation data")
            if batch["data"]["native"] is not None:
                self._payload(batch["data"]["native"], self.description["native_schema_ref"])
            ts = batch["data"]["time_series"]
            if ts is not None:
                keys(ts, {"series"}, label="TimeSeriesData")
                for series in ts["series"]:
                    keys(series, {"entity", "variable", "unit", "timestamps", "values", "valid_mask", "available_at"}, label="Series")
                    ensure(series["variable"] in request["variables"] and series["entity"] in request["entities"],
                           "Backend returned unselected data", "permission_denied")
                    variable = self.description["variables"][series["variable"]]
                    ensure(series["unit"] == variable["unit"], "Backend changed units", "schema_mismatch")
                    n = len(series["timestamps"])
                    ensure(len(series["values"]) == n and len(series["valid_mask"]) == n and
                           (series["available_at"] is None or len(series["available_at"]) == n),
                           "Series arrays have different lengths", "schema_mismatch")
                    for i in range(n):
                        ensure(type(series["valid_mask"][i]) is bool and
                               (series["valid_mask"][i] or series["values"][i] is None),
                               "Invalid points must be explicit null", "schema_mismatch")
                        available = series["timestamps"][i] if series["available_at"] is None else series["available_at"][i]
                        ensure(time_compare(available, clock["visible_until"]) <= 0,
                               "Backend exposed unavailable point", "permission_denied")
                        point = series["timestamps"][i]
                        # A permitted native action can produce a transition at
                        # the decision boundary. It is still execution evidence;
                        # its state/reward is saved even though no new decision
                        # may be made there. Time-window reads remain [start,end).
                        action_transition = (main and self.pending_transition and
                            self.description["observation_granularity"] == "transition" and
                            batch["snapshot_time"] == point)
                        ensure(time_compare(point, self.read_scope["start"]) >= 0 and
                               (self.read_scope["end"] is None or time_compare(point, self.read_scope["end"]) < 0 or action_transition) and
                               time_compare(point, clock["visible_until"]) <= 0,
                               "Backend exposed point outside readable time range", "permission_denied")
                        if not main:
                            ensure(in_scope(point, request["scope"]), "Backend returned point outside query scope", "permission_denied")
                        if series["valid_mask"][i]:
                            self.schemas.validate(variable["schema_ref"], series["values"][i])

    def _raw_feedback(self, feedback):
        keys(feedback, {"feedback_id", "operation_id", "kind", "event_time", "available_at", "source_ref", "payload", "reward"},
             label="EnvironmentFeedback")
        self.schemas.validate("gymts.component/1", feedback["source_ref"])
        ensure(feedback["kind"] in ("operation_status", "reward", "event"), "Unknown feedback kind", "schema_mismatch")
        if feedback["reward"] is not None:
            keys(feedback["reward"], {"name", "value", "unit"}, label="RewardValue")
            ensure(type(feedback["reward"]["value"]) in (int, float), "Reward must be numeric", "schema_mismatch")
        fid = feedback["feedback_id"]
        content = canonical_json(feedback)
        if fid in self.raw_feedback_seen:
            ensure(self.raw_feedback_seen[fid] == content, "Feedback identity changed", "conflict")
            return
        self._payload(feedback["payload"])
        self._emit("environment_feedback", feedback, {"feedback_id": fid, "operation_id": feedback["operation_id"]})
        self.raw_feedback_seen[fid] = content
        self.counts["feedback"] += 1

    def _close_case(self, closure):
        keys(closure, {"case_id", "status", "reason"}, label="CaseClosure")
        ensure(closure["status"] in ("completed", "incomplete"), "Unknown case terminal status", "schema_mismatch")
        cid = closure["case_id"]
        ensure(cid in self.cases, "Cannot close an unknown case", "invalid_state")
        case = self.cases[cid]
        if case["closure"] is not None:
            ensure(case["closure"] == closure, "Case terminal status conflict", "conflict")
            return
        self._emit("case_end", closure, {"case_id": cid})
        case["closure"] = copy.deepcopy(closure)
        self.counts["cases_completed" if closure["status"] == "completed" else "cases_incomplete"] += 1
        if self.current_case == cid:
            self.current_case = None

    def _apply_update(self, update):
        keys(update, {"inputs", "feedback", "done"}, {"closed_cases"}, "TaskUpdate")
        ensure(type(update["done"]) is bool, "Task.done must be boolean", "schema_mismatch")
        ensure(not self.task_done or update["done"], "Task.done cannot become false", "invalid_state")
        closures = update.get("closed_cases", [])
        ensure(not {c["case_id"] for c in closures} & {i["case_id"] for i in update["inputs"]},
               "Task closed and emitted input for the same case", "invalid_state")
        for closure in closures:
            self._close_case(closure)
        for feedback in update["feedback"]:
            self._learn(feedback)
        for task_input in update["inputs"]:
            if self.draining:
                # Task still consumes observations to project delayed feedback;
                # new decision inputs are outside this phase's allowed work.
                continue
            keys(task_input, {"run_id", "case_id", "turn_id", "input_id", "task_protocol_ref", "decision_time",
                              "alignment_key", "observation_refs", "payload"}, label="TaskInput")
            cid, iid = task_input["case_id"], task_input["input_id"]
            ensure(task_input["run_id"] == self.run_id and task_input["task_protocol_ref"] == self.td["task_protocol_ref"],
                   "Task input identity/protocol mismatch", "schema_mismatch")
            ensure(type(task_input["turn_id"]) is int and task_input["turn_id"] >= 0, "Invalid turn ID", "schema_mismatch")
            ensure(in_scope(task_input["decision_time"], self.effective_scope), "Task decision outside effective scope", "permission_denied")
            ensure(time_compare(task_input["decision_time"], self.clock["visible_until"]) <= 0,
                   "Task decision is not yet visible", "permission_denied")
            self.schemas.validate(self.td["alignment_schema_ref"], task_input["alignment_key"])
            self._payload(task_input["payload"], self.td["input_schema_ref"])
            ensure(iid not in self.inputs, "Task input ID reused", "conflict")
            if cid not in self.cases:
                ensure(not self.task_done, "Task created a case after done", "invalid_state")
                self.cases[cid] = {"turn": -1, "attempts": 0, "closure": None}
            case = self.cases[cid]
            ensure(case["closure"] is None and task_input["turn_id"] == case["turn"] + 1,
                   "Task case is closed or turn is not consecutive", "invalid_state")
            # Observe evidence is committed before the Task can reference it.
            known = set(self.data._observations.values())
            for ref in task_input["observation_refs"]:
                if isinstance(ref, str):
                    ensure(ref in known, "Task references uncommitted observation", "invalid_request")
                else:
                    self.artifacts.resolve(ref)
            self._emit("input", task_input, {k: task_input[k] for k in ("input_id", "case_id", "turn_id")},
                       task_input["decision_time"], self.spec["recording"]["inputs"])
            self.inputs[iid] = copy.deepcopy(task_input)
            case["turn"] = task_input["turn_id"]
            self.queue.append(task_input)
        self.task_done = update["done"]

    def _learn(self, feedback):
        keys(feedback, {"feedback_id", "source_feedback_ids", "source_ref", "input_id", "output_id", "available_at", "payload"},
             label="CandidateFeedback")
        fid, content = feedback["feedback_id"], canonical_json(feedback)
        if fid in self.feedback_seen:
            ensure(self.feedback_seen[fid] == content, "Candidate feedback changed", "conflict")
            return
        self._payload(feedback["payload"])
        ensure(all(source in self.raw_feedback_seen for source in feedback["source_feedback_ids"]),
               "Candidate feedback references unknown raw feedback", "permission_denied")
        if feedback["input_id"] is not None:
            ensure(feedback["input_id"] in self.inputs, "Feedback input does not belong to this Run", "permission_denied")
        if feedback["output_id"] is not None:
            ensure(feedback["output_id"] in self.outputs, "Feedback output does not belong to this Run", "permission_denied")
        ensure(time_compare(feedback["available_at"], self.clock["visible_until"]) <= 0,
               "Feedback is not yet available", "permission_denied")
        self._emit("artifact", {"role": "candidate_feedback", "value": feedback}, {"feedback_id": fid})
        learning = self.spec["execution"]["learning"]
        self.feedback_seen[fid] = content
        if learning["online"] == "frozen":
            return
        source = feedback["source_ref"]
        ensure(source["name"] in learning["allowed_feedback_sources"] or
               f"{source['name']}@{source['version']}" in learning["allowed_feedback_sources"],
               "Online feedback source is not authorized", "permission_denied")
        self._checkpoint()
        update = self._invoke("candidate", "update", self.candidate.update, copy.deepcopy(feedback))
        keys(update, {"feedback_id", "before_revision", "after_revision", "state_refs"}, label="UpdateResult")
        ensure(update["feedback_id"] == fid and update["before_revision"] == self.model_revision,
               "Online update identity/revision mismatch", "schema_mismatch")
        for ref in update["state_refs"]:
            self.artifacts.resolve(ref)
        self._emit("candidate_update", update, {"feedback_id": fid})
        self.artifact_refs.extend(update["state_refs"])
        self.model_revision = update["after_revision"]
        self.counts["updates"] += 1

    def _process_queue(self):
        while self.queue and not self.draining:
            if self.current_case is not None:
                index = next((i for i, item in enumerate(self.queue) if item["case_id"] == self.current_case), None)
                if index is None:
                    return
                self.queue.rotate(-index)
                task_input = self.queue.popleft()
                self.queue.rotate(index)
            else:
                task_input = self.queue.popleft()
            cid = task_input["case_id"]
            if self.cases[cid]["closure"] is not None:
                raise GymTSError("invalid_state", "Queued input belongs to a closed case")
            self.current_case = cid
            if self.env_ended and self.td["required_operations"]:
                self._close_case({"case_id": cid, "status": "incomplete", "reason": "environment_ended"})
                continue
            self._checkpoint("infer", cid)
            output_id = new_id("output")
            self.counts["inputs"] += 1
            self.cases[cid]["attempts"] += 1
            self.resources._grant_payload(task_input["payload"])
            output = self._infer(task_input, output_id)
            keys(output, {"input_id", "task_protocol_ref", "produced_at", "model_revision", "payload"}, label="CandidateOutput")
            ensure(output["input_id"] == task_input["input_id"] and output["task_protocol_ref"] == self.td["task_protocol_ref"],
                   "Candidate output identity/protocol mismatch", "schema_mismatch")
            parse_time(output["produced_at"])
            ensure(output["model_revision"] == self.model_revision, "Model revision changed without an update", "invalid_state")
            self._payload(output["payload"], self.td["output_schema_ref"])
            self.data._grant_payload(output["payload"])
            self._checkpoint()
            effect = self._invoke("task", "interpret", self.task_session.interpret, copy.deepcopy(task_input), copy.deepcopy(output), output_id)
            keys(effect, {"results", "requests", "complete"}, label="TaskEffect")
            ensure(type(effect["complete"]) is bool and len(effect["requests"]) <= 1,
                   "Invalid TaskEffect completion or too many requests", "schema_mismatch")
            for result in effect["results"]:
                keys(result, {"result_id", "run_id", "case_id", "turn_id", "input_id", "output_id", "task_protocol_ref",
                              "decision_time", "alignment_key", "status", "payload"}, label="TaskResult")
                ensure(all(result[k] == task_input[k] for k in ("run_id", "case_id", "turn_id", "input_id",
                            "task_protocol_ref", "decision_time", "alignment_key")) and result["output_id"] == output_id,
                       "Task result identity mismatch", "schema_mismatch")
                ensure(result["result_id"] not in self.result_ids and result["status"] in ("valid", "invalid"),
                       "Task result reused or invalid status", "schema_mismatch")
                self._payload(result["payload"], self.td["result_schema_ref"])
                self._emit("task_result", result, {"case_id": cid, "input_id": result["input_id"], "output_id": output_id,
                           "turn_id": result["turn_id"]}, result["decision_time"])
                self.result_ids.add(result["result_id"])
                self.results.append(copy.deepcopy(result))
                self.counts["results"] += 1
            if effect["complete"]:
                self._close_case({"case_id": cid, "status": "completed", "reason": "task_effect_complete"})
            for request in effect["requests"]:
                ensure(request["case_id"] == cid and request["output_id"] == output_id,
                       "Task request identity mismatch", "schema_mismatch")
                if request["kind"] == "query":
                    keys(request, {"kind", "request_id", "case_id", "output_id", "observation"}, label="TaskRequest.query")
                    ensure(not effect["complete"] and request["observation"]["request_id"] == request["request_id"],
                           "Query cannot complete case or mismatch request ID", "invalid_state")
                    self._request(request["observation"])
                elif request["kind"] == "command":
                    keys(request, {"kind", "request_id", "case_id", "output_id", "operation", "arguments"}, label="TaskRequest.command")
                    self._act(request)
                else:
                    raise GymTSError("invalid_request", "Unknown TaskRequest kind")

    def _act(self, request=None, default=False):
        self._checkpoint("act")
        ensure(not self.draining and not self.env_ended, "Action after environment end/boundary", "invalid_state")
        ensure(not self.pending_transition, "Transition must be consumed before another action", "invalid_state")
        if default:
            command = self.description["default_command"]
            name, arguments = command["name"], command["arguments"]
            output_id, request_id = None, new_id("request")
        else:
            operation = self.spec["scene"]["binding"]["operations"].get(request["operation"])
            ensure(operation is not None, "Operation is not bound", "permission_denied")
            name, arguments = operation["source"], request["arguments"]
            output_id, request_id = request["output_id"], request["request_id"]
        ensure(name in self.operations, "Operation outside session permission", "permission_denied")
        self._payload(arguments, self.description["operations"][name]["arguments_schema_ref"])
        command = {"operation_id": new_id("operation"), "request_id": request_id, "output_id": output_id,
                   "origin": "runner_default" if default else "candidate",
                   "trigger_batch_id": self.last_batch["batch_id"] if default else None,
                   "name": name, "arguments": arguments, "idempotency_key": None}
        self._emit("environment_operation", command, {"operation_id": command["operation_id"],
                   "request_id": request_id, "output_id": output_id})
        self.counts["operations"] += 1
        receipt = self._invoke("environment", "act", self.environment.act, copy.deepcopy(command))
        self._emit("environment_receipt", receipt, {"operation_id": command["operation_id"], "request_id": request_id})
        keys(receipt, {"receipt_id", "operation_id", "request_id", "status", "received_at", "payload", "feedback"}, label="ActionReceipt")
        ensure(receipt["operation_id"] == command["operation_id"] and receipt["request_id"] == request_id,
               "Action receipt identity mismatch", "schema_mismatch")
        ensure(receipt["status"] in ("accepted", "completed", "rejected", "unknown"), "Invalid action status", "schema_mismatch")
        if receipt["payload"] is not None:
            self._payload(receipt["payload"], self.description["operations"][name]["receipt_schema_ref"])
        if self.description["advance_mode"] == "on_action" and receipt["status"] in ("accepted", "completed"):
            self.pending_transition = True
        for feedback in receipt["feedback"]:
            self._raw_feedback(feedback)
        self._apply_update(self._invoke("task", "on_action", self.task_session.on_action, copy.deepcopy(receipt)))
        if receipt["status"] == "unknown":
            raise GymTSError("backend_failure", "Operation outcome is unknown; automatic resend is forbidden",
                             stage="act", run_id=self.run_id, links={"operation_id": command["operation_id"]},
                             side_effect="possible")

    def run(self):
        status, completion = "succeeded", "task_completed"
        resolved_ref = self.artifacts.save_json(self.spec, "gymts.experiment/1")
        limits = self.spec["execution"]["limits"]
        if limits["max_wall_time_s"] is not None:
            self.deadline = time.monotonic() + limits["max_wall_time_s"]
        scene, execution = self.spec["scene"], self.spec["execution"]
        try:
            self.records.begin_run({"run_id": self.run_id, "resolved_spec_ref": resolved_ref,
                "component_refs": [self.description["adapter_ref"], self.td["plugin_ref"], self.cm["component_ref"], self.cm["implementation_ref"]],
                "created_at": self.started_at, "origin": "executed",
                "source_refs": copy.deepcopy(self.spec.get("provenance", {}).get("source_refs", [])),
                "usage_policy_ref": copy.deepcopy(self.spec.get("provenance", {}).get("usage_policy_ref"))})
            self.began = True
            self._emit("run_start", {"resolved_spec_ref": resolved_ref})
            self._checkpoint()
            # Actual resource availability and plugin construction belong to an
            # execution, so failure here still produces a sealed failed Run.
            check_execution_resources(self.spec, self.artifacts, self.schemas)
            source_refs = scene["environment"]["source"].get("connection", {}).get("artifact_refs", [])
            self.environment = self._invoke("environment", "create", self.service.registries.environments.create,
                scene["environment"], RestrictedServices(self.artifacts, refs=source_refs, schemas=self.schemas))
            ensure(self._invoke("environment", "describe", self.environment.describe) == self.description, "Opened Environment differs from its pure declaration", "conflict")
            self.task = self._invoke("task", "create", self.service.tasks.create, scene["task"])
            ensure(self._invoke("task", "describe", self.task.describe) == self.td, "Opened Task differs from its pure declaration", "conflict")
            start = {"run_id": self.run_id, "mode": execution["start"]["mode"], "scope": execution["scope"],
                     "read_scope": self.read_scope, "feedback_until": execution["feedback_until"], "seed": execution["seed"],
                     "permitted_variables": self.variables, "permitted_operations": self.operations}
            self.session = self._invoke("environment", "start", self.environment.start, copy.deepcopy(start))
            self._emit("artifact", {"role": "session", "value": self.session})
            keys(self.session, {"session_id", "run_id", "environment_id", "source_revision", "actual_mode", "actual_scope",
                               "read_scope", "clock", "initial_cursor", "seed_used", "ownership", "public_context"}, label="SessionInfo")
            ensure(self.session["run_id"] == self.run_id and self.session["actual_mode"] == start["mode"],
                   "Actual session identity/mode differs", "schema_mismatch")
            ensure(self.session["environment_id"] == self.description["environment_id"], "Actual environment identity differs", "conflict")
            ensure(self.session["ownership"] == ("attached" if start["mode"] == "attach" else "created"),
                   "Session ownership differs from start mode", "schema_mismatch")
            public = self.session["public_context"]
            if self.description["context_schema_ref"] is not None:
                self._payload(public, self.description["context_schema_ref"])
            else:
                ensure(public is None or public == inline({}), "Environment has not declared a public context schema", "schema_mismatch")
            clock = self.session["clock"]
            keys(clock, {"domain", "now", "visible_until"}, label="Session clock")
            ensure(clock["domain"] == self.description["clock_domain"], "Session clock domain differs", "schema_mismatch")
            ensure(isinstance(parse_time(clock["now"]), int) == (clock["domain"] == "step") and
                   isinstance(parse_time(clock["visible_until"]), int) == (clock["domain"] == "step"),
                   "Session clock time type differs from its domain", "schema_mismatch")
            actual_read = self.session["read_scope"]
            keys(actual_read, {"start", "end"}, label="Session read_scope")
            ensure(time_compare(actual_read["start"], self.read_scope["start"]) >= 0 and
                   (self.read_scope["end"] is None or (actual_read["end"] is not None and
                    time_compare(actual_read["end"], self.read_scope["end"]) <= 0)),
                   "Session expanded its authorized read_scope", "permission_denied")
            self.read_scope = intersect_scope(self.read_scope, actual_read)
            ensure(time_compare(clock["visible_until"], self.read_scope["start"]) >= 0 and
                   (self.read_scope["end"] is None or time_compare(clock["visible_until"], self.read_scope["end"]) <= 0),
                   "Initial visible frontier exceeds the readable scope", "permission_denied")
            ensure(self.session["seed_used"] == start["seed"], "Environment did not honor seed", "unsupported_capability")
            ensure(self.session["source_revision"] == scene["environment"]["source"]["revision"] or
                   scene["environment"]["source"]["kind"] == "live", "Environment source revision changed", "conflict")
            ensure(self.environment.describe() == self.description, "Environment capabilities changed during start", "conflict")
            self.effective_scope = intersect_scope(execution["scope"], self.session["actual_scope"])
            self._emit("artifact", {"role": "effective_scope", "value": self.effective_scope})
            self.clock, self.cursor = self.session["clock"], self.session["initial_cursor"]
            self.main_frontier = self.read_scope["start"]
            self.data = RestrictedServices(self.artifacts, purpose="runtime", schemas=self.schemas)
            context = {"run_id": self.run_id, "session": self.session, "effective_scope": self.effective_scope,
                       "execution": execution, "data": self.data}
            self.task_session = self._invoke("task", "bind", self.task.bind, scene["task"], scene["binding"], self.description, context)
            self.candidate = self._invoke("candidate", "create", self.service.candidates.create, self.spec["candidate"])
            learning = execution["learning"]
            self.resources = RestrictedServices(self.artifacts, refs=[self.spec["candidate"]["artifact"]] + self.spec["candidate"]["inherited_state"],
                views=[learning["training_view"], learning["training_targets"]], purpose="prepare", schemas=self.schemas)
            if self.spec["recording"]["model_calls"] != "none":
                self.traces = RunTraceCollector(
                    self.run_id, self.spec["recording"]["model_calls"], self.schemas, self.artifacts,
                    lambda kind, ref, links: self._emit(kind, ref, links, storage="artifact"),
                    self._capture_problem, self._capture_storage_failure,
                    execution_events=lambda: self.records.get_run(self.run_id)["events"])
            self._checkpoint()
            randomness = {"seed": execution["seed"], "scope": "run", "algorithm": "python.random.Random",
                          "backend_enforcement": "adapter"}
            self._emit("artifact", {"role": "candidate_randomness", "value": randomness})
            prepared = self._invoke("candidate", "prepare", self.candidate.prepare, {"run_id": self.run_id, "task_protocol_ref": self.td["task_protocol_ref"],
                "candidate_spec": self.spec["candidate"], "implementation_ref": self.cm["implementation_ref"],
                "session_context": self.session["public_context"], "training_targets": learning["training_targets"],
                "alignment_schema_ref": learning["alignment_schema_ref"], "learning": learning,
                "resources": self.resources, "traces": self.traces,
                "execution_seed": execution["seed"], "rng": random.Random(execution["seed"]),
                "randomness": copy.deepcopy(randomness)}, learning["training_view"])
            keys(prepared, {"model_revision", "state_refs", "training_provenance_ref"}, label="PreparationResult")
            for ref in prepared["state_refs"]:
                self.artifacts.resolve(ref)
            if learning["prepare"] == "fit":
                ensure(prepared["training_provenance_ref"] is not None and prepared["model_revision"] is not None,
                       "fit did not publish provenance and state revision", "schema_mismatch")
            if prepared["training_provenance_ref"] is not None:
                self.artifacts.resolve(prepared["training_provenance_ref"])
            if self.cm["model_revision_mode"] in ("fixed", "tracked"):
                ensure(prepared["model_revision"] is not None, "Candidate did not identify its model revision", "schema_mismatch")
            self.model_revision = prepared["model_revision"]
            self.artifact_refs.extend(prepared["state_refs"])
            self._emit("candidate_prepare", prepared)
            while True:
                self._checkpoint()
                batch = self._request(self._invoke("task", "next_observation", self.task_session.next_observation), main=True)
                self._process_queue()
                if self.env_ended:
                    reason = batch["end"]["reason"]
                    completion = {"read_scope_end": "scope_reached"}.get(reason, reason)
                    break
                boundary = self.effective_scope["end"]
                if boundary is not None and time_compare(self.clock["now"], boundary) >= 0:
                    if execution["feedback_until"] is not None and time_compare(execution["feedback_until"], boundary) > 0:
                        self.draining = True
                        if self.description["advance_mode"] == "on_action":
                            completion = "scope_reached"
                            break
                    else:
                        completion = "scope_reached"
                        break
                if self.task_done and not self.queue and self.current_case is None and not self.draining:
                    completion = "task_completed"
                    break
                if self.task_done and self.current_case is not None and not self.queue:
                    completion = "task_completed"
                    break
                if self.draining:
                    if execution["feedback_until"] is not None and time_compare(self.clock["now"], execution["feedback_until"]) >= 0:
                        completion = "scope_reached"
                        break
                elif (self.description["advance_mode"] == "on_action" and not self.pending_transition
                      and self.td.get("use_default_command", False)):
                    self._act(default=True)
                elif self.description["advance_mode"] == "on_action" and not self.pending_transition and not self.queue:
                    raise GymTSError("invalid_state", "Task neither issued an action nor allowed a default progression")
                if batch["status"] == "waiting":
                    # Avoid busy-polling an external source. Backend calls must honor max_wait_ms.
                    time.sleep(.01)
        except _Stop as stop:
            completion = stop.completion
        except KeyboardInterrupt:
            status, completion = "cancelled", "cancelled"
        except Exception as error:
            status, completion = "failed", "error"
            info = self._error(error, "run")
            self.errors.append(info)
            if self.began and not self.storage_failed:
                try:
                    self._emit("error", info)
                except GymTSError:
                    pass
        finally:
            for name, component, args in (("candidate", self.candidate, ()),
                                          ("task", self.task_session, (completion,)),
                                          ("environment", self.environment, ())):
                if component is None:
                    self.cleanup[name] = {"status": "not_started"}
                    continue
                try:
                    summary = self._invoke(name, "finish", component.finish, *args)
                    try:
                        canonical_json(summary)
                    except (TypeError, ValueError) as exc:
                        raise GymTSError("schema_mismatch", "Cleanup summary is not finite JSON",
                                         stage=f"cleanup.{name}", run_id=self.run_id) from exc
                    self.cleanup[name] = {"status": "succeeded", "summary": summary}
                    refs = summary if name == "candidate" else summary.get("artifact_refs", [])
                    for ref in refs:
                        self.artifacts.resolve(ref)
                    self.artifact_refs.extend(refs)
                except Exception as error:
                    info = self._error(error, f"cleanup.{name}")
                    self.cleanup[name] = {"status": "failed", "error": info}
                    self.errors.append(info)
                    status, completion = "failed", "error"
        if not self.began or self.storage_failed:
            raise GymTSError("recording_failure", "Run could not be reliably sealed", stage="recording", run_id=self.run_id,
                             links={"resolved_spec_ref": resolved_ref, "last_confirmed_event_id": self.last_event})
        try:
            for cid, case in self.cases.items():
                if case["closure"] is None:
                    self._close_case({"case_id": cid, "status": "incomplete", "reason": completion})
            result_ref = self.artifacts.save_json(self.results, "gymts.task-results/1")
            final = {"protocol_version": "gymts.run-result/1", "run_id": self.run_id, "purpose": self.spec["purpose"],
                "status": status, "completion": completion, "started_at": self.started_at, "ended_at": utc_now(),
                "resolved_spec_ref": resolved_ref, "result_ref": result_ref,
                "artifact_refs": list({canonical_json(ref): ref for ref in self.artifact_refs}.values()),
                "evidence_status": self.evidence_status, "errors": self.errors,
                "summary": {"stop_reason": completion, "counts": self.counts, "cleanup": self.cleanup,
                    "environment_end": self.last_batch["end"] if self.last_batch else None}}
            return self.records.end_run(self.run_id, final)
        except Exception as error:
            raise GymTSError("recording_failure", "Could not publish final RunResult", stage="recording", run_id=self.run_id,
                             links={"resolved_spec_ref": resolved_ref, "last_confirmed_event_id": self.last_event}) from error

    def _error(self, error, stage):
        if isinstance(error, GymTSError):
            info = error.to_dict()
            info["run_id"] = self.run_id
            return info
        # Exception text may include request bodies or credentials. Keep it out of public evidence.
        return GymTSError("backend_failure", f"Plugin raised {type(error).__name__}", stage=stage,
                          run_id=self.run_id).to_dict()
