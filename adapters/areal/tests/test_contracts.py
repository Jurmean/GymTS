import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from gymts_areal.codec import native_messages, project_completion
from gymts_areal.tensors import validate_native_tensors
from gymts_areal.cli import worker_environment


def fixture():
    events = [
        {"kind": "model_aggregate", "response": {"input_tokens": [10, 11], "output_tokens": [20],
            "output_logprobs": [-0.5], "output_versions": [0], "stop_reason": "stop"}},
        {"kind": "tool_projection", "token_ids": [30, 31]},
        {"kind": "model_aggregate", "response": {"input_tokens": [10, 11, 20, 30, 31], "output_tokens": [21],
            "output_logprobs": [-1.0], "output_versions": [0], "stop_reason": "stop"}},
    ]
    arrays = {"input_ids": ("int64", [[10, 11, 20, 30, 31, 21]]),
        "logprobs": ("float32", [[0.0, 0.0, -0.5, 0.0, 0.0, -1.0]]),
        "loss_mask": ("int64", [[0, 0, 1, 0, 0, 1]]), "versions": ("int64", [[-1, -1, 0, -1, -1, 0]]),
        "attention_mask": ("bool", [[True] * 6]), "rewards": ("float32", [0.5]), "is_truncated": ("bool", [False])}
    tensors = {name: {"dtype": dtype, "shape": [1, len(values[0])] if isinstance(values[0], list) else [1],
                       "values": values} for name, (dtype, values) in arrays.items()}
    return tensors, events


