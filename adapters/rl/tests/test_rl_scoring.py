"""Sealed RL runs support independent AutoBenchTS scoring without new inference."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import GymTSError
from gymts.environment_ts.capture import NATIVE_INPUTS
from gymts_rl.candidate import LocalHFCandidate
from gymts_rl.evaluation import score_rollout_runs
from gymts_rl.pipeline import experiment_spec, rollouts
from gymts_rl.policy import configure_active_policy
from test_rl_pipeline import FixturePolicy, fixture_sources


class IndependentRLScoringTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.gym = GymTS(Path(self.directory.name), integrations=("rl",))
        self.prepared = fixture_sources(self.gym)
        self.capture = patch.object(LocalHFCandidate, "_native_inputs", lambda candidate, generated, sample:
            candidate._save({"format": "unit-test-no-tensors"}, NATIVE_INPUTS))
        self.capture.start()

    def tearDown(self):
        self.capture.stop()
        self.gym.close()
        self.directory.cleanup()

    def metric(self, report, name):
        return [item["result"] for item in report["metrics"] if item["metric_id"] == name and item["level"] == "aggregate"]

    def test_autobench_scores_and_rescores_old_runs_without_calling_policy(self):
        policy = FixturePolicy()
        batch = rollouts(self.gym, self.prepared, ["eval-0"], policy, split="eval")
        sealed = {run: copy.deepcopy(self.gym.records.get_run(run)["result"]) for run in batch["run_ids"]}
        with patch.object(LocalHFCandidate, "infer", side_effect=AssertionError("Scoring must not infer")):
            report = score_rollout_runs(self.gym, batch["run_ids"], gates=[{
                "metric": "accuracy", "target": "absolute", "candidate_ids": None, "for_metric": None,
                "operator": "ge", "threshold": 1.0, "scope": "aggregate"}])
            rescored = score_rollout_runs(self.gym, batch["run_ids"], previous_evaluation_id=report["evaluation_id"])
        self.assertEqual(len(policy.samples), 1)
        self.assertEqual(report["verdict"], "pass")
        self.assertTrue(all(item["value"] == 1 for item in self.metric(report, "accuracy")))
        self.assertEqual(report["coverage"]["expected_units"], 1)
        self.assertNotEqual(report["evaluation_id"], rescored["evaluation_id"])
        for run in batch["run_ids"]:
            self.assertEqual(sealed[run], self.gym.records.get_run(run)["result"])

    def test_execution_seeds_keep_one_recorded_candidate(self):
        batch = rollouts(self.gym, self.prepared, ["eval-0", "eval-1"], FixturePolicy(), split="eval")
        report = score_rollout_runs(self.gym, batch["run_ids"])
        plan = self.gym.artifacts.read_json(report["plan_ref"])
        self.assertEqual(len({unit["candidate_id"] for unit in plan["expected_units"]}), 1)
        self.assertEqual(report["verdict"], "insufficient_evidence")
        self.assertIn("no_acceptance_gate", report["reasons"])

    def test_historical_explicit_seed_candidates_keep_their_recorded_identities(self):
        from gymts_rl import pipeline
        original = pipeline.experiment_spec
        with patch.object(pipeline, "experiment_spec", side_effect=lambda *args, **kwargs:
                original(*args, **kwargs, legacy_candidate_seed=True)):
            batch = rollouts(self.gym, self.prepared, ["eval-0", "eval-1"], FixturePolicy(), split="eval")
        report = score_rollout_runs(self.gym, batch["run_ids"])
        plan = self.gym.artifacts.read_json(report["plan_ref"])
        self.assertEqual(len({unit["candidate_id"] for unit in plan["expected_units"]}), 2)

    def test_format_failure_is_measured_as_wrong_with_valid_reference(self):
        class Malformed(FixturePolicy):
            def generate(self, *args, **kwargs):
                result = super().generate(*args, **kwargs)
                result["response"] = "I do not know"
                return result
        batch = rollouts(self.gym, self.prepared, ["eval-0"], Malformed(), split="eval")
        report = score_rollout_runs(self.gym, batch["run_ids"])
        for name in ("accuracy", "format_valid"):
            self.assertEqual(self.metric(report, name)[0]["value"], 0)
            self.assertEqual(self.metric(report, name)[0]["counts"]["scored"], 1)

    def test_missing_reference_preserves_denominator_and_does_not_become_zero(self):
        sample = next(row for row in self.gym.artifacts.read_json(self.prepared["snapshot_ref"])["samples"] if row["sample_id"] == "eval-0")
        previous = configure_active_policy(FixturePolicy())
        try:
            result = self.gym.run(experiment_spec(self.prepared["snapshot_ref"], self.prepared["dataset_revision"], sample, {}, 7))
        finally:
            configure_active_policy(previous)
        report = score_rollout_runs(self.gym, [result["run_id"]])
        metric = self.metric(report, "accuracy")[0]
        self.assertIsNone(metric["value"])
        self.assertEqual(metric["counts"], {"eligible": 1, "scored": 0, "missing": 1, "invalid": 0, "excluded": 0})
        self.assertEqual(report["verdict"], "insufficient_evidence")
        self.assertEqual(self.metric(report, "format_valid")[0]["value"], 1)

    def test_explicit_new_reference_revision_rescores_same_output(self):
        batch = rollouts(self.gym, self.prepared, ["eval-0"], FixturePolicy(), split="eval")
        first = score_rollout_runs(self.gym, batch["run_ids"])
        old = self.gym.records.read_outcomes({"run_ids": batch["run_ids"], "purpose": "evaluation"})[0]
        changed = copy.deepcopy(old)
        changed.update(revision="2", recorded_at=None)
        changed["payload"]["value"]["reward_spec"]["ground_truth"] = "43"
        self.gym.records.attach_outcomes(batch["run_ids"][0], [changed])
        with patch.object(LocalHFCandidate, "infer", side_effect=AssertionError("Re-scoring must not infer")):
            second = score_rollout_runs(self.gym, batch["run_ids"],
                outcome_refs=[{"outcome_id": changed["outcome_id"], "revision": "2"}],
                previous_evaluation_id=first["evaluation_id"])
        self.assertEqual(self.metric(first, "accuracy")[0]["value"], 1)
        self.assertEqual(self.metric(second, "accuracy")[0]["value"], 0)
        self.assertEqual(second["previous_evaluation_id"], first["evaluation_id"])

    def test_score_cli_writes_formal_report_without_loading_model(self):
        import contextlib
        import io
        import json
        from gymts_rl.cli import main
        batch = rollouts(self.gym, self.prepared, ["eval-0"], FixturePolicy(), split="eval")
        destination = Path(self.directory.name) / "formal-report.json"
        with patch("gymts_rl.policy.LocalPolicy.from_pretrained", side_effect=AssertionError("Scoring must not load a model")):
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(["--store", self.directory.name, "score", "--run-id", batch["run_ids"][0],
                             "--output", str(destination), "--min-accuracy", "1"])
        self.assertEqual(code, 0)
        report = json.loads(destination.read_text())
        self.assertEqual(report["report"]["protocol_version"], "gymts.evaluation-report/1")
        self.assertEqual(report["report"]["verdict"], "pass")
        self.assertEqual(report["report_ref"]["schema_ref"], "gymts.evaluation-report/1")

    def test_training_runs_cannot_be_relabelled_independent_evaluation(self):
        batch = rollouts(self.gym, self.prepared, ["train-0"], FixturePolicy())
        with self.assertRaises(GymTSError) as error:
            score_rollout_runs(self.gym, batch["run_ids"])
        self.assertEqual(error.exception.code, "permission_denied")


if __name__ == "__main__":
    unittest.main()
