"""Core evaluation contracts: fixed denominators, identity and immutable rescoring."""
from copy import deepcopy
import unittest
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from gymts.autobench_ts import AutoBenchTS, RestrictedScoringServices
from gymts.contracts import GymTSError, digest, inline, utc_now


TASK = {"component_ref": {"name": "task", "version": "1", "origin_ref": None},
        "task_protocol_ref": "task/1", "result_schema_ref": "result/1", "outcome_schema_ref": "outcome/1"}
SCORER = {"component_ref": {"name": "mae", "version": "1", "origin_ref": None}, "params_schema_ref": "params/1",
          "supported_task_protocols": ["task/1"], "result_schema_refs": ["result/1"], "outcome_schema_refs": ["outcome/1"],
          "metrics": {"mae": {"direction": "lower_better", "unit": "value", "requires_outcome": True,
             "eligibility_ref": {"name": "per-result", "version": "1", "origin_ref": None}, "eligibility_schema_ref": "eligibility/1"}}}


class Artifacts:
    def __init__(self):
        self.values = {}
        self.saved = []

    def save_json(self, value, schema_ref):
        identity = digest({"value": value, "schema": schema_ref})
        ref = {"artifact_id": identity, "revision": identity, "uri": "test://" + identity,
               "content_hash": identity, "media_type": "application/json", "schema_ref": schema_ref, "size_bytes": 1}
        self.values[identity] = deepcopy(value)
        self.saved.append((schema_ref, deepcopy(value)))
        return ref

    def read_json(self, ref):
        return deepcopy(self.values[ref["artifact_id"]])

    def read_view(self, ref):
        return inline(self.read_json(ref["source_refs"][0]), ref["source_refs"][0]["schema_ref"])


class Registry:
    def __init__(self, manifest, component=None):
        self.manifest, self.component = manifest, component

    def resolve(self, name, version):
        return deepcopy(self.manifest)

    def create(self, spec):
        return self.component


class Schemas:
    def validate(self, schema, value):
        if not isinstance(value, dict):
            raise GymTSError("schema_mismatch", "Expected object")


class Records:
    def __init__(self, artifacts):
        self.artifacts = artifacts
        self.runs = {}

    def get_run(self, run_id):
        return deepcopy(self.runs[run_id])

    def snapshot(self, run_ids, query):
        ref = self.artifacts.save_json({"runs": run_ids, "query": query}, "gymts.snapshot/1")
        return {"snapshot_ref": ref, "captured_at": utc_now(), "runs": [], "outcome_refs": []}


class Environment:
    def __init__(self, artifacts, records):
        self.artifacts, self.records = artifacts, records
        self.tasks = Registry(TASK)
        self.candidates = Registry({"implementation_ref": {"name": "function", "version": "1", "origin_ref": None}})
        self.calls = 0
        self.fail_seeds = set()
        self.cancel_seeds = set()

    def validate(self, spec):
        return {"valid": True, "issues": [], "resolved_spec_ref": self.artifacts.save_json(spec, "gymts.experiment/1")}

    def run(self, spec):
        assert any(schema == "gymts.evaluation-plan/1" for schema, _ in self.artifacts.saved), "Run before plan commit"
        self.calls += 1
        run_id = "run-{}".format(self.calls)
        ref = self.artifacts.save_json(spec, "gymts.experiment/1")
        rows = [{"result_id": "{}-{}".format(run_id, index), "run_id": run_id, "case_id": "case-{}".format(index),
                 "turn_id": 0, "input_id": "in", "output_id": "out", "task_protocol_ref": "task/1", "decision_time": index,
                 "alignment_key": {"index": index}, "status": "valid", "payload": inline({"prediction": spec["candidate"]["params"]["prediction"]}, "result/1")}
                for index in range(2)]
        status = "cancelled" if spec["execution"].get("seed") in self.cancel_seeds else "failed" if spec["execution"].get("seed") in self.fail_seeds else "succeeded"
        result = {"run_id": run_id, "status": status,
                  "result_ref": self.artifacts.save_json(rows, "gymts.results/1"), "resolved_spec_ref": ref}
        self.records.runs[run_id] = {"run_id": run_id, "metadata": {"resolved_spec_ref": ref}, "result": result, "events": []}
        return result