class NativeContracts(unittest.TestCase):
    def test_original_model_tool_masks_and_likelihoods(self):
        tensors, events = fixture()
        validation = validate_native_tensors(tensors, events, expected_version=0, max_length=6, reward=0.5)
        self.assertEqual((validation["generated_trainable_tokens"], validation["tool_masked_tokens"]), (2, 2))
        tensors["loss_mask"]["values"][0][3] = 1
        with self.assertRaisesRegex(ValueError, "masks or versions"):
            validate_native_tensors(tensors, events, expected_version=0, max_length=6, reward=0.5)

    def test_reject_changed_probability_policy_or_reward(self):
        for field in ("logprobs", "versions", "rewards"):
            tensors, events = fixture()
            if field == "rewards": tensors[field]["values"][0] = 1.0
            else: tensors[field]["values"][0][2] += 0.1
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_native_tensors(tensors, events, expected_version=0, max_length=6, reward=0.5)

    def test_reject_truncation_and_unconsumed_tool(self):
        tensors, events = fixture()
        with self.assertRaisesRegex(ValueError, "sequence length"):
            validate_native_tensors(tensors, events, expected_version=0, max_length=5, reward=0.5)
        tensors["is_truncated"]["values"] = [True]
        with self.assertRaisesRegex(ValueError, "Truncated"):
            validate_native_tensors(tensors, events, expected_version=0, max_length=6, reward=0.5)
        tensors["is_truncated"]["values"] = [False]
        events.append({"kind": "tool_projection", "token_ids": [99]})
        with self.assertRaisesRegex(ValueError, "consuming"):
            validate_native_tensors(tensors, events, expected_version=0, max_length=6, reward=0.5)

    def test_boxed_codec_is_gold_free_and_does_not_repair_answers(self):
        self.assertEqual(project_completion("Reasoning \\boxed{1,024}", "gsm8k.numeric")[0], "#### 1024")
        valid = '{"mean":1,"last":2,"min":-1,"max":3}'
        self.assertEqual(project_completion("\\boxed{" + valid + "}", "chatts.numeric_summary")[0], valid)
        for text in ("\\boxed{2} trailing", "\\boxed{2+3}", "\\boxed{\\frac{1}{2}}", "No answer"):
            projected, metadata = project_completion(text, "gsm8k.numeric")
            self.assertEqual(projected, text)
            self.assertFalse(metadata["converted"])

    def test_all_public_series_values_are_rendered_once(self):
        sample = {"task_id": "chatts.numeric_summary", "messages": [{"role": "user", "content": "A <ts><ts/> B <ts><ts/>"}],
                  "timeseries": [[1.125, 2.25], [3.5, 4.75]]}
        original = copy.deepcopy(sample)
        from gymts_areal.codec import CALCULATOR_INSTRUCTION
        self.assertEqual(native_messages(sample)[0]["content"], "A [1.125,2.25] B [3.5,4.75]\n" + CALCULATOR_INSTRUCTION)
        self.assertEqual(sample, original)

    def test_worker_uses_no_implicit_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            identity = os.path.join(temporary, "identity.json")
            with open(identity, "w") as stream: json.dump({}, stream)
            with patch.dict(os.environ, {"UNEXPECTED_PRIVATE_TOKEN": "contract-fixture", "PYTHONPATH": temporary}):
                env = worker_environment(temporary, identity, temporary)
        self.assertTrue("UNEXPECTED_PRIVATE_TOKEN" not in env, "Private environment field leaked")
        self.assertTrue("PYTHONPATH" not in env, "Repository fallback leaked")
        self.assertEqual(env["CUDA_VISIBLE_DEVICES"], "")

    def test_verifier_exception_is_distinct_from_a_legitimate_zero(self):
        from types import SimpleNamespace
        from gymts_areal.bridge import BridgeService
        audits = []
        class Artifacts:
            def save_json(self, value, schema):
                audits.append(copy.deepcopy(value))
                return {"fixture_ref": len(audits)}
        owner = object.__new__(BridgeService)
        owner.gym = SimpleNamespace(artifacts=Artifacts())
        owner.prepared = {"private_ref": {"fixture_private_ref": True}}
        sample = {"sample_id": "case", "task_id": "gsm8k.numeric", "split": "train"}
        owner.private = {"case": {"reward_spec": {"kind": "gsm8k_numeric", "ground_truth": "NaN"}}}
        with self.assertRaisesRegex(ValueError, "finite"):
            owner.grade(sample, {"completion": "\\boxed{2}"}, terminal_tokens=[])
        self.assertEqual(audits[-1]["status"], "failed")
        owner.private["case"]["reward_spec"]["ground_truth"] = "3"
        reward, _ = owner.grade(sample, {"completion": "\\boxed{2}"}, terminal_tokens=[])
        self.assertEqual(reward, 0.0)
        self.assertEqual(audits[-1]["status"], "succeeded")

    def test_source_manifest_revision_and_duplicate_members_are_rejected(self):
        from pathlib import Path
        from gymts import GymTS
        from gymts_areal.bridge import BridgeService
        from gymts_rl.contracts import SNAPSHOT
        sample = {"sample_id": "case", "group_id": "group", "dataset_id": "fixture", "split": "train",
            "task_id": "gsm8k.numeric", "messages": [{"role": "user", "content": "What is two plus two?"}],
            "timeseries": [], "series_names": [], "output_schema": {}, "context": {}}
        with tempfile.TemporaryDirectory() as temporary, GymTS(Path(temporary) / "store", integrations=["rl", "areal"]) as gym:
            public = {"schema_version": SNAPSHOT, "dataset_revision": "fixed", "samples": [sample]}
            private = {"dataset_revision": "fixed", "samples": [{key: sample[key] for key in
                ("sample_id", "group_id", "dataset_id", "split", "task_id")}]}
            private["samples"][0]["reward_spec"] = {"kind": "gsm8k_numeric", "ground_truth": "4"}
            def prepared(pub, hidden):
                manifest = {"dataset_revision": "fixed", "snapshot_ref": gym.artifacts.save_json(pub, SNAPSHOT),
                    "private_ref": gym.artifacts.save_json(hidden, "gymts.json/1"), "counts": {"train": 1, "eval": 0},
                    "train_sample_ids": ["case"], "eval_sample_ids": []}
                return dict(manifest, manifest_ref=gym.artifacts.save_json(manifest, "gymts.json/1"))
            ready = prepared(public, private)
            tampered = copy.deepcopy(ready)
            tampered["snapshot_ref"] = gym.artifacts.save_json(dict(public, dataset_revision="substituted"), SNAPSHOT)
            with self.assertRaisesRegex(ValueError, "immutable manifest"):
                BridgeService(gym, tampered, Path(temporary) / "mismatch")
            wrong_revision = prepared(public, dict(private, dataset_revision="substituted"))
            with self.assertRaisesRegex(ValueError, "snapshot revisions"):
                BridgeService(gym, wrong_revision, Path(temporary) / "revision")
            duplicate = prepared(dict(public, samples=[sample, copy.deepcopy(sample)]), private)
            with self.assertRaisesRegex(ValueError, "members differ"):
                BridgeService(gym, duplicate, Path(temporary) / "duplicate")
            service = BridgeService(gym, ready, Path(temporary) / "valid").start()
            service.close()
            self.assertEqual(service.drain_status, "sealed_handlers_drained")

    def test_complete_native_sdk_report_without_quality_gate(self):
        from pathlib import Path
        from gymts import GymTS
        from gymts.contracts import utc_now
        from gymts.plugin_support import payload
        from gymts_rl.checkpoint import BUNDLE
        from gymts_rl.contracts import OUTPUT, PROTOCOL, SNAPSHOT
        from gymts_rl.evaluation import checkpoint_evaluation_spec
        from gymts_areal.cli import require_complete_evaluation

        class FixtureCandidate:
            # A deterministic test component; no real model or training claim.
            def __init__(self, spec): pass
            def prepare(self, context, training_view):
                return {"model_revision": "test-fixture", "state_refs": [], "training_provenance_ref": None}
            def infer(self, task_input):
                return {"input_id": task_input["input_id"], "task_protocol_ref": PROTOCOL,
                    "produced_at": utc_now(), "model_revision": "test-fixture",
                    "payload": payload(OUTPUT, {"raw_text": "#### 4", "evidence": {}})}
            def finish(self): return []

        with tempfile.TemporaryDirectory() as temporary, GymTS(Path(temporary) / "store", integrations=["rl", "areal"]) as gym:
            sample = {"sample_id": "fixture", "group_id": "fixture-group", "dataset_id": "fixture",
                "split": "eval", "task_id": "gsm8k.numeric", "messages": [{"role": "user", "content": "Two plus two?"}],
                "timeseries": [], "series_names": [], "output_schema": {}, "context": {}}
            public = gym.artifacts.save_json({"schema_version": SNAPSHOT, "dataset_revision": "fixture-1", "samples": [sample]}, SNAPSHOT)
            hidden = {key: sample[key] for key in ("sample_id", "group_id", "dataset_id", "split", "task_id")}
            hidden["reward_spec"] = {"kind": "gsm8k_numeric", "ground_truth": "4"}
            private = gym.artifacts.save_json({"dataset_revision": "fixture-1", "samples": [hidden]}, "gymts.json/1")
            prepared = {"dataset_revision": "fixture-1", "snapshot_ref": public, "private_ref": private}
            prepared["manifest_ref"] = gym.artifacts.save_json(copy.deepcopy(prepared), "gymts.json/1")
            declaration = gym.registries.candidates.resolve("rl-local-hf", "1.0.0")
            declaration["component_ref"]["name"] = "test-completion-fixture"
            declaration["implementation_ref"]["name"] = "test-completion-fixture"
            declaration["params_schema_ref"] = "gymts.rl/empty/1"
            declaration["capture_profiles"] = []
            gym.registries.candidates.register(declaration, FixtureCandidate)
            # This placeholder is consumed only by specification construction;
            # the actual evaluation uses the explicit deterministic fixture.
            spec = checkpoint_evaluation_spec(gym, prepared, {"schema_ref": BUNDLE, "content_hash": "fixture"}, ["fixture"], seeds=(7,))
            spec["candidates"] = [{"candidate_id": "test-fixture", "spec": {"adapter": "test-completion-fixture",
                "version": "1.0.0", "artifact": None, "inherited_state": [], "params": {}}}]
            spec["cases"][0]["recording"]["model_calls"] = "none"
            report = gym.autobench.evaluate(spec)
        self.assertEqual(report["verdict"], "insufficient_evidence")
        self.assertEqual(report["reasons"], ["no_acceptance_gate"])
        self.assertEqual(report["coverage"]["succeeded_runs"], 1)
        self.assertTrue(all(row["result"]["status"] == "ready" for row in report["metrics"]))
        original = copy.deepcopy(report)
        require_complete_evaluation(report)
        self.assertEqual(report, original, "Completion validation must not alter AutoBench's quality verdict")
        for failure in ("failed_run", "missing_score", "no_metrics", "extra_reason", "failed_gate", "error"):
            changed = copy.deepcopy(report)
            if failure == "failed_run": changed["coverage"].update(succeeded_runs=0, failed_runs=1)
            elif failure == "missing_score": changed["metrics"][0]["result"]["counts"].update(scored=0, missing=1)
            elif failure == "no_metrics": changed["metrics"] = []
            elif failure == "extra_reason": changed["reasons"].append("insufficient_metric_evidence")
            elif failure == "failed_gate":
                changed.update(verdict="fail", gate_results=[{"status": "fail"}])
            else: changed["errors"] = [{"code": "fixture_failure"}]
            with self.subTest(failure=failure), self.assertRaisesRegex(RuntimeError, "every expected Run"):
                require_complete_evaluation(changed)

    def test_duplicate_tensor_multiplicity_is_not_silently_dropped(self):
        from types import SimpleNamespace
        import threading
        from gymts_areal.bridge import BridgeService
        owner = object.__new__(BridgeService)
        owner.bridge_id = "fixture"
        owner.episodes = [{"split": "train", "status": "succeeded", "native_tensor_sha256": "same"}]
        owner._metadata_lock = threading.Lock()
        owner.training_events = []
        owner.gym = SimpleNamespace(artifacts=SimpleNamespace(save_json=lambda *_: {"fixture_ref": True}))
        with self.assertRaisesRegex(ValueError, "outside sealed"):
            owner.training_event({"bridge_id": "fixture", "event": {"kind": "consume_batch", "row_hashes": ["same", "same"]}})
        owner.training_event({"bridge_id": "fixture", "event": {"kind": "consume_batch", "row_hashes": ["same"]}})
        self.assertEqual(len(owner.training_events), 1)

    def test_failed_checkpoint_publication_is_a_failed_parent(self):
        from pathlib import Path
        from types import SimpleNamespace
        from gymts_areal.cli import train_or_preflight
        class FakeGym:
            def __init__(self, *_args, **_kwargs):
                self.artifacts = SimpleNamespace(read_json=lambda _: {"samples": [{"split": "train"}]},
                    save_json=lambda *_: {"fixture_summary_ref": True})
            def __enter__(self): return self
            def __exit__(self, *_): pass
        class FakeBridge:
            def __init__(self, _gym, _prepared, directory, **_kwargs):
                self.path, self.bridge_id = Path(directory) / "bridge.sock", "fixture"
            def start(self): return self
            def close(self): pass
            def summary(self): return {"episodes": [], "training_events": [], "policy_versions": [], "failures": []}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "prepared.json").write_text(json.dumps({"snapshot_ref": {}, "manifest_ref": {}}))
            (root / "identity.json").write_text("{}")
            args = SimpleNamespace(core_identity=str(root / "identity.json"), output=str(root / "attempt"),
                prepared=str(root / "prepared.json"), store=str(root / "store"), group_size=2, model=str(root),
                seed=7, max_new_tokens=16, max_length=128, episode_seconds=10, max_model_requests=8, learning_rate=.001,
                gpu_devices=[0, 2], gpu_uuids=["fixture-a", "fixture-b"], upstream=str(root), python="unused", seconds=10)
            def fake_worker(_python, _module, path, **_kwargs):
                Path(path).with_name("native-training-result.json").write_text("{}")
            with patch("gymts_areal.cli.GymTS", FakeGym), patch("gymts_areal.bridge.BridgeService", FakeBridge), \
                    patch("gymts_areal.cli.verify_core", return_value={}), patch("gymts_areal.cli.model_identity", return_value={}), \
                    patch("gymts_areal.cli.run_worker", side_effect=fake_worker), \
                    patch("gymts_areal.checkpoint.publish_native_checkpoint", side_effect=ValueError("missing native update proof")):
                with self.assertRaisesRegex(ValueError, "missing native update proof"):
                    train_or_preflight(args)
            parent = json.loads((root / "attempt/training-parent.json").read_text())
            self.assertEqual(parent["status"], "failed")
            self.assertEqual(parent["error"]["type"], "ValueError")

    @unittest.skipUnless(__import__("sys").platform.startswith("linux"), "Linux parent-death signal")
    def test_parent_death_kills_only_owned_group(self):
        import signal
        import subprocess
        import sys
        import time
        from pathlib import Path
        worker = ("from gymts_areal.lifecycle import arm_parent_death;import os,subprocess,time,json;"
            "arm_parent_death();c=subprocess.Popen(['sleep','120']);"
            "print(json.dumps([os.getpid(),c.pid,os.getpgrp(),os.getsid(0)]),flush=True);time.sleep(120)")
        supervisor = ("import os,subprocess,sys;"
            "e=dict(os.environ,GYMTS_AREAL_PARENT_PID=str(os.getpid()));"
            "p=subprocess.Popen([sys.executable,'-I','-c',sys.argv[1]],env=e,start_new_session=True);p.wait()")
        unrelated = subprocess.Popen(["sleep", "120"])
        process = subprocess.Popen([sys.executable, "-I", "-c", supervisor, worker], stdout=subprocess.PIPE, text=True)
        owned_group = None
        try:
            worker_pid, sleep_pid, group, session = json.loads(process.stdout.readline())
            self.assertEqual(worker_pid, group)
            self.assertEqual(worker_pid, session)
            owned_group = group
            process.kill()
            process.wait(timeout=5)
            def alive(pid):
                path = Path("/proc") / str(pid) / "stat"
                return path.exists() and path.read_text().split(")", 1)[1].strip().split()[0] not in {"Z", "X"}
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and (alive(worker_pid) or alive(sleep_pid)):
                time.sleep(.05)
            self.assertFalse(alive(worker_pid), "Owned worker survived its parent")
            self.assertFalse(alive(sleep_pid), "Owned child survived its parent")
            self.assertIsNone(unrelated.poll(), "Unrelated process must survive owned-group cleanup")
        finally:
            if process.poll() is None: process.kill(); process.wait(timeout=5)
            if owned_group is not None:
                try: os.killpg(owned_group, signal.SIGKILL)
                except ProcessLookupError: pass
            process.stdout.close()
            unrelated.terminate(); unrelated.wait(timeout=5)

    def test_timeout_cleans_owned_worker_and_child(self):
        import signal
        import subprocess
        import sys
        import time
        from pathlib import Path
        from gymts_areal.cli import run_worker
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            launcher = root / "owned-test-python"
            launcher.write_text("#!" + sys.executable + "\nimport os,subprocess,sys,time,json\n"
                "c=subprocess.Popen(['sleep','120'])\n"
                "open(sys.argv[-1],'w').write(json.dumps([os.getpid(),c.pid]))\n"
                "time.sleep(120)\n")
            launcher.chmod(0o700)
            pids = root / "pids.json"
            with self.assertRaises(TimeoutError):
                run_worker(str(launcher), "unused_fixture", pids, env={"PATH": os.environ["PATH"]},
                           output=root / "worker.log", timeout=.5)
            def alive(pid):
                stat = Path("/proc") / str(pid) / "stat"
                return stat.exists() and stat.read_text().split(")", 1)[1].strip().split()[0] not in {"Z", "X"}
            worker, child = json.loads(pids.read_text())
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and (alive(worker) or alive(child)): time.sleep(.05)
            self.assertFalse(alive(worker))
            self.assertFalse(alive(child))


if __name__ == "__main__":
    unittest.main()
