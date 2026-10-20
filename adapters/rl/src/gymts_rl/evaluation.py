"""Native AutoBenchTS evaluation and independent scoring of fixed RL runs."""
from gymts.contracts import GymTSError, digest, inline, utc_now
from gymts.plugin_support import unpack
from .contracts import ALIGNMENT


def score_rollout_runs(gym, run_ids, *, gates=(), outcome_refs=None, previous_evaluation_id=None):
    """Score sealed evaluation runs using their captured candidate identities.

    Historical seed-in-CandidateSpec conventions are preserved. This helper
    never merges differently recorded candidates. Fresh artifact-based
    evaluation uses checkpoint_evaluation_spec with execution seeds.
    """
    gym.enable_integration("rl")
    if not isinstance(run_ids, list) or not run_ids or len(set(run_ids)) != len(run_ids):
        raise GymTSError("invalid_config", "Select a nonempty, unique list of sealed evaluation runs")
    selections, repetitions = [], {}
    for index, run_id in enumerate(run_ids):
        record = gym.records.get_run(run_id)
        if record["result"] is None:
            raise GymTSError("invalid_state", "Independent scoring requires sealed runs")
        spec = gym.artifacts.read_json(record["result"]["resolved_spec_ref"])
        inputs = [unpack(event["payload"], gym.artifacts) for event in record["events"] if event["kind"] == "input"]
        prepared = [unpack(event["payload"], gym.artifacts) for event in record["events"] if event["kind"] == "candidate_prepare"]
        if len(inputs) != 1 or len(prepared) != 1:
            raise GymTSError("unsupported_capability", "RL QA re-scoring supports one captured case per run")
        sample = unpack(inputs[0]["payload"], gym.artifacts)
        if sample["split"] != "eval":
            raise GymTSError("permission_denied", "Training runs are not independent evaluation cases")
        candidate = digest({"candidate_spec": spec["candidate"], "model_revision": prepared[0]["model_revision"]})
        case = digest(inputs[0]["alignment_key"])
        identity = (candidate, case)
        repetition = repetitions.get(identity, 0)
        repetitions[identity] = repetition + 1
        selections.append({"unit_id": "captured-rl-" + str(index), "evaluation_case_id": case,
            "candidate_id": candidate, "repetition": repetition, "run_id": run_id, "unavailable_reason": None,
            "tags": {"dataset": sample["dataset_id"], "task_id": sample["task_id"],
                     "captured_policy_revision": prepared[0]["model_revision"]}})
    query = {"run_ids": run_ids, "purpose": "evaluation"}
    if outcome_refs is not None:
        query["outcome_refs"] = outcome_refs
    outcomes = gym.records.read_outcomes(query)
    source = gym.artifacts.save_json(outcomes, "gymts.outcomes/1")
    spec = {"protocol_version": "gymts.score/1", "name": "Captured RL QA independent verification", "purpose": "regression",
        "runs": selections, "baseline_id": None, "previous_evaluation_id": previous_evaluation_id,
        "scoring": {"scorer": {"adapter": "rl-qa-scorer", "version": "1.0.0", "params": {}},
            "outcomes": {"sources": [{"view_id": source["artifact_id"], "revision": source["revision"], "source_refs": [source],
                "selection": inline({"kind": "all"}, "gymts.selection/1"), "as_of": None, "purpose": "evaluation"}], "as_of": utc_now()},
            "alignment": {"schema_ref": ALIGNMENT, "keys": ["dataset_revision", "sample_id", "group_id"],
                "matching": "exact", "params": {}, "duplicate_policy": "error"},
            "metrics": ["accuracy", "format_valid"], "evidence_requirements": {"min_scored": 1, "min_coverage": 1.0},
            "missing_outcome_policy": "report_insufficient"},
        "comparison": {"group_by": ["evaluation_case_id"], "repetition_aggregation": "mean", "aggregation": "macro_mean",
            "baseline_method": "difference", "gates": list(gates)},
        "failure_policy": {"partial_results": "exclude", "invalid_result_policy": "report"}}
    return gym.autobench.score(spec)


__all__ = ["score_rollout_runs", "checkpoint_evaluation_spec", "rescore_checkpoint_evaluation"]


