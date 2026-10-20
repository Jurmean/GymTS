"""Native one-call/case RL exports from sealed, fixed RecordSnapshots.

This independently packaged stdlib exporter owns evidence selection and masks.
Trainers retain ownership of grouping, optimization, sampling and policy synchronization.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import Counter
from datetime import datetime

from gymts.contracts import GymTSError, canonical_json, digest, inline, new_id, parse_time, utc_now
from gymts.contracts.schema import ARTIFACT, COMPONENT, OBJECT, PAYLOAD, STRING, array, nullable, obj
from gymts.environment_ts.capture import LOGPROBS, MODEL_CALL, validate_model_call
from gymts.training import register_training_schemas as register_shared_training_schemas
from gymts.contracts.schema import SchemaRegistry, register_core_schemas



# Keep these persisted identities stable across the Python package migration.
BUILDER_REF = {"name": "gymts.native-rollout-builder", "version": "1.0.0", "origin_ref": None}
MASK_BUILDER_REF = {"name": "gymts.native-response-mask", "version": "1.0.0", "origin_ref": None}
RL_SAMPLE = "gymts.rl/rollout-sample/1"
REWARD = "gymts.reward/1"


def _require(condition, reason, code="invalid_dataset"):
    if not condition:
        raise GymTSError(code, reason, stage="dataset_build")


def register_training_schemas(schemas):
    """Register shared export contracts and this adapter's native QA profile."""
    register_shared_training_schemas(schemas)
    schemas.register("gymts.training/selection/1", obj({"splits": array(STRING, minItems=1, uniqueItems=True),
        "require_complete_capture": {"type": "boolean"}}))
    schemas.register("gymts.training/episode-mapping/1", obj({"kind": {"const": "one_call_one_case"}}))
    schemas.register("gymts.training/splits/1", obj({"kind": {"const": "source"},
        "group_key": {"const": "group_id"}, "split_key": {"const": "split"},
        "cross_split_policy": {"const": "reject"}}))
    ids = array({"type": "integer", "minimum": 0}, minItems=1)
    mask = array({"enum": [0, 1]}, minItems=1)
    row = {key: STRING for key in ("sample_id", "source_sample_id", "episode_id", "group_id", "split", "run_id",
                                   "case_id", "input_id", "output_id", "call_id", "attempt_id", "policy_revision")}
    row.update({"schema_version": {"const": RL_SAMPLE}, "prompt_ids": ids, "completion_ids": ids,
        "input_ids": ids, "attention_mask": mask, "action_mask": mask, "loss_mask": mask,
        "completion_mask": mask, "old_per_token_logps": array({"type": "number", "maximum": 0}, minItems=1),
        "logprob_distribution": {"enum": ["model", "sampling"]}, "effective_params": OBJECT,
        "reward": {"type": "number"}, "reward_refs": array(ARTIFACT, minItems=1),
        "native_inputs_ref": ARTIFACT, "model_call_ref": ARTIFACT,
        "tokenizer_ref": ARTIFACT, "chat_template_ref": ARTIFACT,
        "record_snapshot_ref": ARTIFACT, "source_dataset_id": nullable(STRING), "finish_reason": STRING})
    schemas.register(RL_SAMPLE, obj(row))


