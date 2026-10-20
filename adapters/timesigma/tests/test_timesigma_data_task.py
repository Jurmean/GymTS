"""Native planning-unit, split, source-integrity and privilege-boundary tests.

Arrays below are explicit local fixtures, never claimed as benchmark results.
No provider, model fitting or external checkout is needed.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import GymTSError
from gymts.environment_ts.services import RestrictedServices
from gymts_timesigma.contracts import (
    CONTEXT, INPUT, OUTPUT, PRIVATE, SNAPSHOT, TRAINING, identity, timesigma_schemas,
)
from gymts_timesigma.data import import_dataset, native_zero_shot_split, training_view
from gymts_timesigma.environment import TimeSigmaSnapshotEnvironment
from gymts_timesigma.task import TimeSigmaTask
from gymts.plugin_support import payload

try:
    import numpy as np
except ImportError:
    np = None


def fixture(root, members=("a", "b", "c")):
    for index, curve in enumerate(members):
        directory = root / "UTS" / "TODS" / curve
        directory.mkdir(parents=True)
        # Different train/test lengths and float32 values detect silent casting,
        # slicing, interpolation, resampling and concatenation.
        np.save(directory / "train.npy", np.arange(12 + index, dtype="float32") + index * 100)
        np.save(directory / "test.npy", np.arange(9 + index, dtype="float32") + 10000 + index * 100)
        np.save(directory / "test_label.npy", np.asarray([0, 0, 1] + [0] * (6 + index), dtype="int64"))
        (directory / "info.json").write_text('{"private_note":"DO_NOT_SEND_GOLD_INFO"}')
    return root


@unittest.skipIf(np is None, "Optional NumPy is needed to construct local .npy fixtures")
class TimeSigmaDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = fixture(self.root / "data")
        self.gym = GymTS(self.root / "records")
        self.addCleanup(self.gym.close)
        for ref, schema in timesigma_schemas().items():
            self.gym.schemas.register(ref, schema)

    def load(self, imported, name):
        return self.gym.artifacts.read_json(imported[name])

    def test_three_schemas_keep_native_independent_curves_and_gold_separate(self):
        for schema in ("naive", "all_in_one", "zero_shot"):
            with self.subTest(schema=schema):
                imported = import_dataset(self.gym, self.data, schema=schema, **({"curve_id": "b"} if schema == "naive" else {}))
                train, test, private = (self.load(imported, key) for key in ("training_ref", "snapshot_ref", "private_ref"))
                self.assertEqual([row["curve_id"] for row in train["curves"]], imported["preprocessing_members"])
                self.assertEqual([row["curve_id"] for row in test["curves"]], imported["evaluation_members"])
                self.assertEqual([row["curve_id"] for row in private["outcome"]["curves"]], imported["evaluation_members"])
                for phase, body in (("train", train), ("test", test)):
                    for row in body["curves"]:
                        original = np.load(self.data / "UTS/TODS" / row["curve_id"] / (phase + ".npy"))
                        self.assertEqual(row["values"], original.tolist())
                        self.assertEqual(row["dtype"], "float32")
                serialized = json.dumps(train) + json.dumps(test)
                for key in ('"labels"', '"private_ref"', "DO_NOT_SEND_GOLD_INFO", str(self.data)):
                    self.assertNotIn(key, serialized)
                self.assertFalse(any(value >= 10000 for row in train["curves"] for value in row["values"]))
                self.assertTrue(all(value >= 10000 for row in test["curves"] for value in row["values"]))
                if schema == "zero_shot":
                    self.assertFalse(set(imported["training_members"]) & set(imported["evaluation_members"]))
                    self.assertEqual(set(imported["preprocessing_members"]), {"a", "b", "c"})
                    self.assertEqual(len(train["curves"]), 3)
                manifest = self.load(imported, "manifest_ref")
                self.assertTrue(manifest["native_validation"]["arrays_are_unsplit"])
                self.assertEqual(manifest["native_validation"]["valid_proportion"], .2)

    def test_stable_source_revision_changes_with_bytes_and_not_with_selected_schema(self):
        naive = import_dataset(self.gym, self.data, curve_id="a")
        combined = import_dataset(self.gym, self.data, schema="all_in_one")
        self.assertEqual(naive["dataset_revision"], combined["dataset_revision"])
        self.assertNotEqual(naive["planning_unit_id"], combined["planning_unit_id"])
        again = import_dataset(self.gym, self.data, curve_id="a")
        self.assertEqual(naive, again)
        np.save(self.data / "UTS/TODS/a/train.npy", np.arange(12, dtype="float32") + 1)
        changed = import_dataset(self.gym, self.data, curve_id="a")
        self.assertNotEqual(naive["dataset_revision"], changed["dataset_revision"])
        self.assertNotEqual(naive["planning_unit_id"], changed["planning_unit_id"])
        self.assertEqual(self.load(naive, "training_ref")["curves"][0]["values"][0], 0)

    def test_native_zero_shot_shuffle_matches_upstream_tods_and_keeps_global_rng(self):
        members = ["0", "01", "012", "0123", "01234", "1", "12", "123", "1234", "2", "23", "234", "3", "34", "4"]
        np.random.seed(37)
        before = np.random.get_state()
        split = native_zero_shot_split("TODS", members)
        after = np.random.get_state()
        self.assertEqual(split["training_curves"], ["0123", "123", "12", "012", "23", "01234", "01", "34"])
        self.assertEqual(split["held_out_curves"], ["0", "4", "2", "1234", "3", "234", "1"])
        self.assertEqual(before[0], after[0])
        self.assertTrue(np.array_equal(before[1], after[1]))
        self.assertEqual(before[2:], after[2:])

    def test_canonical_membership_order_is_authoritative_and_invalid_partitions_fail(self):
        row = {"dataset": "TODS", "enumerated_curves": ["c", "b", "a"], "training_curves": ["b", "c"],
               "held_out_curves": ["a"], "random_seed": 1, "proportion": .5}
        path = self.root / "membership.json"
        def write(value):
            path.write_text(json.dumps({"schema": "zero_shot", "dataset_type": "UTS", "datasets": [value]}))
        write(row)
        imported = import_dataset(self.gym, self.data, schema="zero_shot", zero_shot_membership=path)
        self.assertEqual(imported["training_members"], ["b", "c"])
        self.assertEqual(imported["preprocessing_members"], ["c", "b", "a"])
        for update in ({"held_out_curves": ["b"]}, {"random_seed": 2}, {"proportion": .8},
                       {"enumerated_curves": ["a", "b"]}, {"training_curves": ["b", "b"]}):
            with self.subTest(update=update):
                write({**row, **update})
                with self.assertRaises(GymTSError):
                    import_dataset(self.gym, self.data, schema="zero_shot", zero_shot_membership=path)

    def test_prepare_capability_has_only_raw_training_and_cannot_reach_gold_or_test(self):
        imported = import_dataset(self.gym, self.data, schema="zero_shot")
        view = training_view(imported)
        resources = RestrictedServices(self.gym.artifacts, views=[view], purpose="prepare", schemas=self.gym.schemas)
        observed = resources.read_view(view)
        self.assertEqual(observed["schema_ref"], TRAINING)
        self.assertEqual(observed["value"], self.load(imported, "training_ref"))
        for name in ("snapshot_ref", "private_ref", "manifest_ref"):
            with self.subTest(name=name), self.assertRaises(GymTSError) as error:
                resources.read_json(imported[name])
            self.assertEqual(error.exception.code, "permission_denied")
        widened = copy.deepcopy(view)
        widened["source_refs"].append(imported["private_ref"])
        with self.assertRaises(GymTSError):
            resources.read_view(widened)
        runtime = RestrictedServices(self.gym.artifacts, views=[view], purpose="runtime")
        with self.assertRaises(GymTSError):
            runtime.read_view(view)

    def test_nonfinite_wrong_shape_object_arrays_and_invalid_gold_fail_before_publish(self):
        target = self.data / "UTS/TODS/a/test.npy"
        for values in (np.array([1, np.nan]), np.ones((3, 1)), np.array(["text"]), np.array([1], dtype=object), np.array([True])):
            with self.subTest(dtype=str(values.dtype), shape=values.shape):
                np.save(target, values)
                with patch.object(self.gym.artifacts, "save_json", wraps=self.gym.artifacts.save_json) as save:
                    with self.assertRaises(GymTSError):
                        import_dataset(self.gym, self.data, curve_id="a")
                    save.assert_not_called()
        np.save(target, np.arange(9, dtype="float32"))
        for labels in (np.array([0, 2] + [0] * 7), np.array([0, 1])):
            np.save(self.data / "UTS/TODS/a/test_label.npy", labels)
            with self.assertRaises(GymTSError):
                import_dataset(self.gym, self.data, curve_id="a")

    def test_symlink_traversal_unknown_member_and_source_mutation_are_rejected(self):
        for kwargs in ({"dataset": "../TODS"}, {"curve_id": "missing"}, {"schema": "zero_shot", "seed": 2},
                       {"schema": "all_in_one", "curve_id": "a"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(GymTSError):
                import_dataset(self.gym, self.data, **kwargs)
        target = self.data / "UTS/TODS/a/train.npy"
        original = target.read_bytes()
        target.unlink()
        outside = self.root / "outside.npy"
        outside.write_bytes(original)
        target.symlink_to(outside)
        with self.assertRaises(GymTSError):
            import_dataset(self.gym, self.data)
        target.unlink()
        target.write_bytes(original)
        from gymts_timesigma import data as module
        read = module._read
        def mutate(path, numpy, **kwargs):
            result = read(path, numpy, **kwargs)
            if kwargs.get("labels"):
                target.write_bytes(original + b"source changed")
            return result
        with patch.object(module, "_read", side_effect=mutate):
            with self.assertRaisesRegex(GymTSError, "changed"):
                import_dataset(self.gym, self.data)

    def test_missing_numpy_has_a_clear_optional_dependency_error(self):
        with patch.dict("sys.modules", {"numpy": None}):
            with self.assertRaises(GymTSError) as error:
                import_dataset(self.gym, self.data)
        self.assertEqual(error.exception.code, "unsupported_capability")


def unit(schema="zero_shot"):
    fitted, evaluated, preprocessed = (["train-b"], ["test-a", "test-c"], ["test-a", "train-b", "test-c"])
    if schema == "naive":
        fitted = evaluated = preprocessed = ["test-a"]
    if schema == "all_in_one":
        fitted = evaluated = preprocessed = ["test-a", "test-c"]
    return {"dataset_revision": "sha256:fixture", "planning_unit_id": "unit-fixture", "dataset": "TODS", "schema": schema,
        "training_members": fitted, "evaluation_members": evaluated, "preprocessing_members": preprocessed,
        "curves": [{"curve_id": curve, "values": [1., 3., 2., 4., 8.], "dtype": "float32"} for curve in evaluated]}


class MemoryServices:
    def __init__(self, value):
        self.value = value
    def read_json(self, reference):
        return copy.deepcopy(self.value)
    def observation_ref(self, batch_id):
        return "committed-observation-" + batch_id


class TimeSigmaEnvironmentTaskTests(unittest.TestCase):
    def environment(self, value=None):
        value = copy.deepcopy(unit() if value is None else value)
        reference = {"schema_ref": SNAPSHOT}
        spec = {"source": {"revision": value["dataset_revision"], "connection": {"artifact_refs": [reference]}},
                "mapping": {}, "options": {}}
        return TimeSigmaSnapshotEnvironment(spec, MemoryServices(value)), spec

    def started(self, value=None):
        environment, _ = self.environment(value)
        session = environment.start({"mode": "reinitialize", "run_id": "run-fixture", "scope": {"start": 0, "end": 1},
            "read_scope": {"start": 0, "end": 1}, "permitted_variables": ["planning_unit"], "permitted_operations": [], "seed": 1})
        task_spec = {"params": {"planning_unit_id": "unit-fixture"}}
        task = TimeSigmaTask(task_spec)
        bound = task.bind(task_spec, {"variables": {"planning_unit": {"source": "planning_unit"}}, "operations": {}},
            environment.describe(), {"run_id": "run-fixture", "session": session,
                "effective_scope": {"start": 0, "end": 1}, "data": MemoryServices(None)})
        return environment, session, bound

    def test_three_schemas_emit_last_unit_before_done_then_one_lossless_result(self):
        for schema in ("naive", "all_in_one", "zero_shot"):
            with self.subTest(schema=schema):
                environment, session, bound = self.started(unit(schema))
                request = bound.next_observation()
                batch = environment.observe(request)
                self.assertEqual(batch["status"], "end")
                self.assertEqual(batch["snapshot_time"], 0)
                self.assertEqual(batch["clock"], {"domain": "step", "now": 0, "visible_until": 0})
                self.assertEqual(batch["data"]["native"]["storage"], "inline")
                self.assertEqual(session["public_context"]["storage"], "inline")
                self.assertNotIn("values", json.dumps(session["public_context"]))
                update = bound.consume(batch)
                self.assertTrue(update["done"])
                self.assertEqual(len(update["inputs"]), 1)
                task_input = update["inputs"][0]
                self.assertEqual(task_input["payload"]["value"], unit(schema))
                output = {"dataset_revision": "sha256:fixture", "planning_unit_id": "unit-fixture", "curves": [
                    {"curve_id": curve, "scores": [.1, .8, .2], "offset": 2, "raw_length": 5}
                    for curve in unit(schema)["evaluation_members"]], "evidence": {"source": "explicit local fixture"}}
                effect = bound.interpret(task_input, {"payload": payload(OUTPUT, output)}, "output-fixture")
                self.assertTrue(effect["complete"])
                self.assertEqual(len(effect["results"]), 1)
                self.assertEqual(effect["results"][0]["payload"]["value"], output)
                self.assertEqual(effect["results"][0]["alignment_key"], task_input["alignment_key"])
                repeated = environment.observe(bound.next_observation())
                self.assertIsNone(repeated["data"])
                self.assertIsNone(repeated["snapshot_time"])
                self.assertEqual(repeated["cursor"], batch["cursor"])
                self.assertEqual(bound.consume(repeated)["inputs"], [])
                self.assertEqual(bound.finish("end")["cases_completed"], 1)
                self.assertEqual(bound.finish("end")["cases_incomplete"], 0)
                self.assertEqual(environment.finish()["counts"]["points"], 1)

    def test_wrong_cursor_request_permissions_and_mixed_clock_scope_fail(self):
        environment, _, bound = self.started()
        request = bound.next_observation()
        for update in ({"cursor": "old"}, {"kind": "range"}, {"variables": ["labels"]}):
            with self.subTest(update=update), self.assertRaises(GymTSError):
                environment.observe({**request, **update})
        with self.assertRaises(GymTSError):
            environment.act({})
        with self.assertRaises(GymTSError):
            environment.start({})
        for scope in ({"start": 1, "end": 2}, {"start": "2026-01-01T00:00:00Z", "end": None}):
            fresh, _ = self.environment()
            with self.subTest(scope=scope), self.assertRaises(GymTSError):
                fresh.start({"mode": "reinitialize", "run_id": "run", "scope": scope, "read_scope": scope,
                    "permitted_variables": ["planning_unit"], "permitted_operations": [], "seed": 1})

    def test_private_fields_member_changes_and_conflicting_repeats_are_rejected(self):
        for change in ({"labels": [1]}, {"private_ref": {}}, {"evaluation_members": ["test-a"]}):
            with self.subTest(change=change), self.assertRaises(GymTSError):
                self.environment({**unit(), **change})
        environment, _, bound = self.started()
        batch = environment.observe(bound.next_observation())
        bound.consume(batch)
        self.assertEqual(bound.consume(batch)["inputs"], [])
        changed = copy.deepcopy(batch)
        changed["data"]["native"]["value"]["curves"][0]["values"][0] = 99
        with self.assertRaisesRegex(GymTSError, "change"):
            bound.consume(changed)

    def test_scores_require_finite_unique_complete_members_and_exact_offsets(self):
        mutations = [lambda value: value["curves"].pop(),
                     lambda value: value["curves"].append(copy.deepcopy(value["curves"][0])),
                     lambda value: value["curves"][0].update(curve_id="train-b"),
                     lambda value: value["curves"][0].update(offset=1),
                     lambda value: value["curves"][0].update(raw_length=6),
                     lambda value: value["curves"][0]["scores"].__setitem__(0, float("nan")),
                     lambda value: value["curves"][0]["scores"].__setitem__(0, True),
                     lambda value: value.update(dataset_revision="changed")]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                environment, _, bound = self.started()
                task_input = bound.consume(environment.observe(bound.next_observation()))["inputs"][0]
                output = {"dataset_revision": "sha256:fixture", "planning_unit_id": "unit-fixture", "curves": [
                    {"curve_id": curve, "scores": [.1, .8, .2], "offset": 2, "raw_length": 5}
                    for curve in unit()["evaluation_members"]], "evidence": {}}
                mutate(output)
                with self.assertRaises(GymTSError):
                    bound.interpret(task_input, {"payload": payload(OUTPUT, output)}, "output")


if __name__ == "__main__":
    unittest.main()
