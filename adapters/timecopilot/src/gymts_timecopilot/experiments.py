"""Public AutoBenchTS evaluation and model-free rescoring of the same sealed Run."""
import copy
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import digest, inline, utc_now
from gymts_timeseries.contracts import OUTCOME
from gymts_timeseries.experiments import scene, scoring


def evaluation_spec(source, params):
    task, version = "forecast.numeric", "0.2.0"
    return {"protocol_version": "gymts.evaluation/1", "name": "Native TimeCopilot AirPassengers agent", "purpose": "development",
        "cases": [{"evaluation_case_id": "airpassengers-h12", "scene": scene(source["snapshot_ref"], source["dataset_revision"],
            source["sample_tokens"][0], task, version),
            "execution": {"mode": "stream", "start": {"mode": "reinitialize"}, "scope": {"start": 0, "end": 1},
                "feedback_until": None, "seed": 7,
                "learning": {"prepare": "load_only", "online": "frozen", "training_view": None, "training_targets": None,
                    "alignment_schema_ref": None, "allowed_feedback_sources": []},
                "limits": {"max_inputs": 1, "max_operations": 1, "max_turns_per_case": 1,
                    "max_wall_time_s": params["limits"]["max_wall_time_s"] + 120}},
            "recording": {"store_ref": "local://records/default", "inputs": "full", "outputs": "full", "artifacts": "reference",
                "model_calls": "io", "on_capture_failure": "fail_run", "redaction_policy_ref": None, "extra_event_kinds": []},
            "tags": {"dataset": "AirPassengers", "native_revision": "961aa330f71afcf53a6ecf2d4b499cb39b44da3e"}}],
        "candidates": [{"candidate_id": "native-timecopilot", "spec": {"adapter": "timecopilot-agent", "version": "1.0.0",
            "artifact": None, "inherited_state": [], "params": copy.deepcopy(params)}}],
        "baseline_id": "native-timecopilot", "repetitions": {"count": 1, "seeds": [7]}, "scoring": scoring(task, version),
        "comparison": {"group_by": ["evaluation_case_id"], "repetition_aggregation": "mean", "aggregation": "macro_mean",
            "baseline_method": "difference", "gates": []},
        "failure_policy": {"partial_results": "include", "invalid_result_policy": "report"}}


def evaluate(gym, source, params, execution_saved=None):
    spec = evaluation_spec(source, params)
    initial = gym.autobench.evaluate(spec)
    if execution_saved is not None:
        execution_saved(copy.deepcopy(initial))
    return score_execution(gym, source, params, initial)


