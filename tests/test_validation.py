"""C01/C02: invalid contracts must be rejected before environment effects."""

import copy
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gymts.contracts import GymTSError
from gymts.contracts.schema import SchemaRegistry, register_core_schemas
from gymts.plugins import (CounterControlTask, CounterTransition, ForecastCandidate,
                           TimeSeriesReplay, register_builtin_plugins)
from gymts.registries import Registries
from gymts.storage import ArtifactStore, LocalExperimentRecords


ROOT = Path(__file__).resolve().parents[1]


class RegistryContracts(unittest.TestCase):
    def setUp(self):
        self.schemas = SchemaRegistry()
        register_core_schemas(self.schemas)
        self.registries = Registries(self.schemas)
        register_builtin_plugins(self.registries, self.schemas)

    def test_every_role_rejects_missing_required_manifest_fields(self):
        cases = [
            (self.registries.environments, "local-timeseries-replay", ["source_schema_ref", "mapping_schema_ref", "options_schema_ref"]),
            (self.registries.tasks, "window_forecast", ["task_protocol_ref", "input_schema_ref", "output_schema_ref", "result_schema_ref", "outcome_schema_ref", "alignment_schema_ref"]),
            (self.registries.candidates, "last-value", ["implementation_ref", "component_refs", "supported_task_protocols", "input_schema_refs", "output_schema_refs", "supports_fit", "fit_requires_targets", "supports_update", "model_revision_mode", "capture_profiles"]),
            (self.registries.scorers, "forecast-mae", ["supported_task_protocols", "result_schema_refs", "outcome_schema_refs", "metrics"]),
        ]
        for registry, name, fields in cases:
            for field in fields:
                with self.subTest(kind=registry.kind, missing=field):
                    manifest = registry.resolve(name, "1.0.0")
                    manifest["component_ref"]["name"] = "incomplete-" + name + "-" + field
                    del manifest[field]
                    with self.assertRaises(GymTSError):
                        registry.register(manifest, lambda *args: None)

    def test_protocol_declarations_are_typed_and_supported(self):
        for index, protocols in enumerate(("gymts.candidate/1", [], ["gymts.candidate/99"], [123])):
            with self.subTest(protocols=protocols):
                manifest = self.registries.candidates.resolve("last-value", "1.0.0")
                manifest["component_ref"]["name"] = "bad-protocol-" + str(index)
                manifest["protocol_versions"] = protocols
                with self.assertRaises(GymTSError):
                    self.registries.candidates.register(manifest, lambda *args: None)

    def test_fixed_component_identity_is_not_overwritten(self):
        manifest = self.registries.candidates.resolve("last-value", "1.0.0")
        manifest["supports_fit"] = True
        with self.assertRaises(GymTSError) as caught:
            self.registries.candidates.register(manifest, lambda *args: None)
        self.assertEqual("conflict", caught.exception.code)
        self.assertFalse(self.registries.candidates.resolve("last-value", "1.0.0")["supports_fit"])

    def test_malformed_schema_definition_cannot_disable_unknown_field_checks(self):
        for index, schema in enumerate((
            {"type": "object", "additionalProperties": "false"},
            {"type": "integar"},
            {"type": "object", "required": "name"},
        )):
            with self.subTest(schema=schema):
                with self.assertRaises(GymTSError):
                    self.schemas.register("invalid-" + str(index) + "/1", schema)


