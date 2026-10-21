"""Four real sources use the same core source, Run and persistent-dataset APIs."""
import argparse
import copy
import hashlib
from importlib import metadata
import json
from pathlib import Path
import shutil
from unittest.mock import patch
import zipfile

from gymts import GymTS
from gymts.contracts import digest, inline, utc_now
from gymts.environment_ts.datasets import EvaluationDatasets
from .live import EXPECTED_VALUE, owned_prometheus
from .sources import generate_chatts, materialize, numerical_sample, source_definition

INTEGRATIONS = ("timeseries", "libraryts", "interaction", "gymnasium", "prometheus")


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def core_identity(wheel):
    distribution = metadata.distribution("gymts")
    files = {}
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            if name.endswith("/") or name.endswith("/RECORD"):
                continue
            if not (name.startswith("gymts/") or ".dist-info/" in name):
                continue
            expected = hashlib.sha256(archive.read(name)).hexdigest()
            actual = hashlib.sha256(Path(distribution.locate_file(name)).read_bytes()).hexdigest()
            if actual != expected:
                raise RuntimeError("Installed core differs from the explicitly frozen wheel: " + name)
            files[name] = actual
    return {"wheel_sha256": hashlib.sha256(Path(wheel).read_bytes()).hexdigest(), "installed_files": files}


def experiment(evaluation, *, seed):
    case = evaluation["cases"][0]
    return {"protocol_version": "gymts.experiment/1", "name": evaluation["name"], "purpose": evaluation["purpose"],
        "scene": copy.deepcopy(case["scene"]), "candidate": copy.deepcopy(evaluation["candidates"][0]["spec"]),
        "execution": dict(copy.deepcopy(case["execution"]), seed=seed),
        "recording": copy.deepcopy(case["recording"]), "extensions": {}}


def comparison(metric):
    return {"group_by": ["evaluation_case_id"], "repetition_aggregation": "mean", "aggregation": "macro_mean",
        "baseline_method": "difference", "gates": [
            {"metric": "run_failure_rate", "target": "absolute", "candidate_ids": None,
                "for_metric": None, "operator": "le", "threshold": 0, "scope": "aggregate"},
            {"metric": "scored_coverage", "target": "absolute", "candidate_ids": None,
                "for_metric": metric, "operator": "ge", "threshold": 1, "scope": "aggregate"}]}


def score_spec(gym, kind, run_id, scoring, compare):
    run = gym.records.get_run(run_id)
    return {"protocol_version": "gymts.score/1", "name": kind + " captured output evaluation", "purpose": "acceptance",
        "runs": [{"unit_id": kind + "-unit", "evaluation_case_id": kind, "candidate_id": kind + "-baseline",
            "repetition": 0, "run_id": run_id, "unavailable_reason": None,
            "unit_spec_ref": run["resolved_spec_ref"], "tags": {"source_kind": kind}}],
        "baseline_id": None, "previous_evaluation_id": None, "scoring": scoring, "comparison": compare,
        "failure_policy": {"partial_results": "exclude", "invalid_result_policy": "report"}}


def outcome_view(gym, outcomes):
    reference = gym.artifacts.save_json(outcomes, "gymts.outcomes/1")
    return {"view_id": reference["artifact_id"], "revision": reference["revision"], "source_refs": [reference],
        "selection": inline({"kind": "all"}, "gymts.selection/1"), "as_of": None, "purpose": "evaluation"}