def native_rollout_build_spec(input_snapshots, reward_refs, mapper_ref, *, build_id=None, name=None,
                              backend_ref=None, missing_data_policy="reject_build", splits=("train",)):
    """Explicit default contract; callers can persist/review it before building."""
    return {"protocol_version": "gymts.dataset-build/1", "build_id": build_id or new_id("build"),
        "name": name, "builder_ref": copy.deepcopy(BUILDER_REF), "input_snapshots": list(input_snapshots),
        "target": {"format": "rl", "schema_ref": RL_SAMPLE, "backend_ref": backend_ref},
        "selection": inline({"splits": list(splits), "require_complete_capture": True}, "gymts.training/selection/1"),
        "episode_mapping": inline({"kind": "one_call_one_case"}, "gymts.training/episode-mapping/1"),
        "splits": inline({"kind": "source", "group_key": "group_id", "split_key": "split", "cross_split_policy": "reject"},
                         "gymts.training/splits/1"),
        "transforms": [], "reward_mapping": {"mapper_ref": copy.deepcopy(mapper_ref), "params": {}, "source_refs": list(reward_refs)},
        "pairing": None, "tokenization": {"mode": "native_rollout", "tokenizer_ref": None,
            "chat_template_ref": None, "mask_builder_ref": copy.deepcopy(MASK_BUILDER_REF), "reconstructor_ref": None,
            "logprob_policy": "captured", "recompute_policies": []},
        "missing_data_policy": missing_data_policy, "require_sealed_runs": True}


def _payload(gym, value, expected=None):
    gym.schemas.validate("gymts.payload/1", value)
    if expected is not None:
        _require(value["schema_ref"] == expected, "unsupported_payload_schema", "unsupported_capability")
    result = value["value"] if value["storage"] == "inline" else gym.artifacts.read_json(value["artifact_ref"])
    gym.schemas.validate(value["schema_ref"], result)
    return result


def _utc(value):
    point = parse_time(value)
    _require(isinstance(point, datetime), "invalid_utc_timestamp")
    original = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _require(original.utcoffset().total_seconds() == 0, "invalid_utc_timestamp")
    return point


def _references(value):
    if isinstance(value, dict):
        if set(ARTIFACT["required"]) == set(value):
            yield value
        else:
            for child in value.values():
                yield from _references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _references(child)


def _call_unit(gym, frozen, snapshot_ref):
    _require(frozen["result_ref"] is not None, "run_not_sealed")
    registered = gym.records.get_run(frozen["run_id"])
    _require(registered["result_ref"] == frozen["result_ref"], "snapshot_differs_from_committed_run")
    result = gym.artifacts.read_json(frozen["result_ref"])
    _require(result["protocol_version"] == "gymts.run-result/1" and result["run_id"] == frozen["run_id"], "run_identity_mismatch")
    _require(result["status"] == "succeeded" and frozen["status"] == "succeeded", "run_not_succeeded")
    _require(result["evidence_status"] == "complete", "run_evidence_incomplete")
    trace = gym.artifacts.read_json(result["trace_ref"])
    events = trace["events"]
    _require(trace["run_id"] == frozen["run_id"] and len(events) == frozen["through_seq"], "sealed_trace_boundary_mismatch")
    _require([event["seq"] for event in events] == list(range(1, len(events) + 1)) and
             all(event["run_id"] == frozen["run_id"] for event in events), "trace_sequence_mismatch")
    _require(bool(events) and events[-1]["kind"] == "run_end", "missing_run_end")
    grouped = {}
    for event in events:
        grouped.setdefault(event["kind"], []).append(event)
    for kind in ("input", "candidate_output", "task_result", "model_call", "case_end", "candidate_prepare"):
        _require(len(grouped.get(kind, [])) == 1, "requires_one_call_one_case:" + kind, "unsupported_capability")
    input_event, output_event = grouped["input"][0], grouped["candidate_output"][0]
    task_input, output = _payload(gym, input_event["payload"]), _payload(gym, output_event["payload"])
    task_result = _payload(gym, grouped["task_result"][0]["payload"])
    closure = _payload(gym, grouped["case_end"][0]["payload"])
    preparation = _payload(gym, grouped["candidate_prepare"][0]["payload"])
    call_event = grouped["model_call"][0]
    _require(call_event["payload"]["storage"] == "artifact" and call_event["payload"]["schema_ref"] == MODEL_CALL,
             "model_call_requires_native_artifact")
    call_ref = call_event["payload"]["artifact_ref"]
    call = gym.artifacts.read_json(call_ref)
    validate_model_call(call, gym.schemas, gym.artifacts, profile="native_rollout")
    _require(call["status"] == "succeeded", "model_attempt_not_succeeded")
    _require(call["run_id"] == frozen["run_id"] and call["input_id"] == task_input["input_id"] == output["input_id"] and
             call["output_id"] == output_event["links"]["output_id"] == task_result["output_id"], "call_domain_identity_mismatch")
    _require(task_result["input_id"] == task_input["input_id"] and task_result["case_id"] == task_input["case_id"] == closure["case_id"]
             and closure["status"] == "completed", "case_identity_mismatch")
    _require(call["policy_revision"] == preparation["model_revision"] == output["model_revision"], "behavior_policy_revision_mismatch")
    request = gym.artifacts.read_json(call["request_ref"])
    sample = request.get("sample")
    _require(isinstance(sample, dict) and all(isinstance(sample.get(key), str) and sample[key]
             for key in ("sample_id", "group_id", "split")), "missing_public_sample_identity")
    _require(canonical_json(sample) == canonical_json(_payload(gym, task_input["payload"])), "request_differs_from_task_input")
    _require(task_input["alignment_key"].get("sample_id") == sample["sample_id"] and
             task_input["alignment_key"].get("group_id") == sample["group_id"], "sample_alignment_mismatch")
    return {"result": result, "input": task_input, "output": output, "call": call, "call_ref": call_ref,
            "sample": sample, "events": grouped, "snapshot_ref": snapshot_ref}


