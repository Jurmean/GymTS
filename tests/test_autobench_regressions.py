"""Adversarial scoring responses must not turn absent evidence into acceptance."""

import unittest
from copy import deepcopy

import test_autobench as fixtures
from gymts.contracts import GymTSError


class AutoBenchRegressionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AutoBenchTests()
        self.fixture.setUp()

    def test_ready_metric_without_any_scored_items_is_rejected(self):
        def empty_score(results, outcomes, context):
            return {"metrics": {"mae": {"value": 0, "status": "ready",
                    "counts": {"eligible": 2, "scored": 0, "missing": 2, "invalid": 0, "excluded": 0},
                    "reason": None}}, "item_scores_ref": None, "diagnostics_ref": None}
        self.fixture.scorer.score = empty_score
        spec = self.fixture.spec(targets=())
        spec["scoring"]["evidence_requirements"] = {"min_scored": 0, "min_coverage": 0}
        report = self.fixture.bench.evaluate(spec)
        self.assertEqual("failed", report["status"])
        self.assertEqual("scorer_failure", report["errors"][-1]["code"])
        self.assertNotEqual("pass", report["verdict"])

    def test_outcome_dependent_metric_cannot_claim_scores_without_outcomes(self):
        def invented_score(results, outcomes, context):
            return {"metrics": {"mae": {"value": 0, "status": "ready",
                    "counts": {"eligible": 2, "scored": 2, "missing": 0, "invalid": 0, "excluded": 0},
                    "reason": None}}, "item_scores_ref": None, "diagnostics_ref": None}
        self.fixture.scorer.score = invented_score
        report = self.fixture.bench.evaluate(self.fixture.spec(targets=()))
        self.assertEqual("failed", report["status"])
        self.assertEqual("scorer_failure", report["errors"][-1]["code"])
        self.assertNotEqual("pass", report["verdict"])

    def test_outcome_independent_metric_can_score_without_outcomes(self):
        self.fixture.bench.scorers.manifest["metrics"]["mae"]["requires_outcome"] = False
        def independent_score(results, outcomes, context):
            return {"metrics": {"mae": {"value": 0, "status": "ready",
                    "counts": {"eligible": 2, "scored": 2, "missing": 0, "invalid": 0, "excluded": 0},
                    "reason": None}}, "item_scores_ref": None, "diagnostics_ref": None}
        self.fixture.scorer.score = independent_score
        report = self.fixture.bench.evaluate(self.fixture.spec(targets=()))
        self.assertEqual("completed", report["status"])
        self.assertEqual("pass", report["verdict"])

    def test_explicit_rescore_tags_preserve_grouping_and_are_frozen(self):
        spec = self.fixture.spec()
        spec["comparison"]["group_by"].append("tags.source")
        first = self.fixture.bench.evaluate(spec)
        rescore = self.fixture.rescore_spec(first, spec)
        rescore["runs"][0]["tags"] = {"source": "test"}
        second = self.fixture.bench.score(rescore)
        self.assertEqual("pass", second["verdict"])
        groups = [entry for entry in second["metrics"] if entry["level"] == "group"]
        self.assertEqual("test", groups[0]["group_key"]["tags.source"])
        rescore["runs"][0]["tags"]["source"] = "changed-after-score"
        plan = self.fixture.artifacts.read_json(second["plan_ref"])
        self.assertEqual({"source": "test"}, plan["expected_units"][0]["tags"])
        self.assertEqual(1, self.fixture.environment.calls)

    def test_rescore_rejects_non_scalar_tags(self):
        spec = self.fixture.spec()
        first = self.fixture.bench.evaluate(spec)
        rescore = self.fixture.rescore_spec(first, spec)
        rescore["runs"][0]["tags"] = {"source": ["nested"]}
        with self.assertRaises(GymTSError) as caught:
            self.fixture.bench.score(rescore)
        self.assertEqual("invalid_config", caught.exception.code)
        self.assertEqual(1, self.fixture.environment.calls)

    def replace_outcomes(self, spec, transform):
        view = spec["scoring"]["outcomes"]["sources"][0]
        rows = self.fixture.artifacts.read_json(view["source_refs"][0])
        transform(rows)
        ref = self.fixture.artifacts.save_json(rows, "gymts.outcomes/1")
        view.update(source_refs=[ref], revision=ref["revision"])

    def test_outcome_purposes_require_unique_supported_strings(self):
        for uses in ("evaluation", ["evaluation", "evaluation"], ["evaluation", "unknown"], ["evaluation", 1]):
            with self.subTest(uses=uses):
                spec = self.fixture.spec()
                self.replace_outcomes(spec, lambda rows: rows[0].update(allowed_uses=uses))
                report = self.fixture.bench.evaluate(spec)
                self.assertEqual("failed", report["status"])
                self.assertNotEqual("pass", report["verdict"])

    def test_outcome_provenance_must_reference_committed_artifact(self):
        spec = self.fixture.spec()
        self.replace_outcomes(spec, lambda rows: rows[0]["source_ref"].update(artifact_id="not-committed"))
        report = self.fixture.bench.evaluate(spec)
        self.assertEqual("failed", report["status"])
        self.assertNotEqual("pass", report["verdict"])

    def test_identical_outcomes_in_multiple_declared_views_are_deduplicated(self):
        spec = self.fixture.spec()
        spec["scoring"]["outcomes"]["sources"] *= 2
        report = self.fixture.bench.evaluate(spec)
        self.assertEqual("pass", report["verdict"])
        view = self.fixture.artifacts.read_json(report["outcome_view_ref"])
        self.assertEqual(2, len(self.fixture.artifacts.read_json(view["records_ref"])))

    def mutate_run_results(self, transform):
        original = self.fixture.environment.run
        def run(spec):
            result = original(spec)
            rows = self.fixture.artifacts.read_json(result["result_ref"])
            transform(rows)
            result["result_ref"] = self.fixture.artifacts.save_json(rows, "gymts.results/1")
            return result
        self.fixture.environment.run = run

    def test_duplicate_result_ids_do_not_inflate_scoring_coverage(self):
        self.mutate_run_results(lambda rows: rows.append(deepcopy(rows[0])))
        report = self.fixture.bench.evaluate(self.fixture.spec())
        self.assertEqual("failed", report["status"])
        self.assertEqual("conflict", report["errors"][-1]["code"])
        self.assertNotEqual("pass", report["verdict"])

    def test_results_must_satisfy_the_declared_alignment_schema(self):
        original = self.fixture.bench.schemas.validate
        def validate(schema, value):
            original(schema, value)
            if schema == "alignment/1" and not isinstance(value.get("index"), int):
                raise GymTSError("schema_mismatch", "Expected integer index")
        self.fixture.bench.schemas.validate = validate
        self.mutate_run_results(lambda rows: rows[0].update(alignment_key={"index": "wrong-type"}))
        report = self.fixture.bench.evaluate(self.fixture.spec())
        self.assertEqual("failed", report["status"])
        self.assertEqual("schema_mismatch", report["errors"][-1]["code"])
        self.assertNotEqual("pass", report["verdict"])


if __name__ == "__main__":
    unittest.main()
