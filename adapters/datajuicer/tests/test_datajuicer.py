"""CPU-only contract tests. Synthetic records here are not native acceptance."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS, GymTSError
from gymts_datajuicer import UPSTREAM_SHA
from gymts_datajuicer.common import dumps, row_identity, sha, source_row, validate_source
from gymts_datajuicer.data import register_derived
from gymts.plugin_support import payload, component
from gymts.contracts import utc_now
from gymts_datajuicer import contracts as c
from gymts_datajuicer.experiments import evaluation_spec, rescore
from gymts_datajuicer.runtime import SourceEnvironment
from gymts_datajuicer.scoring import assess
from gymts_datajuicer.cli import model_identity


def fixture(answer=3.):
    first = source_row([1., 3., 2.], family_id="family-a", sample_id="a", operation="max")
    duplicate = dict(first, sample_id="b")
    short = dict(first, sample_id="c", text="short")
    sources = [first, duplicate, short]
    generated = dict(first, query=dumps({"operation": "max", "family_id": "family-a"}), response=dumps({"value": answer}))
    stages, previous = [], sources
    for index, (operator, outgoing) in enumerate([
        ("text_length_filter", [first, duplicate]), ("document_deduplicator", [first]),
        ("gymts_audited_native_qa_mapper", [generated])]):
        stages.append({"index": index, "operator": operator, "status": "succeeded", "input": copy.deepcopy(previous),
            "output": copy.deepcopy(outgoing), "input_members": [row_identity(row) for row in previous],
            "output_members": [row_identity(row) for row in outgoing],
            "dropped_ids": [row["sample_id"] for row in previous if row["sample_id"] not in {r["sample_id"] for r in outgoing}],
            "output_count_by_source": {row["sample_id"]: 1 for row in outgoing}})
        previous = outgoing
    value = {"rows": [generated], "stages": stages, "model_calls": [{"sample_id": "a", "status": "succeeded",
        "messages": [{"role": "user", "content": first["text"]}],
        "response": [{"generated_text": "Human:" + generated["query"] + "Assistant:" + generated["response"]}]}],
        "identity": {"upstream": {"commit": UPSTREAM_SHA}, "cpu_only": False, "native_execution": True},
        "export_text": dumps(generated) + "\n", "export_sha256": sha((dumps(generated) + "\n").encode()), "artifact_refs": []}
    gold = {"source_revision": sha(sources), "rows": sources, "holdout_families": ["family-heldout"],
            "holdout_series_sha256": [sha([9, 8, 7])]}
    return value, gold


class QualityTests(unittest.TestCase):
    def test_safetensors_header_and_index_reject_truncated_model_before_gpu(self):
        import struct
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "config.json").write_text('{"model_type":"fixture"}')
            header = dumps({"weight": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}}).encode()
            header += b" " * (-len(header) % 8)
            shard = root / "model.safetensors"
            shard.write_bytes(struct.pack("<Q", len(header)) + header + struct.pack("<f", 2.0))
            identity = model_identity(root)
            self.assertIn("model.safetensors", identity["files"])
            shard.write_bytes(shard.read_bytes()[:-1])
            with self.assertRaisesRegex(ValueError, "truncated"):
                model_identity(root)

    def test_independent_numeric_quality_and_full_stage_accounting(self):
        value, gold = fixture()
        result = assess(value, gold)
        self.assertEqual(result["eligible_sources"], 1)
        self.assertEqual(result["values"], {metric: 1. for metric in
            ("answer_accuracy", "structure_rate", "source_coverage", "unique_rate", "lineage_integrity", "holdout_clean")})

    def test_wrong_numeric_answer_does_not_reuse_model_or_filter_score(self):
        value, gold = fixture()
        value["rows"][0]["response"] = dumps({"value": 100})
        result = assess(value, gold)
        self.assertEqual(result["values"]["answer_accuracy"], 0)
        self.assertEqual(result["values"]["structure_rate"], 1)

    def test_invalid_format_and_missing_source_are_counted(self):
        value, gold = fixture()
        value["rows"][0]["response"] = "not-json"
        self.assertEqual(assess(value, gold)["values"]["structure_rate"], 0)
        value["rows"] = []
        result = assess(value, gold)
        self.assertEqual(result["values"]["source_coverage"], 0)
        self.assertEqual(result["values"]["answer_accuracy"], 0)
        self.assertEqual(result["empty_outputs"], 1)

    def test_tampered_stage_dropped_members_and_export_fail_lineage(self):
        for change in (lambda v: v["stages"][0]["dropped_ids"].clear(),
                       lambda v: v["stages"].pop(), lambda v: v.update(export_sha256="0" * 64),
                       lambda v: v["model_calls"].clear()):
            value, gold = fixture()
            change(value)
            self.assertEqual(assess(value, gold)["values"]["lineage_integrity"], 0)

    def test_holdout_family_and_series_overlap_rejected_independently(self):
        value, gold = fixture()
        gold["holdout_families"].append("family-a")
        self.assertEqual(assess(value, gold)["values"]["holdout_clean"], 0)
        value, gold = fixture()
        gold["holdout_series_sha256"].append(sha([1., 3., 2.]))
        self.assertEqual(assess(value, gold)["values"]["holdout_clean"], 0)

    def test_source_purpose_and_private_fields_rejected(self):
        for change in (lambda r: r.update(split="test"), lambda r: r.update(expected_output={"value": 3}),
                       lambda r: r.update(series=[float("nan")])):
            row = source_row([1, 2], family_id="f", sample_id="s")
            change(row)
            with self.assertRaises(ValueError):
                validate_source([row])


class PublicContractTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux parent-death cleanup")
    def test_parent_death_kills_only_the_worker_owned_sleep_process_group(self):
        import os
        import signal
        import time
        worker = ("from gymts_datajuicer.lifecycle import arm_parent_death;import os,subprocess,time,json;"
            "arm_parent_death();c=subprocess.Popen(['sleep','120']);"
            "print(json.dumps([os.getpid(),c.pid,os.getpgrp(),os.getsid(0)]),flush=True);time.sleep(120)")
        supervisor = ("import os,subprocess,sys;"
            "e=dict(os.environ,GYMTS_DATAJUICER_PARENT_PID=str(os.getpid()));"
            "p=subprocess.Popen([sys.executable,'-I','-c',sys.argv[1]],env=e,start_new_session=True);p.wait()")
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
            self.assertFalse(alive(worker_pid))
            self.assertFalse(alive(sleep_pid))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if owned_group is not None:
                try:
                    os.killpg(owned_group, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.stdout.close()

    def test_cli_preserves_virtualenv_python_symlink_as_the_execution_entrypoint(self):
        from gymts_datajuicer.cli import main
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            value, gold = fixture()
            source = root / "source"
            source.mkdir()
            (source / "public.json").write_text(dumps({"source_revision": gold["source_revision"], "rows": gold["rows"]}))
            (source / "reference.json").write_text(dumps(gold))
            (source / "provenance.json").write_text("{}")
            identity = root / "model.json"
            identity.write_text(dumps({"local_path": str(root / "model")}))
            executable = root / "venv-python"
            executable.symlink_to(sys.executable)
            def inspect_params(gym, source, reference, params, **kwargs):
                self.assertEqual(params["worker_python"], str(executable))
                raise RuntimeError("checked without executing a worker")
            with patch("gymts_datajuicer.experiments.evaluation_spec", side_effect=inspect_params):
                with self.assertRaisesRegex(RuntimeError, "checked"):
                    main(["run", "--root", str(root / "run"), "--source", str(source),
                        "--native-python", str(executable), "--upstream", str(root / "upstream"),
                        "--model", str(root / "model"), "--model-identity", str(identity), "--work", str(root / "work")])

    def test_discovery_and_registration_do_not_import_native_runtime(self):
        code = ("import sys,tempfile;from gymts import GymTS;"
                "t=tempfile.TemporaryDirectory();"
                "g=GymTS(t.name,integrations=('datajuicer',),data_home=t.name+'/data',cache_home=t.name+'/cache');"
                "assert not {'torch','transformers','datasets','data_juicer'} & set(sys.modules);g.close()")
        result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_plan_never_opens_environment_model_worker_or_artifact(self):
        with tempfile.TemporaryDirectory() as temp, GymTS(Path(temp) / "records", integrations=("datajuicer",),
            data_home=Path(temp) / "data", cache_home=Path(temp) / "cache") as gym:
            value, gold = fixture()
            params = {"worker_python": "/missing/python", "upstream": "/missing/upstream", "model_path": "/missing/model",
                "model_identity": {"id": "fixed"}, "timeout_seconds": 10, "max_new_tokens": 32, "work_root": "/missing/work"}
            spec = evaluation_spec(gym, {"source_revision": gold["source_revision"], "rows": gold["rows"]}, gold, params)
            case = spec["cases"][0]
            experiment = {"protocol_version": "gymts.experiment/1", "name": "pure", "purpose": "acceptance",
                "scene": case["scene"], "candidate": spec["candidates"][0]["spec"],
                "execution": case["execution"], "recording": case["recording"], "extensions": {}}
            with patch.object(SourceEnvironment, "__init__", side_effect=AssertionError("opened during plan")), \
                 patch.object(gym.artifacts, "read_json", side_effect=AssertionError("CAS read during plan")), \
                 patch("subprocess.Popen", side_effect=AssertionError("worker started during plan")):
                plan = gym.plan(experiment)
            self.assertEqual(plan["resource_checks"], "deferred_to_open")

    def test_source_open_rejects_private_fields_or_wrong_identity_before_observation(self):
        for change in ("private", "identity"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temp, GymTS(Path(temp) / "records", integrations=("datajuicer",),
                data_home=Path(temp) / "data", cache_home=Path(temp) / "cache") as gym:
                _, gold = fixture()
                params = {"worker_python": "/unused", "upstream": "/unused", "model_path": "/unused",
                    "model_identity": {}, "timeout_seconds": 10, "max_new_tokens": 32, "work_root": str(Path(temp) / "unused")}
                spec = evaluation_spec(gym, {"source_revision": gold["source_revision"], "rows": gold["rows"]}, gold, params)
                environment = spec["cases"][0]["scene"]["environment"]
                snapshot = gym.artifacts.read_json(environment["source"]["connection"]["artifact_refs"][0])
                if change == "private":
                    snapshot["sample"]["rows"][0]["expected_output"] = {"value": 3}
                else:
                    snapshot["sample"]["source_revision"] = "wrong-revision"
                environment["source"]["connection"]["artifact_refs"] = [gym.artifacts.save_json(snapshot, c.SNAPSHOT)]
                with patch("gymts_datajuicer.candidate.NativePipelineCandidate.infer", side_effect=AssertionError("Candidate must not see invalid source")):
                    report = gym.autobench.evaluate(spec)
                entry = gym.artifacts.read_json(report["run_manifest_ref"])["entries"][0]
                self.assertEqual(entry["status"], "failed")
                run = gym.records.get_run(entry["run_id"])
                self.assertFalse(any(event["kind"] in {"observation", "task_input"} for event in run["events"]))

    def test_cli_saves_failed_formal_report_and_returns_nonzero(self):
        from gymts_datajuicer.cli import main
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, gold = fixture()
            source = root / "source"
            source.mkdir()
            (source / "public.json").write_text(dumps({"source_revision": gold["source_revision"], "rows": gold["rows"]}))
            (source / "reference.json").write_text(dumps(gold))
            (source / "provenance.json").write_text("{}")
            identity = root / "model.json"
            identity.write_text(dumps({"local_path": str(root / "model")}))
            with self.assertRaises(SystemExit) as raised:
                main(["run", "--root", str(root / "run"), "--source", str(source),
                    "--native-python", str(root / "missing-python"), "--upstream", str(root / "upstream"),
                    "--model", str(root / "model"), "--model-identity", str(identity), "--work", str(root / "work")])
            self.assertEqual(raised.exception.code, 1)
            self.assertEqual(json.loads((root / "run/evaluation.json").read_text())["verdict"], "fail")
            self.assertTrue((root / "run/evaluation.ref.json").is_file())

    def test_register_requires_sealed_success_and_uses_public_resource_service(self):
        with tempfile.TemporaryDirectory() as temp, GymTS(Path(temp) / "records", integrations=("datajuicer",),
            data_home=Path(temp) / "data", cache_home=Path(temp) / "cache") as gym:
            value, gold = fixture()
            class UnitOutputCandidate:
                """Deterministic test data; never presented as native execution acceptance."""
                def __init__(self, spec):
                    pass
                def prepare(self, context, training):
                    return {"model_revision": "unit-test-only", "state_refs": [], "training_provenance_ref": None}
                def infer(self, task_input):
                    return {"input_id": task_input["input_id"], "task_protocol_ref": c.PROTOCOL,
                        "produced_at": utc_now(), "model_revision": "unit-test-only", "payload": payload(c.OUTPUT, value)}
                def finish(self):
                    return []
            manifest = gym.registries.candidates.resolve("datajuicer-native", "1.0.0")
            manifest.update(component_ref=component("datajuicer-unit-output"), params_schema_ref=c.EMPTY,
                implementation_ref=component("unit-test-only"), capture_profiles=[])
            gym.registries.candidates.register(manifest, UnitOutputCandidate)
            params = {"worker_python": "/unused", "upstream": "/unused", "model_path": "/unused",
                "model_identity": {}, "timeout_seconds": 10, "max_new_tokens": 32, "work_root": str(Path(temp) / "unused")}
            spec = evaluation_spec(gym, {"source_revision": gold["source_revision"], "rows": gold["rows"]}, gold, params)
            spec["cases"][0]["recording"]["model_calls"] = "none"
            spec["candidates"][0]["spec"].update(adapter="datajuicer-unit-output", params={})
            report = gym.autobench.evaluate(spec)
            self.assertEqual(report["status"], "completed", report)
            self.assertEqual(report["verdict"], "pass", report)
            report_ref = gym.autobench.last_report_ref
            run_id = gym.artifacts.read_json(report["run_manifest_ref"])["entries"][0]["run_id"]
            run = gym.records.get_run(run_id)
            self.assertEqual(run["result"]["status"], "succeeded")
            self.assertTrue(any(event["kind"] == "task_result" for event in run["events"]))
            self.assertFalse(any(event["kind"] == "result" for event in run["events"]))
            with self.assertRaises(GymTSError):
                register_derived(gym, run_id, "unit-test/missing-report")
            manifest = register_derived(gym, run_id, "unit-test/derived", quality_report_ref=report_ref)
            data = gym.environment_ts.datasets.load_dataset(manifest["dataset_id"], revision=manifest["revision"],
                                                          split="train", purpose="training")
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["parent_sample_id"], "a")
            self.assertEqual(data[0]["label_status"], "model_generated_unverified")
            self.assertEqual(data[0]["prompt"][0]["role"], "user")
            self.assertEqual(data[0]["completion"], value["rows"][0]["response"])
            # Actual Runner, independent Scorer and immutable report references
            # also drive negative publication checks; no result events fabricated.
            other_report = gym.autobench.evaluate(spec)
            other_run = gym.artifacts.read_json(other_report["run_manifest_ref"])["entries"][0]["run_id"]
            with self.assertRaises(GymTSError):
                register_derived(gym, other_run, "unit-test/wrong-run", quality_report_ref=report_ref)
            for bad in ("holdout", "lineage"):
                value, gold = fixture()
                if bad == "holdout":
                    gold["holdout_families"].append("family-a")
                else:
                    value["stages"][0]["dropped_ids"].clear()
                failed_spec = evaluation_spec(gym, {"source_revision": gold["source_revision"], "rows": gold["rows"]}, gold, params)
                failed_spec["cases"][0]["recording"]["model_calls"] = "none"
                failed_spec["candidates"][0]["spec"].update(adapter="datajuicer-unit-output", params={})
                failed = gym.autobench.evaluate(failed_spec)
                self.assertEqual(failed["status"], "completed")
                self.assertEqual(failed["verdict"], "fail")
                bad_run = gym.artifacts.read_json(failed["run_manifest_ref"])["entries"][0]["run_id"]
                self.assertEqual(gym.records.get_run(bad_run)["result"]["status"], "succeeded")
                with self.assertRaises(GymTSError):
                    register_derived(gym, bad_run, "unit-test/" + bad, quality_report_ref=gym.autobench.last_report_ref)
            # Incorrect numeric labels remain unverified, rather than becoming
            # filtered oracle-selected gold, once purpose/lineage gates pass.
            value, gold = fixture(answer=100.)
            wrong = gym.autobench.evaluate(spec)
            self.assertEqual(wrong["verdict"], "pass")
            accuracy = [m["result"] for m in wrong["metrics"] if m["level"] == "aggregate" and m["metric_id"] == "answer_accuracy"][0]
            self.assertEqual(accuracy["value"], 0)
            wrong_run = gym.artifacts.read_json(wrong["run_manifest_ref"])["entries"][0]["run_id"]
            wrong_manifest = register_derived(gym, wrong_run, "unit-test/unverified-wrong", quality_report_ref=gym.autobench.last_report_ref)
            wrong_data = gym.environment_ts.datasets.load_dataset(wrong_manifest["dataset_id"], revision=wrong_manifest["revision"], split="train", purpose="training")
            self.assertEqual(wrong_data[0]["completion"], dumps({"value": 100.}))
            self.assertEqual(wrong_data[0]["label_status"], "model_generated_unverified")
            value, gold = fixture()
            value["rows"] = []
            value["export_text"] = ""
            value["export_sha256"] = sha(b"")
            value["model_calls"][0]["response"] = [{"generated_text": 'Assistant:{"value":3}'}]
            stage = value["stages"][2]
            stage.update(output=[], output_members=[], dropped_ids=["a"], output_count_by_source={})
            empty = gym.autobench.evaluate(spec)
            self.assertEqual(empty["status"], "completed")
            self.assertEqual(empty["coverage"]["succeeded_runs"], 1)
            aggregate = {m["metric_id"]: m["result"] for m in empty["metrics"] if m["level"] == "aggregate"}
            self.assertEqual(aggregate["source_coverage"]["value"], 0)
            self.assertEqual(aggregate["lineage_integrity"]["value"], 1)
            empty_run = gym.artifacts.read_json(empty["run_manifest_ref"])["entries"][0]["run_id"]
            with self.assertRaises(GymTSError):
                register_derived(gym, empty_run, "unit-test/empty", quality_report_ref=gym.autobench.last_report_ref)
            self.assertEqual(len(gym.environment_ts.datasets.list_datasets()), 2)

    def test_real_framework_seals_missing_worker_and_rescores_without_worker(self):
        with tempfile.TemporaryDirectory() as temp, GymTS(Path(temp) / "records", integrations=("datajuicer",),
            data_home=Path(temp) / "data", cache_home=Path(temp) / "cache") as gym:
            _, gold = fixture()
            params = {"worker_python": str(Path(temp) / "missing-python"), "upstream": "/missing/upstream",
                "model_path": "/missing/model", "model_identity": {"id": "fixed"}, "timeout_seconds": 10,
                "max_new_tokens": 32, "work_root": str(Path(temp) / "work")}
            spec = evaluation_spec(gym, {"source_revision": gold["source_revision"], "rows": gold["rows"]}, gold, params)
            report = gym.autobench.evaluate(spec)
            entries = gym.artifacts.read_json(report["run_manifest_ref"])["entries"]
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["status"], "failed")
            run_id = entries[0]["run_id"]
            before = dumps(gym.records.get_run(run_id))
            with patch("subprocess.Popen", side_effect=AssertionError("worker started during re-score")), \
                 patch.object(SourceEnvironment, "__init__", side_effect=AssertionError("environment started during re-score")):
                repeated = rescore(gym, spec, report)
            self.assertEqual(repeated["verdict"], "fail")
            self.assertEqual(before, dumps(gym.records.get_run(run_id)))
            self.assertEqual(gym.environment_ts.datasets.list_datasets(), [])


if __name__ == "__main__":
    unittest.main()