def numerical_case(gym, kind, values, name, horizon, recipe, implementation):
    from gymts_timeseries.contracts import NATIVE, OUTCOME
    from gymts_timeseries.experiments import scene, scoring
    public, private = numerical_sample(values, name=name, horizon=horizon)
    # Initial logical definition contains a recipe and selection, no Run CAS ref.
    environment = {"adapter": "numeric-snapshot", "version": "1.0.0", "mapping": {},
        "options": {"sample_tokens": [public["sample_token"]]}}
    dataset_id, source_id = "four-data/" + kind + "/inputs", "four-data/" + kind
    recipe = dict(recipe, public_dataset_id=dataset_id, observed_points=len(values)-horizon, horizon=horizon,
        materialization="public DatasetHandle -> independent neutral domain snapshot")
    source = gym.environment_ts.datasets.register_source(source_definition(source_id, kind,
        environment, recipe=recipe, seed=27 if kind == "synthetic" else None))
    source_ref = {key: source[key] for key in ("source_id", "config", "revision")}
    dataset = gym.environment_ts.datasets.register_snapshot([public], dataset_id=dataset_id, source_ref=source_ref,
        schema_ref=NATIVE, targets=[private], aliases=("1.0.0",))
    parent = {key: dataset[key] for key in ("dataset_id", "config", "revision")}
    parent["split"] = "test"
    # A new immutable source revision links the exact input dataset used by Run.
    source = gym.environment_ts.datasets.register_source(dict(source, revision=None, parent_datasets=[parent]))
    handle = gym.environment_ts.datasets.load_dataset(dataset_id, revision=dataset["revision"])
    snapshot_ref, revision = materialize(gym, handle)
    candidate = {"adapter": "libraryts-qa", "version": "1.0.0", "artifact": None, "inherited_state": [],
        "params": {"implementation": implementation, "estimator": "naive", "estimator_params": {"strategy": "drift"}}}
    seed = 27 if kind == "synthetic" else 19
    spec = {"protocol_version": "gymts.experiment/1", "name": name, "purpose": "acceptance",
        "scene": scene(snapshot_ref, revision, public["sample_token"], "forecast.numeric", "0.1.0"),
        "candidate": candidate, "execution": {"mode": "stream", "start": {"mode": "reinitialize"},
            "scope": {"start": 0, "end": 1}, "feedback_until": None, "seed": seed,
            "learning": {"prepare": "load_only", "online": "frozen", "training_view": None,
                "training_targets": None, "alignment_schema_ref": None, "allowed_feedback_sources": []},
            "limits": {"max_inputs": 1, "max_operations": 1, "max_turns_per_case": 1, "max_wall_time_s": 120}},
        "recording": {"store_ref": "local://records/default", "inputs": "full", "outputs": "full", "artifacts": "reference",
            "model_calls": "io", "on_capture_failure": "fail_run", "redaction_policy_ref": None, "extra_event_kinds": []},
        "extensions": {}}
    result = gym.run_data(spec, source_id=source_id, revision=source["revision"], dataset_id="four-data/"+kind+"/recorded")
    hidden = EvaluationDatasets(gym.environment_ts.datasets).load_dataset(dataset_id, revision=dataset["revision"]).read_targets()[0]
    reference = gym.artifacts.save_json({"dataset_id": dataset_id, "dataset_revision": dataset["revision"],
        "target_assets": dataset["targets"]}, "gymts.json/1")
    now = utc_now()
    outcome = {"outcome_id": kind+"-holdout", "revision": "1", "alignment_key": {
        "dataset_revision": revision, "sample_token": public["sample_token"]},
        "payload": inline({"task_id": "forecast.numeric", "task_version": "0.1.0", "expected_output": hidden["expected_output"]}, OUTCOME),
        "event_time": 0, "available_at": now, "recorded_at": now, "source_ref": reference,
        "supersedes_ref": None, "allowed_uses": ["evaluation"]}
    scoring_spec = scoring("forecast.numeric", "0.1.0", outcome_views=[outcome_view(gym, [outcome])])
    return result, score_spec(gym, kind, result["run"]["run_id"], scoring_spec, comparison("mae")), {
        "input_dataset": parent, "source": source, "native_recipe": recipe, "public_input_hash": digest(public),
        "private_target_hash": digest(private), "materialized_snapshot_ref": snapshot_ref, "public_handle_has_targets": hasattr(handle, "read_targets")}


def simulation_case(gym):
    from gymts_gymnasium import environment_spec
    from gymts_interaction.experiments import evaluation_spec
    candidate = {"adapter": "interaction-sequence", "version": "1.0.0", "artifact": None, "inherited_state": [],
        "params": {"actions": [{"action": action} for action in (2, 2, 1, 1, 1, 2)], "repeat_last": False}}
    evaluation = evaluation_spec(environment_spec("FrozenLake-v1", kwargs={"is_slippery": False}), candidate,
        scope_end=6, seeds=(19,), name="Real native FrozenLake")
    spec = experiment(evaluation, seed=19)
    source = gym.environment_ts.datasets.register_source(source_definition("four-data/simulation", "simulation",
        spec["scene"]["environment"], recipe={"environment_id": "FrozenLake-v1", "native_version": metadata.version("gymnasium"),
            "kwargs": {"is_slippery": False}}, seed=19))
    result = gym.run_data(spec, source_id=source["source_id"], revision=source["revision"], dataset_id="four-data/simulation/recorded")
    return result, score_spec(gym, "simulation", result["run"]["run_id"], evaluation["scoring"], evaluation["comparison"]), {"source": source}


