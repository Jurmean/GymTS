"""Offline TimeSigma assembly checks use declarations, never scientific execution."""
import copy
from contextlib import ExitStack
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts_timesigma.candidate import BUNDLE, TimeSigmaCandidate
from gymts_timesigma.contracts import SNAPSHOT, TRAINING, identity
from gymts_timesigma.environment import TimeSigmaSnapshotEnvironment
from gymts_timesigma.pipeline import evaluation_spec
from gymts_timesigma.task import TimeSigmaTask
from test_timesigma_candidate import fixture


class TimeSigmaPlanningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.gym = GymTS(self.tmp.name, integrations=("timesigma",))
        self.addCleanup(self.gym.close)
        public, training = fixture(training=False), fixture(training=True)
        self.imported = dict(identity(public), snapshot_ref=self.gym.artifacts.save_json(public, SNAPSHOT),
                             training_ref=self.gym.artifacts.save_json(training, TRAINING))
        self.params = {"source_repo": "/not-opened", "python": "/not-executed", "method": "AR"}

    def experiment(self, **kwargs):
        evaluation = evaluation_spec(self.imported, self.params, execution_seed=19, **kwargs)
        case = evaluation["cases"][0]
        return {"protocol_version": "gymts.experiment/1", "name": "explicit planning fixture", "purpose": "development",
            "scene": case["scene"], "execution": case["execution"], "recording": case["recording"],
            "candidate": evaluation["candidates"][0]["spec"], "extensions": {}}

    def test_pure_fit_plan_does_not_open_arrays_models_interpreters_or_cas(self):
        spec = self.experiment()
        with ExitStack() as stack:
            for cls in (TimeSigmaSnapshotEnvironment, TimeSigmaTask, TimeSigmaCandidate):
                stack.enter_context(patch.object(cls, "__init__", side_effect=AssertionError("Planning constructed a live role")))
            for name in ("resolve", "read_json", "read_view", "save_json"):
                stack.enter_context(patch.object(self.gym.artifacts, name, side_effect=AssertionError("Planning accessed CAS")))
            self.assertTrue(self.gym.validate(spec)["valid"])
            self.assertEqual("deferred_to_open", self.gym.plan(spec)["resource_checks"])
        self.assertNotIn("seed", spec["candidate"]["params"])
        self.assertEqual(19, spec["execution"]["seed"])

    def test_known_fit_bundle_and_native_binding_constraints_fail_before_open(self):
        spec = self.experiment()
        variants = []
        wrong_training = copy.deepcopy(spec)
        wrong_training["execution"]["learning"]["training_view"]["source_refs"][0] = self.imported["snapshot_ref"]
        variants.append((wrong_training, "schema_mismatch"))
        fixed_binding = copy.deepcopy(spec)
        fixed_binding["candidate"]["params"]["method"] = "IsolationForest"
        variants.append((fixed_binding, "unsupported_capability"))
        load = self.experiment(artifact=self.imported["snapshot_ref"])
        variants.append((load, "schema_mismatch"))
        for variant, code in variants:
            with self.subTest(code=code), patch.object(TimeSigmaCandidate, "__init__", side_effect=AssertionError("Unsupported model opened")):
                report = self.gym.validate(variant)
                self.assertFalse(report["valid"])
                self.assertEqual(code, report["issues"][0]["code"])
        bundle = self.gym.artifacts.save_artifact(b"explicit fixture; not a native model", {"schema_ref": BUNDLE})
        self.assertTrue(self.gym.validate(self.experiment(artifact=bundle))["valid"])
        # Bundle identity, Schema member lists and Task planning_unit_id remain
        # data-dependent checks. Offline validation does not claim to inspect them.


if __name__ == "__main__":
    unittest.main()
