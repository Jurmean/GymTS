"""Adapter contracts and explicit opt-in genuine small CPU computations."""
import copy
from contextlib import ExitStack
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import GymTSError
from gymts_libraryts.source import PINNED_REVISION, REPOSITORY_URL, resolve_source
from gymts_libraryts.tools import LibraryTSTools


class LibraryTSContractTests(unittest.TestCase):
    def test_registration_needs_no_scientific_imports(self):
        program = '''
import importlib.abc, sys
class BlockScience(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'numpy','pandas','sktime','sklearn','scipy','numba','skbase'}:
            raise ModuleNotFoundError('Science deliberately unavailable')
sys.meta_path.insert(0, BlockScience())
from gymts import GymTS
with GymTS(sys.argv[1], integrations=('libraryts',)) as gym:
    manifest=gym.registries.candidates.resolve('libraryts-qa','1.0.0')
    assert manifest['implementation_ref']['name']=='sktime'
    assert manifest['implementation_ref']['version']=='080f4c3c3695f239e328548bac7d7a3ef7aa9127'
    assert len(manifest['component_refs'])==2
    assert not manifest['supports_fit'] and not manifest['supports_update']
assert not any(name.split('.')[0] in {'numpy','pandas','sktime','sklearn'} for name in sys.modules)
'''
        with tempfile.TemporaryDirectory() as directory:
            result=subprocess.run([sys.executable,'-I','-B','-c',program,directory],capture_output=True,text=True,cwd=directory,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_known_task_and_state_constraints_plan_without_native_source_or_model_io(self):
        from gymts_timeseries.experiments import scene
        from gymts_timeseries.sources import publish_snapshot
        from gymts_libraryts.candidate import LibraryTSQACandidate
        with tempfile.TemporaryDirectory() as directory, GymTS(directory, integrations=("timeseries", "libraryts")) as gym:
            sample = {"sample_token": "a" * 64, "series": [{"name": "series", "values": [1., 2., 3.]}],
                      "context": {"horizon": 2}, "annotations": {}}
            source = publish_snapshot(gym, [sample])
            spec = {"protocol_version": "gymts.experiment/1", "name": "explicit pure planning fixture", "purpose": "development",
                "scene": scene(source["snapshot_ref"], source["dataset_revision"], sample["sample_token"], "forecast.numeric", "0.2.0"),
                "candidate": {"adapter": "libraryts-qa", "version": "1.0.0", "artifact": None, "inherited_state": [],
                    "params": {"implementation": {"repository": "/not-opened"}, "estimator": "naive"}},
                "execution": {"mode": "stream", "start": {"mode": "reinitialize"}, "scope": {"start": 0, "end": 1},
                    "feedback_until": None, "seed": 7, "learning": {"prepare": "load_only", "online": "frozen", "training_view": None,
                        "training_targets": None, "alignment_schema_ref": None, "allowed_feedback_sources": []},
                    "limits": {"max_inputs": 1, "max_operations": None, "max_turns_per_case": 1, "max_wall_time_s": 10}},
                "recording": {"store_ref": "local", "inputs": "full", "outputs": "full", "artifacts": "reference", "model_calls": "none",
                    "on_capture_failure": "fail_run", "redaction_policy_ref": None, "extra_event_kinds": []}, "extensions": {}}
            with ExitStack() as stack:
                stack.enter_context(patch.object(LibraryTSQACandidate, "__init__", side_effect=AssertionError("Planning constructed native model")))
                stack.enter_context(patch("gymts_libraryts.source.git", side_effect=AssertionError("Planning inspected native checkout")))
                for name in ("resolve", "read_json", "read_view", "save_json"):
                    stack.enter_context(patch.object(gym.artifacts, name, side_effect=AssertionError("Planning accessed CAS")))
                self.assertTrue(gym.validate(spec)["valid"])
                unsupported = copy.deepcopy(spec)
                unsupported["scene"]["task"]["params"]["task_id"] = "anomaly.point_indices"
                report = gym.validate(unsupported)
                self.assertFalse(report["valid"])
                self.assertEqual("unsupported_capability", report["issues"][0]["code"])
                wrong_revision = copy.deepcopy(spec)
                wrong_revision["candidate"]["params"]["implementation"]["revision"] = "0" * 40
                self.assertEqual("conflict", gym.validate(wrong_revision)["issues"][0]["code"])
            manifest = gym.registries.candidates.resolve("libraryts-qa", "1.0.0")
            self.assertFalse(manifest["supports_fit"])
            self.assertEqual("fresh_native_fit_on_current_authorized_input", manifest["execution_semantics"]["infer"])

    def test_wrong_revision_is_rejected_before_source_inspection(self):
        with patch('gymts_libraryts.source.git') as git:
            with self.assertRaises(GymTSError) as error:
                resolve_source({'repository':'/not-used','revision':'0'*40},'forecast.naive')
        self.assertEqual(error.exception.code,'conflict')
        git.assert_not_called()

    def test_failure_preserves_request_and_error_without_fake_run(self):
        with tempfile.TemporaryDirectory() as directory,GymTS(directory,integrations=('libraryts',)) as gym:
            tools=LibraryTSTools(gym.artifacts,{'repository':'/not-used'})
            with patch.object(tools.runtime,'invoke',side_effect=GymTSError('unsupported_capability','explicit failure')):
                with self.assertRaises(GymTSError) as error:
                    tools.call('forecast.naive',{'values':[1,2,3]})
            failed=gym.artifacts.read_json(tools.last_call_ref)
            self.assertEqual(failed['status'],'failed')
            self.assertEqual(failed['error']['code'],'unsupported_capability')
            self.assertEqual(gym.artifacts.read_json(failed['request_ref'])['arguments']['values'],[1,2,3])
            self.assertIn('failed_call_ref',error.exception.info['links'])
            self.assertNotIn('run_id',failed)

    def test_independent_tool_success_is_cas_not_a_run(self):
        with tempfile.TemporaryDirectory() as directory,GymTS(directory,integrations=('libraryts',)) as gym:
            tools=LibraryTSTools(gym.artifacts,{'repository':'/not-used'})
            with patch.object(tools.runtime,'invoke',return_value={'predictions':[4],'fixture':'explicit simulation'}):
                call=tools.call('forecast.naive',{'values':[1,2,3]})
            saved=gym.artifacts.read_json(call['call_ref'])
            self.assertEqual(saved['status'],'succeeded')
            self.assertEqual(gym.artifacts.read_json(saved['response_ref'])['predictions'],[4])
            self.assertNotIn('run_id',saved)

    def test_current_input_catalog_hides_standalone_tools_and_declares_effects(self):
        allowed = {'forecast.naive', 'forecast.polynomial', 'detect.threshold',
                   'analyze.seasonality', 'distance.euclidean'}
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym:
            limited = LibraryTSTools(gym.artifacts, {'repository': '/not-opened'}, scope='current_input')
            with patch.object(limited.runtime, 'describe', return_value={'fixture': 'source metadata'}) as describe:
                catalog = limited.catalog()
            self.assertEqual({row['tool'] for row in catalog}, allowed)
            self.assertEqual({call.args[0] for call in describe.call_args_list}, allowed)
            self.assertTrue(all(row['scope'] == 'current_input' and
                                row['effect'] == 'compute_current_input' and
                                'current_input' in row['allowed_scopes'] for row in catalog))
            standalone = LibraryTSTools(gym.artifacts, {'repository': '/not-opened'})
            with patch.object(standalone.runtime, 'describe', return_value={'fixture': 'source metadata'}):
                full_catalog = standalone.catalog()
            self.assertEqual(len(full_catalog), 10)
            self.assertTrue(all(row['effect'] and row['scope'] == 'standalone' for row in full_catalog))

    def test_current_input_rejects_external_data_experiments_and_evaluation_before_dispatch(self):
        forbidden = ('dataset.load', 'labts.catalog', 'labts.run', 'labts.analyze', 'labts.metrics')
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym:
            tools = LibraryTSTools(gym.artifacts, {'repository': '/not-opened'}, scope='current_input')
            with patch.object(tools.runtime, 'invoke', side_effect=AssertionError('Forbidden dispatch')) as invoke:
                for name in forbidden:
                    with self.subTest(tool=name), self.assertRaises(GymTSError) as raised:
                        tools.call(name, {'dataset_id': 'airline'})
                    self.assertEqual(raised.exception.code, 'permission_denied')
                    failed = gym.artifacts.read_json(tools.last_call_ref)
                    self.assertEqual(failed['status'], 'failed')
                    self.assertEqual(failed['error']['stage'], 'libraryts.scope')
                    request = gym.artifacts.read_json(failed['request_ref'])
                    self.assertEqual(request['tool'], name)
                    self.assertEqual(request['scope'], 'current_input')
                    self.assertTrue(request['effect'])
                    self.assertNotIn('run_id', failed)
                invoke.assert_not_called()

    def test_run_bound_tools_default_to_current_input_and_capture_allowed_calls(self):
        class Captured:
            def __init__(self):
                self.calls = []

            def record_tool_call(self, value):
                self.calls.append(value)

        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym:
            traces = Captured()
            with self.assertRaises(GymTSError) as raised:
                LibraryTSTools(gym.artifacts, {'repository': '/not-opened'}, traces=traces, scope='standalone')
            self.assertEqual(raised.exception.code, 'permission_denied')
            tools = LibraryTSTools(gym.artifacts, {'repository': '/not-opened'}, traces=traces)
            self.assertEqual(tools.scope, 'current_input')
            with patch.object(tools.runtime, 'invoke', return_value={'fixture': 'explicit computation result'}):
                for name in ('forecast.naive', 'forecast.polynomial', 'detect.threshold',
                             'analyze.seasonality', 'distance.euclidean'):
                    result = tools.call(name, {'values': [1, 2, 3]}, parent_call_id='model-parent')
                    self.assertEqual(result['output']['fixture'], 'explicit computation result')
            self.assertEqual(len(traces.calls), 5)
            self.assertTrue(all(call['status'] == 'succeeded' and call['parent_call_id'] == 'model-parent'
                                and call['operation_id'] is None and call['environment_request_id'] is None
                                for call in traces.calls))
            with patch.object(tools.runtime, 'invoke') as invoke, self.assertRaises(GymTSError):
                tools.call('dataset.load', {'dataset': 'airline'}, parent_call_id='model-parent')
            invoke.assert_not_called()
            self.assertEqual(traces.calls[-1]['status'], 'failed')
            self.assertEqual(traces.calls[-1]['error']['code'], 'permission_denied')

    def test_candidate_restricts_tools_even_when_call_capture_is_disabled(self):
        from gymts_libraryts.candidate import LibraryTSQACandidate
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym:
            candidate = LibraryTSQACandidate({'params': {'implementation': {'repository': '/not-opened'}}})
            with patch('gymts_libraryts.runtime.LibraryTSRuntime.describe', return_value={'fixture': 'source metadata'}):
                candidate.prepare({'learning': {'prepare': 'load_only', 'online': 'frozen'},
                                   'resources': gym.artifacts}, None)
            self.assertIsNone(candidate.traces)
            self.assertEqual(candidate.tools.scope, 'current_input')
            with patch.object(candidate.tools.runtime, 'invoke') as invoke, self.assertRaises(GymTSError):
                candidate.tools.call('dataset.load', {'dataset': 'airline'})
            invoke.assert_not_called()


@unittest.skipUnless(os.environ.get('GYMTS_LIBRARYTS_NATIVE_TESTS')=='1','Opt in to fixed-source native CPU computations')
class LibraryTSNativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.gym=GymTS(self.root/'state',integrations=('timeseries','libraryts'))
        self.addCleanup(self.gym.close)
        self.implementation={'repository':os.environ.get('GYMTS_LIBRARYTS_REPO','/tmp/gymts-libraryts-sktime'),
            'python':os.environ.get('GYMTS_LIBRARYTS_PYTHON',sys.executable)}
        self.tools=LibraryTSTools(self.gym.artifacts,self.implementation)

    def test_two_forecasters_record_real_fit_and_loaded_module_hashes(self):
        tools=LibraryTSTools(self.gym.artifacts,self.implementation,scope='current_input')
        for tool,params in [('forecast.naive',{'strategy':'drift'}),('forecast.polynomial',{'degree':1})]:
            with self.subTest(tool=tool):
                out=tools.call(tool,{'values':[1,2,3],'horizons':[1,2]},params)['output']
                for actual,expected in zip(out['predictions'],[4,5]): self.assertAlmostEqual(actual,expected)
                self.assertTrue(out['fit_occurred'])
                self.assertEqual(out['fit_scope'],'current_authorized_input_only')
                self.assertFalse(out['persistent_state_reused'])
                self.assertEqual(len(out['fitted_state_sha256']),64)
                self.assertEqual(out['provenance']['revision'],PINNED_REVISION)
                self.assertEqual(out['provenance']['repository_url'],REPOSITORY_URL)
                self.assertTrue(out['provenance']['loaded_modules'])
                for module in out['provenance']['loaded_modules'].values():
                    self.assertTrue(Path(module['path']).is_relative_to(Path(self.implementation['repository'])))
                    self.assertEqual(len(module['sha256']),64)
                if tool=='forecast.polynomial': self.assertAlmostEqual(out['fitted_state']['coefficients'][1],1.)

    def test_threshold_seasonality_and_distance_use_native_tools(self):
        tools=LibraryTSTools(self.gym.artifacts,self.implementation,scope='current_input')
        detected=tools.call('detect.threshold',{'values':[0,0,5,6,0]},{'upper':3})['output']
        self.assertEqual(detected['flags'],[False,False,True,True,False])
        self.assertEqual(tools.call('distance.euclidean',{'x':[1,2,3],'y':[1,2,5]})['output']['distance'],2.)
        season=tools.call('analyze.seasonality',{'values':[math.sin(2*math.pi*i/12) for i in range(120)]})['output']
        self.assertIn('sp',season['estimates'])

    def test_original_catalog_run_analyze_metrics_and_error_capture(self):
        catalog=self.tools.call('labts.catalog',{'include_registered':False})['output']
        self.assertTrue(any(row['id']=='naive-seasonal-last' for row in catalog['algorithms']))
        result=self.tools.call('labts.run',{'task':'forecasting','dataset_id':'airline','algorithm_id':'naive-seasonal-last'},{'horizon':2})['output']
        self.assertNotIn(result.get('status'),('blocked','failed','error'))
        analyzed=self.tools.call('labts.analyze',{'algorithm_id':'seasonality-acf','dataset_id':'airline'})['output']
        self.assertNotIn(analyzed.get('status'),('blocked','failed','error'))
        metrics=self.tools.call('labts.metrics',{'task':'forecasting','metrics':['mae','rmse'],'context':{'values':[1,2],'predictions':[2,4]}})['output']['metrics']
        self.assertEqual(metrics['mae'],1.5)
        self.assertAlmostEqual(metrics['rmse'],math.sqrt(2.5))
        with self.assertRaises(GymTSError): self.tools.call('forecast.naive',{'values':[]})
        self.assertEqual(self.gym.artifacts.read_json(self.tools.last_call_ref)['status'],'failed')

    def test_loader_separates_holdout_from_task_neutral_source(self):
        from gymts_libraryts.data import load_dataset
        source=load_dataset(self.gym,self.implementation,dataset='airline',horizon=12,context_window=24)
        sample=self.gym.artifacts.read_json(source['snapshot_ref'])['samples'][0]
        private=self.gym.artifacts.read_json(source['private_ref'])
        self.assertEqual(len(sample['series'][0]['values']),24)
        self.assertEqual(sample['context'],{'horizon':12})
        self.assertEqual(len(private['values']),12)
        self.assertEqual(private['allowed_uses'],['evaluation'])
        self.assertNotIn('task_id',sample)
        self.assertNotIn('expected_output',json.dumps(sample))
        self.assertNotIn('private_ref',sample)

    def test_autobench_scores_sealed_runs_and_keeps_model_call_count(self):
        path=Path(__file__).resolve().parents[1]/'examples/libraryts_demo.py'
        spec=importlib.util.spec_from_file_location('libraryts_example',path)
        example=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(example)
        result=example.run_demo(str(self.root/'demo'),self.implementation)
        self.assertEqual(result['report']['status'],'completed')
        self.assertEqual(len(result['run_ids']),2)
        with GymTS(self.root/'demo',integrations=('timeseries','libraryts')) as gym:
            for run_id in result['run_ids']:
                events=gym.records.get_run(run_id)['events']
                for kind in ('candidate_output','model_call','tool_call'):
                    self.assertEqual(sum(row['kind']==kind for row in events),1)
                calls=[gym.artifacts.read_json(row['payload']['artifact_ref']) for row in events if row['kind']=='tool_call']
                self.assertTrue(all(call['operation_id'] is None and call['environment_request_id'] is None for call in calls))
        ready=[row for row in result['report']['metrics'] if row['level']=='unit']
        self.assertEqual(len(ready),4)
        self.assertTrue(all(row['result']['status']=='ready' and row['result']['counts']['eligible']==1 for row in ready))


if __name__=='__main__': unittest.main()
