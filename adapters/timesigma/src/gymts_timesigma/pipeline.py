"""TimeSigma planning units through the public GymTS v1 execution contract."""

import argparse
import copy
import json
from pathlib import Path
import sys

from gymts import GymTS, GymTSError
from gymts.contracts import digest, inline, utc_now

from .contracts import ALIGNMENT, OUTCOME


def recording():
    # This adapter declares no model-call capture profiles. Native worker
    # evidence is returned by Candidate.finish as ordinary CAS artifacts.
    return {"store_ref": "local://records/default", "inputs": "full", "outputs": "full",
            "artifacts": "reference", "model_calls": "none", "on_capture_failure": "fail_run",
            "redaction_policy_ref": None, "extra_event_kinds": []}


def training_view(reference):
    return {"view_id": "timesigma-prepare-" + reference["artifact_id"], "revision": reference["revision"],
            "source_refs": [reference], "selection": inline({"kind": "all", "source_index": 0}, "gymts.selection/1"),
            "as_of": None, "purpose": "prepare"}


def scene(imported):
    return {"environment": {"protocol_version": "gymts.environment/1", "adapter": "timesigma-snapshot",
            "version": "1.0.0", "source": {"kind": "dataset", "locator": "artifact://timesigma-planning-unit",
                "revision": imported["dataset_revision"], "connection": {"artifact_refs": [imported["snapshot_ref"]]},
                "credential_ref": None}, "mapping": {}, "options": {}},
            "task": {"plugin": "timesigma-tsad", "version": "1.0.0",
                "params": {"planning_unit_id": imported["planning_unit_id"]}},
            "binding": {"variables": {"planning_unit": {"source": "planning_unit", "unit": "planning_unit", "transform": None}},
                        "operations": {}}}


def evaluation_spec(imported, params, *, artifact=None, metrics=None, execution_seed=None):
    from .scoring import METRIC_IDS
    metrics = list(METRIC_IDS if metrics is None else metrics)
    if not metrics:
        raise GymTSError("invalid_config", "At least one official TimeSigma metric is required")
    mode = "load_only" if artifact is not None else "fit"
    seed = params.get("seed", 1) if execution_seed is None else execution_seed
    timeout = params.get("timeout_seconds", 300)
    candidate = {"candidate_id": params["method"], "spec": {"adapter": "timesigma-native", "version": "1.0.0",
        "artifact": artifact, "params": copy.deepcopy(params), "inherited_state": []}}
    case = {"evaluation_case_id": imported["planning_unit_id"], "scene": scene(imported),
        "execution": {"mode": "stream", "start": {"mode": "reinitialize"}, "scope": {"start": 0, "end": 1},
            "feedback_until": None, "seed": seed,
            "learning": {"prepare": mode, "online": "frozen",
                "training_view": training_view(imported["training_ref"]) if mode == "fit" else None,
                "training_targets": None, "alignment_schema_ref": None, "allowed_feedback_sources": []},
            "limits": {"max_inputs": 1, "max_operations": 1, "max_turns_per_case": 1,
                "max_wall_time_s": timeout * 2 + 30}},
        "recording": recording(), "tags": {"schema": imported["schema"], "method": params["method"]}}
    scorer_params = {key: params[key] for key in ("source_repo", "python")}
    scorer_params.update(timeout_seconds=timeout, planning_unit_id=imported["planning_unit_id"],
                         evaluation_members=imported["evaluation_members"], dataset=imported["dataset"])
    return {"protocol_version": "gymts.evaluation/1", "name": "TimeSigma " + params["method"] + "/" + imported["schema"],
        "purpose": "development", "cases": [case], "candidates": [candidate], "baseline_id": None,
        "repetitions": {"count": 1, "seeds": [seed]},
        "scoring": {"scorer": {"adapter": "timesigma-official", "version": "1.0.0", "params": scorer_params},
            "outcomes": {"sources": [], "as_of": None},
            "alignment": {"schema_ref": ALIGNMENT, "keys": ["dataset_revision", "planning_unit_id"],
                "matching": "exact", "params": {}, "duplicate_policy": "error"},
            "metrics": metrics, "evidence_requirements": {"min_scored": len(imported["evaluation_members"]),
                "min_coverage": 1, "overrides": {}}, "missing_outcome_policy": "report_insufficient"},
        "comparison": {"group_by": ["evaluation_case_id"], "repetition_aggregation": "mean", "aggregation": "macro_mean",
            "baseline_method": "difference", "gates": [
                {"metric": "run_failure_rate", "target": "absolute", "candidate_ids": [params["method"]],
                    "for_metric": None, "operator": "le", "threshold": 0, "scope": "aggregate"}] + [
                {"metric": "scored_coverage", "target": "absolute", "candidate_ids": [params["method"]],
                    "for_metric": metric, "operator": "ge", "threshold": 1, "scope": "aggregate"}
                for metric in metrics]},
        "failure_policy": {"partial_results": "include", "invalid_result_policy": "report"}}