def live_case(gym, binary, work):
    from gymts_prometheus.demo import evaluation_spec
    with owned_prometheus(binary, work / "owned-prometheus") as (endpoint, identity):
        evaluation = evaluation_spec(endpoint, seconds=3)
        spec = experiment(evaluation, seed=None)
        source = gym.environment_ts.datasets.register_source(source_definition("four-data/live_testbed", "live_testbed",
            spec["scene"]["environment"], recipe=identity))
        result = gym.run_data(spec, source_id=source["source_id"], revision=source["revision"], dataset_id="four-data/live_testbed/recorded")
    # The owning harness has stopped both native Prometheus and its exporter.
    run = gym.records.get_run(result["run"]["run_id"])
    rows = gym.artifacts.read_json(run["result"]["result_ref"])
    reference = gym.artifacts.save_json({"fixture": "independent declared exporter configuration", "value": EXPECTED_VALUE}, "gymts.json/1")
    now = utc_now()
    outcomes = [{"outcome_id": "fixture-"+digest(row["alignment_key"]), "revision": "1", "alignment_key": row["alignment_key"],
        "payload": inline({"value": EXPECTED_VALUE}, "gymts.builtin/forecast-outcome/1"),
        "event_time": row["alignment_key"]["target_time"], "available_at": now, "recorded_at": now,
        "source_ref": reference, "supersedes_ref": None, "allowed_uses": ["evaluation"]} for row in rows]
    scoring = copy.deepcopy(evaluation["scoring"])
    scoring["outcomes"] = {"sources": [outcome_view(gym, outcomes)], "as_of": None}
    return result, score_spec(gym, "live_testbed", result["run"]["run_id"], scoring, evaluation["comparison"]), {
        "source": source, "native_service_stopped_before_scoring": True, "native_identity": identity,
        "reference_origin": "declared exporter fixture; no causal online forecasting or quality claim"}


