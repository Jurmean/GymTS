"""Real GymTS execution/storage boundaries with an explicitly fake test policy."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import GymTSError
from gymts.environment_ts.capture import NATIVE_INPUTS
from gymts_rl.candidate import LocalHFCandidate
from gymts_rl.contracts import MANIFEST, PRIVATE, SNAPSHOT
from gymts_rl.pipeline import _metrics, rollouts
from gymts.plugin_support import component


class FixtureTokenizer:
    chat_template = "fixed-unit-test-template"


class FixturePolicy:
    """Deterministic contract fixture; no learned model or training is claimed."""
    family = "text"
    model_path = None
    identity = {"revision": "fixture-policy-r1"}
    revision = "fixture-policy-r1"
    tokenizer = FixtureTokenizer()
    processor = None
    model_ref = component("fixture-policy")
    adapter_ref = component("fixture-policy-adapter")

    def __init__(self, fail=False, truncated=False):
        self.samples, self.fail, self.truncated = [], fail, truncated

    def tokenizer_manifest(self):
        return {"class": "FixtureTokenizer", "checkpoint_identity": self.identity}

    def generate(self, sample, seed, params):
        self.samples.append(copy.deepcopy(sample))
        if self.fail:
            raise RuntimeError("intentional fixture generation failure")
        return {"prompt_ids": [2, 3], "completion_ids": [4, 1], "raw_model_logprobs": [-.3, -.2],
            "sampling_logprobs": [-.3, -.2], "tensor_bundle": {}, "response": "#### 42", "rendered_prompt": "A public question",
            "effective_params": {"temperature": 1., "top_k": 0, "top_p": 1., "seed": seed}, "policy_revision": self.revision,
            "finish_reason": "length" if self.truncated else "eos"}


def fixture_sources(gym):
    public, private = [], []
    for split in ("train", "eval"):
        for index in range(2):
            token = split + "-" + str(index)
            public.append({"sample_id": token, "group_id": token, "dataset_id": "explicit-unit-test-fixture", "split": split,
                "task_id": "gsm8k.numeric", "messages": [{"role": "user", "content": "What is 21 + 21?"}],
                "timeseries": [], "series_names": [], "output_schema": {}, "context": {}})
            private.append({"sample_id": token, "group_id": token, "dataset_id": "explicit-unit-test-fixture", "split": split,
                "task_id": "gsm8k.numeric", "reward_spec": {"kind": "gsm8k_numeric", "ground_truth": "42"}, "provenance": {"fixture": True}})
    revision = "fixture-dataset-r1"
    snapshot_ref = gym.artifacts.save_json({"schema_version": SNAPSHOT, "dataset_revision": revision, "samples": public}, SNAPSHOT)
    private_ref = gym.artifacts.save_json({"schema_version": PRIVATE, "dataset_revision": revision, "samples": private}, PRIVATE)
    manifest = {"schema_version": MANIFEST, "dataset_revision": revision, "snapshot_ref": snapshot_ref, "private_ref": private_ref}
    return dict(manifest, manifest_ref=gym.artifacts.save_json(manifest, MANIFEST))


class RLPipelineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.gym = GymTS(Path(self.temp.name), integrations=("rl",))
        self.prepared = fixture_sources(self.gym)
        # Keep base contract tests scientific-dependency-free. This fixture
        # manifest is explicit; native HF tests separately capture true tensors.
        self.inputs = patch.object(LocalHFCandidate, "_native_inputs", lambda self, generated, sample:
            self._save({"format": "unit-test-no-tensors", "sample_id": sample["sample_id"]}, NATIVE_INPUTS))
        self.inputs.start()

    def tearDown(self):
        self.inputs.stop()
        self.gym.close()
        self.temp.cleanup()

    def test_eval_runs_capture_first_attach_gold_afterwards_and_never_export_training_rows(self):
        policy = FixturePolicy()
        batch = rollouts(self.gym, self.prepared, ["eval-1", "eval-0"], policy, seed_start=20, split="eval")
        self.assertEqual([row["sample_id"] for row in batch["entries"]], ["eval-1", "eval-0"])
        self.assertEqual([row["seed"] for row in batch["entries"]], [20, 21])
        self.assertEqual(batch["metrics"]["accuracy"], 1)
        self.assertEqual(batch["rows"], [])
        self.assertIsNone(batch["manifest_ref"])
        self.assertNotIn("ground_truth", json.dumps(policy.samples))
        frozen = self.gym.artifacts.read_json(batch["record_snapshot_ref"])
        self.assertEqual(len(frozen["runs"]), 2)
        for entry in batch["entries"]:
            stored = self.gym.records.get_run(entry["run_id"])
            self.assertEqual(stored["result"]["status"], "succeeded")
            gold = self.gym.artifacts.read_json(entry["outcome_ref"])
            self.assertEqual(gold["allowed_uses"], ["evaluation"])
            self.assertGreaterEqual(gold["recorded_at"], stored["result"]["ended_at"])
            reward = self.gym.artifacts.read_json(entry["reward_ref"])
            self.assertEqual(reward["source_refs"], [entry["outcome_ref"]])
            self.assertEqual(reward["target_refs"], [entry["model_call_ref"]])
        with self.assertRaises(GymTSError) as error:
            self.gym.records.read_outcomes({"run_ids": batch["run_ids"], "purpose": "training_export"})
        self.assertEqual(error.exception.code, "purpose_denied")

    def test_split_violation_fails_before_the_policy_is_called(self):
        policy = FixturePolicy()
        with self.assertRaises(GymTSError) as error:
            rollouts(self.gym, self.prepared, ["eval-0"], policy, split="train")
        self.assertEqual(error.exception.code, "permission_denied")
        self.assertEqual(policy.samples, [])

    def test_candidate_resources_never_grant_the_private_reward_artifact(self):
        original = LocalHFCandidate.prepare
        checks = []

        def inspect_prepare(candidate, context, training_view):
            with self.assertRaises(GymTSError) as error:
                context["resources"].read_json(self.prepared["private_ref"])
            self.assertEqual(error.exception.code, "permission_denied")
            self.assertIsNone(training_view)
            self.assertIsNone(context["training_targets"])
            checks.append(True)
            return original(candidate, context, training_view)

        with patch.object(LocalHFCandidate, "prepare", inspect_prepare):
            batch = rollouts(self.gym, self.prepared, ["eval-0"], FixturePolicy(), split="eval")
        self.assertEqual(checks, [True])
        self.assertEqual(batch["entries"][0]["run_status"], "succeeded")

    def test_modified_prepared_handle_is_rejected_against_immutable_manifest(self):
        altered = dict(self.prepared, dataset_revision="tampered")
        policy = FixturePolicy()
        with self.assertRaises(GymTSError):
            rollouts(self.gym, altered, ["train-0"], policy)
        self.assertEqual(policy.samples, [])

    def test_failed_generation_retains_failed_run_and_call_without_fabricating_reward(self):
        batch = rollouts(self.gym, self.prepared, ["eval-0"], FixturePolicy(fail=True), split="eval")
        entry = batch["entries"][0]
        self.assertEqual(entry["run_status"], "failed")
        self.assertIsNone(entry["reward_ref"])
        self.assertEqual(batch["reward_refs"], [])
        stored = self.gym.records.get_run(entry["run_id"])
        calls = [self.gym.artifacts.read_json(event["payload"]["artifact_ref"]) for event in stored["events"] if event["kind"] == "model_call"]
        self.assertEqual(calls[0]["status"], "failed")
        self.assertTrue(batch["batch_ref"])
        self.assertEqual(batch["metrics"]["accuracy"], 0)
        self.assertEqual(batch["metrics"]["coverage"], 0)
        self.assertIsNone(batch["metrics"]["scored_accuracy"])
        self.assertIsNone(batch["metrics"]["mean_reward"])

    def test_missing_reward_stays_missing_in_conditional_reward_metrics(self):
        scored = {"run_status": "succeeded", "reward": {"reward": .8, "correct": True,
            "format_valid": True, "error": None}}
        missing = {"run_status": "failed", "reward": None}
        values = _metrics([scored, missing])
        self.assertEqual(values["planned"], 2)
        self.assertEqual(values["scored"], 1)
        self.assertEqual(values["coverage"], .5)
        self.assertEqual(values["mean_reward"], .8)
        self.assertEqual(values["scored_accuracy"], 1)
        self.assertEqual(values["accuracy"], .5, "Strict overall success keeps the planned denominator")

    def test_repeated_training_prompts_are_distinct_runs_and_builder_preserves_order(self):
        ids = ["train-1", "train-0", "train-1", "train-0"]
        batch = rollouts(self.gym, self.prepared, ids, FixturePolicy(), seed_start=5)
        self.assertEqual(len(set(batch["run_ids"])), 4)
        self.assertEqual([row["source_sample_id"] for row in batch["rows"]], ids)
        self.assertEqual([row["run_id"] for row in batch["rows"]], batch["run_ids"])
        self.assertEqual(len({row["sample_id"] for row in batch["rows"]}), 4)
        self.assertTrue(batch["manifest_ref"])
        with self.assertRaises(GymTSError) as error:
            self.gym.records.read_outcomes({"run_ids": batch["run_ids"], "purpose": "evaluation"})
        self.assertEqual(error.exception.code, "purpose_denied")
        for entry in batch["entries"]:
            self.assertEqual(self.gym.artifacts.read_json(entry["outcome_ref"])["allowed_uses"], ["training_export"])

    def test_truncated_training_calls_are_preserved_and_excluded_from_optimizer_rows(self):
        batch = rollouts(self.gym, self.prepared, ["train-0"], FixturePolicy(truncated=True))
        self.assertEqual(batch["entries"][0]["finish_reason"], "length")
        self.assertTrue(batch["entries"][0]["model_call_ref"])
        self.assertEqual(batch["rows"], [])

    def test_policy_revision_change_freezes_partial_batch_before_any_new_call(self):
        from gymts_rl import pipeline
        policy = FixturePolicy()
        original = pipeline._one_run

        def change_after_sealed_run(*args, **kwargs):
            entry = original(*args, **kwargs)
            policy.revision = "changed-after-first-run"
            return entry

        with patch.object(pipeline, "_one_run", side_effect=change_after_sealed_run), self.assertRaises(GymTSError) as caught:
            rollouts(self.gym, self.prepared, ["train-0", "train-1", "train-0"], policy)
        self.assertEqual(caught.exception.code, "conflict")
        self.assertEqual(len(policy.samples), 1)
        links = caught.exception.to_dict()["links"]
        batch = self.gym.artifacts.read_json(links["rollout_batch_ref"])
        self.assertEqual(batch["status"], "failed")
        self.assertEqual(batch["policy_revision"], "fixture-policy-r1")
        self.assertEqual(batch["requested_sample_ids"], ["train-0", "train-1", "train-0"])
        self.assertEqual(len(batch["run_ids"]), 1)
        self.assertEqual(batch["run_ids"], links["run_ids"])
        frozen = self.gym.artifacts.read_json(links["record_snapshot_ref"])
        self.assertEqual(frozen["runs"][0]["status"], "succeeded")

    def test_builder_failure_links_complete_native_evidence_and_previous_batch(self):
        policy = FixturePolicy()
        with patch("gymts_rl.exporter.build_dataset", side_effect=GymTSError("invalid_dataset", "intentional builder failure")), self.assertRaises(GymTSError) as caught:
            rollouts(self.gym, self.prepared, ["train-0"], policy)
        self.assertEqual(caught.exception.code, "invalid_dataset")
        links = caught.exception.to_dict()["links"]
        batch = self.gym.artifacts.read_json(links["rollout_batch_ref"])
        self.assertEqual(batch["status"], "build_failed")
        self.assertEqual(len(batch["reward_refs"]), 1)
        original = self.gym.artifacts.read_json(batch["previous_batch_ref"])
        self.assertEqual(original["status"], "completed")
        self.assertEqual(batch["record_snapshot_ref"], original["record_snapshot_ref"])
        self.assertEqual(len(policy.samples), 1)

    def test_verifier_exception_keeps_the_current_sealed_run_in_partial_snapshot(self):
        policy = FixturePolicy()
        with patch("gymts_rl.pipeline.score_completion", side_effect=ValueError("intentional verifier failure")), self.assertRaises(GymTSError) as caught:
            rollouts(self.gym, self.prepared, ["eval-0", "eval-1"], policy, split="eval")
        self.assertEqual(caught.exception.code, "rollout_postprocessing_failure")
        links = caught.exception.to_dict()["links"]
        batch = self.gym.artifacts.read_json(links["rollout_batch_ref"])
        self.assertEqual(batch["run_ids"], [caught.exception.run_id])
        frozen = self.gym.artifacts.read_json(batch["record_snapshot_ref"])
        self.assertEqual(frozen["runs"][0]["status"], "succeeded")
        self.assertEqual(len(frozen["outcome_refs"]), 1)
        self.assertTrue(batch["entries"][0]["errors"])
        self.assertEqual(len(policy.samples), 1)


if __name__ == "__main__":
    unittest.main()
