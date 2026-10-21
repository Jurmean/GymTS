"""Public DatasetBuilderProvider for the exact sealed native TIR tensor rows."""
from gymts.contracts import GymTSError, digest, utc_now
from gymts.plugin_support import component
from .contracts import BUILDER, CODEC, MASK, ROLLOUT, SHARD
from .tensors import validate_native_tensors


class SealedTIRBuilder:
    builder_ref = BUILDER
    target_formats = ("rl",)
    output_schema_refs = (SHARD,)

    def build(self, spec, records, artifacts):
        if (not spec["require_sealed_runs"] or spec["tokenization"] is None or spec["reward_mapping"] is None
                or spec["tokenization"]["mode"] != "native_rollout"):
            raise GymTSError("unsupported_capability", "AReaL training requires sealed native rollout evidence")
        rows, lineage, rewards = [], [], []
        for snapshot_ref in spec["input_snapshots"]:
            snapshot = records.get_snapshot(snapshot_ref)
            for frozen in snapshot["runs"]:
                run = records.get_run(frozen["run_id"])
                if frozen["status"] != "succeeded" or frozen["result_ref"] != run["result_ref"]:
                    raise GymTSError("invalid_dataset", "AReaL training requires the complete successful sealed Run")
                if frozen["through_seq"] != run["events"][-1]["seq"]:
                    raise GymTSError("invalid_dataset", "AReaL training rejects prefix snapshots")
                refs = [ref for ref in run["result"]["artifact_refs"] if ref["schema_ref"] == ROLLOUT]
                if len(refs) != 1:
                    raise GymTSError("invalid_dataset", "Expected exactly one native TIR tensor artifact per Run")
                rollout = artifacts.read_json(refs[0])
                expected_transforms = [{"component_ref": CODEC, "params": {"stage": "already_applied_in_live_Run", "reapply": False}}]
                if rollout["codec"] != CODEC or spec["transforms"] != expected_transforms:
                    raise GymTSError("unsupported_capability", "Builder 2 requires recorded CODEC 2 identity; use the original frozen builder for CODEC 1 evidence")
                if rollout["sample"]["split"] != "train":
                    raise GymTSError("permission_denied", "Held-out evaluation episodes cannot enter AReaL training")
                events = [artifacts.read_json(ref) for ref in rollout["native_events"]]
                validation = validate_native_tensors(rollout["native_tensors"], events,
                    expected_version=rollout["native_policy_version"],
                    max_length=spec["reward_mapping"]["params"]["max_length"], reward=rollout["reward"])
                if validation != rollout["validation"]:
                    raise GymTSError("conflict", "Sealed TIR tensor validation differs from execution evidence")
                audit = artifacts.read_json(rollout["reward_audit_ref"])
                if audit.get("answer_codec_ref") != rollout["codec"]:
                    raise GymTSError("conflict", "Sealed reward audit and native rollout use different answer codecs")
                if audit["status"] != "succeeded" or audit["sample_id"] != rollout["sample"]["sample_id"] or audit["split"] != "train":
                    raise GymTSError("invalid_dataset", "Training reward is missing, failed, or belongs to another input")
                reward = {"protocol_version": "gymts.reward/1", "reward_id": "areal-" + run["run_id"],
                    "target_refs": [refs[0]], "granularity": "episode", "value": rollout["reward"],
                    "source_refs": [rollout["reward_audit_ref"]], "mapper_ref": component("areal.private-verifiable-reward"), "created_at": utc_now()}
                reward_ref = artifacts.save_json(reward, "gymts.reward/1")
                rewards.append(reward_ref)
                row = {"run_id": run["run_id"], "record_snapshot_ref": snapshot_ref,
                    "rollout_ref": refs[0], "answer_codec_ref": rollout["codec"], "sample_id": rollout["sample"]["sample_id"],
                    "split": "train", "policy_revision": rollout["policy_revision"],
                    "native_policy_version": rollout["native_policy_version"], "reward_ref": reward_ref,
                    "native_tensors": rollout["native_tensors"], "native_tensor_sha256": validation["native_tensor_sha256"]}
                rows.append(row)
                lineage.append({key: row[key] for key in ("run_id", "record_snapshot_ref", "rollout_ref", "sample_id", "policy_revision", "reward_ref", "answer_codec_ref")})
        if not rows:
            raise GymTSError("invalid_dataset", "AReaL sealed TIR build has no native rows")
        shard_ref = artifacts.save_json({"schema_version": SHARD, "rows": rows}, SHARD)
        manifest = {"protocol_version": "gymts.dataset/1", "dataset_id": "areal-sealed-tir-" + spec["build_id"],
            "revision": digest(rows), "build_id": spec["build_id"],
            "build_spec_ref": artifacts.save_json(spec, "gymts.dataset-build/1"), "builder_ref": BUILDER,
            "input_snapshot_refs": spec["input_snapshots"], "output_schema_ref": SHARD,
            "shards": [{"split": "train", "artifact_ref": shard_ref, "sample_count": len(rows)}],
            "counts": {"input_units": len(rows), "accepted_samples": len(rows), "excluded_units": 0},
            "lineage_ref": artifacts.save_json({"protocol_version": "gymts.lineage/1", "records": lineage}, "gymts.lineage/1"),
            "exclusion_summary_ref": artifacts.save_json({"counts": {}, "records": []}, "gymts.training/exclusions/1"),
            "tokenization_ref": artifacts.save_json(spec["tokenization"], "gymts.training/tokenization/1"),
            "reward_refs": rewards, "created_at": utc_now()}
        return manifest


def build_spec(snapshot_ref, rollout, *, max_length):
    from gymts.contracts import inline, new_id
    return {"protocol_version": "gymts.dataset-build/1", "build_id": new_id("areal-build"),
        "name": "Sealed live native TIR training episode", "builder_ref": BUILDER,
        "input_snapshots": [snapshot_ref], "target": {"format": "rl", "schema_ref": SHARD,
            "backend_ref": component("areal.PPOTrainer", "2.1.0")},
        "selection": inline({"all_native_episodes": True}, "gymts.json/1"),
        "episode_mapping": inline({"one_row_per_run": True}, "gymts.json/1"),
        "splits": inline({"train_only": True}, "gymts.json/1"),
        "transforms": [{"component_ref": CODEC, "params": {"stage": "already_applied_in_live_Run", "reapply": False}}],
        "reward_mapping": {"mapper_ref": component("areal.private-verifiable-reward"),
            "params": {"max_length": max_length, "answer_codec_ref": rollout["codec"]}, "source_refs": [rollout["reward_audit_ref"]]},
        "pairing": None, "tokenization": {"mode": "native_rollout", "tokenizer_ref": rollout["tokenizer_ref"],
            "chat_template_ref": rollout["chat_template_ref"], "mask_builder_ref": MASK,
            "reconstructor_ref": None, "logprob_policy": "captured", "recompute_policies": []},
        "missing_data_policy": "reject_build", "require_sealed_runs": True}
