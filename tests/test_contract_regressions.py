"""Registration failures must be deterministic before any plugin executes."""
import copy
import unittest

from gymts.contracts import GymTSError
from gymts.contracts.schema import SchemaRegistry, register_core_schemas
from gymts.plugins import register_builtin_plugins
from gymts.registries import Registries


class ContractRegressions(unittest.TestCase):
    def setUp(self):
        self.schemas = SchemaRegistry()
        register_core_schemas(self.schemas)
        self.registries = Registries(self.schemas)
        register_builtin_plugins(self.registries, self.schemas)

    def candidate(self):
        item = self.registries.candidates.resolve("last-value", "1.0.0")
        item["component_ref"]["name"] = "external-composite"
        return item

    def test_composite_registers_under_adapter_identity(self):
        item = self.candidate()
        item["component_refs"] = [{"name": "external-inner", "version": "2.0.0", "origin_ref": None}]
        factory = lambda spec: {"created": spec["adapter"]}
        self.registries.candidates.register(item, factory)
        self.assertEqual(item, self.registries.candidates.resolve("external-composite", "1.0.0"))
        self.assertEqual({"created": "external-composite"}, self.registries.candidates.create({
            "adapter": "external-composite", "version": "1.0.0", "params": {}}))
        with self.assertRaises(GymTSError):
            self.registries.candidates.resolve("external-inner", "2.0.0")
        changed = copy.deepcopy(item)
        changed["component_refs"][0]["version"] = "3.0.0"
        with self.assertRaises(GymTSError) as caught:
            self.registries.candidates.register(changed, factory)
        self.assertEqual("conflict", caught.exception.code)

    def test_malformed_candidate_rejected_at_registration(self):
        for patch in ({"component_refs": None}, {"component_refs": "inner"},
                      {"component_refs": [{}]}, {"supported_task_protocols": []},
                      {"input_schema_refs": [None]}, {"origin_ref": "not-an-artifact"},
                      {"params_schema_ref": []}):
            with self.subTest(patch=patch):
                item = self.candidate()
                item.update(patch)
                with self.assertRaises(GymTSError):
                    self.registries.candidates.register(item, lambda spec: None)

    def test_all_composite_identities_must_be_fixed(self):
        for field in ("implementation_ref", "component_refs"):
            item = self.candidate()
            ref = {"name": "moving", "version": "latest", "origin_ref": None}
            item[field] = [ref] if field == "component_refs" else ref
            with self.subTest(field=field), self.assertRaises(GymTSError):
                self.registries.candidates.register(item, lambda spec: None)

    def test_callable_factory_with_noncallable_create_attribute(self):
        class Factory:
            create = None

            def __call__(self, spec):
                return spec["adapter"]

        self.registries.candidates.register(self.candidate(), Factory())
        self.assertEqual("external-composite", self.registries.candidates.create({
            "adapter": "external-composite", "version": "1.0.0", "params": {}}))

    def test_malformed_metric_cannot_reach_evaluation(self):
        for patch in ({"direction": "guess"}, {"requires_outcome": "false"},
                      {"eligibility_schema_ref": []}):
            item = self.registries.scorers.resolve("forecast-mae", "1.0.0")
            item["component_ref"]["name"] = "external-scorer"
            item["metrics"]["mae"].update(patch)
            with self.subTest(patch=patch), self.assertRaises(GymTSError):
                self.registries.scorers.register(item, lambda spec: None)

    def test_malformed_schema_cannot_be_published(self):
        for schema in ({"type": "array", "items": "not-a-schema"},
                       {"type": "array", "items": []},
                       {"enum": [1, 1]}, {"const": float("nan")},
                       {"default": object()}, {"required": ["a", "a"]},
                       {"type": ["string", "string"]}):
            with self.subTest(schema=schema), self.assertRaises(GymTSError):
                self.schemas.register("external/bad/1", schema)

    def test_unhashable_references_raise_structured_errors(self):
        with self.assertRaises(GymTSError):
            self.schemas.resolve([])
        with self.assertRaises(GymTSError):
            self.registries.candidates.resolve([], "1.0.0")

    def test_arbitrary_precision_json_integers_do_not_overflow_float_checks(self):
        large = 10 ** 400
        self.schemas.register("external/large/1", {"type": "integer", "minimum": large})
        self.schemas.validate("external/large/1", large)
        self.schemas.validate("gymts.json/1", large)
        with self.assertRaises(GymTSError):
            self.schemas.validate("external/large/1", large - 1)


if __name__ == "__main__":
    unittest.main()
