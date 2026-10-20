"""Preserve source questions, choices and conditions; interpret responses only."""
import copy

from gymts.contracts import in_scope
from gymts.plugin_support import component, empty_update, fail, identifier, payload, unpack
from .contracts import ALIGNMENT, INPUT, OUTCOME, OUTPUT, PROTOCOL, PUBLIC, RESULT
from .parsing import KINDS, PARSER_REF, parse_response


class TSQATask:
    def __init__(self,spec):
        self.kind=spec['params']['task_kind']

    @staticmethod
    def describe_spec(spec):
        if spec['params']['task_kind'] not in KINDS:
            fail('unsupported_capability','Unknown TSQA response interpretation')
        return {'plugin_ref':component('tsqa-benchmark'),'task_protocol_ref':PROTOCOL,
            'input_schema_ref':INPUT,'output_schema_ref':OUTPUT,'result_schema_ref':RESULT,
            'outcome_schema_ref':OUTCOME,'alignment_schema_ref':ALIGNMENT,
            'required_variables':{'sample':{'dtype':'string','shape':[],'unit':'sample'}},
            'required_operations':{},'required_capabilities':[],'use_default_command':False,
            'warmup':{'duration':None,'min_points':0}}

    @staticmethod
    def compatibility(context):
        experiment=context['experiment']
        kinds=experiment['scene']['environment']['options'].get('task_kinds')
        kind=experiment['scene']['task']['params']['task_kind']
        if context['environment']['native_schema_ref']!=PUBLIC or kinds!=[kind]:
            fail('unsupported_capability','TSQA Task requires matching declared public question kinds')

    def describe(self):
        return self.describe_spec({'params':{'task_kind':self.kind}})

    def bind(self,spec,binding,environment,execution):
        if environment['native_schema_ref']!=PUBLIC or environment['clock_domain']!='step':
            fail('unsupported_capability','TSQA Task requires public question samples on a step clock')
        return TSQASession(self.kind,binding,execution)


class TSQASession:
    def __init__(self,kind,binding,execution):
        self.kind,self.binding,self.execution=kind,copy.deepcopy(binding),execution
        self.cursor=execution['session']['initial_cursor']
        self.revision=unpack(execution['session']['public_context'],execution['data'])['dataset_revision']
        self.done=False; self.seen=set(); self.completed=set()
        self.counts={key:0 for key in ('cases_started','cases_completed','cases_incomplete','results_valid','results_invalid')}

    def next_observation(self):
        return {'request_id':identifier('request'),'kind':'next','entities':['samples'],
            'variables':[self.binding['variables']['sample']['source']],'cursor':self.cursor,'max_wait_ms':0}

    def consume(self,batch):
        self.cursor=batch['cursor']; update=empty_update(self.done)
        if batch['data'] is not None and batch['data'].get('native') is not None:
            sample=unpack(batch['data']['native'],self.execution['data']); point=batch['snapshot_time']
            if type(point) is not int or point<0:
                fail('schema_mismatch','TSQA source snapshot_time must be a nonnegative step')
            if sample['task_kind']!=self.kind:
                fail('unsupported_capability','Source question kind differs from the fixed TSQA Task')
            token=sample['sample_id']
            if token not in self.seen and not self.done and in_scope(point,self.execution['effective_scope']):
                self.seen.add(token)
                update['inputs'].append({'run_id':self.execution['run_id'],'case_id':identifier('case'),'turn_id':0,
                    'input_id':identifier('input'),'task_protocol_ref':PROTOCOL,'decision_time':point,
                    'alignment_key':{'dataset_revision':self.revision,'sample_id':token},
                    'observation_refs':[self.execution['data'].observation_ref(batch['batch_id'])],
                    'payload':payload(INPUT,copy.deepcopy(sample))})
                self.counts['cases_started']+=1
        self.done=self.done or batch['status']=='end'; update['done']=self.done; return update

    def on_action(self,receipt):
        fail('unsupported_capability','TSQA Task has no environment actions')

    def interpret(self,task_input,output,output_id):
        if task_input['input_id'] in self.completed:
            fail('conflict','TSQA input has already been interpreted')
        sample=unpack(task_input['payload'],self.execution['data'])
        raw=unpack(output['payload'],self.execution['data'])['raw_text']
        parsed,reason=parse_response(raw,sample)
        record={key:copy.deepcopy(task_input[key]) for key in (
            'run_id','case_id','turn_id','input_id','task_protocol_ref','decision_time','alignment_key')}
        record.update(result_id=identifier('result'),output_id=output_id,status='valid' if reason is None else 'invalid',
            payload=payload(RESULT,{'raw_text':raw,'parsed':parsed,'reason':reason,'parser_ref':PARSER_REF}))
        self.completed.add(task_input['input_id']); self.counts['cases_completed']+=1
        self.counts['results_valid' if reason is None else 'results_invalid']+=1
        return {'results':[record],'requests':[],'complete':True}

    def finish(self,reason):
        return dict(self.counts,cases_incomplete=self.counts['cases_started']-self.counts['cases_completed'],
            pending_requests=[],artifact_refs=[])
