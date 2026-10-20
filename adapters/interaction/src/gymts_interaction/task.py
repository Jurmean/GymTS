"""Control interpretation; all environment access is requested through Runner."""
import copy
from gymts.contracts import in_scope
from gymts.plugin_support import component, empty_update, fail, identifier, payload, unpack
from .contracts import ACTION, ALIGNMENT, INPUT, NATIVE, OUTPUT, PROTOCOL, RESULT

class ControlTask:
    def __init__(self, spec):
        self.spec = copy.deepcopy(spec)

    @staticmethod
    def describe_spec(spec):
        return {'plugin_ref':component('interaction-control'),'task_protocol_ref':PROTOCOL,
            'input_schema_ref':INPUT,'output_schema_ref':OUTPUT,'result_schema_ref':RESULT,
            'outcome_schema_ref':None,'alignment_schema_ref':ALIGNMENT,
            'required_variables':{'state':{'dtype':'int64','shape':[],'unit':'state'}},
            'required_operations':{'act':{'arguments_schema_ref':ACTION}},
            'required_capabilities':[],'use_default_command':False,
            'warmup':{'duration':None,'min_points':0}}

    @staticmethod
    def compatibility(context):
        env=context['environment']
        if env['native_schema_ref']!=NATIVE or env['advance_mode']!='on_action' or env['clock_domain']!='step':
            fail('unsupported_capability','Interaction control requires step transitions driven by actions')

    def describe(self):
        return self.describe_spec(self.spec)

    def bind(self, spec, binding, environment, execution):
        return ControlSession(binding, execution)

class ControlSession:
    def __init__(self, binding, execution):
        self.binding,self.execution=copy.deepcopy(binding),execution
        self.cursor=execution['session']['initial_cursor']
        self.case_id=identifier('episode-case'); self.step=-1; self.episode=None
        self.started=self.done=False; self.completed=set(); self.inputs=0

    def next_observation(self):
        return {'request_id':identifier('request'),'kind':'next','entities':['episode'],
            'variables':[self.binding['variables']['state']['source']], 'cursor':self.cursor,'max_wait_ms':0}

    def consume(self, batch):
        self.cursor=batch['cursor']; update=empty_update(self.done)
        native=batch['data']['native'] if batch['data'] else None
        if native is not None:
            state=unpack(native,self.execution['data'])
            if state['step']!=self.step+1 or state['step']!=batch['snapshot_time']:
                fail('conflict','Interaction transition index must be consecutive')
            if self.episode is not None and self.episode!=state['episode_id']:
                fail('conflict','An interaction Run cannot silently reset to another episode')
            self.episode=state['episode_id']; self.step=state['step']
            terminal=state['terminated'] or state['truncated'] or state.get('backend_done',False) or batch['status']=='end'
            permitted=in_scope(self.step,self.execution['effective_scope'])
            if not terminal and permitted:
                task_input={'run_id':self.execution['run_id'],'case_id':self.case_id,
                    'turn_id':self.inputs,'input_id':identifier('input'),'task_protocol_ref':PROTOCOL,
                    'decision_time':self.step,'alignment_key':{'episode_id':self.episode,'step':self.step},
                    'observation_refs':[self.execution['data'].observation_ref(batch['batch_id'])],
                    'payload':payload(INPUT,state)}
                update['inputs'].append(task_input); self.started=True; self.inputs+=1
            else:
                self.done=True
        if batch['status']=='end': self.done=True
        if self.done and self.started:
            update['closed_cases'].append({'case_id':self.case_id,'status':'completed','reason':'episode_or_scope_end'})
            self.started=False
        update['done']=self.done
        return update

    def on_action(self, receipt):
        if receipt['status']=='unknown':
            # Runner owns the unknown/possible-side-effect failure and must not
            # lose that information to a Task-level replacement exception.
            return empty_update(self.done)
        if receipt['status']!='completed':
            fail('backend_failure','Synchronous interaction action did not complete')
        return empty_update(self.done)

    def interpret(self, task_input, output, output_id):
        if task_input['input_id'] in self.completed:
            fail('conflict','Interaction input was already interpreted')
        state=unpack(task_input['payload'],self.execution['data'])
        action=unpack(output['payload'],self.execution['data'])['action']
        row={k:copy.deepcopy(task_input[k]) for k in ('run_id','case_id','turn_id','input_id',
            'task_protocol_ref','decision_time','alignment_key')}
        row.update(result_id=identifier('result'),output_id=output_id,status='valid',
            payload=payload(RESULT,{'state':state,'action':copy.deepcopy(action)}))
        self.completed.add(task_input['input_id'])
        return {'results':[row],'requests':[{'kind':'command','request_id':identifier('request'),
            'case_id':self.case_id,'output_id':output_id,'operation':'act',
            'arguments':payload(ACTION,copy.deepcopy(action))}],'complete':False}

    def finish(self, reason):
        return {'cases_started':int(self.inputs>0),'cases_completed':int(self.done and self.inputs>0),
            'cases_incomplete':int(not self.done and self.inputs>0),'pending_requests':[],'artifact_refs':[]}
