"""Data identities, official split separation, native generation and projection."""

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import GymTSError
from gymts_rl import data
from gymts_rl.contracts import INPUT, NATIVE, OUTPUT, SNAPSHOT, rl_schemas
from gymts_rl.task import RLVerifiableQATask
from gymts.plugin_support import payload


def generated():
    return {"source": {"git_revision": "native-fixture", "code_tree_sha256": "fixture"}, "versions": {}, "rows": [
        {"split": "train", "index": 0, "seed": 101, "series": [float(x) for x in range(32)], "attributes": {}},
        {"split": "eval", "index": 0, "seed": 102, "series": [float(x + 1) for x in range(32)], "attributes": {}}]}


class Services:
    def observation_ref(self, batch_id):
        return "committed-" + batch_id


class RLDataTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.gym = GymTS(self.root / "state")
        for ref, schema in rl_schemas().items():
            self.gym.schemas.register(ref, schema)

    def tearDown(self):
        self.gym.records.close()
        self.temporary.cleanup()

    def test_public_snapshot_contains_no_reference_and_summary_uses_actual_series(self):
        with patch.object(data, "generate_chatts", return_value=generated()):
            result = data.prepare_dataset(self.gym, self.root / "dataset", train_limit=0, eval_limit=0,
                chatts_train=1, chatts_eval=1, sequence_length=32)
        public = self.gym.artifacts.read_json(result["snapshot_ref"])
        private = self.gym.artifacts.read_json(result["private_ref"])
        self.assertEqual(result["counts"], {"train": 1, "eval": 1})
        self.assertNotIn("ground_truth", json.dumps(public))
        self.assertNotIn("reward_spec", json.dumps(public))
        self.assertNotIn("generator_attributes", json.dumps(public))
        gold = {r["sample_id"]: r for r in private["samples"]}
        for sample in public["samples"]:
            series = sample["timeseries"][0]
            expected = gold[sample["sample_id"]]["reward_spec"]["ground_truth"]
            self.assertEqual(expected, {"mean": sum(series) / len(series), "min": min(series), "max": max(series), "last": series[-1]})
        groups = {split: {r["group_id"] for r in public["samples"] if r["split"] == split} for split in ("train", "eval")}
        self.assertFalse(groups["train"] & groups["eval"])

    def test_repeated_curve_is_rejected_even_if_source_split_differs(self):
        rows = generated()
        rows["rows"][1]["series"] = rows["rows"][0]["series"][:]
        with patch.object(data, "generate_chatts", return_value=rows), self.assertRaises(GymTSError):
            data.prepare_dataset(self.gym, self.root / "bad", train_limit=0, eval_limit=0,
                                 chatts_train=1, chatts_eval=1, sequence_length=32)
        self.assertFalse((self.root / "bad").exists())

    def test_export_is_deterministic_and_existing_output_is_never_overwritten(self):
        with patch.object(data, "generate_chatts", return_value=generated()):
            one = data.prepare_dataset(self.gym, self.root / "one", train_limit=0, eval_limit=0, chatts_train=1, chatts_eval=1, sequence_length=32)
            two = data.prepare_dataset(self.gym, self.root / "two", train_limit=0, eval_limit=0, chatts_train=1, chatts_eval=1, sequence_length=32)
            self.assertEqual(one["dataset_revision"], two["dataset_revision"])
            self.assertEqual((self.root / "one/train.jsonl").read_bytes(), (self.root / "two/train.jsonl").read_bytes())
            with self.assertRaises(GymTSError):
                data.prepare_dataset(self.gym, self.root / "one", train_limit=0, eval_limit=0)
        exported = json.loads((self.root / "one/train.jsonl").read_text().strip())
        self.assertEqual(exported["prompt"], exported["messages"])
        self.assertIn("reward_spec", exported)
        self.assertNotIn("ground_truth", json.dumps(exported["prompt"]))

    def test_gsm8k_uses_official_source_split_and_preserves_decimal_target(self):
        paths = {}
        for split, q, answer in (("train", "Training question?", "#### 9007199254740993"), ("test", "Evaluation question?", "#### -1.25")):
            paths[split] = self.root / (split + ".jsonl")
            paths[split].write_text(json.dumps({"question": q, "answer": answer}) + "\n")
        public, private = data._gsm8k(paths, 7, (1, 1))
        self.assertEqual([r["split"] for r in public], ["train", "eval"])
        self.assertEqual([r["provenance"]["official_split"] for r in private], ["train", "test"])
        self.assertEqual(private[0]["reward_spec"]["ground_truth"], "9007199254740993")
        paths["test"].write_text(json.dumps({"question": "Training question?", "answer": "#### 1"}) + "\n")
        with self.assertRaises(GymTSError):
            data._gsm8k(paths, 7, (1, 1))

    def test_corrupt_cached_gsm8k_is_rejected_without_network(self):
        (self.root / "train.jsonl").write_bytes(b"wrong bytes")
        with patch.object(data.urllib.request, "urlopen", side_effect=AssertionError("no download expected")), self.assertRaises(GymTSError):
            data.cache_gsm8k(self.root)

    def test_invalid_counts_are_rejected_before_generation(self):
        with patch.object(data, "generate_chatts", side_effect=AssertionError("must reject first")):
            for options in ({"train_limit": -1}, {"train_limit": True}, {"eval_limit": 1320}, {"sequence_length": 4}):
                with self.assertRaises(GymTSError):
                    data.prepare_dataset(self.gym, self.root / "bad", **options)

    def test_terminal_sample_is_projected_with_no_reward_access(self):
        sample = {"sample_id": "sample", "group_id": "group", "dataset_id": "gsm8k", "split": "eval", "task_id": "gsm8k.numeric",
            "messages": [{"role": "user", "content": "Count two apples."}], "timeseries": [], "series_names": [], "output_schema": {}, "context": {}}
        services = Services()
        bound = RLVerifiableQATask({"params": {}}).bind({}, {"variables": {"sample": {"source": "sample"}}},
            {"clock_domain": "step", "observation_granularity": "transition"}, {"run_id": "run", "session": {"initial_cursor": "zero",
                "public_context": payload("gymts.rl/context/1", {"dataset_revision": "revision", "sample_count": 1})},
                "data": services, "effective_scope": {"start": 0, "end": 1}})
        update = bound.consume({"cursor": "one", "batch_id": "batch", "snapshot_time": 0, "status": "end", "data": {"native": payload(NATIVE, sample)}})
        self.assertTrue(update["done"])
        task_input = update["inputs"][0]
        self.assertEqual(task_input["payload"], payload(INPUT, sample))
        self.assertEqual(task_input["observation_refs"], ["committed-batch"])
        result = bound.interpret(task_input, {"payload": payload(OUTPUT, {"raw_text": "#### 2", "evidence": {}})}, "output")["results"][0]
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["alignment_key"], task_input["alignment_key"])
        with self.assertRaises(GymTSError):
            bound.interpret(task_input, {"payload": payload(OUTPUT, {"raw_text": "#### 2", "evidence": {}})}, "again")

    @unittest.skipUnless(os.environ.get("GYMTS_RL_NATIVE") == "1", "enable explicit native ChatTS/GSM8K source checks")
    def test_real_pinned_sources_produce_runnable_mixed_training_and_eval_data(self):
        result = data.prepare_dataset(self.gym, self.root / "native", train_limit=2, eval_limit=2, chatts_train=2, chatts_eval=2)
        manifest = self.gym.artifacts.read_json(result["manifest_ref"])
        self.assertEqual(result["counts"], {"train": 4, "eval": 4})
        self.assertTrue(manifest["sources"]["chatts"]["source"]["matches_pinned_revision"])
        self.assertEqual(manifest["sources"]["gsm8k"]["official_counts"], {"train": 7473, "test": 1319})


if __name__ == "__main__":
    unittest.main()
