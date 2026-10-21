"""Immutable public question snapshots; this source has no access to answers."""
import copy

from gymts.contracts import intersect_scope
from gymts.plugin_support import clock, component, end_info, fail, identifier, payload
from .contracts import CONTEXT, PUBLIC, SNAPSHOT, TOKEN


class ITFormerSnapshotEnvironment:
    @staticmethod
    def describe_spec(spec):
        return {'environment_id':'itformer-snapshot','adapter_ref':component('itformer-snapshot'),
            'clock_domain':'step','observation_granularity':'transition','advance_mode':'on_observe',
            'variables':{'sample':{'dtype':'string','shape':[],'unit':'sample','time_semantics':'sample_index','schema_ref':TOKEN}},
            'operations':{},'capabilities':{'range':False,'query':False,'history':False,
                'reinitialize':True,'attach':False,'seed':True,'operation_idempotency':False},
            'context_schema_ref':CONTEXT,'native_schema_ref':PUBLIC,'default_command':None}

    def __init__(self,spec,services):
        self.spec,self.state=copy.deepcopy(spec),'created'
        refs=spec['source']['connection']['artifact_refs']
        if len(refs)!=1 or refs[0]['schema_ref']!=SNAPSHOT:
            fail('schema_mismatch','ITFormer source requires one public snapshot')
        snapshot=services.read_json(refs[0])
        self.revision=snapshot['dataset_revision']
        self.samples=snapshot['samples']
        if self.revision!=spec['source']['revision'] or len(self.samples)!=spec['options']['row_count']:
            fail('conflict','ITFormer snapshot differs from its fixed source metadata')
        if len({item['sample_id'] for item in self.samples})!=len(self.samples):
            fail('conflict','ITFormer snapshot sample identities must be unique')
        self.session=self._summary=self._terminal=None
        self._counts={key:0 for key in ('batches','points','operations','late_points','dropped_points')}

    def describe(self):
        return self.describe_spec(self.spec)

    def start(self,spec):
        if self.state!='created':
            fail('invalid_state','ITFormer source can only start once')
        if spec['mode']!='reinitialize':
            fail('unsupported_capability','ITFormer source requires reinitialize')
        if set(spec['permitted_variables'])-{'sample'} or spec['permitted_operations']:
            fail('permission_denied','ITFormer source has no requested variable or operation')
        scope=intersect_scope(spec['scope'],{'start':0,'end':len(self.samples)})
        if scope['end'] is None or scope['start']>=scope['end']:
            fail('invalid_config','ITFormer source and execution scope do not overlap')
        self._start=copy.deepcopy(spec)
        self._scope=intersect_scope(spec['read_scope'],{'start':0,'end':len(self.samples)})
        self.position=self.now=self._scope['start']
        self.cursor=identifier('cursor')
        self.session={'session_id':identifier('session'),'run_id':spec['run_id'],'environment_id':'itformer-snapshot',
            'source_revision':self.revision,'actual_mode':'reinitialize','actual_scope':scope,
            'read_scope':copy.deepcopy(self._scope),'clock':clock(self.now,'step'),'initial_cursor':self.cursor,
            'seed_used':spec['seed'],'ownership':'created',
            'public_context':payload(CONTEXT,{'dataset_revision':self.revision,'sample_count':len(self.samples)})}
        self.state='active'
        return copy.deepcopy(self.session)

    def observe(self,request):
        if self.state not in ('active','exhausted'):
            fail('invalid_state','ITFormer source is not active')
        if request['kind']!='next':
            fail('unsupported_capability','ITFormer source supports next only')
        if request['cursor']!=self.cursor:
            fail('cursor_mismatch','ITFormer source cursor does not match')
        if set(request['variables'])-set(self._start['permitted_variables']):
            fail('permission_denied','ITFormer sample read is not permitted')
        if self._terminal is not None:
            batch=copy.deepcopy(self._terminal); batch['request_id']=request['request_id']; return batch
        row=self.samples[self.position]
        self.now=self.position; self.position+=1; self.cursor=identifier('cursor')
        terminal=self.position>=self._scope['end']
        selected='sample' in request['variables'] and 'samples' in request['entities']
        self._counts['batches']+=1; self._counts['points']+=int(selected)
        batch={'batch_id':identifier('batch'),'request_id':request['request_id'],'session_id':self.session['session_id'],
            'status':'end' if terminal else 'data','cursor':self.cursor,'clock':clock(self.now,'step'),
            'coverage':None,'snapshot_time':self.now,
            'data':{'time_series':None,'native':payload(PUBLIC,copy.deepcopy(row))} if selected else None,
            'context':None,'feedback':[],'end':end_info() if terminal else None}
        if terminal:
            self.state='exhausted'; self._terminal=copy.deepcopy(batch); self._terminal.update(data=None,snapshot_time=None)
        return batch

    def act(self,command):
        fail('unsupported_capability','ITFormer source has no environment actions')

    def finish(self):
        if self._summary is None:
            self._summary={'session_id':self.session['session_id'] if self.session else None,
                'actual_scope':self.session['actual_scope'] if self.session else None,
                'last_cursor':self.cursor if self.session else None,'final_clock':clock(self.now,'step') if self.session else None,
                'end':self._terminal['end'] if self._terminal else None,'counts':copy.deepcopy(self._counts),
                'pending_operations':[],'artifact_refs':[],'backend_disposition':'closed' if self.session else 'not_started'}
        self.state='closed'; return copy.deepcopy(self._summary)
