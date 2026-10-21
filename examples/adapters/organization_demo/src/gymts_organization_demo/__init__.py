"""ETT CSV import and domain projection; organization stays in GymTS."""
import csv
from datetime import datetime, timedelta
import io

from gymts.contracts import digest, inline, utc_now
from gymts.environment_ts.datasets import EvaluationDatasets

VERSION = "1.0.0"
IMPORT = {"name": "example.ett-csv-import", "version": VERSION, "origin_ref": None}
EVALUATE = {"name": "example.ett-rolling-evaluate", "version": VERSION, "origin_ref": None}
REFERENCES = {"name": "example.ett-independent-references", "version": VERSION, "origin_ref": None}
POLICY = {"allowed_uses": ["runtime", "evaluation", "prepare"], "training_allowed": False}
ENTITY = "ETTh1-OT"


def import_csv(spec, gym):
    """Convert the upstream wide CSV into a core-owned immutable public dataset."""
    raw = gym.artifacts.resolve(spec["raw_ref"]).read_bytes()
    selected = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    rows = [{"timestamp": row["date"].replace(" ", "T") + "Z", "value": float(row[spec["column"]])} for row in selected]
    source = gym.environment_ts.datasets.register_source({"protocol_version": "gymts.data-source/1",
        "source_id": "example/ett-wide-csv", "config": "default", "revision": None, "kind": "static",
        "provider_ref": {"name": "local-timeseries-replay", "version": "1.0.0", "origin_ref": None},
        "configuration": {"format": "ETT-wide-CSV", "column": spec["column"], "origin": spec["origin"],
            "selected_csv_sha256": spec["raw_ref"]["content_hash"],
            "time_projection": "Naive upstream hours replayed on a UTC coordinate; original timezone unspecified"},
        "recipe": None, "reproducibility": {"mode": "snapshot", "seed": None},
        "usage_policy": POLICY, "parent_datasets": [], "card_ref": None})
    source_ref = {key: source[key] for key in ("source_id", "config", "revision")}
    dataset = gym.environment_ts.datasets.register_snapshot(rows, dataset_id="example/ett-hourly-view",
        source_ref=source_ref, targets=[{"timestamp": row["timestamp"], "answer": row["value"]} for row in rows],
        split="evaluation", features={"column": spec["column"], "native_unit": "degC", "evaluation": "rolling one-hour-ahead", "timezone": "unspecified upstream"})
    return {"dataset": {key: dataset[key] for key in ("dataset_id", "config", "revision")} | {"split": "evaluation"},
            "source": source_ref, "row_count": len(rows)}


def scoring():
    return {"scorer": {"adapter": "forecast-mae", "version": "1.0.0", "params": {}},
        "outcomes": {"sources": [], "as_of": None}, "alignment": {"schema_ref": "gymts.builtin/forecast-alignment/1",
            "keys": ["entity", "variable", "issued_at", "target_time"], "matching": "exact", "params": {}, "duplicate_policy": "error"},
        "metrics": ["mae"], "evidence_requirements": {"min_scored": 1, "min_coverage": 1, "overrides": {}},
        "missing_outcome_policy": "report_insufficient"}


def comparison():
    return {"group_by": ["evaluation_case_id"], "repetition_aggregation": "mean", "aggregation": "macro_mean",
            "baseline_method": "difference", "gates": []}


def evaluate_public(spec, gym):
    """Only public observations are projected to the existing replay/task/models."""
    rows = list(gym.environment_ts.datasets.load_dataset(**spec["dataset"], purpose="runtime"))
    scene = {"environment": {"protocol_version": "gymts.environment/1", "adapter": "local-timeseries-replay", "version": "1.0.0",
        "source": {"kind": "dataset", "locator": "dataset://example/ett-hourly-view", "revision": spec["dataset"]["revision"],
            "connection": {"points": [{"timestamp": row["timestamp"], "values": {"value": row["value"]}} for row in rows]}, "credential_ref": None},
        "mapping": {"variables": {"value": {"field": "value", "dtype": "float64", "unit": "value"}}},
        "options": {"availability": "event_time", "entity": ENTITY}},
        "task": {"plugin": "window_forecast", "version": "1.0.0", "params": {"variable": "value", "unit": "value", "entity": ENTITY,
            "window_points": 3, "horizon": "1h", "advance_by": "1h", "warmup_duration": None}},
        "binding": {"variables": {"value": {"source": "value", "unit": "value", "transform": None}}, "operations": {}}}
    case = {"evaluation_case_id": "ett-rolling", "scene": scene, "execution": {"mode": "stream",
        "start": {"mode": "reinitialize"}, "scope": {"start": rows[0]["timestamp"], "end": rows[-1]["timestamp"]},
        "feedback_until": None, "seed": 7, "learning": {"prepare": "load_only", "online": "frozen", "training_view": None,
            "training_targets": None, "alignment_schema_ref": None, "allowed_feedback_sources": []},
        "limits": {"max_inputs": len(rows), "max_operations": None, "max_turns_per_case": 1, "max_wall_time_s": 30}},
        "recording": {"store_ref": "local://records/default", "inputs": "full", "outputs": "full", "artifacts": "reference",
            "model_calls": "none", "on_capture_failure": "fail_run", "redaction_policy_ref": None, "extra_event_kinds": []},
        "tags": {"source": "public ETTh1", "column": "OT", "time_projection": "declared UTC coordinate"}}
    candidates = [{"candidate_id": name, "spec": {"adapter": name, "version": "1.0.0", "artifact": None,
        "inherited_state": [], "params": {}}} for name in ("last-value", "window-mean")]
    return gym.autobench.evaluate({"protocol_version": "gymts.evaluation/1", "name": "ETTh1 rolling observations",
        "purpose": "regression", "cases": [case], "candidates": candidates, "baseline_id": "window-mean",
        "repetitions": {"count": 1, "seeds": [7]}, "scoring": scoring(), "comparison": comparison(),
        "failure_policy": {"partial_results": "include", "invalid_result_policy": "report"}})


