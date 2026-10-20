"""Source/task replacement contracts on explicit numerical fixtures, no models."""
import copy
from contextlib import ExitStack
import csv
import importlib.abc
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import GymTSError, utc_now
from gymts.plugin_support import component, payload
from gymts_timeseries.contracts import INPUT, OUTPUT, PROTOCOL, SNAPSHOT, validate_sample
from gymts_timeseries.experiments import scene
from gymts_timeseries.sources import import_csv, publish_snapshot
from gymts_timeseries.task import TASK_OUTPUT_SCHEMAS, make_task_input, parse_answer


class FixtureCandidate:
    """Explicit test algorithm; no test output is attributed to a model."""
    def __init__(self, spec):
        pass

    def prepare(self, context, training):
        return {"model_revision": None, "state_refs": [], "training_provenance_ref": None}

    def infer(self, task_input):
        value = task_input["payload"]["value"]
        xs = value["series"][0]["values"]
        answer = ({"forecast": [xs[-1] + (index + 1) * (xs[-1] - xs[-2]) for index in range(value["context"]["horizon"])]}
                  if value["task_id"] == "forecast.numeric" else {"trend_direction": "increasing"})
        return {"input_id": task_input["input_id"], "task_protocol_ref": PROTOCOL,
            "model_revision": None, "produced_at": utc_now(), "payload": payload(OUTPUT, {"raw_text": json.dumps(answer), "evidence": {"test_fixture": True}})}

    def finish(self):
        return []


def register_fixture(gym):
    ref = component("explicit-fixture-candidate")
    gym.schemas.register("fixture.empty/1", {"type": "object", "properties": {}, "additionalProperties": False})
    gym.registries.candidates.register({"component_ref": ref, "protocol_versions": ["gymts.candidate/1", PROTOCOL],
        "params_schema_ref": "fixture.empty/1", "origin_ref": None, "implementation_ref": ref, "component_refs": [],
        "supported_task_protocols": [PROTOCOL], "input_schema_refs": [INPUT], "output_schema_refs": [OUTPUT],
        "supports_fit": False, "fit_requires_targets": False, "supports_update": False,
        "model_revision_mode": "none", "capture_profiles": []}, FixtureCandidate)


def experiment(source_scene):
    return {"protocol_version": "gymts.experiment/1", "name": "explicit-independent-roles-fixture", "purpose": "development",
        "scene": source_scene, "candidate": {"adapter": "explicit-fixture-candidate", "version": "1.0.0", "artifact": None,
            "inherited_state": [], "params": {}},
        "execution": {"mode": "stream", "start": {"mode": "reinitialize"}, "scope": {"start": 0, "end": 1}, "feedback_until": None,
            "seed": 7, "learning": {"prepare": "load_only", "online": "frozen", "training_view": None, "training_targets": None,
                "alignment_schema_ref": None, "allowed_feedback_sources": []},
            "limits": {"max_inputs": None, "max_operations": None, "max_turns_per_case": 1, "max_wall_time_s": 30}},
        "recording": {"store_ref": "local://records/default", "inputs": "full", "outputs": "full", "artifacts": "reference",
            "model_calls": "none", "on_capture_failure": "fail_run", "redaction_policy_ref": None, "extra_event_kinds": []},
        "extensions": {}}


