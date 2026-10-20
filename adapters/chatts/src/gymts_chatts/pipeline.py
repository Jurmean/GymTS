"""Generate/import ChatTS data, export SFT, execute QA, attach labels, and rescore.

Run: python -m gymts_chatts.pipeline --help
The default Candidate is an explicitly identified signal algorithm baseline.
"""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

from gymts import GymTS, GymTSError
from gymts.contracts import canonical_json, digest, inline, utc_now


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def implementation_identity():
    from gymts import __version__
    from . import __version__ as adapter_version
    package = Path(__file__).resolve().parent
    files = {str(path.relative_to(package)): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(package.rglob("*.py"))}
    return {"gymts_version": __version__, "adapter_distribution": "gymts-chatts",
            "adapter_version": adapter_version, "code_files_sha256": files,
            "code_tree_digest": digest(files)}


def execution(seed=7, timeout=150):
    return {"mode": "stream", "start": {"mode": "reinitialize"}, "scope": {"start": 0, "end": 1},
        "feedback_until": None, "seed": seed,
        "learning": {"prepare": "load_only", "online": "frozen", "training_view": None,
            "training_targets": None, "alignment_schema_ref": None, "allowed_feedback_sources": []},
        "limits": {"max_inputs": None, "max_operations": None, "max_turns_per_case": 1, "max_wall_time_s": timeout}}


def recording():
    return {"store_ref": "local://records/default", "inputs": "full", "outputs": "full", "artifacts": "reference",
        "model_calls": "none", "on_capture_failure": "fail_run", "redaction_policy_ref": None, "extra_event_kinds": []}


def scene(snapshot_ref, dataset_revision, row):
    return {"environment": {"protocol_version": "gymts.environment/1", "adapter": "chatts-synthetic-snapshot",
        "version": "1.0.0", "source": {"kind": "dataset", "locator": "artifact://chatts-public-snapshot",
            "revision": dataset_revision, "connection": {"artifact_refs": [snapshot_ref]}, "credential_ref": None},
        "mapping": {}, "options": {"sample_tokens": [row["sample_token"]]}},
        "task": {"plugin": "chatts-synthetic-qa", "version": "1.0.0",
            "params": {"task_id": row["task_id"], "task_version": row["task_version"]}},
        "binding": {"variables": {"sample": {"source": "sample", "unit": "sample", "transform": None}}, "operations": {}}}


def baseline(task_id, *, neutral=False):
    return {"candidate_id": "signal-baseline", "spec": {"adapter": "timeseries-signal-baseline" if neutral else "chatts-signal-baseline", "version": "1.0.0",
        "artifact": None, "params": {"task_id": task_id}, "inherited_state": []}}