def checkpoint_evaluation_spec(gym, prepared, bundle_ref, sample_ids, *, seeds=(7, 11),
                               generation=None, load=None, gates=()):
    """Configure native AutoBenchTS evaluation of one fixed checkpoint candidate.

    Public case snapshots and independent evaluation-only references are
    committed separately. AutoBenchTS owns plan sealing and all execution.
    """
    import copy
    from .checkpoint import BUNDLE
    from .contracts import OUTCOME, SNAPSHOT
    from .pipeline import experiment_spec
    if bundle_ref["schema_ref"] != BUNDLE:
        raise GymTSError("schema_mismatch", "Expected a fixed RL checkpoint artifact")
    if not isinstance(sample_ids, list) or not sample_ids or len(set(sample_ids)) != len(sample_ids):
        raise GymTSError("invalid_config", "Choose unique held-out evaluation samples")
    if not seeds or any(type(seed) is not int or seed < 0 for seed in seeds):
        raise GymTSError("invalid_config", "Specify nonnegative execution seeds")
    gym.enable_integration("rl")
    manifest = gym.artifacts.read_json(prepared["manifest_ref"])
    for name in ("snapshot_ref", "private_ref", "dataset_revision"):
        if manifest[name] != prepared[name]:
            raise GymTSError("conflict", "Prepared evaluation data differs from its committed manifest")
    public = {sample["sample_id"]: sample for sample in gym.artifacts.read_json(prepared["snapshot_ref"])["samples"]}
    private = {sample["sample_id"]: sample for sample in gym.artifacts.read_json(prepared["private_ref"])["samples"]}
    cases, outcomes = [], []
    now = utc_now()
    for token in sample_ids:
        if token not in public or token not in private or public[token]["split"] != "eval" or private[token]["split"] != "eval":
            raise GymTSError("permission_denied", "Checkpoint evaluation only accepts the held-out partition")
        sample, gold = public[token], private[token]
        if any(sample[name] != gold[name] for name in ("sample_id", "group_id", "dataset_id", "task_id", "split")):
            raise GymTSError("conflict", "Evaluation reference belongs to another public sample")
        reference = gym.artifacts.save_json({"schema_version": SNAPSHOT,
            "dataset_revision": prepared["dataset_revision"], "samples": [sample]}, SNAPSHOT)
        experiment = experiment_spec(reference, prepared["dataset_revision"], sample, generation or {}, seeds[0])
        cases.append({"evaluation_case_id": token, "scene": experiment["scene"],
            "execution": experiment["execution"], "recording": experiment["recording"],
            "tags": {"dataset": sample["dataset_id"], "task_id": sample["task_id"]}})
        outcomes.append({"outcome_id": "checkpoint-reference-" + token, "revision": "1",
            "alignment_key": {"dataset_revision": prepared["dataset_revision"], "sample_id": token, "group_id": sample["group_id"]},
            "payload": inline({"sample_id": token, "task_id": sample["task_id"], "reward_spec": copy.deepcopy(gold["reward_spec"])}, OUTCOME),
            "event_time": None, "available_at": now, "recorded_at": now, "source_ref": prepared["private_ref"],
            "supersedes_ref": None, "allowed_uses": ["evaluation"]})
    source = gym.artifacts.save_json(outcomes, "gymts.outcomes/1")
    return {"protocol_version": "gymts.evaluation/1", "name": "Fixed trained checkpoint held-out evaluation", "purpose": "acceptance",
        "cases": cases, "candidates": [{"candidate_id": "checkpoint-" + bundle_ref["content_hash"],
            "spec": {"adapter": "rl-local-hf", "version": "1.0.0", "artifact": bundle_ref, "inherited_state": [],
                     "params": {"generation": generation or {}, "load": load or {}}}}],
        "baseline_id": None, "repetitions": {"count": len(seeds), "seeds": list(seeds)},
        "scoring": {"scorer": {"adapter": "rl-qa-scorer", "version": "1.0.0", "params": {}},
            "outcomes": {"sources": [{"view_id": source["artifact_id"], "revision": source["revision"], "source_refs": [source],
                "selection": inline({"kind": "all"}, "gymts.selection/1"), "as_of": None, "purpose": "evaluation"}], "as_of": now},
            "alignment": {"schema_ref": ALIGNMENT, "keys": ["dataset_revision", "sample_id", "group_id"], "matching": "exact",
                          "params": {}, "duplicate_policy": "error"},
            "metrics": ["accuracy", "format_valid"], "evidence_requirements": {"min_scored": 1, "min_coverage": 1.0},
            "missing_outcome_policy": "report_insufficient"},
        "comparison": {"group_by": ["evaluation_case_id"], "repetition_aggregation": "mean", "aggregation": "macro_mean",
                       "baseline_method": "difference", "gates": list(gates)},
        "failure_policy": {"partial_results": "exclude", "invalid_result_policy": "report"}}


def rescore_checkpoint_evaluation(gym, report):
    """Re-use the original fixed sources, tags, candidate IDs and executed units."""
    import copy
    plan = gym.artifacts.read_json(report["plan_ref"])
    original = gym.artifacts.read_json(plan["spec_ref"])
    executions = {item["unit_id"]: item for item in gym.artifacts.read_json(report["run_manifest_ref"])["entries"]}
    selections = [{"unit_id": unit["unit_id"], "evaluation_case_id": unit["evaluation_case_id"],
                   "candidate_id": unit["candidate_id"], "repetition": unit["repetition"],
                   "run_id": executions[unit["unit_id"]]["run_id"],
                   "unavailable_reason": (None if executions[unit["unit_id"]]["run_id"] is not None
                                          else executions[unit["unit_id"]]["status"]),
                   "unit_spec_ref": unit["resolved_spec_ref"], "tags": copy.deepcopy(unit["tags"])}
                  for unit in plan["expected_units"]]
    return gym.autobench.score({"protocol_version": "gymts.score/1", "name": "Fixed checkpoint output re-scoring",
        "purpose": original["purpose"], "runs": selections, "baseline_id": original["baseline_id"],
        "scoring": copy.deepcopy(original["scoring"]), "comparison": copy.deepcopy(original["comparison"]),
        "failure_policy": copy.deepcopy(original["failure_policy"]), "previous_evaluation_id": report["evaluation_id"]})
