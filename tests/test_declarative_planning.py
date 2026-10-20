"""Pure declaration planning, deferred opening and per-Run random streams."""
import copy
from contextlib import ExitStack
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import GymTSError
from gymts.plugins import ForecastCandidate, TimeSeriesReplay, WindowForecastTask

ROOT = Path(__file__).resolve().parents[1]


class SeededFixture(ForecastCandidate):
    """A fixture using only the Runner's local random stream, not a real model."""
    seeds = []
    inaccessible = None

    def prepare(self, context, training):
        self.rng = context["rng"]
        self.seeds.append(context["execution_seed"])
        if self.inaccessible is not None:
            try:
                context["resources"].read_json(self.inaccessible)
            except GymTSError as error:
                if error.code != "permission_denied":
                    raise
            else:
                raise AssertionError("Provenance reference was granted to a Candidate")
        return super().prepare(context, training)

    def infer(self, value):
        output = super().infer(value)
        output["payload"]["value"]["prediction"] = self.rng.random()
        return output


class PlanningContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.gym = GymTS(self.temp.name)
        self.spec = json.loads((ROOT / "examples/forecast_experiment.json").read_text())

    def tearDown(self):
        self.gym.close()
        self.temp.cleanup()

    def register_seeded(self, compatibility=None):
        manifest = self.gym.registries.candidates.resolve("last-value", "1.0.0")
        manifest["component_ref"]["name"] = "seeded-explicit-fixture"
        self.gym.registries.candidates.register(manifest, SeededFixture, compatibility=compatibility)
        self.spec["candidate"]["adapter"] = "seeded-explicit-fixture"

    def test_plan_and_validate_never_construct_plugins_or_touch_artifact_storage(self):
        ref = self.gym.artifacts.save_json({"private": "deferred"}, "gymts.json/1")
        self.spec["candidate"]["artifact"] = ref
        self.spec["provenance"] = {"source_refs": [ref], "usage_policy_ref": None, "benchmark_definition_ref": None}
        with ExitStack() as stack:
            stack.enter_context(patch.object(self.gym.records, "begin_run", side_effect=AssertionError("Planning opened a Run")))
            for cls in (TimeSeriesReplay, WindowForecastTask, ForecastCandidate):
                stack.enter_context(patch.object(cls, "__init__", side_effect=AssertionError("Planning constructed a plugin")))
            for name in ("resolve", "read_json", "read_view", "save_json", "save_artifact"):
                stack.enter_context(patch.object(self.gym.artifacts, name, side_effect=AssertionError("Planning touched artifact storage")))
            plan = self.gym.environment_ts.plan(self.spec)
            validation = self.gym.validate(self.spec)
        self.assertEqual("gymts.assembly-plan/1", plan["protocol_version"])
        self.assertEqual("deferred_to_open", plan["resource_checks"])
        self.assertTrue(validation["valid"], validation)
        self.assertIsNone(validation["resolved_spec_ref"])
        self.assertEqual(plan["resolved_spec"], validation["resolved_spec"])

    def test_generic_same_protocol_rule_rejects_known_unsupported_configuration(self):
        def compatible(context):
            if context["experiment"]["scene"]["task"]["params"]["window_points"] > 3:
                raise GymTSError("unsupported_capability", "Fixture supports windows of at most three")
            context["experiment"]["name"] = "provider mutation must remain isolated"
        self.register_seeded(compatible)
        original = copy.deepcopy(self.spec)
        self.assertTrue(self.gym.validate(self.spec)["valid"])
        self.assertEqual(original, self.spec)
        self.spec["scene"]["task"]["params"]["window_points"] = 4
        with patch.object(SeededFixture, "__init__", side_effect=AssertionError("Rejected candidate was constructed")):
            result = self.gym.validate(self.spec)
            self.assertFalse(result["valid"])
            self.assertEqual("unsupported_capability", result["issues"][0]["code"])
            with self.assertRaises(GymTSError):
                self.gym.run(self.spec)

    def test_missing_pure_provider_is_explicit_without_legacy_constructor_fallback(self):
        manifest = self.gym.registries.environments.resolve("local-timeseries-replay", "1.0.0")
        manifest["component_ref"]["name"] = "undeclared-external-source"
        def forbidden(*args):
            raise AssertionError("Legacy constructor fallback was called")
        self.gym.registries.environments.register(manifest, forbidden)
        self.spec["scene"]["environment"]["adapter"] = "undeclared-external-source"
        result = self.gym.validate(self.spec)
        self.assertFalse(result["valid"])
        self.assertEqual("unsupported_capability", result["issues"][0]["code"])

    def test_runtime_constructor_failure_is_a_sealed_failed_run(self):
        with patch.object(TimeSeriesReplay, "__init__", side_effect=OSError("unavailable source")):
            self.assertTrue(self.gym.validate(self.spec)["valid"])
            result = self.gym.run(self.spec)
        self.assertEqual("failed", result["status"])
        self.assertEqual("create", result["errors"][0]["stage"])
        saved = self.gym.records.get_run(result["run_id"])
        self.assertEqual(result, saved["result"])
        self.assertTrue(any(event["kind"] == "error" for event in saved["events"]))
        self.assertEqual("run_end", saved["events"][-1]["kind"])

    def test_scene_reference_is_an_explicit_execution_only_compatibility_path(self):
        self.spec["scene_ref"] = self.gym.artifacts.save_json(self.spec.pop("scene"), "gymts.json/1")
        with patch.object(self.gym.artifacts, "read_json", side_effect=AssertionError("Offline planning dereferenced scene_ref")):
            validation = self.gym.validate(self.spec)
            self.assertFalse(validation["valid"])
            self.assertEqual("unsupported_capability", validation["issues"][0]["code"])
        self.assertEqual("succeeded", self.gym.run(self.spec)["status"])

    def test_unavailable_artifact_is_deferred_and_leaves_failed_run_evidence(self):
        ref = self.gym.artifacts.save_json({"state": "unavailable"}, "gymts.json/1")
        self.gym.artifacts.resolve(ref).unlink()
        self.spec["candidate"]["artifact"] = ref
        self.assertTrue(self.gym.validate(self.spec)["valid"])
        with patch.object(ForecastCandidate, "__init__", side_effect=AssertionError("Unavailable state was opened")) as constructor:
            result = self.gym.run(self.spec)
        self.assertEqual("failed", result["status"])
        self.assertEqual(result, self.gym.records.get_run(result["run_id"])["result"])
        constructor.assert_not_called()

    def test_opened_capability_drift_is_rejected_before_candidate_prepare(self):
        original = TimeSeriesReplay.describe
        def drift(instance):
            value = original(instance)
            value["capabilities"]["query"] = False
            return value
        with patch.object(TimeSeriesReplay, "describe", drift), \
                patch.object(ForecastCandidate, "prepare", side_effect=AssertionError("Candidate was prepared after drift")) as prepare:
            self.assertTrue(self.gym.validate(self.spec)["valid"])
            result = self.gym.run(self.spec)
        self.assertEqual("failed", result["status"])
        self.assertEqual("conflict", result["errors"][0]["code"])
        prepare.assert_not_called()

    def test_execution_seed_uses_independent_rng_and_is_recorded(self):
        self.register_seeded()
        SeededFixture.seeds = []
        self.spec["execution"]["seed"] = 7
        global_state = random.getstate()
        first, second = self.gym.run(self.spec), self.gym.run(self.spec)
        self.spec["execution"]["seed"] = 8
        third = self.gym.run(self.spec)
        values = lambda result: [row["payload"]["value"]["prediction"] for row in self.gym.artifacts.read_json(result["result_ref"])]
        self.assertTrue(values(first))
        self.assertEqual(values(first), values(second))
        self.assertNotEqual(values(first), values(third))
        self.assertEqual([7, 7, 8], SeededFixture.seeds)
        self.assertEqual(global_state, random.getstate())
        events = self.gym.records.get_run(first["run_id"])["events"]
        randomness = [event["payload"]["value"]["value"] for event in events if event["kind"] == "artifact" and
                      event["payload"]["storage"] == "inline" and event["payload"]["value"].get("role") == "candidate_randomness"]
        self.assertEqual(7, randomness[0]["seed"])

    def test_autobench_repetition_seeds_reach_same_candidate_identity(self):
        self.register_seeded()
        SeededFixture.seeds = []
        evaluation = json.loads((ROOT / "examples/forecast_evaluation.json").read_text())
        evaluation["candidates"] = [{"candidate_id": "fixture", "spec": copy.deepcopy(self.spec["candidate"])}]
        evaluation["baseline_id"] = None
        evaluation["comparison"]["gates"] = []
        evaluation["repetitions"] = {"count": 2, "seeds": [7, 8]}
        report = self.gym.autobench.evaluate(evaluation)
        self.assertEqual("completed", report["status"])
        self.assertEqual([7, 8], SeededFixture.seeds)
        plan = self.gym.artifacts.read_json(report["plan_ref"])
        candidates = [self.gym.artifacts.read_json(unit["resolved_spec_ref"])["candidate"] for unit in plan["expected_units"]]
        self.assertEqual(candidates[0], candidates[1])
        self.assertNotIn("seed", candidates[0]["params"])

    def test_provenance_reaches_metadata_without_granting_candidate_access(self):
        self.register_seeded()
        ref = self.gym.artifacts.save_json({"private": "source provenance"}, "gymts.json/1")
        policy = self.gym.artifacts.save_json({"allowed_uses": ["evaluation"], "training_allowed": False}, "gymts.source-usage-policy/1")
        self.spec["provenance"] = {"source_refs": [ref], "usage_policy_ref": policy, "benchmark_definition_ref": None}
        SeededFixture.inaccessible = ref
        try:
            result = self.gym.run(self.spec)
        finally:
            SeededFixture.inaccessible = None
        self.assertEqual("succeeded", result["status"], result["errors"])
        metadata = self.gym.records.get_run(result["run_id"])["metadata"]
        self.assertEqual([ref], metadata["source_refs"])
        self.assertEqual(policy, metadata["usage_policy_ref"])

    def test_evaluation_only_source_cannot_be_collected_for_training(self):
        policy = self.gym.artifacts.save_json({"allowed_uses": ["evaluation"], "training_allowed": False}, "gymts.source-usage-policy/1")
        self.spec["provenance"] = {"source_refs": [], "usage_policy_ref": policy, "benchmark_definition_ref": None}
        self.spec["purpose"] = "training_collection"
        with patch.object(TimeSeriesReplay, "__init__", side_effect=AssertionError("Forbidden source was opened")) as constructor:
            self.assertTrue(self.gym.validate(self.spec)["valid"])
            result = self.gym.run(self.spec)
        self.assertEqual("failed", result["status"])
        self.assertEqual("permission_denied", result["errors"][0]["code"])
        self.assertEqual(result, self.gym.records.get_run(result["run_id"])["result"])
        constructor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
