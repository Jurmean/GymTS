"""Trusted local coordinator: live Runs first, frozen dataset consumption second."""
import copy
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import socketserver
import socket
import threading
import time
from collections import Counter

from gymts.contracts import GymTSError, digest, inline, new_id, utc_now
from gymts.training import build_dataset
from gymts_rl.contracts import OUTCOME, SNAPSHOT
from gymts_rl.pipeline import experiment_spec
from gymts_rl.rewards import score_completion
from .builder import build_spec
from .candidate import ACTIVE
from .codec import project_completion
from .contracts import PINNED_REVISION, REWARD_AUDIT, PROMPT_PROJECTION, CODEC
from .wire import receive, send, sha


@dataclass
class Channel:
    owner: object
    stream: object
    header: dict
    sample: dict
    rollout_ref: object = None


class BridgeService:
    def __init__(self, gym, prepared, directory, *, max_episodes=64):
        self.gym, self.prepared = gym, prepared
        self.bridge_id = new_id("areal-bridge")
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=False, mode=0o700)
        self.path = self.directory / "bridge.sock"
        self.max_episodes = max_episodes
        manifest = gym.artifacts.read_json(prepared["manifest_ref"])
        for field in ("snapshot_ref", "private_ref", "dataset_revision"):
            if manifest[field] != prepared[field]:
                raise ValueError("Prepared source differs from its immutable manifest: " + field)
        public_snapshot = gym.artifacts.read_json(manifest["snapshot_ref"])
        private_snapshot = gym.artifacts.read_json(manifest["private_ref"])
        if any(snapshot["dataset_revision"] != manifest["dataset_revision"] for snapshot in (public_snapshot, private_snapshot)):
            raise ValueError("Source snapshot revisions differ from the immutable manifest")
        gym.schemas.validate(SNAPSHOT, public_snapshot)
        self.public = {row["sample_id"]: row for row in public_snapshot["samples"]}
        self.private = {row["sample_id"]: row for row in private_snapshot["samples"]}
        if (len(self.public) != len(public_snapshot["samples"]) or len(self.private) != len(private_snapshot["samples"]) or
                set(self.public) != set(self.private)):
            raise ValueError("Public and private RL members differ")
        for sample_id, sample in self.public.items():
            if any(sample[key] != self.private[sample_id][key] for key in ("sample_id", "group_id", "dataset_id", "task_id", "split")):
                raise ValueError("Private reference does not belong to the public source member")
        groups = {split: {row["group_id"] for row in self.public.values() if row["split"] == split} for split in ("train", "eval")}
        if groups["train"] & groups["eval"]:
            raise ValueError("Training and held-out groups overlap")
        for split in ("train", "eval"):
            ids = [row["sample_id"] for row in self.public.values() if row["split"] == split]
            if len(ids) != manifest["counts"][split] or set(ids) != set(manifest[split + "_sample_ids"]):
                raise ValueError("Source partition differs from its immutable manifest")
        self.versions, self.episodes, self.training_events, self.failures = {}, [], [], []
        self._episode_lock, self._metadata_lock = threading.Lock(), threading.Lock()
        self._active, self._closed, self.drain_status = {}, False, "not_closed"
        owner = self
        class Handler(socketserver.StreamRequestHandler):
            def setup(self):
                super().setup()
                with owner._metadata_lock:
                    owner._active[threading.current_thread()] = self.request

            def finish(self):
                try:
                    super().finish()
                finally:
                    with owner._metadata_lock:
                        owner._active.pop(threading.current_thread(), None)

            def handle(self):
                self.request.settimeout(900)
                try:
                    message = receive(self.rfile)
                    if message["kind"] == "episode":
                        owner.episode(self.wfile, self.rfile, message)
                    elif message["kind"] == "policy_version":
                        owner.policy_version(message)
                        send(self.wfile, {"kind": "ack"})
                    elif message["kind"] == "training_event":
                        owner.training_event(message)
                        send(self.wfile, {"kind": "ack"})
                    else:
                        raise ValueError("Unsupported AReaL coordinator operation")
                except Exception as error:
                    with owner._metadata_lock:
                        owner.failures.append({"type": type(error).__name__, "message": str(error)})
                    try:
                        send(self.wfile, {"kind": "error", "message": str(error)})
                    except (OSError, ValueError):
                        pass
        class Server(socketserver.ThreadingUnixStreamServer):
            daemon_threads = True
        self.server = Server(str(self.path), Handler)
        os.chmod(self.path, 0o600)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        with self._metadata_lock:
            active = list(self._active.items())
        for _thread, connection in active:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        deadline = time.monotonic() + 30
        for thread, _connection in active:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        self.drain_status = "sealed_handlers_drained" if not any(thread.is_alive() for thread, _ in active) else "incomplete_handler_drain"
        if self.drain_status != "sealed_handlers_drained":
            raise RuntimeError("Owned native handlers did not finish sealing within the bounded shutdown period")

    def policy_version(self, message):
        if message["bridge_id"] != self.bridge_id:
            raise ValueError("Policy map belongs to another coordinator")
        version = message["native_policy_version"]
        with self._metadata_lock:
            if version in self.versions and self.versions[version] != message:
                raise ValueError("One native policy version maps to different weights")
            self.versions[version] = copy.deepcopy(message)
            self.gym.artifacts.save_json(message, "gymts.json/1")

    def grade(self, sample, event, *, terminal_tokens):
        request_ref = self.gym.artifacts.save_json(event, "gymts.json/1")
        projected, conversion = project_completion(event["completion"], sample["task_id"], terminal_tokens)
        audit = {"sample_id": sample["sample_id"], "split": sample["split"], "request_ref": request_ref,
                 "codec_result": conversion, "answer_codec_ref": CODEC, "reference_ref": self.prepared["private_ref"], "created_at": utc_now()}
        try:
            if sample["split"] == "eval":
                result = {"reward": 0.0, "reason": "evaluation_native_noop_reward; independent gold not read", "correct": None}
            else:
                result = score_completion(projected, self.private[sample["sample_id"]]["reward_spec"])
                if not math.isfinite(result["reward"]):
                    raise ValueError("Trusted verifier returned nonfinite reward")
            audit.update(status="succeeded", result=result,
                reference_member_sha256=digest(self.private[sample["sample_id"]]) if sample["split"] == "train" else None)
        except Exception as error:
            audit.update(status="failed", error={"type": type(error).__name__, "message": str(error)})
            self.gym.artifacts.save_json(audit, REWARD_AUDIT)
            raise
        ref = self.gym.artifacts.save_json(audit, REWARD_AUDIT)
        return result["reward"], ref

    def episode(self, writer, reader, header):
        class Duplex:
            def readline(self, *args): return reader.readline(*args)
            def write(self, value): return writer.write(value)
            def flush(self): return writer.flush()
        with self._episode_lock:
            if len(self.episodes) >= self.max_episodes:
                raise ValueError("AReaL fixed episode budget exhausted")
            if header["bridge_id"] != self.bridge_id or header["native_revision"] != PINNED_REVISION:
                raise ValueError("Native TIR episode identity differs from the fixed coordinator")
            sample = self.public[header["sample_id"]]
            if header["sample_sha256"] != sha(sample):
                raise ValueError("Native trainer data differs from the public snapshot")
            version = self.versions[header["native_policy_version"]]
            if version["policy_revision"] != header["policy_revision"]:
                raise ValueError("Native policy version/weights map differs from the episode")
            channel = Channel(self, Duplex(), header, sample)
            spec = experiment_spec(self.prepared["snapshot_ref"], self.prepared["dataset_revision"], sample, {}, header["seed"])
            spec["name"] = "Native AReaL live TIR " + sample["task_id"]
            spec["candidate"] = {"adapter": "areal-live-tir", "version": "1.0.0", "artifact": None, "inherited_state": [],
                "params": {"bridge_id": self.bridge_id, "policy_revision": header["policy_revision"],
                    "model_ref": header["model_ref"], "native_revision": PINNED_REVISION}}
            spec["candidate"]["params"]["prompt_projection_ref"] = PROMPT_PROJECTION
            spec["candidate"]["params"]["answer_codec_ref"] = CODEC
            ACTIVE.channel = channel
            try:
                result = self.gym.run(spec)
            finally:
                ACTIVE.channel = None
            run = self.gym.records.get_run(result["run_id"])
            entry = {"run_id": result["run_id"], "sample_id": sample["sample_id"], "split": sample["split"],
                     "status": result["status"], "sealed_result_ref": run["result_ref"]}
            self.episodes.append(entry)
            if result["status"] != "succeeded" or channel.rollout_ref is None:
                raise GymTSError("native_failure", "Native TIR Run failed before sealed training handoff", links={"run_id": result["run_id"]})
            rollout = self.gym.artifacts.read_json(channel.rollout_ref)
            snapshot = self.gym.records.snapshot([result["run_id"]])
            if sample["split"] == "train":
                manifest = build_dataset(build_spec(snapshot["snapshot_ref"], rollout, max_length=header["max_length"]),
                    self.gym.records, self.gym.artifacts)
                shard = self.gym.artifacts.read_json(manifest["shards"][0]["artifact_ref"])
                row = shard["rows"][0]
                if row["rollout_ref"] != channel.rollout_ref or row["native_tensors"] != rollout["native_tensors"]:
                    raise ValueError("Dataset builder substituted the sealed native TIR tensor row")
                entry.update(snapshot_ref=snapshot["snapshot_ref"], manifest_ref=manifest["manifest_ref"],
                             native_tensor_sha256=row["native_tensor_sha256"], native_tensors=row["native_tensors"])
            else:
                entry.update(snapshot_ref=snapshot["snapshot_ref"], manifest_ref=None,
                             native_tensor_sha256=rollout["validation"]["native_tensor_sha256"], native_tensors=rollout["native_tensors"])
                self.attach_outcome(result["run_id"], sample)
            send(channel.stream, {"kind": "sealed", "run_id": result["run_id"], "snapshot_ref": snapshot["snapshot_ref"],
                "manifest_ref": entry["manifest_ref"], "native_tensor_sha256": entry["native_tensor_sha256"],
                "native_tensors": entry["native_tensors"]})

    def attach_outcome(self, run_id, sample):
        stamp = utc_now()
        self.gym.records.attach_outcomes(run_id, [{"outcome_id": "areal-heldout-" + sample["sample_id"], "revision": "1",
            "alignment_key": {"dataset_revision": self.prepared["dataset_revision"], "sample_id": sample["sample_id"], "group_id": sample["group_id"]},
            "payload": inline({"sample_id": sample["sample_id"], "task_id": sample["task_id"],
                "reward_spec": self.private[sample["sample_id"]]["reward_spec"]}, OUTCOME),
            "event_time": None, "available_at": stamp, "recorded_at": None, "source_ref": self.prepared["private_ref"],
            "supersedes_ref": None, "allowed_uses": ["evaluation"]}])

    def training_event(self, message):
        if message["bridge_id"] != self.bridge_id:
            raise ValueError("Training event belongs to another coordinator")
        event = message["event"]
        if event["kind"] == "consume_batch":
            expected = Counter(entry.get("native_tensor_sha256") for entry in self.episodes if entry["split"] == "train" and entry["status"] == "succeeded")
            if not event["row_hashes"] or Counter(event["row_hashes"]) - expected:
                raise ValueError("Native trainer consumed rows outside sealed Run manifests")
        ref = self.gym.artifacts.save_json(message, "gymts.json/1")
        with self._metadata_lock:
            self.training_events.append({"event": event, "artifact_ref": ref})

    def summary(self):
        return {"bridge_id": self.bridge_id, "episodes": self.episodes, "policy_versions": list(self.versions.values()),
                "training_events": self.training_events, "failures": self.failures, "drain_status": self.drain_status}
