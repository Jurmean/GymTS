"""Native GymTS Runs and private rewards for frozen-policy rollout batches."""

import copy
import math

from gymts.contracts import GymTSError, digest, inline, new_id, utc_now
from gymts.plugin_support import component, unpack
from .contracts import OUTCOME, SNAPSHOT
from .rewards import score_completion

BATCH = "gymts.rl/rollout-batch/1"
REWARD = "gymts.reward/1"
REWARD_MAPPER = component("gymts.rl.verifiable-reward", "1.0.0")


def recording():
    return {"store_ref": "local://records/default", "inputs": "full", "outputs": "full", "artifacts": "reference",
            "model_calls": "native_rollout", "on_capture_failure": "fail_run", "redaction_policy_ref": None, "extra_event_kinds": []}


def experiment_spec(snapshot_ref, dataset_revision, sample, generation, seed, *, legacy_candidate_seed=False):
    """A single public prompt, frozen model revision, and one native call."""
    return {"protocol_version": "gymts.experiment/1", "name": "RL " + sample["task_id"],
        "purpose": "training_collection" if sample["split"] == "train" else "development",
        "scene": {"environment": {"protocol_version": "gymts.environment/1", "adapter": "rl-qa-snapshot", "version": "1.0.0",
            "source": {"kind": "dataset", "locator": "artifact://rl-public-snapshot", "revision": dataset_revision,
                "connection": {"artifact_refs": [snapshot_ref]}, "credential_ref": None}, "mapping": {}, "options": {"sample_ids": [sample["sample_id"]]}},
            "task": {"plugin": "rl-verifiable-qa", "version": "1.0.0", "params": {}},
            "binding": {"variables": {"sample": {"source": "sample", "unit": "sample", "transform": None}}, "operations": {}}},
        "candidate": {"adapter": "rl-local-hf", "version": "1.0.0", "artifact": None, "inherited_state": [],
                      "params": {"generation": copy.deepcopy(generation), **({"seed": seed} if legacy_candidate_seed else {})}},
        "execution": {"mode": "stream", "start": {"mode": "reinitialize"}, "scope": {"start": 0, "end": 1},
            "feedback_until": None, "seed": seed, "learning": {"prepare": "load_only", "online": "frozen", "training_view": None,
                "training_targets": None, "alignment_schema_ref": None, "allowed_feedback_sources": []},
            "limits": {"max_inputs": None, "max_operations": None, "max_turns_per_case": 1, "max_wall_time_s": 900}},
        "recording": recording(), "extensions": {}}


def _event_value(gym, event):
    return unpack(event["payload"], gym.artifacts)


def _error_value(error):
    if isinstance(error, GymTSError):
        return error.to_dict()
    return {"type": type(error).__name__, "message": str(error)}


def _raise_with_evidence(error, batch, batch_ref):
    links = {"rollout_batch_ref": batch_ref, "record_snapshot_ref": batch["record_snapshot_ref"],
             "run_ids": batch["run_ids"]}
    if isinstance(error, GymTSError):
        info = error.to_dict()
        raise GymTSError(info["code"], info["message"], stage=info["stage"], method=info["method"],
            run_id=info["run_id"], links=dict(info["links"], **links), retryable=info["retryable"],
            side_effect=info["side_effect"]) from error
    if not isinstance(error, Exception):
        # Preserve cancellation and interpreter-exit semantics while retaining
        # the committed evidence identity for an enclosing experiment journal.
        error.rollout_evidence = links
        if hasattr(error, "add_note"):
            error.add_note("Partial rollout evidence: " + str(links))
        raise error
    raise GymTSError("rollout_failure", str(error), stage="rl_rollout", links=dict(links, error_type=type(error).__name__)) from error


