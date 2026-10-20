"""Prepare fixed HF resources, then use the ordinary GymTS evaluation service."""
import argparse
import json
from pathlib import Path
import sys

from gymts import GymTS
from gymts.contracts import utc_now
from .benchmark import experiment_from_case, last_value_candidate, score_existing
from .importer import freeze_dataset, register_benchmark


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True)
    parser.add_argument("--data-home", required=True)
    parser.add_argument("--cache-home", default="/tmp/gymts-hf-cache")
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze", help="Source JSON explicitly declares hub/save_to_disk/local_files")
    freeze.add_argument("dataset_id")
    freeze.add_argument("--source", required=True, help="Path to source JSON")
    freeze.add_argument("--series-column", required=True)
    freeze.add_argument("--horizon", type=int, required=True)
    freeze.add_argument("--context-length", type=int, required=True)
    freeze.add_argument("--indices", type=int, nargs="+")
    freeze.add_argument("--alias", action="append", default=[])
    freeze.add_argument("--receipt", help="Write a preparation receipt on success or failure; no Run exists during preparation")
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("benchmark_id")
    evaluate.add_argument("--revision", required=True)
    evaluate.add_argument("--rescore", action="store_true")
    evaluate.add_argument("--direct-run", action="store_true")
    args = parser.parse_args(argv)
    receipt = {"operation": args.command, "started_at": utc_now()}
    try:
        with GymTS(args.store, data_home=args.data_home, cache_home=args.cache_home, integrations=("hf-datasets",)) as gym:
            if args.command == "freeze":
                source = json.loads(Path(args.source).read_text())
                dataset = freeze_dataset(gym, args.dataset_id, source, series_column=args.series_column,
                    horizon=args.horizon, context_length=args.context_length, sample_indices=args.indices,
                    aliases=args.alias, cache_dir=str(Path(args.cache_home) / "preparation"))
                benchmark = register_benchmark(gym, args.dataset_id, revision=dataset["revision"], aliases=args.alias)
                result = {"dataset": dataset, "benchmark": benchmark}
            else:
                spec = gym.autobench.resolve_benchmark(args.benchmark_id, revision=args.revision,
                    candidates=[last_value_candidate()])
                result = {}
                if args.direct_run:
                    result["direct_run"] = gym.environment_ts.run(experiment_from_case(spec))
                result["evaluation"] = gym.autobench.evaluate(spec)
                if args.rescore:
                    result["rescoring"] = score_existing(gym, spec, result["evaluation"])
        receipt.update(status="succeeded", finished_at=utc_now(), result=result)
    except Exception as error:
        receipt.update(status="failed", finished_at=utc_now(), error={"type": type(error).__name__,
            "code": getattr(error, "code", None), "message": str(error)})
        if args.command == "freeze" and args.receipt:
            Path(args.receipt).write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
        print(json.dumps(receipt, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    if args.command == "freeze" and args.receipt:
        Path(args.receipt).write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
