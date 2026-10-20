"""Static execution, task interpretation, baseline and independent scoring."""
import copy
import math

from gymts.contracts import canonical_json, in_scope, intersect_scope, utc_now
from gymts.plugin_support import clock, component, empty_update, end_info, fail, identifier, payload, unpack
from .contracts import ALIGNMENT, CONTEXT, OUTCOME, OUTPUT, PROTOCOL, PUBLIC, RESULT, SNAPSHOT, TOKEN


class StaticEnvironment:
    @staticmethod
    def describe_spec(spec):
        return {"environment_id": "hf-static-snapshot", "adapter_ref": component("hf-static-snapshot"),
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
            fail("schema_mismatch", "HF static environment requires one public snapshot")
        snapshot = services.read_json(reference)
        if snapshot["dataset_revision"] != spec["source"]["revision"]:
            fail("conflict", "HF snapshot differs from its fixed dataset revision")
        self.sample, self.revision = snapshot["sample"], snapshot["dataset_revision"]
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
            "environment_id": "hf-static-snapshot", "source_revision": self.revision,
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


class ForecastTask:
    def __init__(self, spec):
        self.spec = copy.deepcopy(spec)

    @staticmethod
    def describe_spec(spec):
        return {"plugin_ref": component("hf-static-forecast"), "task_protocol_ref": PROTOCOL,
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
        return ForecastSession(binding, execution)


class ForecastSession:
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
                update["inputs"].append({"run_id": self.execution["run_id"], "case_id": identifier("case"),
                    "turn_id": 0, "input_id": identifier("input"), "task_protocol_ref": PROTOCOL,
                    "decision_time": point, "alignment_key": {"dataset_revision": self.revision,
                    "sample_id": sample["sample_id"]},
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
        values = unpack(output["payload"], self.execution["data"])["values"]
        valid = len(values) == sample["horizon"] and all(math.isfinite(value) for value in values)
        record = {key: copy.deepcopy(task_input[key]) for key in (
            "run_id", "case_id", "turn_id", "input_id", "task_protocol_ref", "decision_time", "alignment_key")}
        record.update(result_id=identifier("result"), output_id=output_id,
                      status="valid" if valid else "invalid", payload=payload(RESULT, {"values": values}))
        self.completed.add(task_input["input_id"])
        self.counts["cases_completed"] += 1
        self.counts["results_valid" if valid else "results_invalid"] += 1
        return {"results": [record], "requests": [], "complete": True}

    def finish(self, reason):
        return dict(self.counts, cases_incomplete=self.counts["cases_started"] - self.counts["cases_completed"],
                    pending_requests=[], artifact_refs=[])


class LastValueCandidate:
    REVISION = "hf-static-last-value/1.0.0"

    def __init__(self, spec):
        self.spec, self.state = spec, "created"

    def prepare(self, context, training):
        if (self.state != "created" or training is not None or context["learning"]["prepare"] != "load_only"
                or context["learning"]["online"] != "frozen" or self.spec.get("artifact") is not None
                or self.spec.get("inherited_state")):
            fail("unsupported_capability", "Last-value baseline supports only frozen load_only inference")
        self.resources, self.state = context["resources"], "prepared"
        return {"model_revision": self.REVISION, "state_refs": [], "training_provenance_ref": None}

    def infer(self, task_input):
        if self.state != "prepared" or task_input["task_protocol_ref"] != PROTOCOL:
            fail("invalid_state", "Last-value baseline requires its prepared static forecast Task")
        sample = unpack(task_input["payload"], self.resources)
        return {"input_id": task_input["input_id"], "task_protocol_ref": PROTOCOL, "produced_at": utc_now(),
            "model_revision": self.REVISION,
            "payload": payload(OUTPUT, {"values": [sample["history"][-1]] * sample["horizon"]})}

    def update(self, feedback):
        fail("unsupported_capability", "Last-value baseline has no online updates")

    def finish(self):
        self.state = "closed"
        return []


class ReferenceMAE:
    def __init__(self, spec):
        pass

    def validate_scoring(self, scoring):
        alignment = scoring["alignment"]
        if (scoring["metrics"] != ["mae"] or alignment["matching"] != "exact"
                or alignment["keys"] != ["dataset_revision", "sample_id"] or alignment["duplicate_policy"] != "error"):
            fail("unsupported_capability", "Static MAE requires unique exact sample alignment and metric mae")

    def score(self, results, outcomes, context):
        services, scoring = context["services"], context["scoring"]
        self.validate_scoring(scoring)
        def records(view):
            value = services.read_json(view["records_ref"])
            if isinstance(value, list):
                return value
            if isinstance(value, dict) and isinstance(value.get("records"), list):
                return value["records"]
            fail("schema_mismatch", "Static scoring requires a records list")
        rows, gold = records(results), records(outcomes)
        if len(rows) > 1:
            fail("schema_mismatch", "One static evaluation unit may contain at most one result")
        def key(row):
            alignment = row["alignment_key"]
            if set(alignment) != {"dataset_revision", "sample_id"}:
                fail("schema_mismatch", "Static forecast alignment differs from its fixed schema")
            return canonical_json(alignment)
        matched = {}
        for outcome in gold:
            if "evaluation" not in outcome["allowed_uses"]:
                fail("permission_denied", "Reference is not authorized for evaluation")
            token = key(outcome)
            if token in matched:
                fail("conflict", "Duplicate static forecast reference")
            matched[token] = outcome
        row = rows[0] if rows else None
        outcome = matched.get(key(row)) if row else None
        counts = {"eligible": 1, "scored": 0, "missing": 0, "invalid": 0, "excluded": 0}
        value, reason = None, None
        if row is None or outcome is None:
            counts["missing"], reason = 1, "missing_result" if row is None else "missing_reference"
        elif row["status"] != "valid":
            counts["invalid"], reason = 1, "invalid_result"
        else:
            prediction, target = unpack(row["payload"], services)["values"], unpack(outcome["payload"], services)["values"]
            if len(prediction) != len(target):
                counts["invalid"], reason = 1, "horizon_mismatch"
            else:
                value = sum(abs(float(a) - float(b)) for a, b in zip(prediction, target)) / len(target)
                counts["scored"] = 1
        diagnostics = {"result_id": row["result_id"] if row else None,
                       "outcome_id": outcome["outcome_id"] if outcome else None, "value": value, "reason": reason}
        return {"metrics": {"mae": {"value": value, "status": "ready" if value is not None else "insufficient_evidence",
                                   "counts": counts, "reason": reason}},
                "item_scores_ref": services.save_json({"records": [diagnostics]}, "gymts.json/1"), "diagnostics_ref": None}
