"""A native rollout export is fixed evidence with explicit training permission."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import GymTSError, digest, inline, new_id, utc_now
from gymts.environment_ts.capture import LOGPROBS, NATIVE_INPUTS, TOKEN_IDS
from gymts_rl.contracts import INPUT, OUTCOME, OUTPUT, PROTOCOL, SNAPSHOT
from gymts_rl.registration import register_rl_plugins
from gymts_rl.exporter import (REWARD, build_dataset, native_rollout_build_spec,
                            read_dataset_rows, register_training_schemas)


def component(name):
    return {"name": name, "version": "1.0.0", "origin_ref": None}


MAPPER = component("test.fixed-verifier")


class FixturePolicy:
    """Deterministic contract fixture; real HF generation has separate tests."""
    finish_reason = "eos"
    raw_text = "#### 4"
    fail = False
    omit_logprobs = False

    def __init__(self, spec):
        self.refs = []

    def prepare(self, context, training):
        self.resources, self.traces = context["resources"], context["traces"]
        return {"model_revision": "test-weights-17", "state_refs": [], "training_provenance_ref": None}

    def save(self, value, schema="gymts.json/1"):
        ref = self.resources.save_json(value, schema)
        self.refs.append(ref)
        return ref

    def infer(self, task_input):
        if self.fail:
            raise RuntimeError("fixture inference failed")
        sample = task_input["payload"]["value"]
        prompt, response = [11, 17, 23], [29, 2]
        call_id, attempt_id, now = new_id("call"), new_id("attempt"), utc_now()
        params = {"temperature": 1, "top_k": 0, "top_p": 1, "seed": 7}
        likelihood = {"protocol_version": LOGPROBS, "source": "captured", "call_id": call_id,
            "attempt_id": attempt_id, "prompt_sequence_hash": digest(prompt), "response_sequence_hash": digest(response),
            "values": [-.4, -.2], "policy_ref": None, "policy_revision": "test-weights-17",
            "distribution": "sampling", "effective_params": params, "computation_ref": None}
        call = {"call_id": call_id, "attempt_id": attempt_id, "parent_call_id": None,
            "status": "succeeded", "started_at": now, "ended_at": now,
            "model_ref": component("test-policy"), "adapter_ref": component("test-policy-adapter"),
            "policy_revision": "test-weights-17", "request_ref": self.save({"sample": sample}),
            "response_ref": self.save({"raw_text": self.raw_text, "finish_reason": self.finish_reason}),
            "requested_params": params, "effective_params": params,
            "tokenizer_ref": self.save({"fixture": "vocabulary"}), "chat_template_ref": self.save({"fixture": "template"}),
            "native_inputs_ref": self.save({"input_ids": prompt, "attention_mask": [1, 1, 1]}, NATIVE_INPUTS),
            "prompt_token_ids_ref": self.save(prompt, TOKEN_IDS), "response_token_ids_ref": self.save(response, TOKEN_IDS),
            "logprobs_ref": self.save(likelihood, LOGPROBS), "usage": None, "error": None,
            "capture": {"requested_profile": self.traces.profile, "acquired_fields": [], "missing_fields": {},
                        "transforms": [], "completeness": "complete"}}
        if self.omit_logprobs:
            call["logprobs_ref"] = None
        self.traces.record_model_call(call)
        return {"input_id": task_input["input_id"], "task_protocol_ref": PROTOCOL, "produced_at": utc_now(),
                "model_revision": "test-weights-17", "payload": inline({"raw_text": self.raw_text, "evidence": {}}, OUTPUT)}

    def finish(self):
        return self.refs


class NativeDatasetBuilderContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.gym = GymTS(self.temporary.name)
        register_rl_plugins(self.gym.registries, self.gym.schemas)
        register_training_schemas(self.gym.schemas)
        self.policy = type("TestFixturePolicy", (FixturePolicy,), {})
        manifest = self.gym.registries.candidates.resolve("rl-local-hf", "1.0.0")
        manifest["component_ref"] = component("test-native-policy")
        self.gym.registries.candidates.register(manifest, self.policy)

    def tearDown(self):
        self.gym.close()
        self.temporary.cleanup()

    def sample(self, token="question-1", split="train", group="group-1"):
        return {"sample_id": token, "group_id": group, "dataset_id": "test-qa-v1", "split": split,
            "task_id": "gsm8k.numeric", "messages": [{"role": "user", "content": "What is 2+2?"}],
            "timeseries": [], "series_names": [], "output_schema": {}, "context": {}}

    def run_fixture(self, sample=None, extra_samples=()):
        sample = sample or self.sample()
        samples = [sample] + list(extra_samples)
        ref = self.gym.artifacts.save_json({"schema_version": SNAPSHOT, "dataset_revision": "test-dataset-1",
                                          "samples": samples}, SNAPSHOT)
        spec = json.loads((Path(__file__).resolve().parent / "fixtures/forecast_experiment.json").read_text())
        spec["scene"] = {"environment": {"protocol_version": "gymts.environment/1", "adapter": "rl-qa-snapshot", "version": "1.0.0",
            "source": {"kind": "dataset", "locator": "local://test-rl", "revision": "test-dataset-1",
                       "connection": {"artifact_refs": [ref]}, "credential_ref": None}, "mapping": {},
            "options": {"sample_ids": [sample["sample_id"] for sample in samples]}},
            "task": {"plugin": "rl-verifiable-qa", "version": "1.0.0", "params": {}},
            "binding": {"variables": {"sample": {"source": "sample", "unit": "sample", "transform": None}}, "operations": {}}}
        spec["candidate"] = {"adapter": "test-native-policy", "version": "1.0.0", "artifact": None, "params": {}, "inherited_state": []}
        spec["execution"]["mode"] = "batch"
        spec["execution"]["scope"] = {"start": 0, "end": len(samples)}
        spec["recording"]["model_calls"] = "native_rollout"
        result = self.gym.run(spec)
        return result

    def input(self, result):
        event = next(event for event in self.gym.records.get_run(result["run_id"])["events"] if event["kind"] == "input")
        return event["payload"]["value"]

    def attach(self, result, *, allowed=True, revision="1", value=1.0):
        task_input = self.input(result)
        source = self.gym.artifacts.save_json({"source": "fixed-test-gold"}, "gymts.json/1")
        self.gym.records.attach_outcomes(result["run_id"], [{"outcome_id": "gold-" + result["run_id"], "revision": revision,
            "alignment_key": task_input["alignment_key"], "payload": inline({"sample_id": task_input["alignment_key"]["sample_id"],
                "task_id": "gsm8k.numeric", "reward_spec": {"kind": "gsm8k_numeric", "ground_truth": "4"}}, OUTCOME),
            "event_time": None, "available_at": utc_now(), "source_ref": source, "supersedes_ref": None,
            "allowed_uses": ["evaluation", "training_export"] if allowed else ["evaluation"]}])
        outcome = self.gym.records.read_outcomes({"run_ids": [result["run_id"]],
            "outcome_refs": [{"outcome_id": "gold-" + result["run_id"], "revision": revision}]})[0]
        outcome_ref = self.gym.artifacts.save_json(outcome, "gymts.outcome/1")
        call = next(event for event in self.gym.records.get_run(result["run_id"])["events"] if event["kind"] == "model_call")
        return self.gym.artifacts.save_json({"protocol_version": REWARD, "reward_id": new_id("reward"),
            "target_refs": [call["payload"]["artifact_ref"]], "granularity": "call", "value": value,
            "source_refs": [outcome_ref], "mapper_ref": MAPPER, "created_at": utc_now()}, REWARD)

    def specification(self, results, rewards, **kwargs):
        snapshot = self.gym.records.snapshot([result["run_id"] for result in results])
        return native_rollout_build_spec([snapshot["snapshot_ref"]], rewards, MAPPER, **kwargs)

    def test_export_uses_frozen_native_actions_masks_rewards_and_lineage(self):
        result = self.run_fixture()
        reward = self.attach(result)
        spec = self.specification([result], [reward])
        with patch.object(self.policy, "infer", side_effect=AssertionError("Export must never call a model")):
            manifest = build_dataset(self.gym, spec)
        rows = read_dataset_rows(self.gym, manifest)
        self.assertEqual({"input_units": 1, "accepted_samples": 1, "excluded_units": 0}, manifest["counts"])
        self.assertEqual([11, 17, 23], rows[0]["prompt_ids"])
        self.assertEqual([29, 2], rows[0]["completion_ids"])
        self.assertEqual([0, 0, 0, 1, 1], rows[0]["loss_mask"])
        self.assertEqual([1, 1], rows[0]["completion_mask"])
        self.assertEqual([-.4, -.2], rows[0]["old_per_token_logps"])
        self.assertEqual(1.0, rows[0]["reward"])
        lineage = self.gym.artifacts.read_json(manifest["lineage_ref"])["records"][0]
        self.assertEqual(rows[0]["episode_id"], lineage["episode_id"])
        self.assertEqual(rows[0]["call_id"], lineage["call_id"])
        self.assertEqual([reward], lineage["reward_refs"])
        self.assertEqual("1", lineage["reward_sources"][0]["outcome_ref"]["revision"])

    def test_public_three_service_builder_preserves_legacy_ids_and_rows(self):
        from gymts.training import DatasetBuilderRegistry, build_dataset as public_build
        from gymts_rl.exporter import BUILDER_REF, NativeRolloutBuilder
        result = self.run_fixture()
        specification = self.specification([result], [self.attach(result)])
        legacy = build_dataset(self.gym, specification)
        registry = DatasetBuilderRegistry(discover=False)
        registry.register(BUILDER_REF, NativeRolloutBuilder())
        modern = public_build(specification, self.gym.records, self.gym.artifacts, builders=registry)
        self.assertEqual(legacy["dataset_id"], modern["dataset_id"])
        self.assertEqual(read_dataset_rows(self.gym, legacy), read_dataset_rows(self.gym, modern))
        self.assertEqual(legacy["builder_ref"], modern["builder_ref"])

    def test_repeat_rollouts_of_same_question_remain_distinct_in_one_partition(self):
        results = [self.run_fixture(), self.run_fixture()]
        manifest = build_dataset(self.gym, self.specification(results, [self.attach(result) for result in results]))
        rows = read_dataset_rows(self.gym, manifest["manifest_ref"])
        self.assertEqual(2, len({row["sample_id"] for row in rows}))
        self.assertEqual(["question-1", "question-1"], [row["source_sample_id"] for row in rows])
        self.assertEqual(["group-1", "group-1"], [row["group_id"] for row in rows])

    def test_evaluation_partition_is_excluded_before_training_reward_access(self):
        train, evaluate = self.run_fixture(), self.run_fixture(self.sample("eval-question", "eval", "eval-group"))
        reward = self.attach(train)
        self.attach(evaluate, allowed=False)
        manifest = build_dataset(self.gym, self.specification([train, evaluate], [reward]))
        self.assertEqual({"input_units": 2, "accepted_samples": 1, "excluded_units": 1}, manifest["counts"])
        self.assertEqual(["train"], [row["split"] for row in read_dataset_rows(self.gym, manifest)])
        self.assertEqual([], read_dataset_rows(self.gym, manifest, split="eval"))

    def test_related_group_cannot_cross_partitions_even_with_exclusion_policy(self):
        train, evaluate = self.run_fixture(), self.run_fixture(self.sample("eval-question", "eval", "group-1"))
        spec = self.specification([train, evaluate], [self.attach(train)], missing_data_policy="exclude_samples")
        with self.assertRaisesRegex(GymTSError, "group_crosses_source_partitions"):
            build_dataset(self.gym, spec)

    def test_evaluation_only_outcome_is_never_used_for_training_reward(self):
        result = self.run_fixture()
        spec = self.specification([result], [self.attach(result, allowed=False)])
        with self.assertRaises(GymTSError) as caught:
            build_dataset(self.gym, spec)
        self.assertEqual("permission_denied", caught.exception.code)

    def test_outcome_added_after_snapshot_cannot_enter_earlier_export(self):
        result = self.run_fixture()
        spec = self.specification([result], [])
        spec["reward_mapping"]["source_refs"] = [self.attach(result)]
        with self.assertRaisesRegex(GymTSError, "reward_outcome_outside_snapshot"):
            build_dataset(self.gym, spec)

    def test_later_outcome_revision_does_not_change_existing_manifest(self):
        result = self.run_fixture()
        manifest = build_dataset(self.gym, self.specification([result], [self.attach(result)]))
        before = read_dataset_rows(self.gym, manifest)
        self.attach(result, revision="2", value=0.0)
        self.assertEqual(before, read_dataset_rows(self.gym, manifest))

    def test_truncation_rejects_or_produces_explicit_empty_export(self):
        self.policy.finish_reason = "length"
        result = self.run_fixture()
        spec = self.specification([result], [self.attach(result)])
        with self.assertRaisesRegex(GymTSError, "truncated_or_unknown_completion"):
            build_dataset(self.gym, spec)
        spec["missing_data_policy"] = "exclude_samples"
        manifest = build_dataset(self.gym, spec)
        self.assertEqual([], read_dataset_rows(self.gym, manifest))
        self.assertEqual(1, manifest["counts"]["excluded_units"])
        excluded = self.gym.artifacts.read_json(manifest["exclusion_summary_ref"])
        self.assertEqual({"truncated_or_unknown_completion": 1}, excluded["counts"])

    def test_missing_reward_is_never_replaced_by_zero(self):
        result = self.run_fixture()
        spec = self.specification([result], [])
        with self.assertRaisesRegex(GymTSError, "missing_reward"):
            build_dataset(self.gym, spec)
        spec["missing_data_policy"] = "exclude_samples"
        manifest = build_dataset(self.gym, spec)
        self.assertEqual(0, manifest["counts"]["accepted_samples"])

    def test_target_requires_captured_probabilities_even_if_native_tokens_exist(self):
        self.policy.omit_logprobs = True
        result = self.run_fixture()
        self.assertEqual("succeeded", result["status"])
        spec = self.specification([result], [self.attach(result)])
        with self.assertRaisesRegex(GymTSError, "captured_logprobs_required"):
            build_dataset(self.gym, spec)

    def test_verified_shard_bytes_still_require_correct_native_masks(self):
        result = self.run_fixture()
        manifest = build_dataset(self.gym, self.specification([result], [self.attach(result)]))
        row = read_dataset_rows(self.gym, manifest)[0]
        row["loss_mask"][0] = 1
        altered = self.gym.artifacts.read_json(manifest["manifest_ref"])
        altered["shards"][0]["artifact_ref"] = self.gym.artifacts.save_artifact(
            (json.dumps(row) + "\n").encode(), {"media_type": "application/x-ndjson", "schema_ref": altered["output_schema_ref"]})
        altered["revision"] = digest({key: value for key, value in altered.items() if key != "revision"})
        reference = self.gym.artifacts.save_json(altered, "gymts.dataset/1")
        with self.assertRaisesRegex(GymTSError, "dataset_native_sequence_alignment_mismatch"):
            read_dataset_rows(self.gym, reference)

    def test_snapshot_cannot_substitute_a_shadow_run_result(self):
        result = self.run_fixture()
        spec = self.specification([result], [self.attach(result)])
        snapshot = self.gym.artifacts.read_json(spec["input_snapshots"][0])
        altered = copy.deepcopy(result)
        altered["summary"]["unexecuted_change"] = True
        snapshot["runs"][0]["result_ref"] = self.gym.artifacts.save_json(altered, "gymts.run-result/1")
        spec["input_snapshots"] = [self.gym.artifacts.save_json(snapshot, "gymts.record-snapshot/1")]
        with self.assertRaisesRegex(GymTSError, "snapshot_differs_from_committed_run"):
            build_dataset(self.gym, spec)

    def test_legitimate_invalid_answer_can_have_explicit_zero_reward(self):
        self.policy.raw_text = "I do not know"
        result = self.run_fixture()
        manifest = build_dataset(self.gym, self.specification([result], [self.attach(result, value=0.0)]))
        rows = read_dataset_rows(self.gym, manifest)
        self.assertEqual(1, len(rows))
        self.assertEqual(0.0, rows[0]["reward"])
        self.assertEqual([1, 1], rows[0]["completion_mask"])

    def test_failed_run_is_retained_as_an_exclusion(self):
        self.policy.fail = True
        result = self.run_fixture()
        manifest = build_dataset(self.gym, self.specification([result], [], missing_data_policy="exclude_samples"))
        self.assertEqual(1, manifest["counts"]["excluded_units"])
        self.assertEqual([], read_dataset_rows(self.gym, manifest))

    def test_multiple_cases_in_one_run_are_explicitly_unsupported(self):
        result = self.run_fixture(extra_samples=[self.sample("question-2", group="group-2")])
        spec = self.specification([result], [])
        with self.assertRaises(GymTSError) as caught:
            build_dataset(self.gym, spec)
        self.assertEqual("unsupported_capability", caught.exception.code)

    def test_unsealed_prefix_is_not_silently_promoted_to_final_run(self):
        result = self.run_fixture()
        run = self.gym.records.get_run(result["run_id"])
        snapshot = self.gym.records.snapshot([result["run_id"]], {"through_seq": {result["run_id"]: len(run["events"]) - 1}})
        spec = native_rollout_build_spec([snapshot["snapshot_ref"]], [self.attach(result)], MAPPER)
        with self.assertRaisesRegex(GymTSError, "run_not_sealed"):
            build_dataset(self.gym, spec)

    def test_manifest_is_not_published_if_shard_commit_fails(self):
        result = self.run_fixture()
        spec = self.specification([result], [self.attach(result)])
        save, published = self.gym.artifacts.save_artifact, []
        def fail_shard(content, metadata):
            if metadata.get("schema_ref") == "gymts.dataset/1":
                published.append(metadata)
            if metadata.get("media_type") == "application/x-ndjson":
                raise GymTSError("persistence_failed", "injected shard failure", stage="storage")
            return save(content, metadata)
        with patch.object(self.gym.artifacts, "save_artifact", fail_shard):
            with self.assertRaises(GymTSError):
                build_dataset(self.gym, spec)
        self.assertEqual([], published)


if __name__ == "__main__":
    unittest.main()
