"""Meaningful contract/evidence tests; fixtures are not native Agent acceptance."""
import copy
from contextlib import ExitStack
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import GymTSError
from gymts_timeseries.sources import publish_snapshot
from gymts_timecopilot.candidate import TimeCopilotCandidate
from gymts_timecopilot.experiments import evaluation_spec, evaluate, rescore, score_execution
from gymts_timecopilot.runtime import TimeCopilotRuntime, worker_environment


def fixture_params():
    return {"implementation": {"repository": "/not-opened", "python": "/not-executed"},
        "model": {"base_url": "http://127.0.0.1:1/v1", "name": "explicit-fixture", "revision": "fixture-v1"},
        "limits": {"max_requests": 4, "max_total_tokens": 100, "max_response_tokens": 10,
                   "max_tool_calls": 4, "max_wall_time_s": 5}}


def fixture_source(gym):
    source = publish_snapshot(gym, [{"sample_token": "a" * 64, "series": [{"name": "explicit-fixture", "values": [1., 2., 3.]}],
        "context": {"start": "2000-01-01", "freq": "MS", "seasonality": 1, "horizon": 2}, "annotations": {}}])
    source["private_ref"] = gym.artifacts.save_json({"forecast": [4., 5.], "fixture": True}, "gymts.json/1")
    return source