def _sources(gym, prepared, sample_ids, split):
    manifest = gym.artifacts.read_json(prepared["manifest_ref"])
    for key in ("dataset_revision", "snapshot_ref", "private_ref"):
        if manifest.get(key) != prepared.get(key):
            raise GymTSError("conflict", "Prepared RL data differs from its immutable manifest: " + key)
    snapshot = gym.artifacts.read_json(manifest["snapshot_ref"])
    private = gym.artifacts.read_json(manifest["private_ref"])
    if snapshot["dataset_revision"] != manifest["dataset_revision"] or private["dataset_revision"] != manifest["dataset_revision"]:
        raise GymTSError("conflict", "RL public and private dataset revisions differ")
    gym.schemas.validate(SNAPSHOT, snapshot)
    public = {row["sample_id"]: row for row in snapshot["samples"]}
    hidden = {row["sample_id"]: row for row in private["samples"]}
    if len(public) != len(snapshot["samples"]) or len(hidden) != len(private["samples"]) or set(public) != set(hidden):
        raise GymTSError("conflict", "RL public and private source identities are not one-to-one")
    for token in sample_ids:
        if token not in public or public[token]["split"] != split:
            raise GymTSError("permission_denied", "RL sample is unknown or does not belong to the requested split")
        if any(public[token][key] != hidden[token][key] for key in ("sample_id", "group_id", "dataset_id", "split", "task_id")):
            raise GymTSError("conflict", "Private reward belongs to another public sample")
    return manifest, public, hidden


def _one_run(gym, prepared, sample, hidden, generation, seed):
    single = {"schema_version": SNAPSHOT, "dataset_revision": prepared["dataset_revision"], "samples": [sample]}
    reference = gym.artifacts.save_json(single, SNAPSHOT)
    spec = experiment_spec(reference, prepared["dataset_revision"], sample, generation, seed)
    result = gym.run(spec)
    stored = gym.records.get_run(result["run_id"])
    entry = {"sample_id": sample["sample_id"], "group_id": sample["group_id"], "dataset_id": sample["dataset_id"],
        "task_id": sample["task_id"], "split": sample["split"], "seed": seed, "run_id": result["run_id"],
        "run_status": result["status"], "run_result_ref": stored["result_ref"], "model_call_ref": None,
        "raw_text": None, "reward": None, "reward_ref": None, "outcome_ref": None, "finish_reason": None,
        "errors": copy.deepcopy(result["errors"])}
    try:
        return _finish_run(gym, prepared, sample, hidden, result, stored, entry)
    except Exception as error:
        # A verifier/storage error can occur after execution was sealed. Carry
        # its exact Run identity back to the batch finalizer without inventing
        # another Run or mutating the immutable execution result.
        if isinstance(error, GymTSError):
            info = error.to_dict()
            raise GymTSError(info["code"], info["message"], stage=info["stage"], method=info["method"],
                run_id=result["run_id"], links=dict(info["links"], run_result_ref=stored["result_ref"]),
                retryable=info["retryable"], side_effect=info["side_effect"]) from error
        raise GymTSError("rollout_postprocessing_failure", str(error), stage="rl_rollout",
            run_id=result["run_id"], links={"run_result_ref": stored["result_ref"], "error_type": type(error).__name__}) from error