def independent_references(spec, gym):
    """Create evaluation-only outcomes from registered targets after Runs seal."""
    dataset = EvaluationDatasets(gym.environment_ts.datasets).load_dataset(**spec["dataset"])
    rows, targets = list(dataset), dataset.read_targets()
    target_map = {row["timestamp"]: row["answer"] for row in targets}
    private_ref = gym.artifacts.save_json(targets, "gymts.json/1")
    now, outcomes = utc_now(), []
    for row in rows[2:-1]:
        future = (datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        key = {"entity": ENTITY, "variable": "value", "issued_at": row["timestamp"], "target_time": future}
        outcomes.append({"outcome_id": "ett-" + digest(key), "revision": "1", "alignment_key": key,
            "payload": inline({"value": target_map[future]}, "gymts.builtin/forecast-outcome/1"), "event_time": future,
            "available_at": now, "recorded_at": now, "source_ref": private_ref, "supersedes_ref": None, "allowed_uses": ["evaluation"]})
    outcome_ref = gym.artifacts.save_json(outcomes, "gymts.outcome-records/1")
    outcome_view = {"view_id": "ett-private-" + outcome_ref["revision"], "revision": outcome_ref["revision"],
        "source_refs": [outcome_ref], "selection": inline({"kind": "all", "source_index": 0}, "gymts.selection/1"), "as_of": None, "purpose": "evaluation"}
    report = spec["report"]
    plan, manifest = gym.artifacts.read_json(report["plan_ref"]), gym.artifacts.read_json(report["run_manifest_ref"])
    by_unit = {entry["unit_id"]: entry for entry in manifest["entries"]}
    runs = [{"unit_id": unit["unit_id"], "evaluation_case_id": unit["evaluation_case_id"], "candidate_id": unit["candidate_id"],
        "repetition": unit["repetition"], "run_id": by_unit[unit["unit_id"]]["run_id"], "unavailable_reason": None,
        "unit_spec_ref": unit["resolved_spec_ref"]} for unit in plan["expected_units"]]
    values = [row["value"] for row in rows]
    expected = {"last-value": sum(abs(values[i] - values[i+1]) for i in range(2, len(values)-1)) / (len(values)-3),
        "window-mean": sum(abs(sum(values[i-2:i+1])/3 - values[i+1]) for i in range(2, len(values)-1)) / (len(values)-3)}
    return {"runs": runs, "outcomes": {"sources": [outcome_view], "as_of": None},
            "previous_evaluation_id": report["evaluation_id"], "expected_mae": expected, "expected_count": len(outcomes)}


def register(gym):
    """Explicit executor registration; no import hooks or core patching."""
    for ref, executor in ((IMPORT, import_csv), (EVALUATE, evaluate_public), (REFERENCES, independent_references)):
        gym.experiments.register_executor(ref, executor)


def group_definition(raw_ref, origin):
    upstream = lambda stage_id, output: {"kind": "stage_output", "stage_id": stage_id, "output": output}
    return {"group_id": "example/ett-organized", "name": "ETTh1 CSV to immutable data, rolling Runs and independent score", "stages": [
        {"stage_id": "import", "executor_ref": IMPORT, "purpose": "prepare", "spec": {"raw_ref": None, "column": "OT", "origin": origin},
            "inputs": {"raw": {"kind": "artifact", "ref": raw_ref}}, "bindings": {"raw": "/raw_ref"}, "outputs": {"dataset": "/dataset"}},
        {"stage_id": "execute", "executor_ref": EVALUATE, "spec": {"dataset": None}, "inputs": {"data": upstream("import", "dataset")},
            "bindings": {"data": "/dataset"}, "outputs": {"report": ""}},
        {"stage_id": "references", "executor_ref": REFERENCES, "purpose": "evaluation", "spec": {"dataset": None, "report": None},
            "inputs": {"data": upstream("import", "dataset"), "report": upstream("execute", "report")},
            "bindings": {"data": "/dataset", "report": "/report"},
            "outputs": {"runs": "/runs", "outcomes": "/outcomes", "previous": "/previous_evaluation_id"}},
        {"stage_id": "score", "executor_ref": {"name": "gymts.score", "version": "1.0.0", "origin_ref": None}, "purpose": "evaluation",
            "spec": {"protocol_version": "gymts.score/1", "name": "Independent ETTh1 rolling score", "purpose": "regression", "runs": [],
                "baseline_id": "window-mean", "scoring": scoring(), "comparison": comparison(),
                "failure_policy": {"partial_results": "include", "invalid_result_policy": "report"}, "previous_evaluation_id": None},
            "inputs": {"data": upstream("import", "dataset"), "runs": upstream("references", "runs"),
                "outcomes": upstream("references", "outcomes"), "previous": upstream("references", "previous")},
            "bindings": {"runs": "/runs", "outcomes": "/scoring/outcomes", "previous": "/previous_evaluation_id"}, "outputs": {"report": ""}}]}
