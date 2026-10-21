"""Full resource definitions resolve to standard AutoBenchTS plans and scorers."""
import copy

from gymts.contracts import digest, inline, utc_now
from gymts.plugin_support import fail
from .contracts import ALIGNMENT, OUTCOME, SNAPSHOT
from .parsing import PARSER_REF


def first_choice_candidate():
    return {'candidate_id':'first-choice','spec':{'adapter':'tsqa-first-choice','version':'1.0.0',
        'artifact':None,'params':{},'inherited_state':[]}}


class TSQABenchmarkResolver:
    def resolve(self,definition,resources,candidates,purpose,repetitions):
        params=definition['params']
        expected={'scope','metrics','parser_ref','coverage_policy','question_policy'}
        if set(params)!=expected:
            fail('unsupported_capability','TSQA definition must declare exactly scope, metrics, parser_ref, coverage_policy and question_policy')
        if (len(definition['datasets'])!=1 or params['scope']!='full'
                or params['parser_ref']!=PARSER_REF
                or params['coverage_policy']!='all_source_rows_eligible'
                or params['question_policy']!='complete-original-lossless-projection/1'):
            fail('unsupported_capability','TSQA resolver supports only complete source rows, its fixed parser and lossless original question policy')
        if (not isinstance(params['metrics'],list) or len(params['metrics'])!=2
                or not all(isinstance(metric,str) for metric in params['metrics'])
                or set(params['metrics']) not in ({'accuracy','format_valid'}, {'task_score','format_valid'})):
            fail('unsupported_capability','TSQA full definition requires its task metric and format_valid with the fixed coverage Gate')
        reference=definition['datasets'][0]
        dataset=resources.datasets.load_dataset(**reference,purpose='evaluation')
        targets=dataset.read_targets()
        public_ids=dataset.public.sample_ids()
        if (len(targets)!=len(dataset) or len({t['sample_id'] for t in targets})!=len(targets)
                or {t['sample_id'] for t in targets}!=set(public_ids)):
            fail('artifact_integrity','TSQA source and private references do not align exactly')
        targets_by_id={t['sample_id']:t for t in targets}
        structured = {row['task_kind']=='structured' for row in dataset}
        primary = 'task_score' if structured == {True} else 'accuracy'
        if len(structured)!=1 or set(params['metrics'])!={primary,'format_valid'}:
            fail('unsupported_capability','Dataset task kinds and requested scoring metric do not match')
        target_ref=resources.artifacts.save_json({'dataset_revision':reference['revision'],'targets':targets},'gymts.json/1')
        cases,outcomes=[],[]
        available=utc_now()
        for row in dataset:
            token=row['sample_id']; kind=row['task_kind']; target=targets_by_id[token]
            if target['reference_kind']!=kind or target['allowed_uses']!=['evaluation']:
                fail('permission_denied','TSQA target identity or use differs from the fixed public question')
            snapshot_ref=resources.artifacts.save_json({'dataset_revision':reference['revision'],'samples':[row]},SNAPSHOT)
            scene={'environment':{'protocol_version':'gymts.environment/1','adapter':'tsqa-snapshot','version':'1.0.0',
                'source':{'kind':'dataset','locator':'artifact://public-tsqa-snapshot','revision':reference['revision'],
                    'connection':{'artifact_refs':[snapshot_ref]},'credential_ref':None},'mapping':{},
                'options':{'row_count':1,'task_kinds':[kind]}},
                'task':{'plugin':'tsqa-benchmark','version':'1.0.0','params':{'task_kind':kind}},
                'binding':{'variables':{'sample':{'source':'sample','unit':'sample','transform':None}},'operations':{}}}
            cases.append({'evaluation_case_id':token,'scene':scene,
                'execution':{'mode':'stream','start':{'mode':'reinitialize'},'scope':{'start':0,'end':1},
                    'feedback_until':None,'seed':0,
                    'learning':{'prepare':'load_only','online':'frozen','training_view':None,'training_targets':None,
                        'alignment_schema_ref':None,'allowed_feedback_sources':[]},
                    'limits':{'max_inputs':1,'max_operations':None,'max_turns_per_case':1,'max_wall_time_s':180}},
                'recording':{'store_ref':'local://records/default','inputs':'full','outputs':'full','artifacts':'reference',
                    'model_calls':'none','on_capture_failure':'fail_run','redaction_policy_ref':None,'extra_event_kinds':[]},
                'tags':{'dataset':reference['dataset_id'],'task_kind':kind,'source_row':str(row['source_row'])}})
            gold={key:target[key] for key in ('reference_status','reference_answer','reference_kind','reason')}
            if 'input_issue' in target:
                gold['input_issue']=target['input_issue']
            outcomes.append({'outcome_id':'tsqa-gold-'+digest({'revision':reference['revision'],'sample_id':token}),
                'revision':'1','alignment_key':{'dataset_revision':reference['revision'],'sample_id':token},
                'payload':inline(gold,OUTCOME),'event_time':0,'available_at':available,'recorded_at':available,
                'source_ref':target_ref,'supersedes_ref':None,'allowed_uses':['evaluation']})
        outcome_ref=resources.artifacts.save_json(outcomes,'gymts.outcome-records/1')
        view={'view_id':'tsqa-gold-'+outcome_ref['revision'],'revision':outcome_ref['revision'],
            'source_refs':[outcome_ref],'selection':inline({'kind':'all','source_index':0},'gymts.selection/1'),
            'as_of':None,'purpose':'evaluation'}
        return {'protocol_version':'gymts.evaluation/1','name':definition['benchmark_id']+' full benchmark',
            'purpose':purpose,'cases':cases,'candidates':copy.deepcopy(candidates),'baseline_id':None,
            'repetitions':repetitions or {'count':1,'seeds':[0]},
            'scoring':{'scorer':{'adapter':'tsqa-reference-scorer','version':'1.0.0','params':{}},
                'outcomes':{'sources':[view],'as_of':available},
                'alignment':{'schema_ref':ALIGNMENT,'keys':['dataset_revision','sample_id'],'matching':'exact',
                    'params':{},'duplicate_policy':'error'},'metrics':definition['params']['metrics'],
                'evidence_requirements':{'min_scored':1,'min_coverage':1,'overrides':{}},
                'missing_outcome_policy':'report_insufficient'},
            'comparison':{'group_by':['evaluation_case_id','tags.dataset','tags.task_kind'],
                'repetition_aggregation':'mean','aggregation':'macro_mean','baseline_method':'difference',
                'gates':[{'metric':'run_failure_rate','target':'absolute','candidate_ids':None,'for_metric':None,
                    'operator':'le','threshold':0,'scope':'aggregate'},
                    {'metric':'scored_coverage','target':'absolute','candidate_ids':None,'for_metric':primary,
                        'operator':'ge','threshold':1,'scope':'aggregate'}]},
            'failure_policy':{'partial_results':'include','invalid_result_policy':'report'}}