def attach_and_rescore(gym, imported, spec, initial):
    """Attach private labels after execution; score the same sealed Run IDs."""
    private = gym.artifacts.read_json(imported["private_ref"])
    gold = private["outcome"]
    gym.schemas.validate(OUTCOME, gold)
    alignment = {key: imported[key] for key in ("dataset_revision", "planning_unit_id")}
    if any(gold[key] != alignment[key] for key in alignment):
        raise GymTSError("conflict", "Private outcome does not belong to this planning unit")
    manifest = gym.artifacts.read_json(initial["run_manifest_ref"])
    plan = gym.artifacts.read_json(initial["plan_ref"])
    units = {unit["unit_id"]: unit for unit in plan["expected_units"]}
    selections, originals, run_ids = [], {}, []
    outcome = {"outcome_id": "timesigma-gold-" + digest(gold).removeprefix("sha256:"), "revision": "1",
        "alignment_key": alignment, "payload": inline(gold, OUTCOME), "event_time": 0,
        "available_at": utc_now(), "recorded_at": None, "source_ref": imported["private_ref"],
        "supersedes_ref": None, "allowed_uses": ["evaluation"]}
    # Outcome identity is global in native records. Reuse its original temporal
    # facts when another method evaluates the same fixed gold revision.
    try:
        existing = gym.records.read_outcomes({"outcome_refs": [
            {"outcome_id": outcome["outcome_id"], "revision": outcome["revision"]}]})
    except GymTSError as error:
        if error.code != "outcome_unavailable":
            raise
    else:
        old = existing[0]
        if any(old[key] != outcome[key] for key in outcome if key not in {"available_at", "recorded_at"}):
            raise GymTSError("conflict", "Existing gold revision differs from the fixed evaluation source")
        outcome = dict(old, recorded_at=None)
    for entry in manifest["entries"]:
        unit, run_id = units[entry["unit_id"]], entry["run_id"]
        if run_id:
            original = gym.records.get_run(run_id)
            if original["result"] is None:
                raise GymTSError("conflict", "Outcome cannot be attached before execution is sealed")
            originals[run_id] = digest(original["result"])
            gym.records.attach_outcomes(run_id, [outcome])
            run_ids.append(run_id)
        selections.append({"unit_id": unit["unit_id"], "evaluation_case_id": unit["evaluation_case_id"],
            "candidate_id": unit["candidate_id"], "repetition": unit["repetition"], "run_id": run_id,
            "unavailable_reason": None if run_id else "planned_run_unavailable", "unit_spec_ref": unit["resolved_spec_ref"],
            "tags": copy.deepcopy(unit["tags"])})
    cutoff = utc_now()
    records = gym.records.read_outcomes({"run_ids": run_ids, "outcomes_as_of": cutoff, "purpose": "evaluation"})
    ref = gym.artifacts.save_json(records, "gymts.outcome-records/1")
    view = {"view_id": "timesigma-evaluation-" + ref["artifact_id"], "revision": ref["revision"], "source_refs": [ref],
        "selection": inline({"kind": "all", "source_index": 0}, "gymts.selection/1"), "as_of": None, "purpose": "evaluation"}
    scoring = copy.deepcopy(spec["scoring"])
    scoring["outcomes"] = {"sources": [view], "as_of": cutoff}
    score_spec = {"protocol_version": "gymts.score/1", "name": spec["name"] + " fixed outputs", "purpose": "development",
        "runs": selections, "previous_evaluation_id": initial["evaluation_id"], "baseline_id": None,
        "scoring": scoring, "comparison": copy.deepcopy(spec["comparison"]), "failure_policy": copy.deepcopy(spec["failure_policy"])}
    rescored = gym.autobench.score(score_spec)
    after = gym.artifacts.read_json(rescored["run_manifest_ref"])
    if ([row["run_id"] for row in after["entries"]] != [row["run_id"] for row in manifest["entries"]]
            or any(digest(gym.records.get_run(run_id)["result"]) != previous for run_id, previous in originals.items())):
        raise GymTSError("conflict", "Rescoring changed sealed TimeSigma execution evidence")
    return rescored, score_spec, run_ids


