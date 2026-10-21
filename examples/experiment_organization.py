"""Store data, execute dependent stages, record and independently rescore.

Run from the source tree: python examples/experiment_organization.py --work /tmp/gymts-organization-demo
The two small executors below illustrate adapter responsibilities; GymTS owns
data identities, dependencies, attempts, evidence and the evaluation protocol.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gymts import GymTS
from gymts.contracts import digest, utc_now

HERE = Path(__file__).resolve().parent


def component(name):
    return {"name": name, "version": "1.0.0", "origin_ref": None}


def forecast_from_catalog(spec, gym):
    """A format projection: public dataset rows become native replay points."""
    reference = spec["dataset"]
    rows = gym.environment_ts.datasets.load_dataset(reference["dataset_id"], config=reference["config"],
        revision=reference["revision"], split=reference["split"], purpose="runtime")
    experiment = deepcopy(spec["experiment"])
    environment = experiment["scene"]["environment"]
    environment["source"].update(kind="dataset", locator=reference["dataset_id"], revision=reference["revision"],
        connection={"points": [{key: row[key] for key in ("timestamp", "entity", "values")} for row in rows]})
    return gym.run(experiment)


def observed_outcomes(spec, gym):
    """Create evaluation references from observations, without reading predictions."""
    ref = spec["dataset"]
    rows = list(gym.environment_ts.datasets.load_dataset(ref["dataset_id"], config=ref["config"],
        revision=ref["revision"], split=ref["split"], purpose="evaluation"))
    truth = gym.artifacts.save_json(rows, "gymts.json/1")
    outcomes = []
    for before, after in zip(rows, rows[1:]):
        alignment = {"entity": "demo", "variable": "value", "issued_at": before["timestamp"], "target_time": after["timestamp"]}
        outcomes.append({"outcome_id": "observed-" + digest(alignment), "revision": "1", "alignment_key": alignment,
            "payload": {"schema_ref": "gymts.builtin/forecast-outcome/1", "storage": "inline", "value": {"value": after["values"]["value"]}},
            "event_time": after["timestamp"], "available_at": "2026-01-01T01:00:00Z", "recorded_at": None,
            "source_ref": truth, "supersedes_ref": None, "allowed_uses": ["evaluation"]})
    gym.records.attach_outcomes(spec["run_id"], outcomes)
    cutoff = utc_now()
    fixed = gym.records.read_outcomes({"run_ids": [spec["run_id"]], "outcomes_as_of": cutoff, "purpose": "evaluation"})
    artifact = gym.artifacts.save_json(fixed, "gymts.outcome-records/1")
    return {"cutoff": cutoff, "view": {"view_id": "observed-labels", "revision": artifact["revision"], "source_refs": [artifact],
        "selection": {"schema_ref": "gymts.selection/1", "storage": "inline", "value": {"kind": "all", "source_index": 0}},
        "as_of": None, "purpose": "evaluation"}}


def prepare(gym):
    catalog = gym.environment_ts.datasets
    source = catalog.register_source({"protocol_version": "gymts.data-source/1", "source_id": "organization/observations",
        "config": "default", "revision": None, "kind": "static", "provider_ref": component("local-timeseries-replay"),
        "configuration": {}, "recipe": None, "reproducibility": {"mode": "snapshot", "seed": None},
        "usage_policy": {"allowed_uses": ["runtime", "evaluation"], "training_allowed": False},
        "parent_datasets": [], "card_ref": None})
    source_ref = {key: source[key] for key in ("source_id", "config", "revision")}
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [{"sample_id": "point-" + str(i), "timestamp": (start + timedelta(minutes=i)).isoformat().replace("+00:00", "Z"),
             "entity": "demo", "values": {"value": i}} for i in range(12)]
    dataset = catalog.register_snapshot(rows, dataset_id="organization/ramp", source_ref=source_ref)
    dataset_ref = {**{key: dataset[key] for key in ("dataset_id", "config", "revision")}, "split": "test"}
    experiment = json.loads((HERE / "forecast_experiment.json").read_text())
    score = json.loads((HERE / "forecast_score_template.json").read_text())
    score["runs"][0]["run_id"] = None
    score["scoring"]["outcomes"]["sources"] = [None]
    data_input = {"kind": "dataset", "ref": dataset_ref}
    run_input = {"kind": "stage_output", "stage_id": "forecast", "output": "run_id"}
    score_inputs = {"run": run_input, "truth": {"kind": "stage_output", "stage_id": "outcomes", "output": "view"},
                    "cutoff": {"kind": "stage_output", "stage_id": "outcomes", "output": "cutoff"}}
    score_bindings = {"run": "/runs/0/run_id", "truth": "/scoring/outcomes/sources/0", "cutoff": "/scoring/outcomes/as_of"}
    stages = [
        {"stage_id": "forecast", "executor_ref": component("example.catalog-forecast"),
         "spec": {"experiment": experiment, "dataset": None}, "inputs": {"data": data_input,
             "source": {"kind": "source", "ref": source_ref}}, "bindings": {"data": "/dataset"}, "outputs": {"run_id": "/run_id"}},
        {"stage_id": "capture", "executor_ref": component("gymts.capture"), "spec": {"source_ref": source_ref,
            "run_id": None, "dataset_id": "organization/recorded", "split": "recorded"},
         "inputs": {"run": run_input}, "bindings": {"run": "/run_id"}, "outputs": {"dataset": ""}},
        {"stage_id": "outcomes", "executor_ref": component("example.observed-outcomes"), "purpose": "evaluation",
         "spec": {"run_id": None, "dataset": None}, "inputs": {"run": run_input, "data": data_input},
         "bindings": {"run": "/run_id", "data": "/dataset"}, "outputs": {"view": "/view", "cutoff": "/cutoff"}},
        {"stage_id": "score", "executor_ref": component("gymts.score"), "spec": score,
         "inputs": score_inputs, "bindings": score_bindings, "outputs": {"evaluation_id": "/evaluation_id", "verdict": "/verdict"}},
        {"stage_id": "rescore", "executor_ref": component("gymts.score"), "spec": deepcopy(score),
         "inputs": {**score_inputs, "previous": {"kind": "stage_output", "stage_id": "score", "output": "evaluation_id"}},
         "bindings": {**score_bindings, "previous": "/previous_evaluation_id"}, "outputs": {"verdict": "/verdict"}}]
    return gym.experiments.register({"group_id": "organization/forecast-study", "name": "Catalog to independently rescored experiment", "stages": stages})


def main(work):
    work = Path(work).resolve()
    with GymTS(work / "runs", data_home=work / "data", cache_home=work / "cache") as gym:
        gym.experiments.register_executor(component("example.catalog-forecast"), forecast_from_catalog)
        gym.experiments.register_executor(component("example.observed-outcomes"), observed_outcomes)
        definition = prepare(gym)
        state = gym.experiments.execute(definition["group_id"], revision=definition["revision"])
        if state["status"] != "succeeded":
            raise RuntimeError(json.dumps(state, indent=2))
        attempts = {item["stage_id"]: item for item in state["attempts"]}
        forecast_id = attempts["forecast"]["outputs"]["run_id"]
        before = digest(gym.records.get_run(forecast_id)["result"])
        repeat = gym.experiments.execute(definition["group_id"], revision=definition["revision"])
        assert len(repeat["attempts"]) == len(state["attempts"])
        assert attempts["score"]["outputs"]["verdict"] == attempts["rescore"]["outputs"]["verdict"] == "pass"
        assert before == digest(gym.records.get_run(forecast_id)["result"])
        query = gym.experiments.query(dataset_id="organization/ramp")
        assert len(query) == 1
        summary = {"status": state["status"], "group_id": definition["group_id"], "revision": definition["revision"],
            "stage_count": len(state["stages"]), "attempt_count": len(state["attempts"]), "run_count": len(state["runs"]),
            "verdict": attempts["rescore"]["outputs"]["verdict"], "dataset_query_matches": len(query),
            "repeat_did_not_execute": True, "original_result_unchanged": True, "work": str(work)}
        (work / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        (work / "group.json").write_text(json.dumps(definition, indent=2) + "\n")
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", default="/tmp/gymts-organization-demo")
    main(parser.parse_args().work)
