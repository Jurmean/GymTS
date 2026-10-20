"""Task/scorer contracts independent of a ChatTS checkout or GPU model."""

import copy
import json
import unittest

from gymts.contracts import GymTSError
from gymts_chatts.scoring import ChatTSQAScorer, point_metric
from gymts_chatts.task import (
    ALIGNMENT, INPUT, NATIVE, OUTPUT, OUTCOME, PARSER_REF, RESULT,
    TASK_METRICS, TASK_OUTPUT_SCHEMAS, ChatTSSyntheticQATask, parse_answer,
)
from gymts.plugin_support import payload


ANSWERS = {
    "pattern.trend_direction": {"trend_direction": "increasing"},
    "anomaly.point_indices": {"indices": [2, 6]},
    "forecast.numeric": {"forecast": [1.0, 2.0, 3.0]},
    "pattern.seasonality_profile": {"profile": "multiple_periods"},
    "process.stationarity_type": {"type": "unit_root"},
    "relation.lagged_dependence": {"direction": "x_to_y", "lag": 3},
    "similarity.shape_retrieval": {"candidate_id": "candidate_c"},
}


class MemoryServices:
    def __init__(self):
        self.saved = {}

    def save_json(self, value, schema_ref="gymts.json/1"):
        ref = {"artifact_id": str(len(self.saved)), "schema_ref": schema_ref}
        self.saved[ref["artifact_id"]] = copy.deepcopy(value)
        return ref

    def read_json(self, ref):
        return copy.deepcopy(self.saved[ref["artifact_id"]])

    def observation_ref(self, batch_id):
        return "committed-observation-" + batch_id


def params(task_id):
    return {"task_id": task_id, "task_version": "0.2.0" if task_id in (
        "pattern.trend_direction", "anomaly.point_indices", "forecast.numeric") else "0.1.0"}


def model_input(task_id):
    count = 2 if task_id == "relation.lagged_dependence" else 5 if task_id == "similarity.shape_retrieval" else 1
    return {"messages": [{"role": "user", "content": "Analyze the attached series and return JSON."}],
            "timeseries": [[float(i) for i in range(8)] for _ in range(count)],
            "series_names": ["series_" + str(i) for i in range(count)],
            "output_schema": copy.deepcopy(TASK_OUTPUT_SCHEMAS[task_id]),
            "context": {"horizon": 3} if task_id == "forecast.numeric" else {}}


def session(task_id, services=None):
    services = services or MemoryServices()
    spec = {"params": params(task_id)}
    task = ChatTSSyntheticQATask(spec)
    bound = task.bind(spec, {"variables": {"sample": {"source": "sample"}}, "operations": {}},
        {"clock_domain": "step", "observation_granularity": "transition"}, {
            "run_id": "run", "session": {"initial_cursor": "cursor-0",
                "public_context": payload("gymts.chatts/context/1", {"dataset_revision": "sha256:dataset"})},
            "effective_scope": {"start": 0, "end": 1}, "data": services})
    return bound, services


def batch(task_id, *, terminal=True):
    return {"batch_id": "batch-0", "cursor": "cursor-1", "snapshot_time": 0,
            "status": "end" if terminal else "data", "data": {"native": payload(NATIVE, {
                "sample_token": "opaque-token", **params(task_id), "model_input": model_input(task_id)})}}


def result_record(task_id, answer=None):
    bound, _ = session(task_id)
    task_input = bound.consume(batch(task_id))["inputs"][0]
    raw = json.dumps(ANSWERS[task_id] if answer is None else answer)
    effect = bound.interpret(task_input, {"payload": payload(OUTPUT, {"raw_text": raw, "evidence": {}})}, "output")
    return effect["results"][0]


def outcome_record(task_id, answer=None):
    return {"outcome_id": "gold", "revision": "1", "allowed_uses": ["evaluation"],
            "alignment_key": {"dataset_revision": "sha256:dataset", "sample_token": "opaque-token"},
            "available_at": "2026-01-01T00:00:00Z", "recorded_at": "2026-01-01T00:00:00Z",
            "payload": payload(OUTCOME, {**params(task_id), "expected_output": copy.deepcopy(
                ANSWERS[task_id] if answer is None else answer)})}