def _reward(gym, unit, snapshot, reward_index, mapper):
    key = canonical_json(unit["call_ref"])
    candidates = reward_index.get(key, [])
    _require(len(candidates) == 1, "missing_reward" if not candidates else "ambiguous_reward")
    reference, record = candidates[0]
    _require(record["granularity"] == "call" and len(record["target_refs"]) == 1, "unsupported_reward_granularity", "unsupported_capability")
    _require(type(record["value"]) in (int, float) and math.isfinite(record["value"]), "reward_must_be_finite_scalar")
    _require(record["mapper_ref"] == mapper, "reward_mapper_mismatch")
    created = _utc(record["created_at"])
    frozen_outcomes = {(item["outcome_id"], item["revision"]) for item in snapshot["outcome_refs"]}
    sources = []
    for source_ref in record["source_refs"]:
        _require(source_ref["schema_ref"] == "gymts.outcome/1", "reward_source_is_not_outcome")
        outcome = gym.artifacts.read_json(source_ref)
        identity = {key: outcome[key] for key in ("outcome_id", "revision")}
        _require((identity["outcome_id"], identity["revision"]) in frozen_outcomes, "reward_outcome_outside_snapshot")
        _require("training_export" in outcome["allowed_uses"], "outcome_not_authorized_for_training", "permission_denied")
        committed = gym.records.read_outcomes({"run_ids": [unit["call"]["run_id"]],
            "outcome_refs": [identity], "purpose": "training_export"})
        _require(len(committed) == 1 and canonical_json(committed[0]) == canonical_json(outcome), "outcome_revision_mismatch")
        _require(outcome["alignment_key"] == unit["input"]["alignment_key"], "reward_outcome_alignment_mismatch")
        _require(_utc(outcome["recorded_at"]) <= _utc(snapshot["captured_at"]), "outcome_committed_after_snapshot")
        _require(created >= _utc(outcome["available_at"]) and created >= _utc(outcome["recorded_at"]), "reward_predates_its_source")
        sources.append({"outcome_ref": identity, "artifact_ref": source_ref})
    return float(record["value"]), [reference], sources


