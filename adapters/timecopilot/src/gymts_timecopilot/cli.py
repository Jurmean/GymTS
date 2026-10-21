"""Prepare classic holdouts, run native Agent evaluation, or rescore sealed evidence."""
import argparse
import json
from pathlib import Path

from gymts import GymTS


def read(path):
    return json.loads(Path(path).read_text())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True)
    parser.add_argument("--output", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--implementation", required=True, help="JSON file with repository, python, revision")
    prepare.add_argument("--history", type=int, default=120)
    prepare.add_argument("--horizon", type=int, default=12)
    execute = commands.add_parser("evaluate")
    execute.add_argument("--source", required=True)
    execute.add_argument("--params", required=True)
    finalize = commands.add_parser('score', help='Score an existing execution without calling the native Agent')
    finalize.add_argument('--initial', required=True)
    finalize.add_argument('--source', required=True)
    finalize.add_argument('--params', required=True)
    score = commands.add_parser("rescore")
    score.add_argument("--previous", required=True)
    args = parser.parse_args(argv)
    with GymTS(args.store, integrations=("timeseries", "timecopilot")) as gym:
        if args.command == "prepare":
            from .data import prepare_airpassengers
            result = prepare_airpassengers(gym, read(args.implementation), history=args.history, horizon=args.horizon)
        elif args.command == "evaluate":
            from .experiments import evaluate
            def execution_saved(value):
                Path(args.output).with_suffix('.execution.json').write_text(json.dumps(value, indent=2)+'\n')
            result = evaluate(gym, read(args.source), read(args.params), execution_saved)
        elif args.command == 'score':
            from .experiments import score_execution
            result = score_execution(gym, read(args.source), read(args.params), read(args.initial))
        else:
            from .experiments import rescore
            result = rescore(gym, read(args.previous))
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    report = result.get('report', {})
    print(json.dumps({"output": str(Path(args.output).resolve()), "run_ids": result.get("run_ids", []),
                      "failures": len(result.get("failures", [])), 'report_errors':len(report.get('errors', []))}))
    coverage = report.get('coverage', {})
    failed = bool(result.get('failures') or report.get('errors') or
        (report and report.get('status') != 'completed') or
        any(coverage.get(key, 0) for key in ['failed_runs','cancelled_runs','not_started_units']))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
