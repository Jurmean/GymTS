"""Task interpretation for numeric sources, independent of their provider and models."""
import copy

from gymts.contracts import in_scope
from gymts.plugin_support import component, empty_update, fail, identifier, payload, unpack

from .contracts import (ALIGNMENT, CONTEXT, INPUT, NATIVE, OUTCOME, OUTPUT, PROTOCOL, RESULT,
                        validate_input, validate_sample)
from .semantics import (PARSER_REF, TASK_METRICS, TASK_OUTPUT_SCHEMAS, TASK_VERSIONS,
                        answer_semantic_reason, parse_answer, validate_task_params)


def make_task_input(sample, task_id, task_version):
    """Interpret source facts for this task; source objects need no task identity.

    Benchmark adapters may fix their task via public annotations. Re-tasking
    such material requires a separately named source view and independent gold.
    """
    sample = validate_sample(sample)
    validate_task_params({"params": {"task_id": task_id, "task_version": task_version}})
    fixed = sample["annotations"].get("benchmark_task_id")
    fixed_version = sample["annotations"].get("benchmark_task_version")
    if fixed is not None and (fixed != task_id or fixed_version != task_version):
        fail("unsupported_capability", "Benchmark source fixes a different task; publish an explicit new view")
    series, context = sample["series"], copy.deepcopy(sample["context"])
    if task_id == "relation.lagged_dependence":
        if len(series) != 2:
            fail("unsupported_capability", "Lagged dependence requires two ordered series")
    elif task_id == "similarity.shape_retrieval":
        names = {item["name"].lower().replace(" ", "_") for item in series}
        if "query" not in names or not any(name.startswith("candidate_") for name in names):
            fail("unsupported_capability", "Shape retrieval requires named Query and Candidate series")
    elif len(series) != 1:
        fail("unsupported_capability", "This task requires exactly one series")
    schema = copy.deepcopy(TASK_OUTPUT_SCHEMAS[task_id])
    names = ", ".join(item["name"] for item in series)
    questions = {
        "pattern.trend_direction": "Classify the trend as increasing, decreasing, or stable.",
        "anomaly.point_indices": "Return the strictly increasing zero-based indices of point anomalies.",
        "pattern.seasonality_profile": "Classify seasonality as none, single_period, or multiple_periods.",
        "process.stationarity_type": "Classify the process as stationary, deterministic_trend, unit_root, or variance_regime.",
        "relation.lagged_dependence": "Identify lagged dependence between the first (X) and second (Y) series; return direction and lag (0 through 16).",
        "similarity.shape_retrieval": "Choose the Candidate series most similar in shape to Query; return its candidate_id.",
    }
    if task_id == "forecast.numeric":
        horizon = context.get("horizon")
        if type(horizon) is not int or horizon < 1:
            fail("invalid_config", "Forecast requires an explicit positive public context.horizon")
        schema["properties"]["forecast"].update(minItems=horizon, maxItems=horizon)
        question = "Forecast the next " + str(horizon) + " values."
    else:
        question = questions[task_id]
    return validate_input({"task_id": task_id, "task_version": task_version,
        "question": question + " Series: " + names + ". Return only a JSON object matching response_schema.",
        "series": series, "context": context, "response_schema": schema})


class TimeSeriesQATask:
    def __init__(self, spec):
        self.params = validate_task_params(spec)

    @staticmethod
    def describe_spec(spec):
        validate_task_params(spec)
        return {"plugin_ref": component("timeseries-qa"), "task_protocol_ref": PROTOCOL,
            "input_schema_ref": INPUT, "output_schema_ref": OUTPUT, "result_schema_ref": RESULT,
            "outcome_schema_ref": OUTCOME, "alignment_schema_ref": ALIGNMENT,
            "required_variables": {"sample": {"dtype": "string", "shape": [], "unit": "sample"}},
            "required_operations": {}, "required_capabilities": [], "use_default_command": False,
            "warmup": {"duration": None, "min_points": 0}}

    def describe(self):
        return self.describe_spec({"params": self.params})

    @staticmethod
    def check_compatibility_spec(context):
        environment = context["environment"]
        if (environment["native_schema_ref"] != NATIVE or environment["context_schema_ref"] != CONTEXT
                or environment["clock_domain"] != "step" or environment["observation_granularity"] != "transition"):
            fail("unsupported_capability", "Time-series QA requires the public numeric sample/context contracts on a step clock")

    def bind(self, spec, binding, environment, execution):
        if environment["native_schema_ref"] != NATIVE or environment["clock_domain"] != "step":
            fail("unsupported_capability", "Time-series QA requires public numeric samples on a step clock")
        return TimeSeriesQASession(self.params, binding, execution)


class TimeSeriesQASession:
    def __init__(self, params, binding, execution):
        self.params, self.binding, self.execution = copy.deepcopy(params), copy.deepcopy(binding), execution
        self.cursor = execution["session"]["initial_cursor"]
        public = unpack(execution["session"]["public_context"], execution["data"])
        self.dataset_revision = public["dataset_revision"]
        self.done, self.seen, self.completed = False, {}, set()
        self.counts = {key: 0 for key in ("cases_started", "cases_completed", "cases_incomplete",
                                        "results_valid", "results_invalid")}

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
                fail("schema_mismatch", "Numeric sample snapshot_time must be a nonnegative step")
            token = sample["sample_token"]
            if token in self.seen and self.seen[token] != sample:
                fail("conflict", "A sample token has conflicting source facts")
            if token not in self.seen and not self.done and in_scope(point, self.execution["effective_scope"]):
                value = make_task_input(sample, **self.params)
                self.seen[token] = copy.deepcopy(sample)
                update["inputs"].append({"run_id": self.execution["run_id"], "case_id": identifier("case"),
                    "turn_id": 0, "input_id": identifier("input"), "task_protocol_ref": PROTOCOL,
                    "decision_time": point, "alignment_key": {"dataset_revision": self.dataset_revision, "sample_token": token},
                    "observation_refs": [self.execution["data"].observation_ref(batch["batch_id"])],
                    "payload": payload(INPUT, value)})
                self.counts["cases_started"] += 1
        self.done = self.done or batch["status"] == "end"
        update["done"] = self.done
        return update

    def on_action(self, receipt):
        fail("unsupported_capability", "Numeric QA has no environment actions")

    def interpret(self, task_input, output, output_id):
        if task_input["input_id"] in self.completed:
            fail("conflict", "QA input has already been interpreted")
        value = unpack(task_input["payload"], self.execution["data"])
        raw = unpack(output["payload"], self.execution["data"])["raw_text"]
        parsed, reason = parse_answer(raw, value["response_schema"], self.params["task_id"], value)
        record = {key: copy.deepcopy(task_input[key]) for key in (
            "run_id", "case_id", "turn_id", "input_id", "task_protocol_ref", "decision_time", "alignment_key")}
        record.update(result_id=identifier("result"), output_id=output_id,
            status="valid" if reason is None else "invalid", payload=payload(RESULT, {
                "raw_text": raw, "parsed": parsed, "reason": reason, "parser_ref": PARSER_REF}))
        self.completed.add(task_input["input_id"])
        self.counts["cases_completed"] += 1
        self.counts["results_valid" if reason is None else "results_invalid"] += 1
        return {"results": [record], "requests": [], "complete": True}

    def finish(self, reason):
        return dict(self.counts, cases_incomplete=self.counts["cases_started"] - self.counts["cases_completed"],
                    pending_requests=[], artifact_refs=[])