def _validate_reward_sources(gym, snapshots, rewards):
    """Every requested reward must refer to this fixed, authorized selection."""
    selected = {frozen["run_id"]: snapshot for snapshot in snapshots for frozen in snapshot["runs"]}
    for reference, record in rewards:
        _require(record["granularity"] == "call" and len(record["target_refs"]) == 1,
                 "unsupported_reward_granularity", "unsupported_capability")
        target = record["target_refs"][0]
        _require(target["schema_ref"] == MODEL_CALL, "reward_target_is_not_model_call")
        call = gym.artifacts.read_json(target)
        run_id = call["run_id"]
        _require(run_id in selected, "reward_target_outside_snapshot")
        snapshot = selected[run_id]
        _require(next(item["result_ref"] for item in snapshot["runs"] if item["run_id"] == run_id) is not None,
                 "run_not_sealed")
        committed = gym.records.get_run(run_id)
        _require(any(event["kind"] == "model_call" and event["seq"] <= next(
            item["through_seq"] for item in snapshot["runs"] if item["run_id"] == run_id)
            and event["payload"].get("artifact_ref") == target for event in committed["events"]),
            "reward_target_not_committed_in_snapshot")
        outcome_ids = {(item["outcome_id"], item["revision"]) for item in snapshot["outcome_refs"]}
        created = _utc(record["created_at"])
        for source in record["source_refs"]:
            _require(source["schema_ref"] == "gymts.outcome/1", "reward_source_is_not_outcome")
            outcome = gym.artifacts.read_json(source)
            identity = {key: outcome[key] for key in ("outcome_id", "revision")}
            _require((identity["outcome_id"], identity["revision"]) in outcome_ids, "reward_outcome_outside_snapshot")
            _require("training_export" in outcome["allowed_uses"], "outcome_not_authorized_for_training", "permission_denied")
            actual = gym.records.read_outcomes({"run_ids": [run_id], "outcome_refs": [identity], "purpose": "training_export"})
            _require(len(actual) == 1 and actual[0] == outcome, "outcome_revision_mismatch")
            _require(_utc(outcome["recorded_at"]) <= _utc(snapshot["captured_at"]), "outcome_committed_after_snapshot")
            _require(created >= _utc(outcome["available_at"]) and created >= _utc(outcome["recorded_at"]), "reward_predates_its_source")