def evaluation_spec(gym, imported, public_rows, samples, task_id, candidates, seed=7, repetitions=1, *, neutral=False):
    if neutral:
        from gymts_timeseries.task import TASK_METRICS
        from gymts_timeseries.contracts import SNAPSHOT, ALIGNMENT
        from gymts_timeseries.experiments import scene as numeric_scene
    else:
        from .task import TASK_METRICS
        SNAPSHOT, ALIGNMENT = "gymts.chatts.snapshot/1", "gymts.chatts/alignment/1"
    task_version = samples[0]["task_version"]
    cases = []
    timeout = max([150] + [item["spec"]["params"].get("timeout_seconds", 120) + 30 for item in candidates])
    for row in samples:
        # A per-sample public artifact avoids repeatedly loading the full dataset
        # and gives the Environment exactly one planned sample.
        snapshot = {"schema_version": SNAPSHOT, "dataset_revision": imported["dataset_revision"],
                    "samples": [public_rows[row["sample_token"]]]}
        ref = gym.artifacts.save_json(snapshot, SNAPSHOT)
        selected_scene = (numeric_scene(ref, imported["dataset_revision"], row["sample_token"], task_id, task_version)
                          if neutral else scene(ref, imported["dataset_revision"], row))
        cases.append({"evaluation_case_id": row["sample_token"], "scene": selected_scene,
            "execution": execution(seed, timeout), "recording": recording(), "tags": {"task_id": task_id}})
    metrics = list(TASK_METRICS[task_id])
    return {"protocol_version": "gymts.evaluation/1", "name": "ChatTS synthetic " + task_id, "purpose": "development",
        "cases": cases, "candidates": candidates,
        "baseline_id": "signal-baseline" if any(c["candidate_id"] == "signal-baseline" for c in candidates) else None,
        "repetitions": {"count": repetitions, "seeds": [seed + i for i in range(repetitions)]},
        "scoring": {"scorer": {"adapter": "timeseries-qa-scorer" if neutral else "chatts-qa-scorer", "version": "1.0.0",
            "params": {"task_id": task_id, "task_version": task_version}},
            "outcomes": {"sources": [], "as_of": None},
            "alignment": {"schema_ref": ALIGNMENT, "keys": ["dataset_revision", "sample_token"],
                "matching": "exact", "params": {}, "duplicate_policy": "error"},
            "metrics": metrics, "evidence_requirements": {"min_scored": 1, "min_coverage": 1, "overrides": {}},
            "missing_outcome_policy": "report_insufficient"},
        "comparison": {"group_by": ["evaluation_case_id"], "repetition_aggregation": "mean", "aggregation": "macro_mean",
            "baseline_method": "difference", "gates": [
                {"metric": "run_failure_rate", "target": "absolute", "candidate_ids": [c["candidate_id"] for c in candidates], "for_metric": None,
                    "operator": "le", "threshold": 0, "scope": "aggregate"},
                {"metric": "scored_coverage", "target": "absolute", "candidate_ids": [c["candidate_id"] for c in candidates], "for_metric": metrics[0],
                    "operator": "ge", "threshold": 1, "scope": "aggregate"}]},
        "failure_policy": {"partial_results": "include", "invalid_result_policy": "report"}}


def attach_and_rescore(gym, imported, spec, report):
    """Append gold after inference, preserving the original sealed RunResult."""
    outcome_schema = ("gymts.timeseries/qa-outcome/1" if spec["scoring"]["alignment"]["schema_ref"] == "gymts.timeseries/qa-alignment/1" else "gymts.chatts/outcome/1")
    plan = gym.artifacts.read_json(report["plan_ref"])
    manifest = gym.artifacts.read_json(report["run_manifest_ref"])
    units = {unit["unit_id"]: unit for unit in plan["expected_units"]}
    rows = {row["sample_token"]: row for row in imported["samples"]}
    before, selections, run_ids, drafts = {}, [], [], {}
    for entry in manifest["entries"]:
        unit = units[entry["unit_id"]]
        run_id = entry["run_id"]
        if run_id:
            before[run_id] = digest(gym.records.get_run(run_id)["result"])
            row = rows[unit["evaluation_case_id"]]
            outcome = drafts.get(row["sample_token"])
            if outcome is None:
                outcome = {"outcome_id": "chatts-gold-" + row["sample_token"], "revision": "1",
                "alignment_key": row["alignment_key"],
                "payload": inline({"task_id": row["task_id"], "task_version": row["task_version"],
                    "expected_output": row["expected_output"]}, outcome_schema),
                "event_time": 0, "available_at": utc_now(), "recorded_at": None,
                    "source_ref": imported["private_ref"], "supersedes_ref": None, "allowed_uses": ["evaluation"]}
                drafts[row["sample_token"]] = outcome
            gym.records.attach_outcomes(run_id, [outcome])
            run_ids.append(run_id)
        selections.append({"unit_id": unit["unit_id"], "evaluation_case_id": unit["evaluation_case_id"],
            "candidate_id": unit["candidate_id"], "repetition": unit["repetition"], "run_id": run_id,
            "unavailable_reason": None if run_id else "planned_run_unavailable", "unit_spec_ref": unit["resolved_spec_ref"],
            "tags": copy.deepcopy(unit.get("tags", {}))})
    cutoff = utc_now()
    labels = gym.records.read_outcomes({"run_ids": run_ids, "outcomes_as_of": cutoff, "purpose": "evaluation"})
    ref = gym.artifacts.save_json(labels, "gymts.outcome-records/1")
    view = {"view_id": "chatts-evaluation-" + ref["artifact_id"], "revision": ref["revision"], "source_refs": [ref],
        "selection": inline({"kind": "all", "source_index": 0}, "gymts.selection/1"), "as_of": None, "purpose": "evaluation"}
    scoring = copy.deepcopy(spec["scoring"])
    scoring["outcomes"] = {"sources": [view], "as_of": cutoff}
    score_spec = {"protocol_version": "gymts.score/1", "name": spec["name"] + " fixed outputs", "purpose": "development",
        "runs": selections, "previous_evaluation_id": report["evaluation_id"], "baseline_id": spec["baseline_id"],
        "scoring": scoring, "comparison": copy.deepcopy(spec["comparison"]), "failure_policy": copy.deepcopy(spec["failure_policy"])}
    rescored = gym.autobench.score(score_spec)
    after = gym.artifacts.read_json(rescored["run_manifest_ref"])
    unchanged = ([entry["run_id"] for entry in after["entries"]] == [entry["run_id"] for entry in manifest["entries"]]
        and all(digest(gym.records.get_run(run_id)["result"]) == value for run_id, value in before.items()))
    if not unchanged:
        raise GymTSError("conflict", "Rescoring changed sealed execution evidence")
    return rescored, score_spec, run_ids