class ValidationContracts(unittest.TestCase):
    def setUp(self):
        from gymts.environment_ts import EnvironmentTS
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.schemas = SchemaRegistry()
        register_core_schemas(self.schemas)
        self.registries = Registries(self.schemas)
        register_builtin_plugins(self.registries, self.schemas)
        self.artifacts = ArtifactStore(root / "artifacts")
        self.records = LocalExperimentRecords(root / "records", self.artifacts)
        self.service = EnvironmentTS(self.registries, self.schemas, self.records, self.artifacts,
                                     store_refs=("local://records/default",))
        self.forecast = json.loads((ROOT / "examples/forecast_experiment.json").read_text())
        self.counter = json.loads((ROOT / "examples/counter_experiment.json").read_text())

    def tearDown(self):
        self.records.close()
        self.temporary.cleanup()

    def no_effects(self):
        stack = ExitStack()
        mocks = []
        for cls, method in ((TimeSeriesReplay, "start"), (TimeSeriesReplay, "act"),
                            (CounterTransition, "start"), (CounterTransition, "act"),
                            (ForecastCandidate, "prepare"), (ForecastCandidate, "infer")):
            mocks.append(stack.enter_context(patch.object(cls, method, side_effect=AssertionError("Validation performed an execution effect"))))
        return stack, mocks

    def reject(self, spec):
        stack, mocks = self.no_effects()
        with stack:
            report = self.service.validate(spec)
            self.assertFalse(report["valid"])
            self.assertTrue(report["issues"])
            with self.assertRaises(GymTSError):
                self.service.run(spec)
        for mock in mocks:
            mock.assert_not_called()

    def test_valid_configuration_only_resolves_and_describes(self):
        stack, mocks = self.no_effects()
        with stack:
            report = self.service.validate(self.forecast)
        self.assertTrue(report["valid"], report)
        self.assertIsNone(report["resolved_spec_ref"])
        fixed = report["resolved_spec"]
        self.assertEqual("gymts.experiment/1", fixed["protocol_version"])
        for mock in mocks:
            mock.assert_not_called()

    def test_missing_unknown_and_wrong_version_are_rejected_before_start(self):
        missing = copy.deepcopy(self.forecast)
        del missing["candidate"]["artifact"]
        unknown = copy.deepcopy(self.forecast)
        unknown["execution"]["limits"]["max_input"] = 3
        wrong = copy.deepcopy(self.forecast)
        wrong["protocol_version"] = "gymts.experiment/99"
        wrong_environment = copy.deepcopy(self.forecast)
        wrong_environment["scene"]["environment"]["protocol_version"] = "gymts.environment/99"
        for spec in (missing, unknown, wrong, wrong_environment):
            with self.subTest(spec=spec.get("protocol_version")):
                self.reject(spec)

    def test_unknown_plugin_params_and_incompatible_candidate(self):
        params = copy.deepcopy(self.forecast)
        params["candidate"]["params"]["silently_ignored"] = True
        incompatible = copy.deepcopy(self.forecast)
        incompatible["candidate"] = copy.deepcopy(self.counter["candidate"])
        self.reject(params)
        self.reject(incompatible)

    def test_binding_units_and_environment_shape_are_checked(self):
        unit = copy.deepcopy(self.forecast)
        unit["scene"]["binding"]["variables"]["value"]["unit"] = "percent"
        self.reject(unit)
        provider = self.registries.environments._providers[("local-timeseries-replay", "1.0.0")]
        describe = provider["describe"]
        def vector(spec):
            result = describe(spec)
            result["variables"]["value"]["shape"] = [2]
            return result
        with patch.dict(provider, describe=vector):
            self.reject(self.forecast)

    def test_seed_fit_and_online_learning_capabilities_are_checked(self):
        provider = self.registries.environments._providers[("local-timeseries-replay", "1.0.0")]
        describe = provider["describe"]
        def no_seed(spec):
            result = describe(spec)
            result["capabilities"]["seed"] = False
            return result
        with patch.dict(provider, describe=no_seed):
            self.reject(self.forecast)
        fit = copy.deepcopy(self.forecast)
        fit["execution"]["learning"]["prepare"] = "fit"
        self.reject(fit)
        online = copy.deepcopy(self.forecast)
        online["execution"]["learning"]["online"] = "update"
        online["execution"]["learning"]["allowed_feedback_sources"] = ["authorized"]
        self.reject(online)

    def test_same_operation_name_with_different_argument_contract_is_rejected(self):
        self.schemas.register("test.wrong-operation/1", {"type": "object", "required": ["text"],
                             "properties": {"text": {"type": "string"}}, "additionalProperties": False})
        provider = self.registries.tasks._providers[("counter_control", "1.0.0")]
        describe = provider["describe"]
        def wrong_operation(spec):
            result = describe(spec)
            result["required_operations"]["increment"]["arguments_schema_ref"] = "test.wrong-operation/1"
            return result
        with patch.dict(provider, describe=wrong_operation):
            self.reject(self.counter)

    def test_malformed_environment_description_is_rejected(self):
        provider = self.registries.environments._providers[("local-timeseries-replay", "1.0.0")]
        describe = provider["describe"]
        for changed in ({"clock_domain": "guess"}, {"advance_mode": "magic"}):
            def malformed(spec, changed=changed):
                result = describe(spec)
                result.update(changed)
                return result
            with self.subTest(changed=changed), patch.dict(provider, describe=malformed):
                self.reject(self.forecast)

    def test_invalid_task_duration_is_rejected_before_start(self):
        for field in ("horizon", "advance_by"):
            bad = copy.deepcopy(self.forecast)
            bad["scene"]["task"]["params"][field] = "0"
            with self.subTest(field=field):
                self.reject(bad)


if __name__ == "__main__":
    unittest.main()
