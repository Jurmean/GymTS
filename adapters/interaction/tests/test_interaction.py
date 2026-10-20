import copy
import tempfile
import unittest
from gymts import GymTS, GymTSError
from gymts.plugin_support import component,payload
from gymts_interaction.contracts import ACTION
from gymts_interaction.environment import CachedInteractionEnvironment
from gymts_interaction.experiments import evaluation_spec
from gymts_interaction.task import ControlSession

class Backend(CachedInteractionEnvironment):
    ADAPTER='test-interaction'
    def __init__(self,fail_reset=False):
        super().__init__({'source':{'revision':'fixed'}},None)
        self.resets=self.steps=self.closes=0; self.fail_reset=fail_reset
    def _reset(self,seed):
        self.resets+=1; self.seed=seed
        if self.fail_reset: raise RuntimeError('reset failed')
        return {'observation':0,'info':{},'source_identity':{'fixture':True},
            'observation_space':{},'action_space':{}}
    def _step(self,action):
        self.steps+=1
        return {'observation':self.steps,'reward':float(self.steps),
            'terminated':self.steps==2,'truncated':False,'info':{}}
    def _close(self): self.closes+=1

def start(env,end=2):
    return env.start({'run_id':'test','mode':'reinitialize','scope':{'start':0,'end':end},
        'read_scope':{'start':0,'end':end},'feedback_until':None,'seed':19,
        'permitted_variables':['state'],'permitted_operations':['act']})

def observe(env):
    return env.observe({'request_id':'read','kind':'next','cursor':env.cursor,
        'variables':['state'],'entities':['episode'],'max_wait_ms':0})

def act(env,number):
    return env.act({'operation_id':'op'+str(number),'request_id':'req'+str(number),
        'output_id':'out'+str(number),'origin':'candidate','trigger_batch_id':None,
        'name':'act','arguments':payload(ACTION,{'action':1}),'idempotency_key':None})

