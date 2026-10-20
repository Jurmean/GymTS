#!/usr/bin/env python3
"""Real CPU GRPO -> immutable bundle -> fresh-process AutoBenchTS acceptance.

This is an explicitly controlled tiny Qwen2 engineering fixture, not a pretrained
model or a model-quality benchmark. It uses verified official GSM8K source rows
and genuine ChatTS numerical generation. No user benchmark attachment is used.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def controlled_base(directory):
    """Construct the declared initial policy before any training occurs.

    At initialization two genuine sampled answer tokens have equal probability;
    each is followed by EOS. Attention LoRA can change that distribution. The
    controlled vocabulary intentionally limits task competence to this fixture.
    """
    import torch
    from tokenizers import Tokenizer, models, pre_tokenizers
    from transformers import PreTrainedTokenizerFast, Qwen2Config, Qwen2ForCausalLM
    directory.mkdir()
    vocab = {"<pad>": 0, "<unk>": 1, "<assistant>": 2, "#### 0": 3,
             "#### 1": 4, "<eos>": 5, "x": 6, "y": 7}
    backend = Tokenizer(models.WordLevel(vocab=vocab, unk_token="<unk>"))
    backend.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer = PreTrainedTokenizerFast(tokenizer_object=backend, pad_token="<pad>", eos_token="<eos>",
        unk_token="<unk>", additional_special_tokens=["<assistant>"],
        model_input_names=["input_ids", "attention_mask"])
    tokenizer.model_input_names = ["input_ids", "attention_mask"]
    tokenizer.chat_template = '{% for message in messages %}{{ message["content"] }} {% endfor %}<assistant>'
    config = Qwen2Config(vocab_size=8, hidden_size=16, intermediate_size=32, num_hidden_layers=1,
        num_attention_heads=2, num_key_value_heads=2, max_position_embeddings=2048,
        pad_token_id=0, eos_token_id=5, tie_word_embeddings=False, attention_dropout=0.)
    model = Qwen2ForCausalLM(config)
    with torch.no_grad():
        for parameter in model.parameters():
            parameter.zero_()
        model.model.embed_tokens.weight[:8, :8] = torch.eye(8)
        model.model.norm.weight.fill_(1)
        layer = model.model.layers[0]
        layer.input_layernorm.weight.fill_(1)
        layer.post_attention_layernorm.weight.fill_(1)
        layer.self_attn.o_proj.weight.copy_(torch.eye(16))
        model.lm_head.weight[:, 2] = -5
        model.lm_head.weight[3:5, 2] = 2
        model.lm_head.weight[3, 0], model.lm_head.weight[4, 0] = 2, -2
        model.lm_head.weight[:, 3:5] = -5
        model.lm_head.weight[5, 3:5] = 5
    model.save_pretrained(directory, safe_serialization=True)
    tokenizer.save_pretrained(directory)
    return {"kind": "controlled-qwen2-cpu-engineering-fixture", "pretrained": False,
            "vocab_size": 8, "hidden_size": 16, "layers": 1,
            "initialization": "two equiprobable numeric answer tokens then EOS; fixed before LoRA training",
            "quality_claim": False}


def train_stage(root):
    import importlib.metadata
    from gymts import GymTS
    from gymts_rl.data import prepare_dataset
    from gymts_rl.policy import LocalPolicy
    from gymts_rl.train import run_training
    fixture = controlled_base(root / "base")
    with GymTS(root / "records", integrations=("rl",)) as gym:
        prepared = prepare_dataset(gym, root / "data", train_limit=128, eval_limit=4,
                                  chatts_train=2, chatts_eval=2, sequence_length=32)
        rows = [json.loads(line) for line in Path(prepared["train_path"]).read_text().splitlines()]
        # Explicit training-only selection keeps this tiny two-answer fixture
        # capable of producing a genuine verifiable GRPO reward difference.
        selected = [row["sample_id"] for row in rows if row["dataset_id"] == "openai/gsm8k"
                    and (row["reward_spec"] if isinstance(row["reward_spec"], dict) else json.loads(row["reward_spec"]))["ground_truth"] == "1"]
        if len(selected) < 1:
            raise RuntimeError("Pinned official subset lacks the declared training fixture")
        policy = LocalPolicy.from_pretrained(root / "base", family="text", device="cpu", dtype="float32")
        summary = run_training(gym, prepared, policy, root / "training", steps=2, generations=8,
            groups_per_step=1, max_new_tokens=4, learning_rate=.02, lora_rank=2,
            seed=7, eval_per_source=0, train_sample_ids=selected, include_base_in_bundle=True)
        rewards = [[entry["reward"]["reward"] for entry in batch["entries"] if entry["reward"] is not None]
                   for batch in summary["rollout_batches"]]
        gradients = [item["grad_norm"] for item in summary["log_history"] if "grad_norm" in item]
        if not summary["weights_changed"] or not any(len(set(group)) > 1 for group in rewards):
            raise RuntimeError("No actual nonzero-advantage RL parameter update")
        if not any(value > 0 for value in gradients):
            raise RuntimeError("No measured nonzero training gradient")
        public = gym.artifacts.read_json(prepared["snapshot_ref"])["samples"]
        chosen = [next(row["sample_id"] for row in public if row["split"] == "eval" and row["dataset_id"] == source)
                  for source in ("openai/gsm8k", "chatts-native-generated/v1")]
        request = {"prepared": prepared, "bundle_ref": summary["checkpoint_bundle_ref"], "sample_ids": chosen,
                   "training_summary_ref": summary["summary_ref"], "training_provenance_ref": summary["training_provenance_ref"],
                   "deployment_policy_revision": summary["deployment_policy_revision"]}
        save(root / "evaluation-request.json", request)
        save(root / "training-result.json", {"status": "passed", "pid": os.getpid(), "fixture": fixture,
            "training_sample_ids": selected, "selection": "official training rows with numeric answer 1; no eval label filtering",
            "training_partition_counts": prepared["counts"], "steps_completed": summary["steps_completed"],
            "reward_groups": rewards, "gradient_norms": gradients, "weights_changed": summary["weights_changed"],
            "weight_decay": 0.0, "initial_trainable_digest": summary["initial_trainable_digest"],
            "final_trainable_digest": summary["final_trainable_digest"], "checkpoint_reload_equal": summary["checkpoint_reload_equal"],
            "checkpoint_bundle_ref": summary["checkpoint_bundle_ref"], "training_provenance_ref": summary["training_provenance_ref"],
            "dataset_manifest_refs": [batch["manifest_ref"] for batch in summary["rollout_batches"]],
            "record_snapshot_refs": [batch["record_snapshot_ref"] for batch in summary["rollout_batches"]],
            "versions": {name: importlib.metadata.version(name) for name in ("gymts", "gymts-rl", "torch", "transformers", "trl", "peft")}})


def evaluate_stage(root):
    from unittest.mock import patch
    import gymts
    import gymts_rl
    from gymts import GymTS
    from gymts.contracts import digest
    from gymts.plugin_support import unpack
    from gymts_rl.evaluation import checkpoint_evaluation_spec, rescore_checkpoint_evaluation
    request = json.loads((root / "evaluation-request.json").read_text())
    seeds = [0, 1, 5]
    gate = lambda metric, threshold, for_metric=None: {"metric": metric, "target": "absolute", "candidate_ids": None,
        "for_metric": for_metric, "operator": "le" if metric == "run_failure_rate" else "ge", "threshold": threshold, "scope": "aggregate"}
    with GymTS(root / "records", integrations=("rl",)) as gym:
        spec = checkpoint_evaluation_spec(gym, request["prepared"], request["bundle_ref"], request["sample_ids"],
            seeds=seeds, generation={"max_new_tokens": 4}, load={"device": "cpu", "dtype": "float32"},
            gates=[gate("run_failure_rate", 0), gate("scored_coverage", 1, "accuracy")])
        # Only the actual run phase may materialize/load model bytes.
        experiment = {"protocol_version": "gymts.experiment/1", "purpose": "acceptance", "name": "pure checkpoint validation",
            "scene": spec["cases"][0]["scene"], "candidate": spec["candidates"][0]["spec"],
            "execution": spec["cases"][0]["execution"], "recording": spec["cases"][0]["recording"], "extensions": {}}
        with patch("gymts_rl.checkpoint.load_checkpoint_policy", side_effect=AssertionError("Validation loaded model")):
            validation = gym.validate(experiment)
        if not validation["valid"]:
            raise RuntimeError("Checkpoint experiment validation failed: " + str(validation))
        with patch("gymts_rl.candidate.active_policy", side_effect=AssertionError("Fresh candidate used resident policy")):
            report = gym.autobench.evaluate(spec)
        report_ref = gym.autobench.last_report_ref
        plan = gym.artifacts.read_json(report["plan_ref"])
        executions = gym.artifacts.read_json(report["run_manifest_ref"])["entries"]
        run_ids = [entry["run_id"] for entry in executions if entry["run_id"] is not None]
        units = {unit["unit_id"]: unit for unit in plan["expected_units"]}
        before, calls, sampled_tokens = {}, [], {}
        for entry in executions:
            run = gym.records.get_run(entry["run_id"])
            before[entry["run_id"]] = {"result_digest": digest(run["result"]), "events": len(run["events"])}
            candidate_preparation = [unpack(event["payload"], gym.artifacts) for event in run["events"] if event["kind"] == "candidate_prepare"]
            if (len(candidate_preparation) != 1 or candidate_preparation[0]["training_provenance_ref"] is None
                    or candidate_preparation[0]["training_provenance_ref"]["content_hash"] != request["training_provenance_ref"]["content_hash"]):
                raise RuntimeError("Checkpoint Candidate did not publish training provenance")
            for event in run["events"]:
                if event["kind"] == "model_call":
                    call = unpack(event["payload"], gym.artifacts)
                    expected_seed = units[entry["unit_id"]]["seed"]
                    if call["effective_params"]["seed"] != expected_seed or call["policy_revision"] != request["deployment_policy_revision"]:
                        raise RuntimeError("Candidate did not honor fixed weights/execution seed")
                    sampled_tokens[(units[entry["unit_id"]]["evaluation_case_id"], expected_seed)] = call["response_token_ids_ref"]["content_hash"]
                    calls.append({"run_id": run["run_id"], "call_id": call["call_id"], "seed": expected_seed,
                        "policy_revision": call["policy_revision"], "call_ref": event["payload"]["artifact_ref"],
                        "training_provenance_ref": candidate_preparation[0]["training_provenance_ref"]})
        # Re-run the same immutable candidate with the same three execution
        # seeds. Each Run loads from the archive again; no resident policy is used.
        with patch("gymts_rl.candidate.active_policy", side_effect=AssertionError("Repeat used resident policy")):
            repeated = gym.autobench.evaluate(spec)
        repeated_ref = gym.autobench.last_report_ref
        repeated_plan = gym.artifacts.read_json(repeated["plan_ref"])
        repeated_units = {unit["unit_id"]: unit for unit in repeated_plan["expected_units"]}
        repeated_tokens = {}
        for entry in gym.artifacts.read_json(repeated["run_manifest_ref"])["entries"]:
            record = gym.records.get_run(entry["run_id"])
            for event in record["events"]:
                if event["kind"] == "model_call":
                    call = unpack(event["payload"], gym.artifacts)
                    unit = repeated_units[entry["unit_id"]]
                    if call["policy_revision"] != request["deployment_policy_revision"]:
                        raise RuntimeError("Repeated execution changed checkpoint identity")
                    repeated_tokens[(unit["evaluation_case_id"], unit["seed"])] = call["response_token_ids_ref"]["content_hash"]
        if repeated["verdict"] != "pass" or sampled_tokens != repeated_tokens:
            raise RuntimeError("Repeated checkpoint execution did not reproduce sampled token IDs")
        with patch("gymts_rl.checkpoint.load_checkpoint_policy", side_effect=AssertionError("Re-score loaded model")), \
             patch("gymts_rl.policy.LocalPolicy.generate", side_effect=AssertionError("Re-score generated output")):
            rescored = rescore_checkpoint_evaluation(gym, report)
        rescored_ref = gym.autobench.last_report_ref
        unchanged = all(before[run_id] == {"result_digest": digest(gym.records.get_run(run_id)["result"]),
            "events": len(gym.records.get_run(run_id)["events"])} for run_id in run_ids)
        if report["status"] != "completed" or report["verdict"] != "pass" or rescored["verdict"] != "pass" or not unchanged:
            raise RuntimeError("Fresh checkpoint evaluation/re-scoring failed: " + str(report["errors"]) + str(report["gate_results"]))
        if len({unit["candidate_id"] for unit in plan["expected_units"]}) != 1 or len(run_ids) != len(seeds) * 2:
            raise RuntimeError("Repetitions changed candidate identity or dropped planned units")
        save(root / "evaluation-result.json", {"status": "passed", "pid": os.getpid(),
            "installed_modules": {"gymts": gymts.__file__, "gymts_rl": gymts_rl.__file__},
            "pure_validation": True, "fresh_process_resident_policy_used": False,
            "technical_gates_only": True, "quality_claim": False, "seeds": seeds,
            "candidate_count": 1, "run_ids": run_ids, "model_calls": calls,
            "report_ref": report_ref, "repeated_report_ref": repeated_ref, "rescored_report_ref": rescored_ref,
            "repeated_evaluation_id": repeated["evaluation_id"], "same_seed_token_ids_reproduced": True,
            "training_provenance_content_identity_preserved": True,
            "evaluation_id": report["evaluation_id"], "rescored_evaluation_id": rescored["evaluation_id"],
            "metrics": report["metrics"], "gate_results": report["gate_results"],
            "coverage": report["coverage"], "verdict": report["verdict"],
            "rescore_new_model_calls": 0, "sealed_results_and_events_unchanged": unchanged,
            "base_and_training_checkpoint_paths_unavailable": not (root / "base").exists() and not (root / "training/final-adapter").exists()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stage", choices=("train", "evaluate"))
    args = parser.parse_args()
    root = args.output.resolve()
    if args.stage == "train":
        train_stage(root)
    elif args.stage == "evaluate":
        evaluate_stage(root)
    else:
        root.mkdir(parents=True, exist_ok=False)
        environment = dict(os.environ, CUDA_VISIBLE_DEVICES="", ACCELERATE_USE_CPU="true", OMP_NUM_THREADS="1", TOKENIZERS_PARALLELISM="false")
        for stage in ("train", "evaluate"):
            with (root / (stage + ".log")).open("w") as log:
                subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--output", str(root), "--stage", stage],
                               cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
            if stage == "train":
                (root / "base").rename(root / "base-original-evidence")
                (root / "training/final-adapter").rename(root / "training/final-adapter-original-evidence")
        training = json.loads((root / "training-result.json").read_text())
        evaluation = json.loads((root / "evaluation-result.json").read_text())
        if training["pid"] == evaluation["pid"]:
            raise RuntimeError("Checkpoint was not evaluated in a new process")
        save(root / "summary.json", {"status": "passed", "training": training, "evaluation": evaluation,
             "fixture_model": True, "data": "pinned official GSM8K + genuine ChatTS numerical generation",
             "attachment_benchmarks_used": False, "paid_calls": False, "gpu_training": False})
        print(json.dumps({"status": "passed", "summary": str(root / "summary.json")}, indent=2))


if __name__ == "__main__":
    main()