def _build_native_dataset(gym, build_spec):
    """Build and publish a formal Manifest only after every output is committed."""
    register_training_schemas(gym.schemas)
    spec = copy.deepcopy(build_spec)
    spec.setdefault("require_sealed_runs", True)
    gym.schemas.validate("gymts.dataset-build/1", spec)
    _require(spec["builder_ref"] == BUILDER_REF, "unsupported_builder", "unsupported_capability")
    _require(spec["target"]["format"] == "rl" and spec["target"]["schema_ref"] == RL_SAMPLE, "unsupported_training_target", "unsupported_capability")
    _require(spec["require_sealed_runs"] and spec["pairing"] is None and not spec["transforms"], "unsupported_build_transforms_or_boundary", "unsupported_capability")
    selection = _payload(gym, spec["selection"], "gymts.training/selection/1")
    _require(selection["splits"] == ["train"], "this_builder_exports_training_partition_only", "permission_denied")
    _payload(gym, spec["episode_mapping"], "gymts.training/episode-mapping/1")
    _payload(gym, spec["splits"], "gymts.training/splits/1")
    tokenization = spec["tokenization"]
    _require(tokenization is not None and tokenization["mode"] == "native_rollout" and
             tokenization["logprob_policy"] == "captured" and tokenization["mask_builder_ref"] == MASK_BUILDER_REF
             and tokenization["reconstructor_ref"] is None and not tokenization["recompute_policies"],
             "unsupported_tokenization_contract", "unsupported_capability")
    mapping = spec["reward_mapping"]
    _require(mapping is not None and mapping["params"] == {}, "explicit_scalar_reward_mapping_required", "unsupported_capability")
    for component in (mapping["mapper_ref"], spec["target"]["backend_ref"]):
        if component is not None:
            _require(component["version"] not in {"latest", "main", "master"}, "mutable_component_revision")
    reward_index, reward_ids, rewards = {}, set(), []
    for reference in mapping["source_refs"]:
        _require(reference["schema_ref"] == REWARD, "reward_mapping_requires_reward_records")
        record = gym.artifacts.read_json(reference)
        gym.schemas.validate(REWARD, record)
        _require(record["reward_id"] not in reward_ids, "duplicate_reward_identity")
        reward_ids.add(record["reward_id"])
        _require(record["mapper_ref"] == mapping["mapper_ref"], "reward_mapper_mismatch")
        rewards.append((reference, record))
        for target in record["target_refs"]:
            reward_index.setdefault(canonical_json(target), []).append((reference, record))
    snapshots, units, seen_runs = [], [], set()
    for reference in spec["input_snapshots"]:
        snapshot = gym.records.get_snapshot(reference)
        gym.schemas.validate("gymts.record-snapshot/1", {key: value for key, value in snapshot.items()
                                                       if key != "snapshot_ref"})
        _utc(snapshot["captured_at"])
        snapshots.append(snapshot)
        for frozen in snapshot["runs"]:
            _require(frozen["run_id"] not in seen_runs, "duplicate_run_selection")
            seen_runs.add(frozen["run_id"])
            units.append((snapshot, frozen))
    _validate_reward_sources(gym, snapshots, rewards)
    build_spec_ref = gym.artifacts.save_json(spec, "gymts.dataset-build/1")
    rows, lineage, excluded, groups = [], [], [], {}
    for snapshot, frozen in units:
        try:
            unit = _call_unit(gym, frozen, snapshot["snapshot_ref"])
            sample, call = unit["sample"], unit["call"]
            previous = groups.setdefault(sample["group_id"], sample["split"])
            _require(previous == sample["split"], "group_crosses_source_partitions", "permission_denied")
            if sample["split"] not in selection["splits"]:
                excluded.append({"run_id": frozen["run_id"], "reason": "split_not_selected", "group_id": sample["group_id"]})
                continue
            if selection["require_complete_capture"]:
                _require(call["capture"]["completeness"] == "complete", "model_call_capture_incomplete")
            _require(call["logprobs_ref"] is not None, "captured_logprobs_required")
            probabilities = gym.artifacts.read_json(call["logprobs_ref"])
            _require(probabilities["source"] == "captured", "captured_logprobs_required")
            response = gym.artifacts.read_json(call["response_ref"])
            finish = response.get("finish_reason")
            _require(finish in {"eos", "stop", "stopping_criteria"}, "truncated_or_unknown_completion")
            for field in ("tokenizer_ref", "chat_template_ref"):
                _require(tokenization[field] is None or tokenization[field] == call[field], "tokenizer_or_template_mismatch")
            native = gym.artifacts.read_json(call["native_inputs_ref"])
            for reference in _references(native):
                gym.artifacts.resolve(reference)
            prompt = gym.artifacts.read_json(call["prompt_token_ids_ref"])
            completion = gym.artifacts.read_json(call["response_token_ids_ref"])
            reward, reward_refs, reward_sources = _reward(gym, unit, snapshot, reward_index, mapping["mapper_ref"])
            sample_id = digest({"builder": BUILDER_REF, "run_id": frozen["run_id"], "call_id": call["call_id"],
                                "attempt_id": call["attempt_id"]})
            episode_id = digest({"run_id": frozen["run_id"], "case_id": unit["input"]["case_id"]})
            action_mask = [0] * len(prompt) + [1] * len(completion)
            row = {"schema_version": RL_SAMPLE, "sample_id": sample_id, "source_sample_id": sample["sample_id"],
                "episode_id": episode_id, "group_id": sample["group_id"], "split": sample["split"],
                "run_id": call["run_id"], "case_id": unit["input"]["case_id"], "input_id": call["input_id"],
                "output_id": call["output_id"], "call_id": call["call_id"], "attempt_id": call["attempt_id"],
                "policy_revision": call["policy_revision"], "prompt_ids": prompt, "completion_ids": completion,
                "input_ids": prompt + completion, "attention_mask": [1] * (len(prompt) + len(completion)),
                "action_mask": action_mask, "loss_mask": list(action_mask), "completion_mask": [1] * len(completion),
                "old_per_token_logps": probabilities["values"], "logprob_distribution": probabilities["distribution"],
                "effective_params": call["effective_params"], "reward": reward, "reward_refs": reward_refs,
                "native_inputs_ref": call["native_inputs_ref"], "model_call_ref": unit["call_ref"],
                "tokenizer_ref": call["tokenizer_ref"], "chat_template_ref": call["chat_template_ref"],
                "record_snapshot_ref": snapshot["snapshot_ref"], "source_dataset_id": sample.get("dataset_id"), "finish_reason": finish}
            gym.schemas.validate(RL_SAMPLE, row)
            rows.append(row)
            lineage.append({"sample_id": sample_id, "episode_id": episode_id, "run_id": call["run_id"],
                "case_id": unit["input"]["case_id"], "input_id": call["input_id"], "output_id": call["output_id"],
                "call_id": call["call_id"], "attempt_id": call["attempt_id"], "model_call_ref": unit["call_ref"],
                "event_ids": {kind: [event["event_id"] for event in events] for kind, events in unit["events"].items()},
                "record_snapshot_ref": snapshot["snapshot_ref"], "run_result_ref": frozen["result_ref"],
                "token_ranges": {"prompt": [0, len(prompt)], "response": [len(prompt), len(prompt) + len(completion)]},
                "segment_rule": "one_call_one_case", "reward_allocation": "full_call_scalar", "reward_refs": reward_refs,
                "reward_sources": reward_sources, "source_sample_id": sample["sample_id"], "group_id": sample["group_id"]})
        except GymTSError as error:
            if spec["missing_data_policy"] == "reject_build" or error.code == "persistence_failed":
                raise
            excluded.append({"run_id": frozen["run_id"], "reason": str(error), "code": error.code})
    # A related group crossing a partition is a split contract violation, even
    # when the offending row would otherwise be excluded for missing evidence.
    if any(item.get("reason") == "group_crosses_source_partitions" for item in excluded):
        raise GymTSError("permission_denied", "group_crosses_source_partitions", stage="dataset_build")
    lineage_ref = gym.artifacts.save_json({"protocol_version": "gymts.lineage/1", "records": lineage}, "gymts.lineage/1")
    exclusion_ref = gym.artifacts.save_json({"counts": dict(Counter(item["reason"] for item in excluded)), "records": excluded},
                                          "gymts.training/exclusions/1")
    tokenization_ref = gym.artifacts.save_json(tokenization, "gymts.training/tokenization/1")
    shards = []
    for split in selection["splits"]:
        selected = [row for row in rows if row["split"] == split]
        content = b"".join(canonical_json(row) + b"\n" for row in selected)
        reference = gym.artifacts.save_artifact(content, {"media_type": "application/x-ndjson", "schema_ref": RL_SAMPLE})
        shards.append({"split": split, "artifact_ref": reference, "sample_count": len(selected)})
    manifest = {"protocol_version": "gymts.dataset/1", "dataset_id": digest({"builder": BUILDER_REF, "build_id": spec["build_id"]}),
        "build_id": spec["build_id"], "build_spec_ref": build_spec_ref, "builder_ref": copy.deepcopy(BUILDER_REF),
        "input_snapshot_refs": spec["input_snapshots"], "output_schema_ref": RL_SAMPLE, "shards": shards,
        "counts": {"input_units": len(units), "accepted_samples": len(rows), "excluded_units": len(excluded)},
        "lineage_ref": lineage_ref, "exclusion_summary_ref": exclusion_ref, "tokenization_ref": tokenization_ref,
        "reward_refs": mapping["source_refs"], "created_at": utc_now()}
    manifest["revision"] = digest(manifest)
    gym.schemas.validate("gymts.dataset/1", manifest)
    manifest_ref = gym.artifacts.save_json(manifest, "gymts.dataset/1")
    return dict(manifest, manifest_ref=manifest_ref)


