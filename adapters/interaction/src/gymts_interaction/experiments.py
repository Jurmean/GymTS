"""Optional JSON builders; execution and reporting remain native GymTS services."""
import copy
from .contracts import ACTION, ALIGNMENT
from .scoring import METRICS

def control_scene(environment):
    return {'environment':copy.deepcopy(environment),'task':{'plugin':'interaction-control','version':'1.0.0','params':{}},
        'binding':{'variables':{'state':{'source':'state','unit':'state','transform':None}},
            'operations':{'act':{'source':'act','arguments_schema_ref':ACTION,'transform':None}}}}

def evaluation_spec(environment,candidate,*,scope_end=100,seeds=(0,),name='interaction environment',candidate_id='policy'):
    return {'protocol_version':'gymts.evaluation/1','name':name,'purpose':'acceptance',
        'cases':[{'evaluation_case_id':'episode','scene':control_scene(environment),
            'execution':{'mode':'stream','start':{'mode':'reinitialize'},'scope':{'start':0,'end':scope_end},
                'feedback_until':None,'seed':0,'learning':{'prepare':'load_only','online':'frozen',
                    'training_view':None,'training_targets':None,'alignment_schema_ref':None,'allowed_feedback_sources':[]},
                'limits':{'max_inputs':None,'max_operations':None,'max_turns_per_case':scope_end,'max_wall_time_s':120}},
            'recording':{'store_ref':'local://records/default','inputs':'full','outputs':'full','artifacts':'reference',
                'model_calls':'none','on_capture_failure':'fail_run','redaction_policy_ref':None,'extra_event_kinds':[]},'tags':{}}],
        'candidates':[{'candidate_id':candidate_id,'spec':copy.deepcopy(candidate)}],'baseline_id':None,
        'repetitions':{'count':len(seeds),'seeds':list(seeds)},
        'scoring':{'scorer':{'adapter':'interaction-episode-scorer','version':'1.0.0','params':{}},
            'outcomes':{'sources':[],'as_of':None},'alignment':{'schema_ref':ALIGNMENT,
                'keys':['episode_id','step'],'matching':'exact','params':{},'duplicate_policy':'error'},
            'metrics':list(METRICS),'evidence_requirements':{'min_scored':1,'min_coverage':1,'overrides':{}},
            'missing_outcome_policy':'report_insufficient'},
        'comparison':{'group_by':['evaluation_case_id'],'repetition_aggregation':'mean','aggregation':'macro_mean',
            'baseline_method':'difference','gates':[{'metric':'run_failure_rate','target':'absolute','candidate_ids':None,
                'for_metric':None,'operator':'le','threshold':0,'scope':'aggregate'},
                {'metric':'scored_coverage','target':'absolute','candidate_ids':None,'for_metric':'episode_return',
                    'operator':'ge','threshold':1,'scope':'aggregate'}]},
        'failure_policy':{'partial_results':'include','invalid_result_policy':'report'}}

def rescore_spec(gym,evaluation,spec):
    manifest=gym.artifacts.read_json(evaluation['run_manifest_ref'])
    plan=gym.artifacts.read_json(evaluation['plan_ref'])
    executions={row['unit_id']:row for row in manifest['entries']}
    rows=[]
    for unit in plan['expected_units']:
        execution=executions[unit['unit_id']]
        rows.append({'unit_id':unit['unit_id'],'evaluation_case_id':unit['evaluation_case_id'],
            'candidate_id':unit['candidate_id'],'repetition':unit['repetition'],'tags':unit['tags'],
            'run_id':execution['run_id'],'unit_spec_ref':unit['resolved_spec_ref'],
            'unavailable_reason':None if execution['run_id'] else 'run_unavailable'})
    return {'protocol_version':'gymts.score/1','name':spec['name'],'purpose':spec['purpose'],'runs':rows,
        'previous_evaluation_id':evaluation['evaluation_id'],**{key:copy.deepcopy(spec[key]) for key in
            ('baseline_id','scoring','comparison','failure_policy')}}