def score_execution(gym, source, params, initial):
    """Score an already sealed evaluation, including after a late driver failure."""
    spec = evaluation_spec(source, params)
    plan = gym.artifacts.read_json(initial["plan_ref"])
    if gym.artifacts.read_json(plan['spec_ref']) != spec:
        raise ValueError('Initial evaluation does not match the supplied source and parameters')
    manifest = gym.artifacts.read_json(initial["run_manifest_ref"])
    units = {unit["unit_id"]: unit for unit in plan["expected_units"]}
    selections, originals, failures = [], {}, []
    gold = gym.artifacts.read_json(source["private_ref"])
    existing = {(r['outcome_id'], r['revision']):r for r in gym.records.read_outcomes()}
    for entry in manifest["entries"]:
        run_id, unit = entry["run_id"], units[entry["unit_id"]]
        if run_id is None:
            failures.append({"unit_id": unit["unit_id"], "reason": "Run allocation failed"})
            selections.append({'unit_id':unit['unit_id'],'evaluation_case_id':unit['evaluation_case_id'],
                'candidate_id':unit['candidate_id'],'repetition':unit['repetition'],'run_id':None,
                'unavailable_reason':'native_run_allocation_failed','unit_spec_ref':unit['resolved_spec_ref'],
                'tags':copy.deepcopy(unit['tags'])})
            continue
        run = gym.records.get_run(run_id)
        originals[run_id] = digest(run["result"])
        if run["result"]["status"] != "succeeded":
            failures.append({"run_id": run_id, "errors": run["result"]["errors"]})
        stamp = utc_now()
        outcome = {"outcome_id": "timecopilot-future-" + digest(gold).removeprefix("sha256:"), "revision": "1",
            "alignment_key": {"dataset_revision": source["dataset_revision"], "sample_token": source["sample_tokens"][0]},
            "payload": inline({"task_id": "forecast.numeric", "task_version": "0.2.0",
                               "expected_output": {"forecast": gold["forecast"]}}, OUTCOME),
            "event_time": 0, "available_at": stamp, "recorded_at": None, "source_ref": source["private_ref"],
            "supersedes_ref": None, "allowed_uses": ["evaluation"]}
        prior = existing.get((outcome['outcome_id'], outcome['revision']))
        if prior is not None:
            previous = copy.deepcopy(prior)
            previous.pop('recorded_at', None)
            outcome.pop('recorded_at', None)
            outcome['available_at'] = previous['available_at']
            if outcome != previous:
                raise ValueError('The existing future outcome revision has different content; use an explicit new reference identity')
        gym.records.attach_outcomes(run_id, [outcome])
        selections.append({"unit_id": unit["unit_id"], "evaluation_case_id": unit["evaluation_case_id"],
            "candidate_id": unit["candidate_id"], "repetition": unit["repetition"], "run_id": run_id,
            "unavailable_reason": None, "unit_spec_ref": unit["resolved_spec_ref"], "tags": copy.deepcopy(unit["tags"])})
    records = gym.records.read_outcomes({"run_ids": list(originals), "purpose": "evaluation"})
    reference = gym.artifacts.save_json(records, "gymts.outcome-records/1")
    view = {"view_id": "timecopilot-independent-future", "revision": reference["revision"], "source_refs": [reference],
        "selection": inline({"kind": "all", "source_index": 0}, "gymts.selection/1"), "as_of": None, "purpose": "evaluation"}
    score_spec = {"protocol_version": "gymts.score/1", "name": "Native TimeCopilot future-only evaluation", "purpose": "development",
        "runs": selections, "baseline_id": spec["baseline_id"], "scoring": copy.deepcopy(spec["scoring"]),
        "comparison": spec["comparison"], "failure_policy": spec["failure_policy"], "previous_evaluation_id": initial["evaluation_id"]}
    score_spec["scoring"]["outcomes"] = {"sources": [view], "as_of": None}
    final = gym.autobench.score(score_spec)
    assert all(digest(gym.records.get_run(run_id)["result"]) == value for run_id, value in originals.items())
    return {"source": source, "run_ids": list(originals), "sealed_result_hashes": originals,
            "initial_report": initial, "report": final, "score_spec": score_spec, "failures": failures}


def rescore(gym, previous):
    """This guard also proves that scoring does not construct the Candidate or worker."""
    hashes = {run_id: digest(gym.records.get_run(run_id)["result"]) for run_id in previous["run_ids"]}
    with patch("gymts_timecopilot.candidate.TimeCopilotCandidate.__init__", side_effect=AssertionError("Candidate forbidden during rescore")), \
         patch("gymts_timecopilot.runtime.TimeCopilotRuntime.invoke", side_effect=AssertionError("Native backend forbidden during rescore")):
        result = gym.autobench.score(copy.deepcopy(previous["score_spec"]))
    if hashes != previous["sealed_result_hashes"]:
        raise AssertionError("Sealed Run result changed before rescore")
    if any(digest(gym.records.get_run(run_id)["result"]) != expected for run_id, expected in hashes.items()):
        raise AssertionError("Rescoring changed a sealed Run")
    return {"report": result, "run_ids": previous["run_ids"], "sealed_result_hashes": hashes,
            "candidate_construction_forbidden": True, "native_backend_forbidden": True}