def _finish_run(gym, prepared, sample, hidden, result, stored, entry):
    calls = [event for event in stored["events"] if event["kind"] == "model_call" and _event_value(gym, event)["status"] == "succeeded"]
    outputs = [event for event in stored["events"] if event["kind"] == "candidate_output"]
    if result["status"] != "succeeded" or len(calls) != 1 or len(outputs) != 1:
        return entry
    call, output = _event_value(gym, calls[0]), _event_value(gym, outputs[0])
    output_body = unpack(output["payload"], gym.artifacts)
    if call["input_id"] != output["input_id"]:
        raise GymTSError("conflict", "RL captured call and Candidate output refer to different inputs")
    call_ref = calls[0]["payload"]["artifact_ref"]
    if output_body["evidence"].get("model_call_ref") != call_ref:
        raise GymTSError("conflict", "RL output does not identify its committed model call")
    alignment = {"dataset_revision": prepared["dataset_revision"], "sample_id": sample["sample_id"], "group_id": sample["group_id"]}
    purpose = "training_export" if sample["split"] == "train" else "evaluation"
    gold = {"sample_id": sample["sample_id"], "task_id": sample["task_id"], "reward_spec": copy.deepcopy(hidden["reward_spec"])}
    gym.schemas.validate(OUTCOME, gold)
    outcome = {"outcome_id": "rl-gold-" + result["run_id"], "revision": "1", "alignment_key": alignment,
        "payload": inline(gold, OUTCOME), "event_time": 0, "available_at": utc_now(), "recorded_at": None,
        "source_ref": prepared["private_ref"], "supersedes_ref": None, "allowed_uses": [purpose]}
    sealed_digest = digest(stored["result"])
    gym.records.attach_outcomes(result["run_id"], [outcome])
    committed = gym.records.read_outcomes({"run_ids": [result["run_id"]], "purpose": purpose})
    if len(committed) != 1 or digest(gym.records.get_run(result["run_id"])["result"]) != sealed_digest:
        raise GymTSError("conflict", "Private reward attachment changed sealed execution or outcome identity")
    outcome_ref = gym.artifacts.save_json(committed[0], "gymts.outcome/1")
    reward = score_completion(output_body["raw_text"], hidden["reward_spec"])
    reward_record = {"protocol_version": REWARD, "reward_id": "rl-reward-" + result["run_id"],
        "target_refs": [call_ref], "granularity": "call", "value": reward["reward"], "source_refs": [outcome_ref],
        "mapper_ref": copy.deepcopy(REWARD_MAPPER), "created_at": utc_now()}
    reward_ref = gym.artifacts.save_json(reward_record, REWARD)
    response = gym.artifacts.read_json(call["response_ref"])
    entry.update(model_call_ref=call_ref, raw_text=output_body["raw_text"], reward=reward, reward_ref=reward_ref,
                 outcome_ref=outcome_ref, finish_reason=response.get("finish_reason"))
    return entry


def _metrics(entries):
    scored = [row for row in entries if row["reward"] is not None]
    count = len(entries)
    errors = [row["reward"]["error"] for row in scored if row["reward"]["error"] is not None]
    return {"planned": count, "scored": len(scored), "failed": sum(row["run_status"] != "succeeded" for row in entries),
        "correct": sum(row["reward"]["correct"] for row in scored), "format_valid": sum(row["reward"]["format_valid"] for row in scored),
        "accuracy": sum(row["reward"]["correct"] for row in scored) / count if count else None,
        "coverage": len(scored) / count if count else None,
        "scored_accuracy": sum(row["reward"]["correct"] for row in scored) / len(scored) if scored else None,
        "mean_reward": math.fsum(row["reward"]["reward"] for row in scored) / len(scored) if scored else None,
        "mean_numeric_error": math.fsum(error / len(errors) for error in errors) if errors else None}


