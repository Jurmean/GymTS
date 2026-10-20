"""Local verifiable RL CLI; --help and data preparation do not import torch."""
import argparse
import hashlib
import json
import os
from pathlib import Path

from gymts import GymTS
from gymts.contracts import GymTSError, canonical_json


def _prepared(gym, directory):
    path = Path(directory).resolve()
    value = json.loads((path / "manifest.json").read_text())
    for name, metadata in value["files"].items():
        if hashlib.sha256((path / name).read_bytes()).hexdigest() != metadata["sha256"]:
            raise GymTSError("invalid_dataset", "Prepared prompt data changed after publication")
    for key in ("snapshot_ref", "private_ref", "manifest_ref"):
        gym.artifacts.read_json(value[key])
    return dict(value, output_dir=str(path), train_path=str(path / "train.jsonl"), eval_path=str(path / "eval.jsonl"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="GymTS native GSM8K + ChatTS rollouts and TRL GRPO")
    parser.add_argument("--store", default="/tmp/gymts-rl/records", help="Local CAS/SQLite directory")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Prepare pinned official GSM8K and native ChatTS synthetic data")
    prepare.add_argument("--output", default="/tmp/gymts-rl/data")
    prepare.add_argument("--gsm8k-dir")
    prepare.add_argument("--chatts-source", default="/zzr/scripts/ChatTS")
    prepare.add_argument("--generator-python")
    prepare.add_argument("--gsm8k-train", type=int, default=128)
    prepare.add_argument("--gsm8k-eval", type=int, default=32)
    prepare.add_argument("--chatts-train", type=int, default=32)
    prepare.add_argument("--chatts-eval", type=int, default=8)
    prepare.add_argument("--sequence-length", type=int, default=64)
    prepare.add_argument("--seed", type=int, default=7)
    for command in ("rollout", "train"):
        sub = commands.add_parser(command, help="Capture real native policy actions" if command == "rollout" else "Run TRL LoRA GRPO and held-out evaluation")
        sub.add_argument("--data", default="/tmp/gymts-rl/data")
        sub.add_argument("--model", default="/zzr/models/ChatTS-3-8B")
        sub.add_argument("--family", choices=("text", "chatts"), default="chatts")
        sub.add_argument("--device", default="cuda:0")
        sub.add_argument("--dtype", choices=("bfloat16", "float16", "float32"), default="bfloat16")
        sub.add_argument("--trust-remote-code", action="store_true", help="Trust custom code in the selected local ChatTS checkpoint")
        sub.add_argument("--max-new-tokens", type=int, default=512)
        sub.add_argument("--seed", type=int, default=7)
        sub.add_argument("--output", default="/tmp/gymts-rl/" + command)
        if command == "rollout":
            sub.add_argument("--adapter")
            sub.add_argument("--split", choices=("train", "eval"), default="eval")
            sub.add_argument("--per-source", type=int, default=1)
            sub.add_argument("--generations", type=int, default=2)
        else:
            sub.add_argument("--steps", type=int, default=2)
            sub.add_argument("--generations", type=int, default=4)
            sub.add_argument("--groups-per-step", type=int, default=2)
            sub.add_argument("--lora-rank", type=int, default=8)
            sub.add_argument("--learning-rate", type=float, default=1e-5)
            sub.add_argument("--eval-per-source", type=int, default=1)
    score = commands.add_parser("score", help="Independently score sealed eval Runs through AutoBenchTS; no model is loaded")
    score.add_argument("--run-id", action="append", required=True, help="Existing sealed eval Run; repeat for more Runs")
    score.add_argument("--output", required=True, help="New JSON report index file")
    score.add_argument("--min-accuracy", type=float, help="Optional explicit acceptance gate in [0,1]")
    args = parser.parse_args(argv)
    with GymTS(args.store, integrations=("rl",)) as gym:
        if args.command == "prepare":
            from .data import prepare_dataset
            result = prepare_dataset(gym, args.output, gsm8k_dir=args.gsm8k_dir,
                chatts_source=args.chatts_source, python=args.generator_python, seed=args.seed,
                train_limit=args.gsm8k_train, eval_limit=args.gsm8k_eval,
                chatts_train=args.chatts_train, chatts_eval=args.chatts_eval, sequence_length=args.sequence_length)
        elif args.command == "score":
            from .evaluation import score_rollout_runs
            gates = []
            if args.min_accuracy is not None:
                if not 0 <= args.min_accuracy <= 1:
                    parser.error("--min-accuracy must be in [0,1]")
                gates.append({"metric": "accuracy", "target": "absolute", "candidate_ids": None, "for_metric": None,
                              "operator": "ge", "threshold": args.min_accuracy, "scope": "aggregate"})
            result = score_rollout_runs(gym, args.run_id, gates=gates)
            destination = Path(args.output).resolve()
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(canonical_json({"report_ref": gym.autobench.last_report_ref, "report": result}) + b"\n")
        else:
            os.environ.setdefault("HF_HOME", "/tmp/gymts-rl-runtime/huggingface")
            os.environ.setdefault("HF_MODULES_CACHE", "/tmp/gymts-rl-runtime/huggingface/modules")
            if args.device.startswith("cuda") and "CUDA_VISIBLE_DEVICES" not in os.environ:
                # Trainer otherwise enables DataParallel on every visible GPU.
                # Select the requested physical device before importing torch.
                os.environ["CUDA_VISIBLE_DEVICES"] = args.device.partition(":")[2] or "0"
                args.device = "cuda:0"
            from .policy import LocalPolicy
            prepared = _prepared(gym, args.data)
            policy = LocalPolicy.from_pretrained(args.model, family=args.family,
                device=args.device, dtype=args.dtype, trust_remote_code=args.trust_remote_code,
                adapter_path=getattr(args, "adapter", None))
            if args.command == "train":
                from .train import run_training
                result = run_training(gym, prepared, policy, args.output,
                    steps=args.steps, generations=args.generations, groups_per_step=args.groups_per_step,
                    max_new_tokens=args.max_new_tokens, learning_rate=args.learning_rate,
                    lora_rank=args.lora_rank, seed=args.seed, eval_per_source=args.eval_per_source)
            else:
                from .pipeline import rollouts
                if args.per_source < 1 or args.generations < 1:
                    parser.error("--per-source and --generations must be positive")
                rows = [json.loads(line) for line in Path(prepared[args.split + "_path"]).read_text().splitlines()]
                ids, counts = [], {}
                for row in rows:
                    source = row["dataset_id"]
                    if counts.get(source, 0) < args.per_source:
                        ids.extend([row["sample_id"]] * args.generations)
                        counts[source] = counts.get(source, 0) + 1
                result = rollouts(gym, prepared, ids, policy, generation={"max_new_tokens": args.max_new_tokens},
                                  seed_start=args.seed, split=args.split)
                result = {key: value for key, value in result.items() if key != "rows"}
                output = Path(args.output).resolve()
                output.mkdir(parents=True, exist_ok=True)
                destination = output / "rollout-summary.json"
                with destination.open("xb") as stream:
                    stream.write(canonical_json(result) + b"\n")
        print(json.dumps({key: value for key, value in result.items()
                          if key in {"status", "counts", "dataset_revision", "manifest_ref", "summary_ref", "metrics",
                                     "weights_changed", "checkpoint_reload_equal", "checkpoint", "checkpoint_bundle_ref",
                                     "deployment_policy_revision", "training_provenance_ref", "run_ids", "evaluation_id", "verdict", "reasons"}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
