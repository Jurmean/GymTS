"""Public-prompt Task projection and answer-format interpretation only."""

import copy

from gymts.contracts import in_scope
from gymts.plugin_support import component, empty_update, fail, identifier, payload, unpack
from .contracts import ALIGNMENT, CONTEXT, INPUT, NATIVE, OUTCOME, OUTPUT, PARSER_REF, PROTOCOL, RESULT
from .rewards import parse_completion


class RLVerifiableQATask:
    def __init__(self, spec):
        self.spec = copy.deepcopy(spec)
        if spec.get("params", {}):
            fail("invalid_config", "RL verifiable QA has no task parameters")

    @staticmethod
    def describe_spec(spec):
        if spec.get("params", {}):
            fail("invalid_config", "RL verifiable QA has no task parameters")
        return {"plugin_ref": component("rl-verifiable-qa"), "task_protocol_ref": PROTOCOL,
            "input_schema_ref": INPUT, "output_schema_ref": OUTPUT, "result_schema_ref": RESULT,
            "outcome_schema_ref": OUTCOME, "alignment_schema_ref": ALIGNMENT,
            "required_variables": {"sample": {"dtype": "string", "shape": [], "unit": "sample"}},
            "required_operations": {}, "required_capabilities": [], "use_default_command": False,
            "warmup": {"duration": None, "min_points": 0}}

    @staticmethod
    def check_compatibility_spec(context):
        environment = context["environment"]
        if environment["clock_domain"] != "step" or environment["observation_granularity"] != "transition":
            fail("unsupported_capability", "RL QA requires a step snapshot environment")

    def describe(self):
        return self.describe_spec(self.spec)

    def bind(self, spec, binding, environment, execution):
        if environment["clock_domain"] != "step" or environment["observation_granularity"] != "transition":
            fail("unsupported_capability", "RL QA requires a step snapshot environment", "bind")
        return RLQASession(binding, execution)


class RLQASession:
    def __init__(self, binding, execution):
        self.binding, self.execution = copy.deepcopy(binding), execution
        self.cursor = execution["session"]["initial_cursor"]
        self.dataset_revision = unpack(execution["session"]["public_context"], execution["data"])["dataset_revision"]
        self.done, self.seen, self.completed = False, {}, set()
        self.counts = {key: 0 for key in ("cases_started", "cases_completed", "cases_incomplete", "results_valid", "results_invalid")}
        self._summary = None

    def next_observation(self):
        return {"request_id": identifier("request"), "kind": "next", "entities": ["samples"],
            "variables": [self.binding["variables"]["sample"]["source"]], "cursor": self.cursor, "max_wait_ms": 0}

    def consume(self, batch):
        self.cursor = batch["cursor"]
        update = empty_update(self.done)
        if batch["data"] is not None and batch["data"].get("native") is not None:
            sample = unpack(batch["data"]["native"], self.execution["data"])
            point = batch["snapshot_time"]
            if type(point) is not int or point < 0:
                fail("schema_mismatch", "RL snapshot requires an integer sample step", "consume")
            token = sample["sample_id"]
            if token in self.seen:
                if self.seen[token] != sample:
                    fail("conflict", "Repeated RL sample has conflicting public content", "consume")
            elif not self.done and in_scope(point, self.execution["effective_scope"]):
                self.seen[token] = copy.deepcopy(sample)
                update["inputs"].append({"run_id": self.execution["run_id"], "case_id": identifier("case"), "turn_id": 0,
                    "input_id": identifier("input"), "task_protocol_ref": PROTOCOL, "decision_time": point,
                    "alignment_key": {"dataset_revision": self.dataset_revision, "sample_id": token, "group_id": sample["group_id"]},
                    "observation_refs": [self.execution["data"].observation_ref(batch["batch_id"])], "payload": payload(INPUT, sample)})
                self.counts["cases_started"] += 1
        self.done = self.done or batch["status"] == "end"
        update["done"] = self.done
        return update

    def on_action(self, receipt):
        fail("unsupported_capability", "RL prompt QA has no environment actions", "on_action")

    def interpret(self, task_input, output, output_id):
        if task_input["input_id"] in self.completed:
            fail("conflict", "RL QA input has already been interpreted", "interpret")
        sample = unpack(task_input["payload"], self.execution["data"])
        raw = unpack(output["payload"], self.execution["data"])["raw_text"]
        parsed, reason = parse_completion(raw, sample["task_id"])
        result = {key: copy.deepcopy(task_input[key]) for key in (
            "run_id", "case_id", "turn_id", "input_id", "task_protocol_ref", "decision_time", "alignment_key")}
        result.update(result_id=identifier("result"), output_id=output_id, status="valid" if reason is None else "invalid",
            payload=payload(RESULT, {"raw_text": raw, "parsed": parsed, "reason": reason, "parser_ref": PARSER_REF,
                                    "sample_id": sample["sample_id"], "task_id": sample["task_id"]}))
        self.completed.add(task_input["input_id"])
        self.counts["cases_completed"] += 1
        self.counts["results_valid" if reason is None else "results_invalid"] += 1
        return {"results": [result], "requests": [], "complete": True}

    def finish(self, reason):
        if self._summary is None:
            self.counts["cases_incomplete"] = self.counts["cases_started"] - self.counts["cases_completed"]
            self._summary = dict(self.counts, pending_requests=[], artifact_refs=[])
        return copy.deepcopy(self._summary)