class ContractTests(unittest.TestCase):
    def test_unallocated_native_unit_remains_in_score_plan(self):
        with tempfile.TemporaryDirectory() as directory, GymTS(directory,integrations=('timeseries','timecopilot')) as gym:
            source=fixture_source(gym)
            with patch.object(gym.environment_ts,'run',side_effect=GymTSError('execution_failure','Explicit allocation failure fixture')):
                result=evaluate(gym,source,fixture_params())
            self.assertEqual(len(result['failures']),1)
            self.assertEqual(len(result['score_spec']['runs']),1)
            self.assertIsNone(result['score_spec']['runs'][0]['run_id'])
            self.assertEqual(result['report']['coverage']['expected_units'],1)
            self.assertEqual(result['report']['coverage']['not_started_units'],1)

    def test_tool_schema_exposes_choices_without_mutating_native_schema(self):
        from gymts_timecopilot.worker import declared_tool_schema
        original={'type':'object','properties':{'features':{'type':'array','items':{'type':'string'}}},'required':['features']}
        before=copy.deepcopy(original)
        declared=declared_tool_schema(original,'tsfeatures_tool',['stl_features','acf_features'],['AutoETS'])
        self.assertEqual(original,before)
        self.assertEqual(declared['properties']['features']['items']['enum'],['acf_features','stl_features'])
        self.assertEqual(declared['required'],original['required'])
        anomaly={'type':'object','properties':{'model':{'type':'string'},'level':{'type':'integer','default':95}}}
        published=declared_tool_schema(anomaly,'detect_anomalies_tool',[],['AutoETS','SeasonalNaive'])
        self.assertEqual(published['properties']['level'],anomaly['properties']['level'])
        self.assertEqual(published['properties']['model']['enum'],['AutoETS','SeasonalNaive'])

    def test_discovery_and_registration_do_not_import_native_stack(self):
        program = '''
import importlib.abc,sys
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'timecopilot','pydantic_ai','openai','torch','numpy','pandas','statsforecast','httpx'}:
   raise AssertionError('Unexpected native import: '+fullname)
sys.meta_path.insert(0,Block())
from gymts import GymTS
with GymTS(sys.argv[1],integrations=('timecopilot',)) as gym:
 m=gym.registries.candidates.resolve('timecopilot-agent','1.0.0')
 assert m['capture_profiles']==['io'] and not m['supports_fit']
 assert len(m['component_refs'])==4
'''
        with tempfile.TemporaryDirectory() as directory:
            run = subprocess.run([sys.executable, "-I", "-B", "-c", program, directory],
                                 cwd=directory, capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_pure_plan_rejects_wrong_task_training_and_mutable_revision(self):
        with tempfile.TemporaryDirectory() as directory, GymTS(directory, integrations=("timeseries", "timecopilot")) as gym:
            spec = evaluation_spec(fixture_source(gym), fixture_params())
            experiment = {"protocol_version": "gymts.experiment/1", "name": "Explicit pure planning fixture", "purpose": "development",
                "scene": spec["cases"][0]["scene"], "execution": spec["cases"][0]["execution"],
                "recording": spec["cases"][0]["recording"], "candidate": spec["candidates"][0]["spec"], "extensions": {}}
            with ExitStack() as stack:
                stack.enter_context(patch.object(TimeCopilotCandidate, "__init__", side_effect=AssertionError("Candidate constructed while planning")))
                stack.enter_context(patch("gymts_timecopilot.candidate.checkout_identity", side_effect=AssertionError("Checkout read while planning")))
                for name in ("resolve", "read_json", "read_view", "save_json"):
                    stack.enter_context(patch.object(gym.artifacts, name, side_effect=AssertionError("CAS accessed while planning")))
                self.assertTrue(gym.validate(experiment)["valid"])
            ctx = {"experiment": {"scene": spec["cases"][0]["scene"], "execution": spec["cases"][0]["execution"],
                                   "candidate": spec["candidates"][0]["spec"]}}
            for path, value in (("task", "anomaly.point_indices"), ("revision", "main"), ("training", "fit")):
                bad = copy.deepcopy(ctx)
                if path == "task": bad["experiment"]["scene"]["task"]["params"]["task_id"] = value
                elif path == "revision": bad["experiment"]["candidate"]["params"]["model"]["revision"] = value
                else: bad["experiment"]["execution"]["learning"]["prepare"] = value
                with self.assertRaises(GymTSError): TimeCopilotCandidate.check_compatibility_spec(bad)

    def test_environment_passes_only_named_credential_and_hides_cuda(self):
        with patch.dict("os.environ", {"UNRELATED_API_KEY": "discard-fixture", "HF_TOKEN": "discard-fixture", "MY_ENDPOINT_TOKEN": "pass-fixture", "PYTHONPATH": "/bad"}):
            env = worker_environment("MY_ENDPOINT_TOKEN")
        self.assertFalse("UNRELATED_API_KEY" in env, "Unrelated API key must not pass to worker")
        self.assertFalse("HF_TOKEN" in env, "Unrelated token must not pass to worker")
        self.assertFalse("PYTHONPATH" in env, "Repository source injection must not pass to worker")
        self.assertEqual(env["MY_ENDPOINT_TOKEN"], "pass-fixture")
        self.assertEqual(env["CUDA_VISIBLE_DEVICES"], "")

    def test_packaged_worker_acknowledges_failed_terminal_without_scientific_imports(self):
        events = []
        runtime = TimeCopilotRuntime({"repository": "/not-opened", "python": sys.executable}, timeout_seconds=10)
        with self.assertRaises(GymTSError):
            runtime.invoke({"mode": "explicit-invalid-fixture"}, events.append)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "terminal")
        self.assertEqual(events[0]["status"], "failed")
        self.assertEqual(events[0]["error"]["type"], "ValueError")

    def test_evidence_binding_independent_score_and_forbidden_backend_rescore(self):
        def invoke(runtime, request, on_event=None):
            if request["mode"] == "identity": return {"fixture": "explicit worker identity"}
            events = [
                {"kind": "model_start", "call_id": "fixture-model", "attempt_id": "fixture-attempt", "request": {"messages": ["fixture prompt"]}},
                {"kind": "model_end", "call_id": "fixture-model", "status": "succeeded", "response": {"tool_calls": ["forecast_tool"]}, "usage": {"total_tokens": 4}},
                {"kind": "tool_start", "call_id": "fixture-tool", "attempt_id": "fixture-tool-attempt", "tool": "forecast_tool", "parent_call_id": "fixture-model", "request": {"model": "fixture"}},
                {"kind": "tool_end", "call_id": "fixture-tool", "status": "succeeded", "response": {"return_value": [4., 5.]}}]
            for index, event in enumerate(events):
                on_event({"sequence": index + 1, "at": "2026-10-21T00:00:00Z", **event})
            return {"forecast": [4., 5.], "analysis": {"selected_model": "explicit-fixture"}}
        with tempfile.TemporaryDirectory() as directory, GymTS(directory, integrations=("timeseries", "timecopilot")) as gym:
            source = fixture_source(gym)
            with patch("gymts_timecopilot.candidate.checkout_identity", return_value={"fixture": True}), \
                 patch("gymts_timecopilot.runtime.TimeCopilotRuntime.invoke", invoke):
                result = evaluate(gym, source, fixture_params())
                repeated = evaluate(gym, source, fixture_params())
            self.assertFalse(repeated['failures'])
            self.assertNotEqual(repeated['run_ids'], result['run_ids'])
            with patch.object(TimeCopilotCandidate, '__init__', side_effect=AssertionError('Existing execution must not construct Candidate')):
                recovered = score_execution(gym, source, fixture_params(), repeated['initial_report'])
            self.assertEqual(recovered['run_ids'],repeated['run_ids'])
            self.assertFalse(result["failures"], result["failures"])
            self.assertEqual(len(result["run_ids"]), 1)
            scored = rescore(gym, result)
            self.assertTrue(scored["native_backend_forbidden"])
            run = gym.records.get_run(result["run_ids"][0])
            self.assertEqual(run["result"]["status"], "succeeded")
            # Formal event validation and independent future matching were exercised by a real sealed fixture Run.
            self.assertEqual(scored["sealed_result_hashes"], result["sealed_result_hashes"])

    def test_interrupted_worker_preserves_unknown_model_attempt_and_failed_session(self):
        def invoke(runtime, request, on_event=None):
            if request["mode"] == "identity": return {"fixture": "explicit worker identity"}
            on_event({"sequence": 1, "kind": "model_start", "at": "2026-10-21T00:00:00Z",
                      "call_id": "fixture-interrupted-model", "attempt_id": "fixture-attempt",
                      "request": {"fixture": "sent before interruption"}})
            raise GymTSError("deadline_exceeded", "Explicit simulated worker interruption")
        with tempfile.TemporaryDirectory() as directory, GymTS(directory, integrations=("timeseries", "timecopilot")) as gym:
            source = fixture_source(gym)
            with patch("gymts_timecopilot.candidate.checkout_identity", return_value={"fixture": True}), \
                 patch("gymts_timecopilot.runtime.TimeCopilotRuntime.invoke", invoke):
                result = evaluate(gym, source, fixture_params())
            self.assertEqual(len(result["failures"]), 1)
            self.assertEqual(len(result["run_ids"]), 1)
            run = gym.records.get_run(result["run_ids"][0])
            self.assertEqual(run["result"]["status"], "failed")
            self.assertIn("deadline_exceeded", json.dumps(run["result"]["errors"]))
            calls = [gym.artifacts.read_json(event["payload"]["artifact_ref"])
                     for event in run["events"] if event["kind"] == "model_call"]
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["status"], "unknown")
            self.assertIsNone(calls[0]["response_ref"])
            self.assertEqual(gym.artifacts.read_json(calls[0]["request_ref"])["fixture"], "sent before interruption")
            previous=Path(directory)/'failed.json';output=Path(directory)/'failed-rescore.json'
            previous.write_text(json.dumps(result))
            from gymts_timecopilot.cli import main
            self.assertEqual(main(['--store',directory,'--output',str(output),'rescore','--previous',str(previous)]),1)
            self.assertEqual(json.loads(output.read_text())['run_ids'],result['run_ids'])


if __name__ == "__main__":
    unittest.main()