class IndependentRolesTests(unittest.TestCase):
    def sample(self):
        return {"sample_token": "a" * 64, "series": [{"name": "Series 1", "values": [1., 2., 3., 4.]}],
                "context": {"horizon": 2}, "annotations": {}}

    def test_same_source_facts_select_two_tasks_without_source_identity(self):
        source = self.sample()
        before = copy.deepcopy(source)
        forecast = make_task_input(source, "forecast.numeric", "0.2.0")
        trend = make_task_input(source, "pattern.trend_direction", "0.2.0")
        self.assertEqual(before, source)
        self.assertEqual(forecast["series"], trend["series"])
        self.assertNotEqual(forecast["question"], trend["question"])
        self.assertEqual(2, forecast["response_schema"]["properties"]["forecast"]["maxItems"])
        self.assertFalse(set(forecast) & {"messages", "model_input", "timeseries", "tokenizer"})
        self.assertNotIn("<ts>", json.dumps(forecast))

    def test_benchmark_task_constraint_requires_explicit_new_view(self):
        source = self.sample()
        source["annotations"] = {"benchmark_task_id": "forecast.numeric", "benchmark_task_version": "0.2.0"}
        with self.assertRaises(GymTSError) as caught:
            make_task_input(source, "pattern.trend_direction", "0.2.0")
        self.assertEqual("unsupported_capability", caught.exception.code)

    def test_json_csv_sources_support_both_tasks_with_identical_public_inputs(self):
        with tempfile.TemporaryDirectory() as directory, GymTS(Path(directory) / "records", integrations=("timeseries",)) as gym:
            register_fixture(gym)
            sample = self.sample()
            source = publish_snapshot(gym, [sample])
            path = Path(directory) / "source.csv"
            with path.open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["sample_token", "series_name", "index", "value"])
                for index, value in enumerate(sample["series"][0]["values"]):
                    writer.writerow([sample["sample_token"], "Series 1", index, value])
            table = import_csv(gym, path, context=sample["context"])
            observed = {}
            for adapter, artifact, revision, options in (("numeric-snapshot", source["snapshot_ref"], source["dataset_revision"], {}),
                    ("csv-numeric-snapshot", table["source_ref"], table["dataset_revision"], {"context": table["context"]})):
                for task_id in ("forecast.numeric", "pattern.trend_direction"):
                    spec = experiment(scene(artifact, revision, sample["sample_token"], task_id, "0.2.0",
                                            source_adapter=adapter, source_options=options))
                    result = gym.run(spec)
                    self.assertEqual("succeeded", result["status"], result["errors"])
                    rows = gym.artifacts.read_json(result["result_ref"])
                    self.assertEqual("valid", rows[0]["status"])
                    events = gym.records.get_run(result["run_id"])["events"]
                    item = next(event for event in events if event["kind"] == "input")["payload"]
                    saved = item["value"] if item["storage"] == "inline" else gym.artifacts.read_json(item["artifact_ref"])
                    observed[adapter, task_id] = saved["payload"]["value"]
            for task_id in ("forecast.numeric", "pattern.trend_direction"):
                self.assertEqual(observed["numeric-snapshot", task_id], observed["csv-numeric-snapshot", task_id])

    def test_offline_planning_never_loads_source_bytes_or_constructs_roles(self):
        from gymts_timeseries.environment import NumericSnapshotEnvironment
        from gymts_timeseries.task import TimeSeriesQATask
        with tempfile.TemporaryDirectory() as directory, GymTS(directory, integrations=("timeseries",)) as gym:
            register_fixture(gym)
            sample = self.sample()
            source = publish_snapshot(gym, [sample])
            spec = experiment(scene(source["snapshot_ref"], source["dataset_revision"], sample["sample_token"], "forecast.numeric", "0.2.0"))
            with ExitStack() as stack:
                for cls in (NumericSnapshotEnvironment, TimeSeriesQATask, FixtureCandidate):
                    stack.enter_context(patch.object(cls, "__init__", side_effect=AssertionError("Planning constructed a role")))
                for name in ("resolve", "read_json", "read_view", "save_json"):
                    stack.enter_context(patch.object(gym.artifacts, name, side_effect=AssertionError("Planning accessed source bytes")))
                self.assertTrue(gym.validate(spec)["valid"])
                self.assertEqual("deferred_to_open", gym.plan(spec)["resource_checks"])
                spec["scene"]["task"]["params"]["task_version"] = "unsupported-version"
                self.assertFalse(gym.validate(spec)["valid"])

    def test_private_fields_and_nonfinite_source_facts_are_rejected(self):
        source = self.sample()
        source["context"]["expected_output"] = {"forecast": [5, 6]}
        with self.assertRaises(GymTSError):
            validate_sample(source)
        source = self.sample()
        source["series"][0]["values"][0] = float("nan")
        with self.assertRaises((GymTSError, ValueError)):
            validate_sample(source)

    def test_strict_parser_is_domain_owned_and_shape_preserving(self):
        value = make_task_input(self.sample(), "forecast.numeric", "0.2.0")
        parsed, reason = parse_answer('{"forecast":[5,6]}', value["response_schema"], value["task_id"], value)
        self.assertEqual({"forecast": [5, 6]}, parsed)
        self.assertIsNone(reason)
        for answer in ('{"forecast":[5]}', '{"forecast":[5,6],"forecast":[7,8]}', '```json\n{"forecast":[5,6]}\n```'):
            self.assertIsNotNone(parse_answer(answer, value["response_schema"], value["task_id"], value)[1])

    def test_shared_package_imports_with_all_project_implementations_blocked(self):
        script = '''
import importlib.abc, sys
class BlockProjects(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('gymts_chatts','gymts_libraryts','gymts_rl','gymts_timesigma'):
            raise ModuleNotFoundError(fullname)
sys.meta_path.insert(0, BlockProjects())
from gymts import GymTS
from gymts_timeseries.task import make_task_input
g=GymTS(sys.argv[1],integrations=('timeseries',))
assert not any(name.startswith(('gymts_chatts','gymts_libraryts','gymts_rl','gymts_timesigma')) for name in sys.modules)
g.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-I", "-B", "-c", script, directory],
                                    cwd=directory, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