def score(task_id, rows=None, outcomes=None, duplicate_policy="error", metrics=None):
    services = MemoryServices()
    rows = [result_record(task_id)] if rows is None else rows
    outcomes = [outcome_record(task_id)] if outcomes is None else outcomes
    context = {"services": services, "scoring": {
        "alignment": {"schema_ref": ALIGNMENT, "keys": ["dataset_revision", "sample_token"],
                      "matching": "exact", "duplicate_policy": duplicate_policy},
        "metrics": list(TASK_METRICS[task_id]) if metrics is None else metrics}}
    result = ChatTSQAScorer({"params": params(task_id)}).score(
        {"records_ref": services.save_json(rows)}, {"records_ref": services.save_json(outcomes)}, context)
    return result, services


class ChatTSTaskContractsTest(unittest.TestCase):
    def test_seven_task_answers_parse_score_and_preserve_raw_output(self):
        for task_id, answer in ANSWERS.items():
            with self.subTest(task_id=task_id):
                bound, _ = session(task_id)
                update = bound.consume(batch(task_id))
                self.assertTrue(update["done"])
                self.assertEqual(len(update["inputs"]), 1, "Final sample was lost before done")
                task_input = update["inputs"][0]
                self.assertEqual(task_input["payload"]["schema_ref"], INPUT)
                self.assertNotIn("expected_output", task_input["payload"]["value"])
                self.assertNotIn("opaque-token", json.dumps(task_input["payload"]["value"]))
                raw = " \n" + json.dumps(answer) + "\t"
                output = {"payload": payload(OUTPUT, {"raw_text": raw, "evidence": {"response_id": "request"}})}
                before = copy.deepcopy(output)
                record = bound.interpret(task_input, output, "output")["results"][0]
                self.assertEqual(record["status"], "valid")
                self.assertEqual(record["payload"]["value"], {
                    "raw_text": raw, "parsed": answer, "reason": None, "parser_ref": PARSER_REF})
                self.assertEqual(output, before)
                self.assertEqual(bound.finish("done"), bound.finish("other"))
                self.assertEqual(bound.finish("done")["cases_completed"], 1)
                scored, _ = score(task_id, rows=[record])
                for metric, item in scored["metrics"].items():
                    self.assertEqual(item["value"], 0.0 if metric in ("mae", "rmse") else 1.0)
                    self.assertEqual(item["counts"], {
                        "eligible": 1, "scored": 1, "missing": 0, "invalid": 0, "excluded": 0})

    def test_strict_parser_rejects_wrappers_duplicates_nonfinite_and_wrong_types(self):
        cases = [
            ('```json\n{"trend_direction":"increasing"}\n```', "invalid_json"),
            ('Here is the answer: {"trend_direction":"increasing"}', "invalid_json"),
            ('{"trend_direction":"increasing"} {}', "invalid_json"),
            ('{"trend_direction":"increasing","trend_direction":"decreasing"}', "duplicate_key"),
            ('{"trend_direction":NaN}', "non_finite_number"),
            ('[]', "root_type_mismatch"), ('', "empty_output"),
            ('{"trend_direction":true}', "schema_violation"),
            ('{"trend_direction":"up"}', "schema_violation"),
            ('{"trend_direction":"increasing","rationale":"x"}', "schema_violation"),
        ]
        task_id = "pattern.trend_direction"
        for raw, expected_reason in cases:
            with self.subTest(raw=raw):
                parsed, reason = parse_answer(raw, TASK_OUTPUT_SCHEMAS[task_id], task_id, model_input(task_id))
                self.assertIsNone(parsed)
                self.assertEqual(reason, expected_reason)

    def test_semantic_constraints_are_not_repaired(self):
        cases = [
            ("anomaly.point_indices", {"indices": [6, 2]}, "indices_not_strictly_increasing"),
            ("anomaly.point_indices", {"indices": [2, 2]}, "schema_violation"),
            ("anomaly.point_indices", {"indices": [-1]}, "schema_violation"),
            ("anomaly.point_indices", {"indices": [True]}, "schema_violation"),
            ("anomaly.point_indices", {"indices": [8]}, "index_out_of_bounds"),
            ("forecast.numeric", {"forecast": [1, 2]}, "forecast_horizon_mismatch"),
            ("forecast.numeric", {"forecast": [True, 2, 3]}, "schema_violation"),
            ("relation.lagged_dependence", {"direction": "neither", "lag": 1}, "direction_lag_inconsistent"),
            ("relation.lagged_dependence", {"direction": "x_to_y", "lag": 0}, "direction_lag_inconsistent"),
        ]
        for task_id, answer, expected_reason in cases:
            with self.subTest(task_id=task_id, answer=answer):
                record = result_record(task_id, answer)
                self.assertEqual(record["status"], "invalid")
                self.assertEqual(record["payload"]["value"]["reason"], expected_reason)
                self.assertIsNone(record["payload"]["value"]["parsed"])

    def test_duplicate_snapshot_does_not_create_second_case_and_changed_content_conflicts(self):
        bound, _ = session("pattern.trend_direction")
        item = batch("pattern.trend_direction", terminal=False)
        self.assertEqual(len(bound.consume(item)["inputs"]), 1)
        self.assertEqual(bound.consume(item)["inputs"], [])
        item["data"]["native"]["value"]["model_input"]["timeseries"][0][0] = 10
        with self.assertRaises(GymTSError) as caught:
            bound.consume(item)
        self.assertEqual(caught.exception.code, "conflict")

    def test_scope_filter_and_task_identity(self):
        bound, _ = session("pattern.trend_direction")
        item = batch("pattern.trend_direction")
        item["snapshot_time"] = 1
        self.assertEqual(bound.consume(item)["inputs"], [])
        bound, _ = session("pattern.trend_direction")
        with self.assertRaises(GymTSError):
            bound.consume(batch("anomaly.point_indices"))

    def test_missing_forecast_public_horizon_is_configuration_error(self):
        value = model_input("forecast.numeric")
        value["context"] = {}
        with self.assertRaises(GymTSError) as caught:
            parse_answer('{"forecast":[1,2,3]}', value["output_schema"], "forecast.numeric", value)
        self.assertEqual(caught.exception.code, "invalid_config")


