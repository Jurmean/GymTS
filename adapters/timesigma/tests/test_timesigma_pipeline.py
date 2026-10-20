"""Real GymTS/AutoBench orchestration with explicitly simulated worker evidence.

Scientific execution boundaries are patched in fixtures. No result in this file
is presented as a real benchmark measurement or a paid-provider execution.
"""
import base64
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import GymTSError, canonical_json, digest
from gymts_timesigma.contracts import INPUT, TRAINING, identity
from gymts_timesigma.data import import_dataset
from gymts_timesigma.environment import TimeSigmaSnapshotEnvironment
from gymts_timesigma.scoring import METRIC_IDS, TimeSigmaOfficialScorer
try:
    from .test_timesigma_data_task import fixture, np
except ImportError:  # unittest discover also runs outside the source package.
    from test_timesigma_data_task import fixture, np


class TimeSigmaRegistrationIsolationTests(unittest.TestCase):
    def run_script(self, text):
        with tempfile.TemporaryDirectory() as root:
            result = subprocess.run([sys.executable, "-B", "-c", text, root], cwd=root,
                                    capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_core_discovery_never_imports_an_unselected_timesigma_integration(self):
        self.run_script('''
import importlib.abc,sys
class BlockTimeSigma(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "gymts_timesigma" or fullname.startswith("gymts_timesigma."):
            raise ModuleNotFoundError("TimeSigma deliberately unavailable")
sys.meta_path.insert(0,BlockTimeSigma())
from gymts import GymTS
with GymTS(sys.argv[1]) as gym:
    assert any(row['name']=='timesigma' for row in gym.available_integrations())
    assert not any(name.startswith('gymts_timesigma') for name in sys.modules)
    try: gym.enable_integration('timesigma')
    except Exception as error: assert error.code=='unsupported_capability'
    else: raise AssertionError('Missing explicitly selected integration must fail')
    assert gym.enabled_integrations==()
''')

    def test_explicit_registration_is_idempotent_and_needs_no_scientific_packages(self):
        self.run_script('''
import importlib.abc,sys
class BlockScientific(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'numpy','scipy','torch','sklearn','EasyTSAD','timesigma'}:
            raise ModuleNotFoundError('Optional scientific package blocked')
sys.meta_path.insert(0,BlockScientific())
from gymts import GymTS
with GymTS(sys.argv[1],integrations=('timesigma','timesigma')) as gym:
    assert gym.enabled_integrations==('timesigma',)
    gym.enable_integration('timesigma')
    for registry,name in ((gym.registries.environments,'timesigma-snapshot'),(gym.registries.tasks,'timesigma-tsad'),
                          (gym.registries.candidates,'timesigma-native'),(gym.registries.scorers,'timesigma-official')):
        assert registry.resolve(name,'1.0.0')['component_ref']['name']==name
    assert not any(name.split('.')[0] in {'numpy','scipy','torch','sklearn','EasyTSAD','timesigma'} for name in sys.modules)
''')


@unittest.skipIf(np is None, "Optional NumPy is needed to construct local .npy fixtures")
class TimeSigmaPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dataset = fixture(self.root / "fixture-data")
        self.app = GymTS(self.root / "records", integrations=("timesigma",))
        self.addCleanup(self.app.close)
        self.order, self.calls, self.scoring_calls = [], [], []
        self.fit_data, self.score_data = None, []
        self.expected_imported, self.denied_prepare_refs = None, []
        self.source = {"repository": str(self.root / "synthetic-source"), "revision": "synthetic-unit-test-only",
                       "python": sys.executable, "evidence_origin": "explicit_simulated_worker_fixture"}
        from gymts_timesigma.runtime import TimeSigmaRuntime
        self.runtime = TimeSigmaRuntime
        patchers = [patch.object(TimeSigmaRuntime, "describe", return_value=self.source),
                    patch.object(TimeSigmaRuntime, "call", side_effect=self.native),
                    patch.object(TimeSigmaOfficialScorer, "_run_native", side_effect=self.official)]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        original = TimeSigmaSnapshotEnvironment.observe
        def observe(environment, request):
            self.order.append("observe")
            self.assertIsNotNone(self.fit_data, "The real Runner must finish prepare.fit before observing rawtest")
            return original(environment, request)
        patcher = patch.object(TimeSigmaSnapshotEnvironment, "observe", observe)
        patcher.start()
        self.addCleanup(patcher.stop)
        from gymts_timesigma.candidate import TimeSigmaCandidate
        original_prepare = TimeSigmaCandidate.prepare
        def prepare(candidate, context, training):
            if self.expected_imported is not None:
                for name in ("snapshot_ref", "private_ref", "manifest_ref"):
                    reference = self.expected_imported[name]
                    with self.assertRaises(GymTSError) as error:
                        context["resources"].read_json(reference)
                    self.assertEqual(error.exception.code, "permission_denied")
                    self.denied_prepare_refs.append(name)
            return original_prepare(candidate, context, training)
        patcher = patch.object(TimeSigmaCandidate, "prepare", prepare)
        patcher.start()
        self.addCleanup(patcher.stop)

    def params(self):
        return {"method": "AR", "source_repo": str(self.root / "synthetic-source"),
                "python": sys.executable, "timeout_seconds": 30, "seed": 1}

    def native(self, operation, payload):
        """Fake only the external worker, retaining production Candidate lifecycle."""
        self.order.append(operation)
        self.calls.append((operation, copy.deepcopy(payload)))
        if operation == "fit":
            self.fit_data = copy.deepcopy(payload["training"])
            encoded = canonical_json({"fixture": True, "training_identity": identity(self.fit_data)})
            revision = hashlib.sha256(encoded).hexdigest()
            self.bundle, self.revision = encoded, revision
            return {"bundle_base64": base64.b64encode(encoded).decode(), "model_revision": revision,
                "preprocessing_state": {"test_values_used": False, "fit_members": self.fit_data["training_members"]},
                "training_provenance": {"evidence_origin": "simulated_fit_fixture", "native_training_calls": 1,
                    "evaluation_values_read": False, "source": self.source, "revision": self.source["revision"]},
                "identity": identity(self.fit_data), "evaluation_lengths": payload["evaluation_lengths"],
                "work_dir": str(self.root / "synthetic-worker-dir")}
        if operation in ("score", "replay"):
            data = payload["input"]
            self.score_data.append(copy.deepcopy(data))
            curves = [{"curve_id": row["curve_id"], "scores": [float(index) / len(row["values"]) for index in range(2, len(row["values"]))],
                       "offset": 2, "raw_length": len(row["values"])} for row in data["curves"]]
            digests = {row["curve_id"]: digest(row["scores"]) for row in curves}
            return {"dataset_revision": data["dataset_revision"], "planning_unit_id": data["planning_unit_id"],
                "curves": curves, "model_revision": self.revision, "score_digests": digests,
                "provenance": {**self.source, "pid": 1002 if operation == "score" else 1003},
                "training_pid": 1001, "native_training_calls": 0, "scaler_fit_calls": 0, "fresh_process": True,
                "bitwise_equal": operation == "replay",
                "work_dir": str(self.root / "synthetic-worker-dir")}
        self.fail("Unexpected scientific operation in lightweight fixture: " + operation)

    def official(self, curves, metrics):
        self.scoring_calls.append(copy.deepcopy(curves))
        return {"metrics": {metric: .75 for metric in metrics}, "per_curve": [
            {"curve_id": curve["curve_id"], "status": "scored", "reason": None,
             "metrics": {metric: .75 for metric in metrics}} for curve in curves],
            "provenance": {"evidence_origin": "explicit_simulated_official_metric_fixture"}}

    def test_prepare_observation_one_result_and_postrun_rescore_keep_sealed_execution(self):
        from gymts_timesigma.pipeline import attach_and_rescore, evaluation_spec
        imported = import_dataset(self.app, self.dataset, schema="all_in_one")
        self.expected_imported = imported
        spec = evaluation_spec(imported, self.params())
        case = spec["cases"][0]
        experiment = {"protocol_version": "gymts.experiment/1", "name": "explicit simulation test",
            "purpose": "development", **{key: case[key] for key in ("scene", "execution", "recording")},
            "candidate": spec["candidates"][0]["spec"], "extensions": {}}
        validation = self.app.validate(experiment)
        self.assertTrue(validation["valid"], validation["issues"])
        initial = self.app.autobench.evaluate(spec)
        self.assertEqual(initial["status"], "completed")
        manifest = self.app.artifacts.read_json(initial["run_manifest_ref"])
        self.assertEqual(len(manifest["entries"]), 1)
        run_id = manifest["entries"][0]["run_id"]
        original = self.app.records.get_run(run_id)
        self.assertEqual(original["result"]["status"], "succeeded", original["result"])
        sealed_digest = digest(original["result"])
        trace = self.app.artifacts.read_json(original["result"]["trace_ref"])["events"]
        decoded = [(event, event["payload"]["value"] if event["payload"]["storage"] == "inline" else self.app.artifacts.read_json(event["payload"]["artifact_ref"])) for event in trace]
        self.assertEqual(len([event for event, _ in decoded if event["kind"] == "input"]), 1)
        self.assertEqual(len([event for event, _ in decoded if event["kind"] == "task_result"]), 1)
        self.assertLess(self.order.index("fit"), self.order.index("observe"))
        self.assertEqual(self.denied_prepare_refs, ["snapshot_ref", "private_ref", "manifest_ref"])
        kinds = [event["kind"] for event, _ in decoded]
        self.assertLess(kinds.index("candidate_prepare"), kinds.index("observation"))
        self.assertLess(kinds.index("observation"), kinds.index("input"))
        model_input = next(body for event, body in decoded if event["kind"] == "input")["payload"]["value"]
        self.assertEqual(model_input["curves"], self.app.artifacts.read_json(imported["snapshot_ref"])["curves"])
        self.assertEqual(self.fit_data, self.app.artifacts.read_json(imported["training_ref"]))
        self.assertNotIn('"labels"', json.dumps(self.fit_data))
        self.assertNotIn('"labels"', json.dumps(model_input))
        self.assertFalse(any(value >= 10000 for row in self.fit_data["curves"] for value in row["values"]))
        expected_count = len(imported["evaluation_members"])
        for entry in initial["metrics"]:
            if entry["level"] == "unit":
                self.assertIsNone(entry["result"]["value"])
                self.assertEqual(entry["result"]["counts"], {"eligible": expected_count, "scored": 0,
                    "missing": expected_count, "invalid": 0, "excluded": 0})
        self.assertEqual(self.scoring_calls, [], "Unlabeled outputs must not invoke the native evaluator")
        final, _, run_ids = attach_and_rescore(self.app, imported, spec, initial)
        self.assertEqual(run_ids, [run_id])
        self.assertEqual(self.app.artifacts.read_json(final["run_manifest_ref"])["entries"], manifest["entries"])
        self.assertEqual(digest(self.app.records.get_run(run_id)["result"]), sealed_digest)
        self.assertEqual([op for op, _ in self.calls].count("fit"), 1, "Rescore must not refit or reinfer")
        self.assertEqual(len(self.scoring_calls), 1)
        self.assertEqual([row["curve_id"] for row in self.scoring_calls[0]], imported["evaluation_members"])
        for entry in final["metrics"]:
            if entry["level"] == "unit":
                self.assertEqual(entry["result"]["value"], .75)
                self.assertEqual(entry["result"]["counts"], {"eligible": expected_count, "scored": expected_count,
                    "missing": 0, "invalid": 0, "excluded": 0})
        self.assertEqual({entry["metric_id"] for entry in final["metrics"]}, set(METRIC_IDS))

    def test_tag_grouped_rescore_preserves_plan_tags_and_sealed_execution(self):
        from gymts_timesigma.pipeline import attach_and_rescore, evaluation_spec
        imported = import_dataset(self.app, self.dataset, schema="all_in_one")
        spec = evaluation_spec(imported, self.params())
        spec["comparison"]["group_by"] = ["evaluation_case_id", "tags.schema"]
        initial = self.app.autobench.evaluate(spec)
        self.assertEqual(initial["status"], "completed")
        plan = self.app.artifacts.read_json(initial["plan_ref"])
        manifest = self.app.artifacts.read_json(initial["run_manifest_ref"])
        run_id = manifest["entries"][0]["run_id"]
        sealed_digest = digest(self.app.records.get_run(run_id)["result"])
        operations = [operation for operation, _ in self.calls]
        self.assertEqual(operations, ["fit", "score", "replay"])

        final, score_spec, run_ids = attach_and_rescore(self.app, imported, spec, initial)

        self.assertEqual(final["status"], "completed")
        self.assertEqual(final["verdict"], "pass")
        self.assertEqual(run_ids, [run_id])
        rescored_plan = self.app.artifacts.read_json(final["plan_ref"])
        original_tags = [unit["tags"] for unit in plan["expected_units"]]
        self.assertEqual([unit["tags"] for unit in rescored_plan["expected_units"]], original_tags)
        self.assertEqual([selection["tags"] for selection in score_spec["runs"]], original_tags)
        self.assertEqual(original_tags[0]["schema"], "all_in_one")
        self.assertEqual(digest(self.app.records.get_run(run_id)["result"]), sealed_digest)
        self.assertEqual([operation for operation, _ in self.calls], operations)

    def test_partial_outcome_keeps_every_planned_curve_in_the_denominator(self):
        from gymts_timesigma.pipeline import attach_and_rescore, evaluation_spec
        imported = import_dataset(self.app, self.dataset, schema="all_in_one")
        self.expected_imported = imported
        spec = evaluation_spec(imported, self.params())
        initial = self.app.autobench.evaluate(spec)
        original_manifest = self.app.artifacts.read_json(initial["run_manifest_ref"])
        private = self.app.artifacts.read_json(imported["private_ref"])
        private["outcome"]["curves"] = private["outcome"]["curves"][:1]
        partial = {**imported, "private_ref": self.app.artifacts.save_json(private, imported["private_ref"]["schema_ref"])}
        final, _, _ = attach_and_rescore(self.app, partial, spec, initial)
        self.assertEqual(self.app.artifacts.read_json(final["run_manifest_ref"])["entries"], original_manifest["entries"])
        for row in final["metrics"]:
            if row["level"] == "unit":
                self.assertEqual(row["result"]["counts"], {"eligible": 3, "scored": 1, "missing": 2, "invalid": 0, "excluded": 0})
        self.assertEqual(len(self.scoring_calls), 1)
        self.assertEqual(len(self.scoring_calls[0]), 1)
        self.assertEqual([operation for operation, _ in self.calls], ["fit", "score", "replay"])

    def test_repeated_fixed_gold_revision_attaches_to_new_run_without_changing_temporal_facts(self):
        from gymts_timesigma.pipeline import run_experiment
        imported = import_dataset(self.app, self.dataset, schema="all_in_one")
        self.expected_imported = imported
        first = run_experiment(self.app, imported, self.params())
        original = self.app.records.read_outcomes({"run_ids": first["run_ids"]})
        second = run_experiment(self.app, imported, self.params())
        self.assertNotEqual(first["run_ids"], second["run_ids"])
        self.assertEqual(original, self.app.records.read_outcomes({"run_ids": second["run_ids"]}))
        self.assertEqual("pass", second["report"]["verdict"])
        self.assertEqual(2, [operation for operation, _ in self.calls].count("fit"))

    def test_zero_shot_prepare_sees_heldout_train_but_only_fit_members_can_train(self):
        from gymts_timesigma.pipeline import evaluation_spec
        imported = import_dataset(self.app, self.dataset, schema="zero_shot")
        self.expected_imported = imported
        report = self.app.autobench.evaluate(evaluation_spec(imported, self.params()))
        self.assertEqual(report["coverage"]["succeeded_runs"], 1)
        self.assertEqual([row["curve_id"] for row in self.fit_data["curves"]], imported["preprocessing_members"])
        self.assertFalse(set(self.fit_data["training_members"]) & set(imported["evaluation_members"]))
        self.assertEqual(len(self.fit_data["curves"]), 3)
        self.assertEqual([row["curve_id"] for row in self.score_data[0]["curves"]], imported["evaluation_members"])
        self.assertEqual(self.score_data[0], self.score_data[1], "Replay must use exactly the committed evaluation inputs")
        self.assertTrue(all(value >= 10000 for row in self.score_data[0]["curves"] for value in row["values"]))
        self.assertEqual([operation for operation, _ in self.calls], ["fit", "score", "replay"])


if __name__ == "__main__":
    unittest.main()