def read_dataset_rows(gym, manifest_ref, split="train"):
    """Read verified committed shards; never query a live rollout queue."""
    register_training_schemas(gym.schemas)
    if isinstance(manifest_ref, dict) and "manifest_ref" in manifest_ref:
        manifest_ref = manifest_ref["manifest_ref"]
    _require(manifest_ref["schema_ref"] == "gymts.dataset/1", "expected_dataset_manifest")
    manifest = gym.artifacts.read_json(manifest_ref)
    gym.schemas.validate("gymts.dataset/1", manifest)
    _require(manifest["builder_ref"] == BUILDER_REF and manifest["revision"] == digest({
        key: value for key, value in manifest.items() if key != "revision"}), "dataset_manifest_revision_mismatch")
    _require(manifest["output_schema_ref"] == RL_SAMPLE, "unsupported_dataset_schema", "unsupported_capability")
    rows = []
    for shard in manifest["shards"]:
        if shard["split"] != split:
            continue
        reference = shard["artifact_ref"]
        content = gym.artifacts.resolve(reference).read_bytes()
        _require(len(content) == reference["size_bytes"] and hashlib.sha256(content).hexdigest() == reference["content_hash"],
                 "dataset_shard_integrity", "artifact_integrity")
        selected = [json.loads(line) for line in content.splitlines() if line]
        _require(len(selected) == shard["sample_count"], "dataset_shard_count_mismatch")
        for row in selected:
            gym.schemas.validate(RL_SAMPLE, row)
            _require(row["split"] == split, "dataset_shard_partition_mismatch")
            prompt, completion = row["prompt_ids"], row["completion_ids"]
            mask = [0] * len(prompt) + [1] * len(completion)
            _require(row["input_ids"] == prompt + completion and row["attention_mask"] == [1] * len(mask)
                     and row["action_mask"] == row["loss_mask"] == mask
                     and row["completion_mask"] == [1] * len(completion)
                     and len(row["old_per_token_logps"]) == len(completion), "dataset_native_sequence_alignment_mismatch")
        rows.extend(selected)
    return rows