class InteractionLifecycleTests(unittest.TestCase):
    def test_reset_once_observe_consumes_only_terminal_reward_kept(self):
        env=Backend(); session=start(env)
        self.assertEqual(session['seed_used'],19); self.assertEqual(env.resets,1)
        self.assertEqual(observe(env)['snapshot_time'],0)
        self.assertEqual(observe(env)['status'],'waiting'); self.assertEqual(env.steps,0)
        act(env,1); self.assertEqual(env.steps,1)
        with self.assertRaises(GymTSError): act(env,2)
        self.assertEqual(env.steps,1); observe(env); act(env,2)
        final=observe(env)
        self.assertEqual(final['status'],'end')
        self.assertEqual(final['data']['native']['value']['reward'],2)
        self.assertTrue(final['end']['terminated'])
        self.assertIsNone(observe(env)['data']); self.assertEqual(env.resets,1)
        with self.assertRaises(GymTSError): act(env,3)
        env.finish(); env.finish(); self.assertEqual(env.closes,1)

    def test_duplicate_operation_never_steps_twice(self):
        env=Backend(); start(env); observe(env); act(env,1); observe(env)
        with self.assertRaises(GymTSError) as raised: act(env,1)
        self.assertEqual(raised.exception.code,'conflict'); self.assertEqual(env.steps,1)
        env.finish()

    def test_scope_end_keeps_transition_reward_without_rewriting_native_done(self):
        env=Backend(); start(env,end=1); observe(env); act(env,1); final=observe(env)
        self.assertEqual(final['status'],'end'); self.assertEqual(final['end']['reason'],'read_scope_end')
        self.assertFalse(final['data']['native']['value']['terminated'])
        self.assertFalse(final['data']['native']['value']['truncated'])
        self.assertFalse(final['end']['truncated']); self.assertEqual(final['data']['native']['value']['reward'],1)
        env.finish()

    def test_permissions_and_stale_cursor_do_not_consume(self):
        env=Backend(); start(env)
        for change in ({'variables':[]},{'entities':['other']},{'cursor':'stale'},{'kind':'range'}):
            request={'request_id':'read','kind':'next','cursor':env.cursor,'variables':['state'],
                'entities':['episode'],'max_wait_ms':0}; request.update(change)
            with self.assertRaises(GymTSError): env.observe(request)
        self.assertEqual(observe(env)['snapshot_time'],0); env.finish()

    def test_failed_reset_still_closes_created_backend(self):
        env=Backend(fail_reset=True)
        with self.assertRaises(RuntimeError): start(env)
        env.finish(); self.assertEqual(env.closes,1)

    def test_unstarted_finish_does_not_claim_ownership(self):
        env=Backend(); self.assertEqual(env.finish()['backend_disposition'],'not_started')
        self.assertEqual(env.closes,0)

    def test_cleanup_preserves_executed_but_unconsumed_reward(self):
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym:
            env=Backend(); env.services=gym.artifacts; start(env); observe(env); act(env,1)
            summary=env.finish()
            pending=gym.artifacts.read_json(summary['artifact_refs'][0])
            self.assertEqual(pending['reward'],1); self.assertEqual(pending['step'],1)
            self.assertEqual(env.closes,1)
            self.assertEqual(set(summary),{'session_id','actual_scope','last_cursor','final_clock','end',
                'counts','pending_operations','artifact_refs','backend_disposition'})

    def test_uncertain_native_operation_poisoned_not_retried(self):
        env=Backend(); start(env); observe(env)
        def uncertain(action):
            env.steps+=1; raise ConnectionError('response lost')
        env._step=uncertain
        with self.assertRaises(GymTSError) as raised: act(env,1)
        self.assertEqual(raised.exception.info['side_effect'],'possible')
        self.assertEqual(raised.exception.info['links']['operation_id'],'op1')
        with self.assertRaises(GymTSError): act(env,2)
        self.assertEqual(env.steps,1)
        self.assertEqual(env.finish()['pending_operations'],['op1'])

    def test_unknown_receipt_preserves_runner_side_effect_error(self):
        session=object.__new__(ControlSession); session.done=False
        self.assertFalse(session.on_action({'status':'unknown'})['done'])

    def test_null_reward_affects_return_but_not_observed_length(self):
        class NullReward(Backend):
            def _step(self,action):
                value=super()._step(action); value['reward']=None; return value
        with tempfile.TemporaryDirectory() as directory, GymTS(directory,integrations=('interaction',)) as gym:
            manifest={'component_ref':component('test-interaction'),'protocol_versions':['gymts.environment/1'],
                'params_schema_ref':None,'origin_ref':None,'source_schema_ref':'gymts.json/1',
                'mapping_schema_ref':'gymts.json/1','options_schema_ref':'gymts.json/1'}
            gym.registries.environments.register(manifest,lambda spec,services:NullReward(),describe=Backend.describe_spec)
            environment={'protocol_version':'gymts.environment/1','adapter':'test-interaction','version':'1.0.0',
                'source':{'kind':'simulator','locator':'fixture://null-reward','revision':'fixed',
                    'connection':{},'credential_ref':None},'mapping':{},'options':{}}
            candidate={'adapter':'interaction-fixed','version':'1.0.0','artifact':None,'inherited_state':[],
                'params':{'action':{'action':1}}}
            report=gym.autobench.evaluate(evaluation_spec(environment,candidate,scope_end=2))
            metrics={r['metric_id']:r['result'] for r in report['metrics'] if r['level']=='unit'}
            self.assertEqual(report['coverage']['succeeded_runs'],1)
            self.assertEqual(metrics['episode_return']['status'],'insufficient_evidence')
            self.assertEqual(metrics['episode_return']['reason'],'reward_unavailable')
            self.assertEqual(metrics['episode_length']['value'],2)
            self.assertEqual(metrics['terminated']['value'],1)

    def test_unclassified_done_closes_episode_without_inventing_cause(self):
        class Unclassified(Backend):
            def _step(self,action):
                value=super()._step(action); done=value['terminated']; value['terminated']=False
                value.update(backend_done=done,end_cause='unclassified' if done else None)
                return value
        with tempfile.TemporaryDirectory() as directory, GymTS(directory,integrations=('interaction',)) as gym:
            manifest={'component_ref':component('test-interaction'),'protocol_versions':['gymts.environment/1'],
                'params_schema_ref':None,'origin_ref':None,'source_schema_ref':'gymts.json/1',
                'mapping_schema_ref':'gymts.json/1','options_schema_ref':'gymts.json/1'}
            gym.registries.environments.register(manifest,lambda spec,services:Unclassified(),describe=Backend.describe_spec)
            environment={'protocol_version':'gymts.environment/1','adapter':'test-interaction','version':'1.0.0',
                'source':{'kind':'simulator','locator':'fixture://done-only','revision':'fixed',
                    'connection':{},'credential_ref':None},'mapping':{},'options':{}}
            candidate={'adapter':'interaction-fixed','version':'1.0.0','artifact':None,'inherited_state':[],
                'params':{'action':{'action':1}}}
            report=gym.autobench.evaluate(evaluation_spec(environment,candidate,scope_end=4))
            metrics={r['metric_id']:r['result'] for r in report['metrics'] if r['level']=='unit'}
            self.assertEqual(report['coverage']['succeeded_runs'],1)
            self.assertEqual(metrics['episode_return']['value'],3)
            self.assertEqual(metrics['episode_length']['value'],2)
            for metric in ('terminated','truncated'):
                self.assertIsNone(metrics[metric]['value'])
                self.assertEqual(metrics[metric]['reason'],'termination_cause_unavailable')
            run_id=gym.artifacts.read_json(report['run_manifest_ref'])['entries'][0]['run_id']
            result=gym.records.get_run(run_id)['result']
            self.assertEqual(result['completion'],'source_exhausted')
            self.assertEqual(result['summary']['environment_end']['detail']['reason'],'native_done_unclassified')
            self.assertFalse(result['summary']['environment_end']['terminated'])
            self.assertFalse(result['summary']['environment_end']['truncated'])

    def test_malformed_post_step_reply_cannot_be_retried(self):
        env=Backend(); start(env); observe(env)
        def malformed(action):
            env.steps+=1
            return {'observation':1,'reward':1,'terminated':False,'truncated':False,'info':{},
                'backend_done':True,'end_cause':None}
        env._step=malformed
        with self.assertRaises(GymTSError) as raised: act(env,1)
        self.assertEqual(raised.exception.info['side_effect'],'possible')
        with self.assertRaises(GymTSError): act(env,2)
        self.assertEqual(env.steps,1)
        self.assertEqual(env.finish()['pending_operations'],['op1'])

    def test_pending_capture_failure_still_closes_backend(self):
        class BrokenServices:
            def save_json(self,*args): raise OSError('CAS unavailable')
        env=Backend(); env.services=BrokenServices(); start(env); observe(env); act(env,1)
        with self.assertRaises(GymTSError) as raised: env.finish()
        self.assertEqual(raised.exception.code,'recording_failure')
        self.assertEqual(env.closes,1)

    def test_close_failure_retains_pending_evidence_and_is_not_retried(self):
        with tempfile.TemporaryDirectory() as directory, GymTS(directory) as gym:
            env=Backend(); env.services=gym.artifacts; start(env); observe(env); act(env,1)
            def failed_close():
                env.closes+=1; raise OSError('close outcome unknown')
            env._close=failed_close
            with self.assertRaises(GymTSError) as raised: env.finish()
            ref=raised.exception.info['links']['artifact_refs'][0]
            self.assertEqual(gym.artifacts.read_json(ref)['reward'],1)
            with self.assertRaises(GymTSError): env.finish()
            self.assertEqual(env.closes,1)

if __name__=='__main__': unittest.main()