class ChatTSScorerContractsTest(unittest.TestCase):
    def test_missing_outcome_and_missing_result_keep_one_planned_sample(self):
        for kwargs, reason in (({"outcomes": []}, "missing_outcome"), ({"rows": []}, "missing_result")):
            with self.subTest(reason=reason):
                scored, _ = score("pattern.trend_direction", **kwargs)
                metric = scored["metrics"]["accuracy"]
                self.assertIsNone(metric["value"])
                self.assertEqual(metric["counts"], {
                    "eligible": 1, "scored": 0, "missing": 1, "invalid": 0, "excluded": 0})
                self.assertEqual(metric["reason"], reason)

    def test_invalid_prediction_is_not_silently_zero_or_missing(self):
        task_id = "pattern.trend_direction"
        scored, _ = score(task_id, rows=[result_record(task_id, {"trend_direction": "up"})], outcomes=[])
        metric = scored["metrics"]["accuracy"]
        self.assertEqual(metric["counts"]["invalid"], 1)
        self.assertEqual(metric["counts"]["missing"], 0)
        self.assertIsNone(metric["value"])

    def test_type_sensitive_accuracy_and_exact_match(self):
        scored, _ = score("pattern.trend_direction", outcomes=[outcome_record(
            "pattern.trend_direction", {"trend_direction": "decreasing"})])
        self.assertEqual(scored["metrics"]["accuracy"]["value"], 0)
        value, reason = point_metric("relation.lagged_dependence", "exact_match",
            {"direction": "x_to_y", "lag": 4}, {"direction": "x_to_y", "lag": 3})
        self.assertEqual((value, reason), (0, None))
        value, reason = point_metric("relation.lagged_dependence", "exact_match",
            {"direction": "x_to_y", "lag": True}, {"direction": "x_to_y", "lag": 3})
        self.assertIsNone(value)
        self.assertEqual(reason, "schema_violation")

    def test_event_f1_one_to_one_and_clean_control(self):
        value, _ = point_metric("anomaly.point_indices", "event_f1", {"indices": [2]}, {"indices": [2, 6]})
        self.assertAlmostEqual(value, 2 / 3)
        value, _ = point_metric("anomaly.point_indices", "event_f1", {"indices": []}, {"indices": []})
        self.assertEqual(value, 1)
        value, _ = point_metric("anomaly.point_indices", "event_f1", {"indices": [1]}, {"indices": []})
        self.assertEqual(value, 0)

    def test_numeric_metrics_are_shape_strict_and_known_values(self):
        prediction, expected = {"forecast": [2, 4, 6]}, {"forecast": [1, 2, 3]}
        value, _ = point_metric("forecast.numeric", "mae", prediction, expected)
        self.assertEqual(value, 2)
        value, _ = point_metric("forecast.numeric", "rmse", prediction, expected)
        self.assertAlmostEqual(value, (14 / 3) ** .5)
        value, reason = point_metric("forecast.numeric", "mae", {"forecast": [1, 2]}, expected)
        self.assertIsNone(value)
        self.assertEqual(reason, "forecast_horizon_mismatch")
        value, reason = point_metric("forecast.numeric", "rmse", {"forecast": [1e308]}, {"forecast": [-1e308]})
        self.assertIsNone(value)
        self.assertEqual(reason, "non_finite_result")

    def test_outcome_permission_and_task_identity_are_enforced(self):
        task_id = "pattern.trend_direction"
        for change, code in (("permission", "permission_denied"), ("task", "schema_mismatch")):
            with self.subTest(change=change):
                outcome = outcome_record(task_id)
                if change == "permission":
                    outcome["allowed_uses"] = ["dataset_build"]
                else:
                    outcome["payload"]["value"]["task_id"] = "process.stationarity_type"
                with self.assertRaises(GymTSError) as caught:
                    score(task_id, outcomes=[outcome])
                self.assertEqual(caught.exception.code, code)

    def test_duplicate_outcome_policy_latest_and_ambiguity(self):
        task_id = "pattern.trend_direction"
        old = outcome_record(task_id, {"trend_direction": "decreasing"})
        newer = outcome_record(task_id)
        newer.update(revision="2", available_at="2026-01-02T00:00:00Z", recorded_at="2026-01-02T00:00:00Z")
        with self.assertRaises(GymTSError):
            score(task_id, outcomes=[old, newer])
        scored, services = score(task_id, outcomes=[newer, old], duplicate_policy="latest_available")
        self.assertEqual(scored["metrics"]["accuracy"]["value"], 1)
        item = services.read_json(scored["item_scores_ref"])["records"][0]
        self.assertEqual(item["outcome_revision"], "2")
        newer["available_at"], newer["recorded_at"] = old["available_at"], old["recorded_at"]
        with self.assertRaises(GymTSError) as caught:
            score(task_id, outcomes=[old, newer], duplicate_policy="latest_available")
        self.assertEqual(caught.exception.code, "conflict")

    def test_wrong_metric_alignment_and_multiple_results_rejected(self):
        with self.assertRaises(GymTSError):
            score("pattern.trend_direction", metrics=["mae"])
        record = result_record("pattern.trend_direction")
        with self.assertRaises(GymTSError):
            score("pattern.trend_direction", rows=[record, copy.deepcopy(record)])

    def test_rescoring_does_not_mutate_results_or_outcomes(self):
        task_id = "pattern.trend_direction"
        rows, outcomes = [result_record(task_id)], [outcome_record(task_id)]
        before = copy.deepcopy((rows, outcomes))
        score(task_id, rows=rows, outcomes=outcomes)
        self.assertEqual((rows, outcomes), before)
        outcomes[0]["payload"]["value"]["expected_output"] = {"trend_direction": "decreasing"}
        scored, _ = score(task_id, rows=rows, outcomes=outcomes)
        self.assertEqual(scored["metrics"]["accuracy"]["value"], 0)
        self.assertEqual(rows, before[0])


if __name__ == "__main__":
    unittest.main()
