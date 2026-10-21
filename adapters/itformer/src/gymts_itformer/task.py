"""Preserve original questions and native signal projection; never read gold."""
import copy
from gymts.contracts import in_scope
from gymts.plugin_support import component, empty_update, fail, identifier, payload, unpack
from .contracts import INPUT, OUTPUT, RESULT, OUTCOME, ALIGNMENT, PUBLIC, PROTOCOL, PARSER_REF
from .scoring import parse_options


class ITFormerTask:
    def __init__(self, spec):
        pass

    @staticmethod
    def describe_spec(spec):
        return {"plugin_ref": component("itformer-qa"), "task_protocol_ref": PROTOCOL,
            "input_schema_ref": INPUT, "output_schema_ref": OUTPUT, "result_schema_ref": RESULT,
            "outcome_schema_ref": OUTCOME, "alignment_schema_ref": ALIGNMENT,
            "required_variables": {"sample": {"dtype": "string", "shape": [], "unit": "sample"}},
            "required_operations": {}, "required_capabilities": [], "use_default_command": False,
            "warmup": {"duration": None, "min_points": 0}}

    @staticmethod
    def compatibility(context):
        if context["environment"]["native_schema_ref"] != PUBLIC:
            fail("unsupported_capability", "ITFormer Task requires the public signal/question contract")

    def describe(self):
        return self.describe_spec({})

    def bind(self, spec, binding, environment, execution):
        if environment["native_schema_ref"] != PUBLIC or environment["clock_domain"] != "step":
            fail("unsupported_capability", "ITFormer Task requires step-clock public samples")
        return Session(binding, execution)


class Session:
    def __init__(self, binding, execution):
        self.binding, self.execution = copy.deepcopy(binding), execution
        self.cursor = execution["session"]["initial_cursor"]
        self.revision = unpack(execution["session"]["public_context"], execution["data"])["dataset_revision"]
        self.done = False
        self.seen, self.completed = set(), set()
        self.counts = {key: 0 for key in ("cases_started", "cases_completed", "cases_incomplete", "results_valid", "results_invalid")}

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
                fail("schema_mismatch", "Source step must be a nonnegative integer")
            token = sample["sample_id"]
            if token not in self.seen and not self.done and in_scope(point, self.execution["effective_scope"]):
                self.seen.add(token)
                update["inputs"].append({"run_id": self.execution["run_id"], "case_id": identifier("case"),
                    "turn_id": 0, "input_id": identifier("input"), "task_protocol_ref": PROTOCOL,
                    "decision_time": point, "alignment_key": {"dataset_revision": self.revision, "sample_id": token},
                    "observation_refs": [self.execution["data"].observation_ref(batch["batch_id"])],
                    "payload": payload(INPUT, sample)})
                self.counts["cases_started"] += 1
        self.done = self.done or batch["status"] == "end"
        update["done"] = self.done
        return update

    def on_action(self, receipt):
        fail("unsupported_capability", "ITFormer QA has no environment actions")

    def interpret(self, task_input, output, output_id):
        if task_input["input_id"] in self.completed:
            fail("conflict", "Input has already been interpreted")
        sample = unpack(task_input["payload"], self.execution["data"])
        raw = unpack(output["payload"], self.execution["data"])["raw_text"]
        options = parse_options(raw) if sample["stage"] in (2, 3) else None
        reason = "empty_answer" if not raw.strip() else (
            "unparseable_closed_answer" if sample["stage"] in (2, 3) and options is None else None)
        record = {key: copy.deepcopy(task_input[key]) for key in (
            "run_id", "case_id", "turn_id", "input_id", "task_protocol_ref", "decision_time", "alignment_key")}
        record.update(result_id=identifier("result"), output_id=output_id,
            status="valid" if reason is None else "invalid", payload=payload(RESULT, {
                "raw_text": raw, "parsed_options": options, "stage": sample["stage"],
                "reason": reason, "parser_ref": PARSER_REF}))
        self.completed.add(task_input["input_id"])
        self.counts["cases_completed"] += 1
        self.counts["results_valid" if reason is None else "results_invalid"] += 1
        return {"results": [record], "requests": [], "complete": True}

    def finish(self, reason):
        return dict(self.counts, cases_incomplete=self.counts["cases_started"] - self.counts["cases_completed"],
            pending_requests=[], artifact_refs=[])