def rollouts(gym, prepared_dataset, sample_ids, policy, generation=None, seed_start=7, split="train"):
    """Generate one sealed Run per requested prompt, then build from its snapshot.

    Repeated prompt IDs are independent rollout samples. TRL may update the
    resident policy only after this complete, single-revision batch returns.
    Evaluation outcomes are intentionally unavailable to the training builder.
    """
    from .policy import configure_active_policy
    if split not in ("train", "eval") or not isinstance(sample_ids, list) or not sample_ids or any(not isinstance(token, str) for token in sample_ids):
        raise GymTSError("invalid_config", "RL rollouts require nonempty sample IDs and an explicit train/eval split")
    if type(seed_start) is not int or seed_start < 0 or not isinstance(generation or {}, dict):
        raise GymTSError("invalid_config", "RL generation requires a nonnegative integer seed and parameter object")
    gym.enable_integration("rl")
    _, public, hidden = _sources(gym, prepared_dataset, sample_ids, split)
    revision, entries, failure = policy.revision, [], None
    current_sample, current_seed = None, None
    previous = configure_active_policy(policy)
    try:
        for index, token in enumerate(sample_ids):
            current_sample, current_seed = public[token], seed_start + index
            if policy.revision != revision:
                raise GymTSError("conflict", "Policy revision changed within a rollout batch")
            entries.append(_one_run(gym, prepared_dataset, current_sample, hidden[token], generation or {}, current_seed))
        if policy.revision != revision:
            raise GymTSError("conflict", "Policy revision changed before the frozen batch completed")
    except BaseException as error:
        failure = error
        failed_run_id = error.run_id if isinstance(error, GymTSError) else None
        if failed_run_id is not None and failed_run_id not in {entry["run_id"] for entry in entries}:
            stored = gym.records.get_run(failed_run_id)
            result = stored["result"]
            entries.append({"sample_id": current_sample["sample_id"], "group_id": current_sample["group_id"],
                "dataset_id": current_sample["dataset_id"], "task_id": current_sample["task_id"], "split": split,
                "seed": current_seed, "run_id": failed_run_id, "run_status": result["status"] if result else "running",
                "run_result_ref": stored["result_ref"], "model_call_ref": None, "raw_text": None, "reward": None,
                "reward_ref": None, "outcome_ref": None, "finish_reason": None,
                "errors": (copy.deepcopy(result["errors"]) if result else []) + [_error_value(error)]})
    finally:
        configure_active_policy(previous)
    run_ids = [row["run_id"] for row in entries]
    snapshot = gym.records.snapshot(run_ids, {"through_seq": None, "outcomes_as_of": utc_now(), "outcome_refs": None})
    reward_refs = [row["reward_ref"] for row in entries if row["reward_ref"] is not None]
    metrics = _metrics(entries)
    metrics["datasets"] = {dataset: _metrics([row for row in entries if row["dataset_id"] == dataset]) for dataset in sorted({row["dataset_id"] for row in entries})}
    batch = {"schema_version": BATCH, "batch_id": new_id(), "policy_revision": revision, "split": split,
        "status": "failed" if failure is not None else "completed", "requested_sample_ids": list(sample_ids),
        "error": _error_value(failure) if failure is not None else None,
        "dataset_manifest_ref": prepared_dataset["manifest_ref"], "record_snapshot_ref": snapshot["snapshot_ref"],
        "entries": entries, "run_ids": run_ids, "reward_refs": reward_refs, "metrics": metrics}
    # Persist the complete sampling evidence before any downstream builder error.
    batch_ref = gym.artifacts.save_json(batch, BATCH)
    if failure is not None:
        _raise_with_evidence(failure, batch, batch_ref)
    manifest_ref, rows = None, []
    if split == "train":
        try:
            from .exporter import build_dataset, native_rollout_build_spec, read_dataset_rows
            spec = native_rollout_build_spec([snapshot["snapshot_ref"]], reward_refs, REWARD_MAPPER,
                name="Frozen RL policy batch " + revision, missing_data_policy="exclude_samples", splits=("train",))
            manifest = build_dataset(gym, spec)
            manifest_ref = manifest["manifest_ref"]
            rows = read_dataset_rows(gym, manifest_ref, split="train")
            order = {run_id: index for index, run_id in enumerate(run_ids)}
            rows.sort(key=lambda row: order[row["run_id"]])
        except BaseException as error:
            batch.update(status="build_failed", error=_error_value(error), previous_batch_ref=batch_ref,
                         dataset_manifest_ref_partial=manifest_ref)
            batch_ref = gym.artifacts.save_json(batch, BATCH)
            _raise_with_evidence(error, batch, batch_ref)
    return dict(batch, batch_ref=batch_ref, manifest_ref=manifest_ref, rows=rows)


__all__ = ["REWARD_MAPPER", "recording", "experiment_spec", "rollouts", "qa_rollout_provider"]


def qa_rollout_provider(gym, prepared_dataset):
    """Adapt this package's QA source to the source-independent TRL consumer.

    Other sources supply the same callable boundary and publish the native row
    contract; the Trainer does not inspect GSM8K/ChatTS source configuration.
    """
    def collect(inputs, policy, *, generation, seed_start):
        return rollouts(gym, prepared_dataset, [row["sample_id"] for row in inputs], policy,
                        generation=generation, seed_start=seed_start, split="train")
    return collect