def export_trajectories(gym, reports, output_dir, *, neutral=False):
    """Build a lossless QA IO dataset from a fixed RecordSnapshot, with no tokens invented."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    runs = []
    identities = {}
    for task_id, report in reports.items():
        units = {u["unit_id"]: u for u in gym.artifacts.read_json(report["plan_ref"])["expected_units"]}
        for entry in gym.artifacts.read_json(report["run_manifest_ref"])["entries"]:
            if entry["run_id"]:
                runs.append(entry["run_id"])
                identities[entry["run_id"]] = {"task_id": task_id, "candidate_id": units[entry["unit_id"]]["candidate_id"]}
    snapshot = gym.records.snapshot(runs, {"through_seq": None, "outcomes_as_of": utc_now(), "outcome_refs": None})
    # Read the frozen execution artifacts, rather than a live inference queue.
    frozen = gym.artifacts.read_json(snapshot["snapshot_ref"])
    path = output_dir / "qa_trajectories.jsonl"
    count = 0
    with path.open("wb") as stream:
        for frozen_run in frozen["runs"]:
            run_id = frozen_run["run_id"]
            if frozen_run["result_ref"] is None:
                continue
            run_result = gym.artifacts.read_json(frozen_run["result_ref"])
            events = gym.artifacts.read_json(run_result["trace_ref"])
            events = events["events"] if isinstance(events, dict) else events
            events = [event for event in events if event.get("seq", 0) <= frozen_run["through_seq"]]
            inputs, outputs, results = {}, {}, {}
            for event in events:
                body = event["payload"]
                value = body["value"] if body["storage"] == "inline" else gym.artifacts.read_json(body["artifact_ref"])
                if event["kind"] == "input":
                    inputs[value["input_id"]] = value
                elif event["kind"] == "candidate_output":
                    outputs[value["input_id"]] = value
                elif event["kind"] == "task_result":
                    results[value["input_id"]] = value
            for input_id, value in inputs.items():
                stream.write(canonical_json({"schema_version": "gymts.timeseries.qa-trajectory/1" if neutral else "gymts.chatts.qa-trajectory/1", "run_id": run_id,
                    **identities[run_id], "input": value, "output": outputs.get(input_id), "result": results.get(input_id),
                    "record_snapshot_ref": snapshot["snapshot_ref"], "run_result_ref": frozen_run["result_ref"],
                    "capture": {"native_timeseries": True, "raw_text": input_id in outputs,
                        "token_ids": False, "logprobs": False, "training_eligibility": "not_assessed"}}) + b"\n")
                count += 1
    metadata = {"builder": "gymts.chatts.qa-trajectories/1.0.0", "record_snapshot_ref": snapshot["snapshot_ref"],
        "run_count": len(runs), "row_count": count,
        "path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "purpose": "qa_io_analysis", "native_rollout": False,
        "missing_fields": ["token_ids", "logprobs", "response_mask"], "training_eligibility": "not_assessed"}
    write_json(output_dir / "manifest.json", metadata)
    return metadata


def run_pipeline(output_dir, *, source_repo=None, profile_dirs=(), python=None, profiles=("native", "classical"),
                 candidate_entries=(), include_baseline=True, evaluation_split="eval", eval_fraction=0.2,
                 seed=7, repetitions=1, max_per_task=None, tasks=None, progress=None, legacy=False):
    from .data import generate_profiles
    if legacy:
        from .data import import_profiles, export_sft
    else:
        from .neutral_data import import_profiles
        from .supervision import export_sft
    output_dir = Path(output_dir).resolve()
    if output_dir.exists():
        raise GymTSError("conflict", "Pipeline output directory already exists; choose a new experiment directory")
    if repetitions < 1 or max_per_task is not None and max_per_task < 1:
        raise GymTSError("invalid_config", "Repetitions and sample limits must be positive")
    output_dir.mkdir(parents=True)
    progress = progress or (lambda value: None)
    progress("generate_or_import")
    dirs = list(profile_dirs)
    if not dirs:
        if source_repo is None:
            raise GymTSError("invalid_config", "Provide --source-repo or --profile-dir")
        dirs = generate_profiles(source_repo, output_dir / "source_profiles", python=python, profiles=profiles)
    with GymTS(root=output_dir / "records", integrations=("chatts",)) as gym:
        implementation_ref = gym.artifacts.save_json(implementation_identity(), "gymts.chatts.implementation/1")
        imported = import_profiles(gym, dirs, source_repo=source_repo)
        write_json(output_dir / "import.json", {key: value for key, value in imported.items() if key != "samples"})
        exported = export_sft(gym, imported, output_dir / "datasets" / "synthetic_sft", eval_fraction=eval_fraction, seed=seed)
        write_json(output_dir / "datasets" / "export.json", exported)
        if evaluation_split not in ("all", "eval", "train"):
            raise GymTSError("invalid_config", "Unknown evaluation split")
        selected_tokens = None if evaluation_split == "all" else set(exported[evaluation_split + "_sample_tokens"])
        samples = [row for row in imported["samples"] if selected_tokens is None or row["sample_token"] in selected_tokens]
        if tasks:
            samples = [row for row in samples if row["task_id"] in tasks]
        task_ids = sorted({row["task_id"] for row in samples})
        if not task_ids:
            raise GymTSError("invalid_config", "No samples selected for evaluation")
        public = gym.artifacts.read_json(imported["snapshot_ref"])
        public_rows = {row["sample_token"]: row for row in public["samples"]}
        reports, brief = {}, {}
        for task_id in task_ids:
            selected = [row for row in samples if row["task_id"] == task_id]
            if max_per_task:
                selected = selected[:max_per_task]
            candidates = copy.deepcopy(list(candidate_entries))
            if include_baseline:
                candidates.append(baseline(task_id, neutral=not legacy))
            if not candidates:
                raise GymTSError("invalid_config", "At least one Candidate is required")
            spec = evaluation_spec(gym, imported, public_rows, selected, task_id, candidates, seed, repetitions, neutral=not legacy)
            stem = task_id.replace(".", "_")
            write_json(output_dir / "configs" / (stem + ".evaluation.json"), spec)
            progress("evaluate " + task_id + " (" + str(len(selected)) + " samples)")
            initial = gym.autobench.evaluate(spec)
            write_json(output_dir / "reports" / (stem + ".before_labels.json"), initial)
            progress("attach_outcomes_and_rescore " + task_id)
            report, score_spec, run_ids = attach_and_rescore(gym, imported, spec, initial)
            write_json(output_dir / "configs" / (stem + ".score.json"), score_spec)
            write_json(output_dir / "reports" / (stem + ".json"), report)
            reports[task_id] = report
            brief[task_id] = {"sample_count": len(selected), "coverage": report["coverage"],
                "status": report["status"], "integration_verdict": report["verdict"],
                "same_run_ids": True, "sealed_results_unchanged": True,
                "metrics": [{"candidate_id": item["candidate_id"], "metric_id": item["metric_id"], **item["result"]}
                            for item in report["metrics"] if item["level"] == "aggregate"],
                "report_path": str((output_dir / "reports" / (stem + ".json")).resolve())}
            if not legacy:
                brief[task_id]["prompt_policy"] = copy.deepcopy(imported["prompt_policy"])
        progress("export_fixed_trajectories")
        trajectories = export_trajectories(gym, reports, output_dir / "datasets" / "trajectories", neutral=not legacy)
        summary = {"schema_version": "gymts.chatts.pipeline/1", "created_at": utc_now(),
            "implementation_ref": implementation_ref, "task_protocol_ref": "gymts.task/chatts-qa/1" if legacy else "gymts.task/timeseries-qa/1",
            "dataset_revision": imported["dataset_revision"], "source_samples": len(imported["samples"]),
            "evaluation_split": evaluation_split, "seed": seed, "repetitions": repetitions,
            "synthetic_sft": exported, "trajectories": trajectories, "tasks": brief,
            "http_candidate_requested": any(item["spec"]["adapter"] in ("chatts-http", "chatts-text-http", "timeseries-chatts-http", "timeseries-text-http") for item in candidate_entries),
            "candidate_adapters": {item["candidate_id"]: item["spec"]["adapter"] for item in candidate_entries},
            "formal_benchmark": False, "acceptance_basis": "execution_failure_rate_and_parse_score_coverage_only",
            "model_calls_capture": "none; QA request/response evidence is in CandidateOutput artifacts",
            "output_dir": str(output_dir), "records_root": str((output_dir / "records").resolve()),
            "status": "completed" if all(item["status"] == "completed" and item["integration_verdict"] == "pass"
                                          for item in brief.values()) else "failed"}
        if not legacy:
            summary["prompt_policy"] = copy.deepcopy(imported["prompt_policy"])
        write_json(output_dir / "summary.json", summary)
        return summary


def run_legacy_pipeline(output_dir, **kwargs):
    """Explicit historical ChatTS /1 path, including its original source checks."""
    return run_pipeline(output_dir, legacy=True, **kwargs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New output directory (contains records, datasets, configs and reports)")
    parser.add_argument("--source-repo", help="Local ChatTS-Bench-new checkout")
    parser.add_argument("--python", help="Existing generator Python environment")
    parser.add_argument("--profile-dir", action="append", default=[], help="Import a validated generated profile instead of generating")
    parser.add_argument("--profiles", nargs="+", choices=["native", "classical"], default=["native", "classical"])
    parser.add_argument("--candidate-config", help="JSON list of {candidate_id,spec}, or a single such entry")
    parser.add_argument("--no-baseline", action="store_true")
    parser.add_argument("--legacy", action="store_true", help="Use historical ChatTS /1 inputs and component IDs")
    parser.add_argument("--evaluation-split", choices=["eval", "train", "all"], default="eval")
    parser.add_argument("--eval-fraction", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--max-per-task", type=int, help="Limit evaluation samples per task for smoke runs")
    parser.add_argument("--tasks", nargs="+")
    args = parser.parse_args(argv)
    try:
        entries = []
        if args.candidate_config:
            entries = json.loads(Path(args.candidate_config).read_text(encoding="utf-8"))
            entries = entries if isinstance(entries, list) else [entries]
        value = run_pipeline(args.output, source_repo=args.source_repo, profile_dirs=args.profile_dir,
            python=args.python, profiles=args.profiles, candidate_entries=entries, include_baseline=not args.no_baseline,
            evaluation_split=args.evaluation_split, eval_fraction=args.eval_fraction, seed=args.seed,
            repetitions=args.repetitions, max_per_task=args.max_per_task, tasks=args.tasks, legacy=args.legacy,
            progress=lambda message: print(message, file=sys.stderr, flush=True))
        print(json.dumps({"status": value["status"], "source_samples": value["source_samples"],
            "http_candidate_requested": value["http_candidate_requested"],
            "summary": str(Path(args.output).resolve() / "summary.json")}, ensure_ascii=False, indent=2))
        return 0 if value["status"] == "completed" else 1
    except (GymTSError, ValueError, OSError, KeyError, TypeError) as error:
        info = error.info if isinstance(error, GymTSError) else {"code": "pipeline_failure", "message": type(error).__name__}
        print(json.dumps({"error": info}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
