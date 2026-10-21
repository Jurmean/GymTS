"""A model independent distribution task over the external numerical source."""
import copy
import json

from gymts.contracts import in_scope
from gymts.plugin_support import component, empty_update, fail, identifier, payload, unpack
from gymts_timeseries.contracts import ALIGNMENT, CONTEXT, NATIVE, validate_sample
from .contracts import INPUT, OUTPUT, OUTCOME, PARSER, PROTOCOL, RESULT, validate_input, validate_prediction


class DistributionTask:
    def __init__(self, spec):
        if spec["params"]:
            fail("invalid_config", "The task takes its declared forecast grid from the public source")

    @staticmethod
    def describe_spec(spec):
        if spec["params"]:
            fail("invalid_config", "Distribution task has no hidden parameters")
        return {"plugin_ref": component("forecast-distribution"), "task_protocol_ref": PROTOCOL,
                "input_schema_ref": INPUT, "output_schema_ref": OUTPUT, "result_schema_ref": RESULT,
                "outcome_schema_ref": OUTCOME, "alignment_schema_ref": ALIGNMENT,
                "required_variables": {"sample": {"dtype": "string", "shape": [], "unit": "sample"}},
                "required_operations": {}, "required_capabilities": [], "use_default_command": False,
                "warmup": {"duration": None, "min_points": 0}}

    def describe(self):
        return self.describe_spec({"params": {}})

    @staticmethod
    def check_compatibility_spec(context):
        env = context["environment"]
        if env["native_schema_ref"] != NATIVE or env["context_schema_ref"] != CONTEXT or env["clock_domain"] != "step":
            fail("unsupported_capability", "Distribution task requires a neutral numerical snapshot")

    def bind(self, spec, binding, environment, execution):
        return DistributionSession(binding, execution)


class DistributionSession:
    def __init__(self, binding, execution):
        self.binding, self.execution = binding, execution
        self.cursor = execution["session"]["initial_cursor"]
        self.revision = unpack(execution["session"]["public_context"], execution["data"])["dataset_revision"]
        self.seen, self.completed, self.done = set(), set(), False

    def next_observation(self):
        return {"request_id": identifier("request"), "kind": "next", "entities": ["samples"],
                "variables": [self.binding["variables"]["sample"]["source"]], "cursor": self.cursor, "max_wait_ms": 0}

    def consume(self, batch):
        self.cursor = batch["cursor"]
        update = empty_update(self.done)
        if batch["data"] and batch["data"].get("native"):
            sample = validate_sample(unpack(batch["data"]["native"], self.execution["data"]))
            token, point = sample["sample_token"], batch["snapshot_time"]
            if token not in self.seen and in_scope(point, self.execution["effective_scope"]):
                value = validate_input({"series": sample["series"], "context": sample["context"]})
                self.seen.add(token)
                update["inputs"].append({"run_id": self.execution["run_id"], "case_id": identifier("case"),
                    "turn_id": 0, "input_id": identifier("input"), "task_protocol_ref": PROTOCOL,
                    "decision_time": point, "alignment_key": {"dataset_revision": self.revision, "sample_token": token},
                    "observation_refs": [self.execution["data"].observation_ref(batch["batch_id"])],
                    "payload": payload(INPUT, value)})
        self.done = self.done or batch["status"] == "end"
        update["done"] = self.done
        return update

    def on_action(self, receipt):
        fail("unsupported_capability", "Distribution forecasts perform no environment actions")

    def interpret(self, task_input, output, output_id):
        if task_input["input_id"] in self.completed:
            fail("conflict", "Input was already completed")
        value = unpack(task_input["payload"], self.execution["data"])
        raw = unpack(output["payload"], self.execution["data"])["raw_text"]
        try:
            prediction = json.loads(raw)
            validate_prediction(prediction, value["context"])
            reason = None
        except (ValueError, TypeError, KeyError) as error:
            prediction, reason = None, str(error)
        record = {k: copy.deepcopy(task_input[k]) for k in (
            "run_id", "case_id", "turn_id", "input_id", "task_protocol_ref", "decision_time", "alignment_key")}
        record.update(result_id=identifier("result"), output_id=output_id,
                      status="valid" if reason is None else "invalid",
                      payload=payload(RESULT, {"raw_text": raw, "parsed": prediction, "reason": reason,
                                               "parser_ref": PARSER, "context": value["context"]}))
        self.completed.add(task_input["input_id"])
        return {"results": [record], "requests": [], "complete": True}

    def finish(self, reason):
        return {"cases_started": len(self.seen), "cases_completed": len(self.completed),
                "cases_incomplete": len(self.seen)-len(self.completed), "pending_requests": [], "artifact_refs": []}