def resolve_all(handle, value):
    if isinstance(value, list):
        return [resolve_all(handle, item) for item in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {"dataset_asset_ref", "source_artifact_identity"}:
        return resolve_all(handle, handle.resolve_payload(value))
    return {key: resolve_all(handle, item) for key, item in value.items()}


def inspect_data(work, *, data_home=None):
    work = Path(work)
    expected = json.loads((work / "run-summary.json").read_text())
    checked = {}
    with GymTS(work / "fresh-inspection-runs", data_home=data_home or work/"data", cache_home=work/"inspection-cache", integrations=INTEGRATIONS) as gym:
        for kind, entry in expected["sources"].items():
            manifest = entry["dataset"]
            handle = gym.environment_ts.datasets.load_dataset(manifest["dataset_id"], revision=manifest["revision"], split="recorded")
            rows = [resolve_all(handle, row) for row in handle]
            capture = resolve_all(handle, handle.read_capture())
            checked[kind] = {"row_count": len(rows), "rows_hash": digest(rows), "capture_hash": digest(capture),
                "source_ref": handle.info["origin"]["source_ref"], "kind": handle.info["kind"],
                "seed_used": capture["seed_used"], "ownership": capture["ownership"], "status": capture["status"],
                "environment_end": capture["environment_end"], "event_kinds": sorted({row["kind"] for row in rows})}
            if kind in ("static", "synthetic"):
                reference = entry["details"]["input_dataset"]
                public = gym.environment_ts.datasets.load_dataset(reference["dataset_id"], revision=reference["revision"])
                rebuilt, _ = materialize(gym, public)
                checked[kind]["public_materialization_ref_identical"] = rebuilt == entry["details"]["materialized_snapshot_ref"]
                if not checked[kind]["public_materialization_ref_identical"]:
                    raise AssertionError("Public dataset changed when reconstructed without original Run CAS")
    return {"status": "passed", "source_run_store_required": False, "sources": checked}


def rescore(work, wheel):
    work = Path(work)
    before_core = core_identity(wheel)
    summary = json.loads((work / "run-summary.json").read_text())
    reports = {}
    with GymTS(work / "runs", data_home=work/"data", cache_home=work/"rescore-cache", integrations=INTEGRATIONS) as gym:
        for kind, entry in summary["sources"].items():
            run_id = entry["run"]["run_id"]
            before = digest(gym.records.get_run(run_id))
            fixed = json.loads((work/(kind+"-score-spec.json")).read_text())
            fixed["previous_evaluation_id"] = entry["evaluation"]["evaluation_id"]
            with patch.object(gym.environment_ts, "run", side_effect=AssertionError("Re-scoring executed an experiment")), \
                    patch.object(gym.registries.candidates, "create", side_effect=AssertionError("Re-scoring constructed a model")), \
                    patch.object(gym.registries.environments, "create", side_effect=AssertionError("Re-scoring constructed a source")):
                report = gym.autobench.score(fixed)
            if report["metrics"] != entry["evaluation"]["metrics"] or report["coverage"] != entry["evaluation"]["coverage"]:
                raise AssertionError("Fixed-output re-scoring changed metrics or coverage")
            if digest(gym.records.get_run(run_id)) != before:
                raise AssertionError("Re-scoring changed the sealed Run")
            reports[kind] = {"report": report, "sealed_run_unchanged": True, "backends_forbidden": True}
    if core_identity(wheel) != before_core:
        raise AssertionError("Frozen core changed during independent re-scoring")
    result = {"status": "passed", "reports": reports, "core": before_core}
    write(work/"rescore-summary.json", result)
    return result


def run(args):
    from gymts_libraryts.tools import LibraryTSTools
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=False)
    frozen = core_identity(args.core_wheel)
    implementation = {"repository": args.libraryts_repository, "python": args.libraryts_python,
        "revision": "080f4c3c3695f239e328548bac7d7a3ef7aa9127"}
    entries = {}
    with GymTS(work/"runs", data_home=work/"data", cache_home=work/"cache", integrations=INTEGRATIONS) as gym:
        raw = LibraryTSTools(gym.artifacts, implementation).call("dataset.load", {"dataset": "airline"})["output"]
        result, score, details = numerical_case(gym, "static", raw["values"], "AirPassengers", 12,
            {"dataset": "airline", "native_provenance": raw["provenance"]}, implementation)
        entries["static"] = {**result, "score": score, "details": details}
        values, generator = generate_chatts(args.chatts_repository, args.chatts_python, work/"chatts-generator.stderr.log")
        result, score, details = numerical_case(gym, "synthetic", values, "ChatTS", 8, generator, implementation)
        entries["synthetic"] = {**result, "score": score, "details": details}
        for kind, case in (("simulation", lambda: simulation_case(gym)),
                           ("live_testbed", lambda: live_case(gym, args.prometheus_binary, work))):
            result, score, details = case()
            entries[kind] = {**result, "score": score, "details": details}
        for kind, entry in entries.items():
            if entry["run"]["status"] != "succeeded":
                raise RuntimeError(kind + " Run failed; sealed evidence is retained")
            report = gym.autobench.score(entry.pop("score"))
            # Save a new spec with the same immutable outcome views for later re-scoring.
            # The committed plan is the authoritative exact scoring specification.
            plan = gym.artifacts.read_json(report["plan_ref"])
            fixed = gym.artifacts.read_json(plan["spec_ref"])
            write(work/(kind+"-score-spec.json"), fixed)
            if report["verdict"] != "pass":
                raise RuntimeError(kind + " did not cover every intended score")
            record = gym.records.get_run(entry["run"]["run_id"])
            entry.update(evaluation=report, trace_ref=record["execution_snapshot_ref"],
                sealed_result_ref=record["result_ref"], sealed_run_hash=digest(record))
        summary = {"status": "passed", "scope": "CPU source/data organization engineering acceptance, no model-quality claim",
            "sources": entries, "core_before": frozen, "core_after": core_identity(args.core_wheel),
            "data_home": str((work/"data").resolve()), "run_root": str((work/"runs").resolve())}
        write(work/"run-summary.json", summary)
    if summary["core_before"] != summary["core_after"]:
        raise AssertionError("Frozen core changed")
    # Copy only the persistent ResourceStore, then remove access to original Run CAS.
    portable_home = work/"portable-data-copy"
    shutil.copytree(work/"data", portable_home)
    hidden = work/"runs-unavailable-during-portability"
    (work/"runs").rename(hidden)
    try:
        portable = inspect_data(work, data_home=portable_home)
    finally:
        hidden.rename(work/"runs")
    write(work/"portable-read-summary.json", portable)
    return {"status": "passed", "work": str(work), "run_ids": {key: value["run"]["run_id"] for key,value in entries.items()}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    execute = commands.add_parser("run")
    for name in ("work", "core-wheel", "libraryts-repository", "libraryts-python", "chatts-repository", "chatts-python", "prometheus-binary"):
        execute.add_argument("--"+name, required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--work", required=True)
    inspect.add_argument("--data-home")
    scoring = commands.add_parser("rescore")
    scoring.add_argument("--work", required=True)
    scoring.add_argument("--core-wheel", required=True)
    args = parser.parse_args(argv)
    if args.command == "run": result = run(args)
    elif args.command == "inspect": result = inspect_data(args.work, data_home=args.data_home)
    else: result = rescore(args.work, args.core_wheel)
    print(json.dumps({key:value for key,value in result.items() if key in ("status", "work", "run_ids")}))


if __name__ == "__main__":
    main()