class _EvidenceServices:
    """Only evidence services and profile schemas; no execution/orchestrator."""
    __slots__ = ("records", "artifacts", "schemas")

    def __init__(self, records, artifacts):
        from .contracts import rl_schemas
        self.records, self.artifacts = records, artifacts
        self.schemas = SchemaRegistry()
        register_core_schemas(self.schemas)
        register_training_schemas(self.schemas)
        for reference, definition in rl_schemas().items():
            self.schemas.register(reference, definition)


class NativeRolloutBuilder:
    """Fixed one-call/one-case QA export provider, independent of GymTS."""
    builder_ref = BUILDER_REF
    target_formats = ("rl",)
    output_schema_refs = (RL_SAMPLE,)

    def build(self, spec, records, artifacts):
        return _build_native_dataset(_EvidenceServices(records, artifacts), spec)


def build_dataset(gym, build_spec):
    """Legacy adapter helper; new callers use gymts.training.build_dataset.

    Retains the old two-argument helper without making an entire GymTS object
    part of the public provider contract or requiring entry-point installation.
    """
    from gymts.training import DatasetBuilderRegistry, build_dataset as dispatch
    register_training_schemas(gym.schemas)
    providers = DatasetBuilderRegistry(discover=False)
    providers.register(BUILDER_REF, NativeRolloutBuilder())
    return dispatch(build_spec, gym.records, gym.artifacts, builders=providers)


def read_native_dataset_rows(manifest_ref, artifacts, split="train"):
    """Consume the published native profile without a GymTS orchestrator."""
    return read_dataset_rows(_EvidenceServices(None, artifacts), manifest_ref, split)


__all__ = ["BUILDER_REF", "MASK_BUILDER_REF", "RL_SAMPLE", "REWARD",
           "register_training_schemas", "native_rollout_build_spec",
           "build_dataset", "read_dataset_rows", "read_native_dataset_rows", "NativeRolloutBuilder"]
