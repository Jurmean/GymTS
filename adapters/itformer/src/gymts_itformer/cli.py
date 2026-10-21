"""Explicit local preparation, planning, native evaluation and zero-inference score."""
import argparse
import json
import os
from pathlib import Path
import sys


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze-core", help="CPU-only: match installed core bytes to its wheel and write a portable identity")
    freeze.add_argument("--wheel", required=True, help="Original wheel used to install the current GymTS core")
    freeze.add_argument("--expected-sha256", help="Optional independently obtained SHA-256 of that wheel")
    freeze.add_argument("--output", required=True)
    prepare = commands.add_parser("prepare", help="Select fixed official QA; separate public signals/questions from evaluation-only answers")
    prepare.add_argument("--h5", required=True)
    prepare.add_argument("--qa", required=True)
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--per-stage", type=int, default=1)
    prepare.add_argument("--projection", help="Manifest for a bounded official range projection")
    project = commands.add_parser("project", help="Read fixed official HDF5 ranges into a compact derived asset")
    project.add_argument("--qa", required=True)
    project.add_argument("--output", required=True)
    project.add_argument("--per-stage", type=int, default=2)
    official = commands.add_parser("prepare-official", help="One-command fixed official 8-QA view: verified QA download + bounded H5 ranges + private separation")
    official.add_argument("--output", required=True)
    official.add_argument("--qa", help="Reuse a local official test_qa.jsonl after exact LFS hash verification")
    official.add_argument("--per-stage", type=int, default=2)
    preflight = commands.add_parser("preflight", help="CPU-only fixed source and checkpoint validation; no inference")
    preflight.add_argument("--params", required=True)
    preflight.add_argument("--output", required=True)
    for name in ("plan", "run"):
        command = commands.add_parser(name)
        command.add_argument("--view", required=True)
        command.add_argument("--params", required=True)
        command.add_argument("--root", required=True, help="Local POSIX run/CAS store")
        command.add_argument("--core-identity", required=True)
        command.add_argument("--output", required=True)
    score = commands.add_parser("score", help="Rescore an existing Run with model/runtime unavailable")
    score.add_argument("--evaluation", required=True, help="Saved run command output")
    score.add_argument("--root", required=True)
    score.add_argument("--core-identity", required=True)
    score.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        optional_identity = os.environ.get("GYMTS_CORE_IDENTITY")
        if optional_identity and args.command in ("prepare", "project", "preflight", "prepare-official"):
            from .workflow import verify_frozen_core
            verify_frozen_core(optional_identity)
        if args.command == "freeze-core":
            from .workflow import freeze_core
            result = freeze_core(args.wheel, expected_wheel_sha256=args.expected_sha256)
            write(args.output, result)
        elif args.command == "prepare":
            from .data import prepare_view
            result = prepare_view(args.h5, args.qa, args.output, per_stage=args.per_stage, projection=args.projection)
        elif args.command == "project":
            from .projection import project_official
            result = project_official(args.qa, args.output, per_stage=args.per_stage)
        elif args.command == "prepare-official":
            from .projection import prepare_official
            result = prepare_official(args.output, qa_path=args.qa, per_stage=args.per_stage)
        elif args.command == "preflight":
            from .runtime import preflight as check
            params = load(args.params)
            result = check(params["source_path"], params["checkpoint_path"], params["base_model_path"])
            write(args.output, result)
        else:
            from gymts import GymTS
            from .workflow import build_evaluation, score_spec, verify_frozen_core
            identity = verify_frozen_core(args.core_identity)
            with GymTS(args.root, integrations=("itformer",), data_home=str(Path(args.root) / "resources"),
                       cache_home=str(Path(args.root) / "cache")) as gym:
                if args.command in ("plan", "run"):
                    view = Path(args.view)
                    spec = build_evaluation(gym, load(view / "public.json"), load(view / "private-targets.json"), load(args.params))
                    if args.command == "plan":
                        case = spec["cases"][0]
                        experiment = {"protocol_version": "gymts.experiment/1", "name": spec["name"], "purpose": spec["purpose"],
                            "scene": case["scene"], "candidate": spec["candidates"][0]["spec"],
                            "execution": case["execution"], "recording": case["recording"], "extensions": {}}
                        result = {"core_identity": identity, "plan": gym.plan(experiment), "evaluation_spec": spec}
                    else:
                        report = gym.autobench.evaluate(spec)
                        manifest = gym.artifacts.read_json(report["run_manifest_ref"])
                        run_ids = [row["run_id"] for row in manifest["entries"] if row["run_id"]]
                        result = {"core_identity": identity, "evaluation_spec": spec, "report": report,
                            "snapshot": gym.records.snapshot(run_ids), "run_ids": run_ids}
                else:
                    previous = load(args.evaluation)
                    # Explicitly fail if the score path ever starts new execution.
                    calls = {"execution": 0, "model_prepare": 0}
                    def forbidden_run(*a, **kw):
                        calls["execution"] += 1
                        raise RuntimeError("Zero-inference score attempted a new Run")
                    def forbidden_model(*a, **kw):
                        calls["model_prepare"] += 1
                        raise RuntimeError("Zero-inference score attempted native model loading")
                    gym.environment_ts.run = forbidden_run
                    from .candidate import ITFormerCandidate
                    ITFormerCandidate.prepare = forbidden_model
                    spec = score_spec(gym, previous["evaluation_spec"], previous["report"])
                    result = {"core_identity": identity, "report": gym.autobench.score(spec), "execution_calls": calls}
                write(args.output, result)
        summary = {"command": args.command, "status": "completed"}
        if "report" in result:
            summary.update(evaluation_id=result["report"]["evaluation_id"], status=result["report"]["status"],
                verdict=result["report"]["verdict"], coverage=result["report"]["coverage"])
        elif args.command == "freeze-core":
            summary.update(core_version=result["core_version"], wheel_sha256=result["wheel_sha256"],
                verified_files=len(result["installed_files"]))
        elif args.command in ("prepare", "prepare-official"):
            summary.update(view_revision=result["view_revision"], selected_count=result["selected_count"])
        print(json.dumps(summary, ensure_ascii=False))
        return 0 if "report" not in result or result["report"]["status"] == "completed" and result["report"]["verdict"] == "pass" else 2
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
