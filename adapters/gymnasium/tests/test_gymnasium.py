import copy
import importlib.util
import tempfile
import unittest
from unittest.mock import patch
from gymts import GymTS
from gymts.contracts import canonical_json
from gymts_gymnasium import environment_spec
from gymts_interaction.experiments import control_scene,evaluation_spec,rescore_spec

def candidate(actions=(2,2,1,1,1,2),repeat=False):
    return {'adapter':'interaction-sequence','version':'1.0.0','artifact':None,'inherited_state':[],
        'params':{'actions':[{'action':i} for i in actions],'repeat_last':repeat}}

def experiment(spec):
    case=spec['cases'][0]
    return {'protocol_version':'gymts.experiment/1','purpose':'acceptance','name':'native-test',
        'scene':case['scene'],'candidate':spec['candidates'][0]['spec'],'execution':case['execution'],
        'recording':case['recording'],'extensions':{}}

class DeclarationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.gym=GymTS(self.tmp.name,integrations=('interaction','gymnasium'))
    def tearDown(self): self.gym.close(); self.tmp.cleanup()

    def test_pure_plan_does_not_import_native_backend(self):
        spec=evaluation_spec(environment_spec(kwargs={'is_slippery':False}),candidate(),scope_end=6)
        with patch.dict('sys.modules',{'gymnasium':None}):
            self.assertTrue(self.gym.validate(experiment(spec))['valid'])

    def test_source_revision_config_drift_rejected(self):
        spec=evaluation_spec(environment_spec(),candidate(),scope_end=6)
        spec['cases'][0]['scene']['environment']['options']['kwargs']={'is_slippery':False}
        self.assertFalse(self.gym.validate(experiment(spec))['valid'])

    def test_nonzero_episode_start_rejected(self):
        spec=evaluation_spec(environment_spec(),candidate(),scope_end=6)
        spec['cases'][0]['execution']['scope']['start']=1
        self.assertFalse(self.gym.validate(experiment(spec))['valid'])

    def test_negative_native_seed_rejected_without_open(self):
        spec=evaluation_spec(environment_spec(),candidate(),scope_end=6)
        spec['cases'][0]['execution']['seed']=-1
        self.assertFalse(self.gym.validate(experiment(spec))['valid'])

    def test_json_projection_rejects_key_coercion_collision(self):
        from gymts import GymTSError
        from gymts_gymnasium.environment import _json
        with self.assertRaises(GymTSError): _json({1:'a','1':'b'})

@unittest.skipUnless(importlib.util.find_spec('gymnasium'),'Install gymts-gymnasium[runtime] for native checks')
class NativeTests(DeclarationTests):
    def test_native_terminal_reward_and_immutable_rescore(self):
        spec=evaluation_spec(environment_spec(kwargs={'is_slippery':False}),candidate(),scope_end=6,seeds=(19,29))
        report=self.gym.autobench.evaluate(spec)
        self.assertEqual(report['verdict'],'pass'); self.assertEqual(report['coverage']['succeeded_runs'],2)
        values={row['metric_id']:row['result']['value'] for row in report['metrics'] if row['level']=='aggregate'}
        self.assertEqual(values['episode_return'],1); self.assertEqual(values['episode_length'],6)
        self.assertEqual(values['terminated'],1); self.assertEqual(values['truncated'],0)
        manifest=self.gym.artifacts.read_json(report['run_manifest_ref'])
        before={row['run_id']:canonical_json(self.gym.records.get_run(row['run_id'])) for row in manifest['entries']}
        with patch('gymnasium.make',side_effect=AssertionError('Scoring cannot run simulator')):
            second=self.gym.autobench.score(rescore_spec(self.gym,report,spec))
        self.assertEqual(second['verdict'],'pass')
        self.assertEqual(before,{run_id:canonical_json(self.gym.records.get_run(run_id)) for run_id in before})

    def test_native_cartpole_horizon_reward_preserved(self):
        spec=evaluation_spec(environment_spec('CartPole-v1'),candidate((1,),True),scope_end=2,seeds=(19,))
        report=self.gym.autobench.evaluate(spec)
        self.assertEqual(report['verdict'],'pass')
        values={row['metric_id']:row['result']['value'] for row in report['metrics'] if row['level']=='aggregate'}
        self.assertEqual(values['episode_return'],2); self.assertEqual(values['episode_length'],2)
        self.assertEqual(values['truncated'],0); self.assertEqual(values['scope_limited'],1)

    def test_native_out_of_space_action_seals_failure(self):
        spec=evaluation_spec(environment_spec('CartPole-v1'),candidate((9,),True),scope_end=2)
        result=self.gym.run(experiment(spec))
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['summary']['counts']['operations'],1)
        self.assertEqual(result['summary']['cleanup']['environment']['summary']['counts']['operations'],0)
        self.assertEqual(result['summary']['cleanup']['environment']['summary']['backend_disposition'],'closed')

    def test_native_version_mismatch_seals_failed_run(self):
        spec=evaluation_spec(environment_spec(version='0.0.0'),candidate(),scope_end=6)
        result=self.gym.run(experiment(spec))
        self.assertEqual(result['status'],'failed'); self.assertEqual(result['errors'][0]['code'],'conflict')

    def test_native_instance_reset_and_close_exactly_once(self):
        import gymnasium
        from gymts_gymnasium.environment import GymnasiumEnvironment
        class Counting(gymnasium.Wrapper):
            resets=steps=closes=0
            def reset(self,**kwargs): self.resets+=1; return self.env.reset(**kwargs)
            def step(self,action): self.steps+=1; return self.env.step(action)
            def close(self): self.closes+=1; return self.env.close()
        wrapped=Counting(gymnasium.make('FrozenLake-v1',is_slippery=False))
        spec=evaluation_spec(environment_spec(kwargs={'is_slippery':False}),candidate(),scope_end=6)
        with patch('gymnasium.make',return_value=wrapped):
            report=self.gym.autobench.evaluate(spec)
        self.assertEqual(report['verdict'],'pass')
        self.assertEqual((wrapped.resets,wrapped.steps,wrapped.closes),(1,6,1))

    def test_invalid_native_flag_is_not_coerced_to_termination(self):
        import gymnasium
        class InvalidFlag(gymnasium.Wrapper):
            steps=closes=0
            def step(self,action):
                self.steps+=1
                observation,reward,terminated,truncated,info=self.env.step(action)
                return observation,reward,'False',truncated,info
            def close(self): self.closes+=1; return self.env.close()
        wrapped=InvalidFlag(gymnasium.make('CartPole-v1'))
        spec=evaluation_spec(environment_spec('CartPole-v1'),candidate((1,),True),scope_end=2)
        with patch('gymnasium.make',return_value=wrapped):
            result=self.gym.run(experiment(spec))
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['errors'][0]['code'],'schema_mismatch')
        self.assertEqual(result['errors'][0]['side_effect'],'possible')
        self.assertIn('operation_id',result['errors'][0]['links'])
        self.assertEqual(len(result['summary']['cleanup']['environment']['summary']['pending_operations']),1)
        self.assertEqual((wrapped.steps,wrapped.closes),(1,1))

if __name__=='__main__': unittest.main()