class MAE:
    def __init__(self):
        self.units = []
        self.bad_counts = False

    def score(self, results, outcomes, context):
        services = context["services"]
        rows = services.read_json(results["records_ref"])
        labels = services.read_json(outcomes["records_ref"])
        self.units.append((context["unit"]["candidate_id"], [row["unit_id"] for row in rows]))
        targets = {row["alignment_key"]["index"]: row["payload"]["value"]["target"] for row in labels}
        errors = [abs(row["payload"]["value"]["prediction"] - targets[row["alignment_key"]["index"]]) for row in rows if row["alignment_key"]["index"] in targets]
        counts = {"eligible": len(rows), "scored": len(errors), "missing": len(rows) - len(errors), "invalid": 0, "excluded": 0}
        if self.bad_counts:
            counts["eligible"] += 1
        return {"metrics": {"mae": {"value": sum(errors) / len(errors) if errors else None,
                "status": "ready" if errors else "insufficient_evidence", "counts": counts, "reason": None}},
                "item_scores_ref": None, "diagnostics_ref": None}


class AutoBenchTests(unittest.TestCase):
    def setUp(self):
        self.artifacts = Artifacts()
        self.records = Records(self.artifacts)
        self.environment = Environment(self.artifacts, self.records)
        self.scorer = MAE()
        self.bench = AutoBenchTS(self.environment, Registry(SCORER, self.scorer), Schemas(), self.records, self.artifacts)

    def labels(self, targets=(0, 0), revision="1", available="2026-01-01T00:00:00Z", recorded="2026-01-01T00:00:00Z"):
        source = self.artifacts.save_json({"label-source": revision}, "source/1")
        rows = [{"outcome_id": "label-{}".format(index), "revision": revision, "alignment_key": {"index": index},
                 "payload": inline({"target": target}, "outcome/1"), "event_time": index,
                 "available_at": available, "recorded_at": recorded, "source_ref": source,
                 "supersedes_ref": None, "allowed_uses": ["evaluation"]} for index, target in enumerate(targets)]
        ref = self.artifacts.save_json(rows, "gymts.outcomes/1")
        return {"view_id": "labels", "revision": revision, "source_refs": [ref],
                "selection": inline({"kind": "all"}, "gymts.selection/1"), "as_of": None, "purpose": "evaluation"}

    def spec(self, targets=(0, 0), candidate_count=1, repetitions=1, gates=True):
        candidates = [{"candidate_id": "c{}".format(index), "spec": {"adapter": "constant", "version": "1", "artifact": None,
                      "params": {"prediction": index}, "inherited_state": []}} for index in range(candidate_count)]
        return {"protocol_version": "gymts.evaluation/1", "name": "test", "purpose": "regression",
                "cases": [{"evaluation_case_id": "condition", "scene": {"task": {"plugin": "task", "version": "1", "params": {}}},
                           "execution": {"seed": None, "learning": {"prepare": "load_only", "online": "frozen"}}, "recording": {}, "tags": {"source": "test"}}],
                "candidates": candidates, "baseline_id": None,
                "repetitions": {"count": repetitions, "seeds": list(range(repetitions))},
                "scoring": {"scorer": {"adapter": "mae", "version": "1", "params": {}},
                    "outcomes": {"sources": [self.labels(targets)], "as_of": "2026-06-01T00:00:00Z"},
                    "alignment": {"schema_ref": "alignment/1", "keys": ["index"], "matching": "exact", "params": {}, "duplicate_policy": "error"},
                    "metrics": ["mae"], "evidence_requirements": {"min_scored": 1, "min_coverage": 1.0}, "missing_outcome_policy": "report_insufficient"},
                "comparison": {"group_by": ["evaluation_case_id"], "repetition_aggregation": "mean", "aggregation": "macro_mean", "baseline_method": "difference",
                    "gates": [{"metric": "mae", "target": "absolute", "candidate_ids": None, "for_metric": None, "operator": "le", "threshold": 0.0, "scope": "aggregate"}] if gates else []},
                "failure_policy": {"partial_results": "exclude", "invalid_result_policy": "report"}}

    def rescore_spec(self, report, evaluation_spec):
        plan = self.artifacts.read_json(report["plan_ref"])
        manifest = self.artifacts.read_json(report["run_manifest_ref"])
        executions = {entry["unit_id"]: entry for entry in manifest["entries"]}
        return {"protocol_version": "gymts.score/1", "name": "rescore", "purpose": "regression", "baseline_id": evaluation_spec["baseline_id"],
                "runs": [{"unit_id": unit["unit_id"], "evaluation_case_id": unit["evaluation_case_id"], "candidate_id": unit["candidate_id"],
                          "repetition": unit["repetition"], "run_id": executions[unit["unit_id"]]["run_id"], "unavailable_reason": None} for unit in plan["expected_units"]],
                "scoring": deepcopy(evaluation_spec["scoring"]), "comparison": deepcopy(evaluation_spec["comparison"]),
                "failure_policy": deepcopy(evaluation_spec["failure_policy"]), "previous_evaluation_id": report["evaluation_id"]}

    @staticmethod
    def metric(report, candidate="c0", level="aggregate"):
        return next(entry["result"] for entry in report["metrics"] if entry["candidate_id"] == candidate and entry["level"] == level)

    def test_fixed_plan_candidate_separation_and_counts(self):
        spec = self.spec(candidate_count=2, repetitions=2)
        spec["baseline_id"] = "c1"
        report = self.bench.evaluate(spec)
        self.assertEqual(report["coverage"]["expected_units"], 4)
        self.assertEqual(self.metric(report)["value"], 0)
        self.assertEqual(self.metric(report, "c1")["value"], 1)
        self.assertEqual(self.metric(report)["counts"]["eligible"], 4)
        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(len(self.scorer.units), 4)
        self.assertTrue(all(len(set(unit_ids)) == 1 for _, unit_ids in self.scorer.units))
        self.assertTrue(any(entry["value"] == -1 for entry in report["comparisons"]))

    def test_partial_labels_do_not_shrink_eligible_denominator(self):
        report = self.bench.evaluate(self.spec(targets=(0,)))
        metric = self.metric(report)
        self.assertEqual(metric["counts"], {"eligible": 2, "scored": 1, "missing": 1, "invalid": 0, "excluded": 0})
        self.assertIsNone(metric["value"])
        self.assertEqual(report["verdict"], "insufficient_evidence")

    def test_partial_labels_can_score_at_declared_coverage(self):
        spec = self.spec(targets=(0,))
        spec["scoring"]["evidence_requirements"]["min_coverage"] = .5
        report = self.bench.evaluate(spec)
        self.assertEqual(self.metric(report)["value"], 0)
        self.assertEqual(report["verdict"], "pass")

    def test_failed_run_retained_and_partial_results_excluded(self):
        self.environment.fail_seeds.add(1)
        spec = self.spec(repetitions=2)
        spec["comparison"]["gates"] = [{"metric": "run_failure_rate", "target": "absolute", "candidate_ids": None,
                "for_metric": None, "operator": "le", "threshold": .5, "scope": "aggregate"}]
        report = self.bench.evaluate(spec)
        self.assertEqual(report["coverage"]["failed_runs"], 1)
        self.assertEqual(report["gate_results"][0]["value"], .5)
        self.assertEqual(self.metric(report)["counts"]["excluded"], 2)
        self.assertEqual(self.metric(report)["counts"]["eligible"], 4)
        self.assertEqual(report["verdict"], "insufficient_evidence")

    def test_cancelled_run_stops_starting_units_but_preserves_plan(self):
        self.environment.cancel_seeds.add(0)
        report = self.bench.evaluate(self.spec(repetitions=3))
        self.assertEqual(self.environment.calls, 1)
        self.assertEqual(report["coverage"]["expected_units"], 3)
        self.assertEqual(report["coverage"]["cancelled_runs"], 1)
        self.assertEqual(report["coverage"]["not_started_units"], 2)
        self.assertIn("evaluation_cancelled", report["reasons"])
        self.assertNotEqual(report["verdict"], "pass")

    def test_score_never_executes_candidate_and_old_reports_remain(self):
        spec = self.spec()
        first = self.bench.evaluate(spec)
        saved_first = self.artifacts.read_json(first["outcome_view_ref"])
        run_snapshot = deepcopy(self.records.runs)
        rescore = self.rescore_spec(first, spec)
        rescore["scoring"]["outcomes"]["sources"] = [self.labels((2, 2), revision="2")]
        second = self.bench.score(rescore)
        self.assertEqual(self.environment.calls, 1)
        self.assertEqual(self.metric(first)["value"], 0)
        self.assertEqual(self.metric(second)["value"], 2)
        self.assertNotEqual(first["evaluation_id"], second["evaluation_id"])
        self.assertEqual(second["previous_evaluation_id"], first["evaluation_id"])
        self.assertEqual(self.records.runs, run_snapshot)
        self.assertEqual(self.artifacts.read_json(first["outcome_view_ref"]), saved_first)

    def test_not_started_unit_kept_in_manifest(self):
        spec = self.spec()
        report = self.bench.evaluate(spec)
        rescore = self.rescore_spec(report, spec)
        unit = self.artifacts.read_json(report["plan_ref"])["expected_units"][0]
        rescore["runs"].append({"unit_id": "missing", "evaluation_case_id": "condition", "candidate_id": "c0", "repetition": 1,
                                "run_id": None, "unavailable_reason": "worker unavailable", "unit_spec_ref": unit["resolved_spec_ref"]})
        second = self.bench.score(rescore)
        self.assertEqual(second["coverage"]["not_started_units"], 1)
        self.assertEqual(second["coverage"]["expected_units"], 2)
        self.assertIsNone(self.metric(second)["value"])
        self.assertEqual(self.environment.calls, 1)

    def test_same_candidate_label_cannot_hide_different_implementations(self):
        spec = self.spec(candidate_count=2)
        report = self.bench.evaluate(spec)
        rescore = self.rescore_spec(report, spec)
        rescore["runs"][1]["candidate_id"] = "c0"
        rescore["runs"][1]["repetition"] = 1
        with self.assertRaises(GymTSError) as raised:
            self.bench.score(rescore)
        self.assertEqual(raised.exception.code, "conflict")
        self.assertEqual(self.environment.calls, 2)

    def test_malformed_scorer_counts_fails_report_not_fake_success(self):
        self.scorer.bad_counts = True
        report = self.bench.evaluate(self.spec())
        self.assertEqual(report["status"], "failed")
        self.assertNotEqual(report["verdict"], "pass")
        self.assertEqual(report["errors"][-1]["code"], "scorer_failure")
        self.assertEqual(len(report["result_view_refs"]), 1)

    def test_no_gates_reports_metrics_without_acceptance(self):
        report = self.bench.evaluate(self.spec(gates=False))
        self.assertEqual(self.metric(report)["status"], "ready")
        self.assertEqual(report["verdict"], "insufficient_evidence")
        self.assertIn("no_acceptance_gate", report["reasons"])

    def test_aggregate_gate_rejected_before_any_run(self):
        spec = self.spec()
        spec["comparison"]["aggregation"] = "none"
        with self.assertRaises(GymTSError):
            self.bench.evaluate(spec)
        self.assertEqual(self.environment.calls, 0)

    def test_unknown_configuration_fields_rejected(self):
        spec = self.spec()
        spec["comparision"] = {}
        with self.assertRaises(GymTSError):
            self.bench.evaluate(spec)
        self.assertEqual(self.environment.calls, 0)

    def test_as_of_checks_commit_time_not_only_available_time(self):
        spec = self.spec()
        spec["scoring"]["outcomes"]["sources"] = [self.labels(recorded="2026-07-01T00:00:00Z")]
        report = self.bench.evaluate(spec)
        self.assertEqual(self.metric(report)["counts"]["missing"], 2)
        self.assertEqual(report["verdict"], "insufficient_evidence")

    def test_zero_baseline_relative_change_is_insufficient(self):
        spec = self.spec(candidate_count=2)
        spec["baseline_id"] = "c0"
        spec["comparison"]["gates"][0].update(target="relative_change", candidate_ids=["c1"])
        report = self.bench.evaluate(spec)
        self.assertEqual(report["gate_results"][0]["reason"], "zero_baseline")
        self.assertEqual(report["verdict"], "insufficient_evidence")

    def test_supported_matching_checked_before_execution(self):
        self.bench.scorers.manifest["supported_matchings"] = ["exact"]
        spec = self.spec()
        spec["scoring"]["alignment"]["matching"] = "interval"
        with self.assertRaises(GymTSError) as raised:
            self.bench.evaluate(spec)
        self.assertEqual(raised.exception.code, "unsupported_capability")
        self.assertEqual(self.environment.calls, 0)

    def test_real_gymts_group_threshold_and_immutable_rescore(self):
        from gymts import GymTS
        with TemporaryDirectory(prefix="gymts-autobench-contract-") as root, GymTS(root) as gym:
            spec = json.loads((Path(__file__).resolve().parents[1] / "examples/forecast_evaluation.json").read_text())
            for case in spec["cases"]:
                case["recording"]["store_ref"] = "local"
            spec["repetitions"] = {"count": 2, "seeds": [7, 8]}
            # Each repetition has 8 valid results. Requirements belong to the
            # expected group (16), not an arbitrary individual repetition (8).
            spec["scoring"]["evidence_requirements"]["min_scored"] = 12
            start = datetime(2026, 1, 1, tzinfo=timezone.utc)
            timestamp = lambda i: (start + timedelta(minutes=i)).isoformat().replace("+00:00", "Z")
            source = gym.artifacts.save_json({"definition": "linear ramp", "delta": 1}, "gymts.json/1")
            now = utc_now()
            labels = [{"outcome_id": "ramp-{}".format(i), "revision": "1",
                       "alignment_key": {"entity": "demo", "variable": "value", "issued_at": timestamp(i), "target_time": timestamp(i + 1)},
                       "payload": inline({"value": i + 1}, "gymts.builtin/forecast-outcome/1"), "event_time": timestamp(i + 1),
                       "available_at": now, "recorded_at": now, "source_ref": source,
                       "supersedes_ref": None, "allowed_uses": ["evaluation"]} for i in range(11)]
            label_ref = gym.artifacts.save_json(labels, "gymts.outcome-records/1")
            spec["scoring"]["outcomes"] = {"sources": [{"view_id": "ramp-labels", "revision": label_ref["revision"],
                "source_refs": [label_ref], "selection": inline({"kind": "all"}, "gymts.selection/1"),
                "as_of": None, "purpose": "evaluation"}], "as_of": utc_now()}
            report = gym.autobench.evaluate(spec)
            self.assertEqual(report["status"], "completed", report["errors"])
            self.assertEqual(report["verdict"], "pass", report["errors"])
            values = {entry["candidate_id"]: entry["result"] for entry in report["metrics"] if entry["level"] == "aggregate"}
            self.assertEqual(values["last-value"]["value"], 1)
            self.assertEqual(values["window-mean"]["value"], 2)
            self.assertEqual(values["last-value"]["counts"]["scored"], 16)
            plan = gym.artifacts.read_json(report["plan_ref"])
            manifest = gym.artifacts.read_json(report["run_manifest_ref"])
            by_unit = {entry["unit_id"]: entry for entry in manifest["entries"]}
            selected = [{"unit_id": unit["unit_id"], "evaluation_case_id": unit["evaluation_case_id"], "candidate_id": unit["candidate_id"],
                         "repetition": unit["repetition"], "run_id": by_unit[unit["unit_id"]]["run_id"], "unavailable_reason": None}
                        for unit in plan["expected_units"]]
            before = {item["run_id"]: digest(gym.records.get_run(item["run_id"])["result"]) for item in selected}
            def forbidden_run(spec):
                raise AssertionError("Rescoring must not execute a Candidate")
            gym.environment_ts.run = forbidden_run
            rescored = gym.autobench.score({"protocol_version": "gymts.score/1", "name": "fixed-output-rescore", "purpose": "regression",
                "runs": selected, "baseline_id": spec["baseline_id"], "scoring": spec["scoring"], "comparison": spec["comparison"],
                "failure_policy": spec["failure_policy"], "previous_evaluation_id": report["evaluation_id"]})
            self.assertEqual(rescored["verdict"], "pass", rescored["errors"])
            self.assertEqual({item["run_id"]: digest(gym.records.get_run(item["run_id"])["result"]) for item in selected}, before)
            self.assertEqual(gym.artifacts.read_json(gym.autobench.last_report_ref), rescored)

    def test_real_task_alignment_omission_rejected_before_run(self):
        from gymts import GymTS
        with TemporaryDirectory(prefix="gymts-alignment-contract-") as root, GymTS(root) as gym:
            spec = json.loads((Path(__file__).resolve().parents[1] / "examples/forecast_evaluation.json").read_text())
            for case in spec["cases"]:
                case["recording"]["store_ref"] = "local"
            spec["scoring"]["alignment"]["keys"].remove("target_time")
            calls = []
            gym.environment_ts.run = lambda value: calls.append(value)
            with self.assertRaises(GymTSError) as raised:
                gym.autobench.evaluate(spec)
            self.assertEqual(raised.exception.code, "schema_mismatch")
            self.assertEqual(calls, [])

    def test_restricted_services_reject_undeclared_artifact(self):
        ref = self.artifacts.save_json({"private": True}, "private/1")
        with self.assertRaises(GymTSError) as raised:
            RestrictedScoringServices(self.artifacts, []).read_json(ref)
        self.assertEqual(raised.exception.code, "permission_denied")


if __name__ == "__main__":
    unittest.main()
