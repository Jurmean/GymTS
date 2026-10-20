"""Installed-wheel native CPU proof; CAS and SQLite stay under --output (/tmp)."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
from unittest.mock import patch
from gymts import GymTS
from gymts.contracts import canonical_json
from gymts_gymnasium import environment_spec
from gymts_interaction.experiments import evaluation_spec,rescore_spec

def run(output):
    output=Path(output); output.mkdir(parents=True,exist_ok=False)
    scenarios=[('frozenlake-terminal',environment_spec(kwargs={'is_slippery':False}),
        {'actions':[{'action':i} for i in [2,2,1,1,1,2]],'repeat_last':False},6),
        ('cartpole-terminal',environment_spec('CartPole-v1'),{'actions':[{'action':1}],'repeat_last':True},100),
        ('cartpole-scope-boundary',environment_spec('CartPole-v1'),{'actions':[{'action':1}],'repeat_last':True},2)]
    summary={'protocol_version':'gymts.gymnasium-native-validation/1',
        'versions':{name:importlib.metadata.version(name) for name in
            ('gymts','gymts-interaction','gymts-gymnasium','gymnasium','numpy')},
        'loaded_modules':{},'scenarios':[]}
    import gymts, gymts_interaction, gymts_gymnasium
    def core_hashes():
        root=Path(gymts.__file__).resolve().parent
        return {path.relative_to(root.parent).as_posix():hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob('*.py'))}
    summary['core_code_hashes_before']=core_hashes()
    for name,module in [('gymts',gymts),('gymts_interaction',gymts_interaction),('gymts_gymnasium',gymts_gymnasium)]:
        summary['loaded_modules'][name]=str(Path(module.__file__).resolve())
    with GymTS(str(output/'records'),integrations=('interaction','gymnasium')) as gym:
        for name,env,params,horizon in scenarios:
            candidate={'adapter':'interaction-sequence','version':'1.0.0','artifact':None,
                'inherited_state':[],'params':params}
            spec=evaluation_spec(env,candidate,scope_end=horizon,seeds=(19,29),name=name)
            case=spec['cases'][0]
            experiment={'protocol_version':'gymts.experiment/1','name':name,'purpose':'acceptance',
                'scene':case['scene'],'candidate':candidate,'execution':case['execution'],
                'recording':case['recording'],'extensions':{}}
            with patch.dict('sys.modules',{'gymnasium':None}):
                plan=gym.plan(experiment)
            report=gym.autobench.evaluate(spec)
            assert report['verdict']=='pass',report
            manifest=gym.artifacts.read_json(report['run_manifest_ref'])
            run_ids=[row['run_id'] for row in manifest['entries']]
            before={rid:hashlib.sha256(canonical_json(gym.records.get_run(rid))).hexdigest() for rid in run_ids}
            records=[gym.records.get_run(rid) for rid in run_ids]
            with patch('gymnasium.make',side_effect=AssertionError('Rescoring cannot create or step a simulator')):
                rescored=gym.autobench.score(rescore_spec(gym,report,spec))
            after={rid:hashlib.sha256(canonical_json(gym.records.get_run(rid))).hexdigest() for rid in run_ids}
            assert before==after
            assert rescored['verdict']=='pass'
            metrics={r['metric_id']:r['result']['value'] for r in report['metrics'] if r['level']=='aggregate'}
            transitions=[]
            for record in records:
                states=[]
                for event in record['events']:
                    if event['kind']=='observation':
                        batch=event['payload']['value']
                        if batch['data'] and batch['data']['native']:
                            states.append(batch['data']['native']['value'])
                transitions.append({'run_id':record['run_id'],'rewards':[s['reward'] for s in states],
                    'observations':[s['observation'] for s in states],'final_state':states[-1],
                    'seed_used':next(e['payload']['value']['value']['seed_used'] for e in record['events']
                        if e['kind']=='artifact' and e['payload']['value'].get('role')=='session')})
            if name=='frozenlake-terminal':
                assert metrics['episode_return']==1 and metrics['episode_length']==6
                assert all(t['rewards'][-1]==1 and t['final_state']['terminated'] for t in transitions)
            if name=='cartpole-scope-boundary':
                assert metrics['episode_return']==2 and metrics['episode_length']==2
                assert metrics['truncated']==0 and metrics['scope_limited']==1
            row={'name':name,'run_ids':run_ids,'verdict':report['verdict'],'rescore_verdict':rescored['verdict'],
                'coverage':report['coverage'],'metrics':metrics,'run_hashes_before':before,'run_hashes_after':after,
                'sealed_runs_unchanged':before==after,'pure_plan_without_backend_import':True,
                'rescore_backend_calls':0,'transitions':transitions}
            summary['scenarios'].append(row)
            for suffix,value in [('spec',spec),('plan',plan),('evaluation',report),('rescore',rescored),('runs',records)]:
                (output/(name+'-'+suffix+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    summary['successful_runs']=sum(row['coverage']['succeeded_runs'] for row in summary['scenarios'])
    summary['core_code_hashes_after']=core_hashes()
    summary['core_changed']=summary['core_code_hashes_before']!=summary['core_code_hashes_after']
    assert not summary['core_changed']
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--output',required=True)
    run(parser.parse_args().output)