def run_experiment(gym, imported, params, *, artifact=None, metrics=None, execution_seed=None):
    """One fixed detector pipeline × one Schema planning unit, using native APIs."""
    gym.enable_integration("timesigma")
    manifest = gym.artifacts.read_json(imported["manifest_ref"])
    if any(key not in manifest or manifest[key] != value for key, value in imported.items() if key != "manifest_ref"):
        raise GymTSError("conflict", "Imported planning unit differs from its fixed import manifest")
    spec = evaluation_spec(imported, params, artifact=artifact, metrics=metrics, execution_seed=execution_seed)
    initial = gym.autobench.evaluate(spec)
    final, score_spec, run_ids = attach_and_rescore(gym, imported, spec, initial)
    snapshot = gym.records.snapshot(run_ids, {"outcomes_as_of": utc_now()})
    body = {"schema_version": "gymts.timesigma/experiment/1", "imported": imported,
            "evaluation_spec": spec, "initial_report": initial, "score_spec": score_spec,
            "report": final, "run_ids": run_ids, "record_snapshot_ref": snapshot["snapshot_ref"]}
    reference = gym.artifacts.save_json(body, "gymts.timesigma/experiment/1")
    return dict(body, experiment_ref=reference)


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True, help="Native GymTS CAS/SQLite store; use a local POSIX filesystem")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Import, fit, infer, attach outcomes and score one planning unit")
    for argument in ("dataset-root", "source-repo", "python", "output"):
        run.add_argument("--" + argument, required=True)
    run.add_argument("--dataset", default="TODS")
    run.add_argument("--schema", choices=("naive", "all_in_one", "zero_shot"), default="naive")
    run.add_argument("--curve-id")
    run.add_argument("--zero-shot-membership")
    run.add_argument("--method", choices=("AR", "IsolationForest"), default="IsolationForest")
    run.add_argument("--hyper-params", default="{}", help="JSON overrides resolved against the original native configuration")
    run.add_argument("--preprocess", choices=("min-max", "z-score", "raw"))
    run.add_argument("--diff-order", type=int)
    run.add_argument("--seed", type=int, default=1)
    run.add_argument("--timeout-seconds", type=int, default=300)
    inspect = commands.add_parser("inspect", help="Inspect a native Run and its trajectory")
    inspect.add_argument("run_id")
    export = commands.add_parser("export", help="Freeze a native trajectory and its complete CAS closure")
    export.add_argument("--run-id", action="append", required=True)
    export.add_argument("--output", required=True)
    restore = commands.add_parser("import-evidence", help="Import historical evidence, without fabricating new Runs")
    restore.add_argument("path")
    args = parser.parse_args(argv)
    try:
        from .trajectory import describe_run, export_evidence, import_evidence
        with GymTS(args.store, integrations=("timesigma",)) as gym:
            if args.command == "inspect":
                result = describe_run(gym, args.run_id)
            elif args.command == "export":
                result = export_evidence(gym, args.run_id, args.output)
            elif args.command == "import-evidence":
                result = import_evidence(gym, args.path)
            else:
                from .data import import_dataset
                output = Path(args.output)
                if output.exists():
                    raise GymTSError("conflict", "Pipeline output directory already exists")
                imported = import_dataset(gym, args.dataset_root, dataset=args.dataset, schema=args.schema,
                    curve_id=args.curve_id, source_repo=args.source_repo, zero_shot_membership=args.zero_shot_membership,
                    seed=1)
                params = {"source_repo": args.source_repo, "python": args.python, "method": args.method,
                    "hyper_params": json.loads(args.hyper_params), "timeout_seconds": args.timeout_seconds}
                if args.preprocess is not None:
                    params["preprocess"] = args.preprocess
                if args.diff_order is not None:
                    params["diff_order"] = args.diff_order
                result = run_experiment(gym, imported, params, execution_seed=args.seed)
                output.mkdir(parents=True)
                _write_json(output / "experiment.json", result)
                archive = export_evidence(gym, result["run_ids"], output / "evidence.zip", roots=[result["experiment_ref"]])
                _write_json(output / "archive.json", archive)
                result = {"output": str(output.resolve()), "experiment_ref": result["experiment_ref"],
                    "run_ids": result["run_ids"], "report": result["report"], "archive": archive}
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (GymTSError, ValueError, OSError) as error:
        # Core errors already redact implementation details; no credential file
        # or provider configuration is accepted by this local CPU entry point.
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
