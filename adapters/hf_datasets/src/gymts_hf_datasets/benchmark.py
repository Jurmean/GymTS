"""Resource resolution into native AutoBenchTS plans, never another evaluator."""
import copy

from gymts.contracts import digest, inline, utc_now
from gymts.plugin_support import fail
from .contracts import ALIGNMENT, OUTCOME, PROJECTION, SNAPSHOT


def last_value_candidate():
    return {"candidate_id": "hf-last-value", "spec": {"adapter": "hf-static-last-value", "version": "1.0.0",
            "artifact": None, "params": {}, "inherited_state": []}}


class StaticBenchmarkResolver:
    def resolve(self, definition, resources, candidates, purpose, repetitions):
        if (len(definition["datasets"]) != 1 or definition["params"] != {
                "projection_ref": PROJECTION, "scope": "all_frozen_rows", "metrics": ["mae"]}):
            fail("unsupported_capability", "Static resolver supports exactly all frozen rows and its declared MAE projection")
        reference = definition["datasets"][0]
        dataset = resources.datasets.load_dataset(**reference, purpose="evaluation")
        targets = dataset.read_targets()
        by_id = {row["sample_id"]: row for row in targets}
        if len(by_id) != len(dataset) or set(by_id) != set(dataset.public.sample_ids()):
            fail("artifact_integrity", "Static public samples and private references do not align")
        target_ref = resources.artifacts.save_json(targets, "gymts.json/1")
        cases, outcomes, available = [], [], utc_now()
        for row in dataset:
            target, token = by_id[row["sample_id"]], row["sample_id"]
            if target["allowed_uses"] != ["evaluation"] or len(target["values"]) != row["horizon"]:
                fail("permission_denied", "Static references differ from the declared horizon/evaluation policy")
            snapshot = resources.artifacts.save_json({"dataset_revision": reference["revision"], "sample": row}, SNAPSHOT)
            cases.append({"evaluation_case_id": token,
                "scene": {"environment": {"protocol_version": "gymts.environment/1", "adapter": "hf-static-snapshot",
                    "version": "1.0.0", "source": {"kind": "dataset", "locator": "artifact://hf-static/public",
                        "revision": reference["revision"], "connection": {"artifact_refs": [snapshot]}, "credential_ref": None},
                    "mapping": {}, "options": {}},
                    "task": {"plugin": "hf-static-forecast", "version": "1.0.0", "params": {}},
                    "binding": {"variables": {"sample": {"source": "sample", "unit": "sample", "transform": None}},
                                "operations": {}}},
                "execution": {"mode": "stream", "start": {"mode": "reinitialize"}, "scope": {"start": 0, "end": 1},
                    "feedback_until": None, "seed": 0, "learning": {"prepare": "load_only", "online": "frozen",
                        "training_view": None, "training_targets": None, "alignment_schema_ref": None,
                        "allowed_feedback_sources": []},
                    "limits": {"max_inputs": 1, "max_operations": None, "max_turns_per_case": 1, "max_wall_time_s": 60}},
                "recording": {"store_ref": "local://records/default", "inputs": "full", "outputs": "full",
                    "artifacts": "reference", "model_calls": "none", "on_capture_failure": "fail_run",
                    "redaction_policy_ref": None, "extra_event_kinds": []},
                "tags": {"dataset": reference["dataset_id"], "source_row": str(row["source_row"])}})
            outcomes.append({"outcome_id": "hf-static-gold-" + digest({"revision": reference["revision"], "sample_id": token}),
                "revision": "1", "alignment_key": {"dataset_revision": reference["revision"], "sample_id": token},
                "payload": inline({"values": target["values"]}, OUTCOME), "event_time": 0,
                "available_at": available, "recorded_at": available, "source_ref": target_ref,
                "supersedes_ref": None, "allowed_uses": ["evaluation"]})
        outcome_ref = resources.artifacts.save_json(outcomes, "gymts.outcome-records/1")
        view = {"view_id": "hf-static-evaluation", "revision": outcome_ref["revision"], "source_refs": [outcome_ref],
                "selection": inline({"kind": "all", "source_index": 0}, "gymts.selection/1"), "as_of": None, "purpose": "evaluation"}
        return {"protocol_version": "gymts.evaluation/1", "name": definition["benchmark_id"], "purpose": purpose,
            "cases": cases, "candidates": copy.deepcopy(candidates), "baseline_id": None,
            "repetitions": repetitions or {"count": 1, "seeds": [0]},
            "scoring": {"scorer": {"adapter": "hf-static-reference-mae", "version": "1.0.0", "params": {}},
                "outcomes": {"sources": [view], "as_of": available},
                "alignment": {"schema_ref": ALIGNMENT, "keys": ["dataset_revision", "sample_id"], "matching": "exact",
                    "params": {}, "duplicate_policy": "error"}, "metrics": ["mae"],
                "evidence_requirements": {"min_scored": 1, "min_coverage": 1, "overrides": {}},
                "missing_outcome_policy": "report_insufficient"},
            "comparison": {"group_by": ["evaluation_case_id", "tags.dataset"], "repetition_aggregation": "mean",
                "aggregation": "macro_mean", "baseline_method": "difference", "gates": [
                    {"metric": "run_failure_rate", "target": "absolute", "candidate_ids": None, "for_metric": None,
                     "operator": "le", "threshold": 0, "scope": "aggregate"},
                    {"metric": "scored_coverage", "target": "absolute", "candidate_ids": None, "for_metric": "mae",
                     "operator": "ge", "threshold": 1, "scope": "aggregate"}]},
            "failure_policy": {"partial_results": "include", "invalid_result_policy": "report"}}


def experiment_from_case(spec, index=0):
    """Public helper for a direct EnvironmentTS.run of the same frozen case."""
    case = spec["cases"][index]
    result = {"protocol_version": "gymts.experiment/1", "name": spec["name"] + " direct Run",
        "scene": copy.deepcopy(case["scene"]), "candidate": copy.deepcopy(spec["candidates"][0]["spec"]),
        "execution": copy.deepcopy(case["execution"]), "recording": copy.deepcopy(case["recording"])}
    if "provenance" in spec:
        result["provenance"] = copy.deepcopy(spec["provenance"])
    return result


def score_existing(gym, spec, report):
    """Independent rescoring references only sealed existing Run IDs."""
    plan = gym.artifacts.read_json(report["plan_ref"])
    original = gym.artifacts.read_json(plan["spec_ref"])
    if original != spec:
        fail("conflict", "Rescoring requires the original sealed evaluation specification")
    entries = {row["unit_id"]: row for row in gym.artifacts.read_json(report["run_manifest_ref"])["entries"]}
    runs = [{"unit_id": unit["unit_id"], "evaluation_case_id": unit["evaluation_case_id"],
             "candidate_id": unit["candidate_id"], "repetition": unit["repetition"],
             "run_id": entries[unit["unit_id"]]["run_id"],
             "unavailable_reason": None if entries[unit["unit_id"]]["run_id"] else entries[unit["unit_id"]]["status"],
             "unit_spec_ref": unit["resolved_spec_ref"], "tags": copy.deepcopy(unit["tags"])}
            for unit in plan["expected_units"]]
    return gym.autobench.score({"protocol_version": "gymts.score/1", "name": spec["name"] + " re-scoring",
        "purpose": spec["purpose"], "runs": runs, "baseline_id": spec["baseline_id"],
        "previous_evaluation_id": report["evaluation_id"], "scoring": copy.deepcopy(spec["scoring"]),
        "comparison": copy.deepcopy(spec["comparison"]), "failure_policy": copy.deepcopy(spec["failure_policy"])})
