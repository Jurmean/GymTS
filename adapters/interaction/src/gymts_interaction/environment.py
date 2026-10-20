"""A single-session transition cache; concrete project I/O remains in subclasses.

The backend hooks are called only by start/act/finish. observe never steps or
resets a backend. The class is an external adapter utility, not GymTS core.
"""
import copy
from gymts.contracts import GymTSError, canonical_json, utc_now
from gymts.plugin_support import clock, component, end_info, fail, identifier, payload, unpack
from .contracts import ACTION, CONTEXT, NATIVE, RECEIPT, TOKEN

class CachedInteractionEnvironment:
    ADAPTER='interaction-external'

    @classmethod
    def describe_spec(cls,spec):
        return {'environment_id':cls.ADAPTER,'adapter_ref':component(cls.ADAPTER),
            'clock_domain':'step','observation_granularity':'transition','advance_mode':'on_action',
            'variables':{'state':{'dtype':'int64','shape':[],'unit':'state',
                'time_semantics':'transition_index','schema_ref':TOKEN}},
            'operations':{'act':{'arguments_schema_ref':ACTION,'receipt_schema_ref':RECEIPT,
                'changes_state':True,'idempotent':False}},
            'capabilities':{'range':False,'query':False,'history':False,'reinitialize':True,
                'attach':False,'seed':True,'operation_idempotency':False},
            'context_schema_ref':CONTEXT,'native_schema_ref':NATIVE,'default_command':None}

    def __init__(self,spec,services):
        self.spec=copy.deepcopy(spec); self.services=services
        self.state='created'; self.session=None; self._summary=None; self._pending=None
        self._used=set(); self._counts={k:0 for k in ('batches','points','operations','late_points','dropped_points')}
        self._unconfirmed=set()
        self._reset_attempted=False; self._terminal=None
        self._close_attempted=False; self._close_error=None

    def describe(self): return self.describe_spec(self.spec)

    def _reset(self,seed):
        """Return observation, info, source_identity, observation_space, action_space."""
        raise NotImplementedError

    def _step(self,action):
        """Return observation, reward, terminated, truncated, info as a JSON dict."""
        raise NotImplementedError

    def _close(self): raise NotImplementedError

    def start(self,spec):
        if self.state!='created': fail('invalid_state','Interaction source starts only once')
        if spec['mode']!='reinitialize': fail('unsupported_capability','Interaction adapter creates one new episode')
        if (spec['permitted_variables']!=['state'] or spec['permitted_operations']!=['act']):
            fail('permission_denied','Interaction source requires exact state/act permissions')
        if spec['scope']['start']!=0 or spec['read_scope']['start']!=0:
            fail('unsupported_capability','A new interaction episode begins at step zero')
        self._start=copy.deepcopy(spec); self._reset_attempted=True
        reset=self._reset(spec['seed']); canonical_json(reset)
        if set(reset)!={'observation','info','source_identity','observation_space','action_space'}:
            fail('schema_mismatch','Native reset hook returned an unexpected envelope')
        self.step=0; self.cursor=identifier('cursor'); self.episode=identifier('episode')
        self._pending={'episode_id':self.episode,'step':0,'observation':reset['observation'],'reward':None,
            'terminated':False,'truncated':False,'info':reset['info']}
        self.session={'session_id':identifier('session'),'run_id':spec['run_id'],'environment_id':self.ADAPTER,
            'source_revision':self.spec['source']['revision'],'actual_mode':'reinitialize',
            'actual_scope':copy.deepcopy(spec['scope']),'read_scope':copy.deepcopy(spec['read_scope']),
            'clock':clock(0,'step'),'initial_cursor':self.cursor,'seed_used':spec['seed'],'ownership':'created',
            'public_context':payload(CONTEXT,{key:reset[key] for key in
                ('source_identity','observation_space','action_space')})}
        self.state='active'; return copy.deepcopy(self.session)

    def observe(self,request):
        if self.state not in ('active','exhausted'): fail('invalid_state','Interaction source is not active')
        if request['kind']!='next': fail('unsupported_capability','Interaction source supports next only')
        if request['cursor']!=self.cursor: fail('cursor_mismatch','Interaction cursor is stale')
        if request['variables']!=['state'] or request['entities']!=['episode']:
            fail('permission_denied','Interaction read must select the authorized episode state')
        if self._terminal is not None:
            result=copy.deepcopy(self._terminal); result['request_id']=request['request_id']; return result
        if self._pending is None:
            return {'batch_id':identifier('batch'),'request_id':request['request_id'],'session_id':self.session['session_id'],
                'status':'waiting','cursor':self.cursor,'clock':clock(self.step,'step'),
                'coverage':None,'snapshot_time':None,'data':None,'context':None,'feedback':[],'end':None}
        value=self._pending; self._pending=None; self.cursor=identifier('cursor')
        boundary=self._start['scope']['end']
        unclassified=value.get('backend_done',False) and value.get('end_cause')=='unclassified'
        terminal=value['terminated'] or value['truncated'] or unclassified or boundary is not None and self.step>=boundary
        end=None
        if terminal:
            end=end_info('backend_terminated' if value['terminated'] else 'backend_truncated' if value['truncated'] else
                'source_exhausted' if unclassified else 'read_scope_end',value['terminated'],value['truncated'])
            if unclassified: end['detail']={'reason':'native_done_unclassified'}
        self._counts['batches']+=1; self._counts['points']+=1
        result={'batch_id':identifier('batch'),'request_id':request['request_id'],'session_id':self.session['session_id'],
            'status':'end' if terminal else 'data','cursor':self.cursor,'clock':clock(self.step,'step'),
            'coverage':None,'snapshot_time':self.step,'context':None,'feedback':[],'end':end,
            'data':{'native':payload(NATIVE,copy.deepcopy(value)),'time_series':{'series':[{
                'entity':'episode','variable':'state','unit':'state','timestamps':[self.step],
                'values':[self.step],'valid_mask':[True],'available_at':None}]}}}
        if terminal:
            self.state='exhausted'; self._terminal=copy.deepcopy(result)
            self._terminal.update(data=None,snapshot_time=None)
        return result

    def act(self,command):
        if self.state!='active' or self._terminal is not None: fail('invalid_state','Action after interaction end')
        if command['name']!='act' or command['name'] not in self._start['permitted_operations']:
            fail('permission_denied','Interaction operation is not authorized')
        if self._pending is not None: fail('invalid_state','Consume the pending transition before acting')
        if command['idempotency_key'] is not None:
            fail('unsupported_capability','Native actions do not support idempotent replay')
        identities={command['operation_id'],command['request_id']}
        if self._used & identities: fail('conflict','Interaction operation or request identity was already used')
        boundary=self._start['scope']['end']
        if boundary is not None and self.step>=boundary: fail('permission_denied','Action exceeds execution scope')
        if command['arguments']['schema_ref']!=ACTION:
            fail('schema_mismatch','Interaction action schema differs')
        action=unpack(command['arguments'],self.services)
        if not isinstance(action,dict): fail('schema_mismatch','Interaction actions are JSON objects')
        canonical_json(action)
        # Reserve before native I/O: an uncertain side effect must never be resent.
        self._used.update(identities)
        self._unconfirmed.add(command['operation_id'])
        self.state='uncertain'
        try:
            transition=self._step(copy.deepcopy(action))
        except GymTSError as error:
            if error.info['side_effect']=='none': self._unconfirmed.discard(command['operation_id'])
            else: error.info['links'].setdefault('operation_id',command['operation_id'])
            raise
        except Exception as error:
            raise GymTSError('backend_failure','Native action raised '+type(error).__name__,stage='plugin',
                method='act',side_effect='possible',links={'operation_id':command['operation_id']}) from error
        try:
            self._validate_transition(transition)
        except Exception as error:
            raise GymTSError('schema_mismatch','Native step returned an invalid transition',stage='plugin',
                method='act',side_effect='possible',links={'operation_id':command['operation_id']}) from error
        self.step+=1; self._counts['operations']+=1
        self._pending=dict(transition,episode_id=self.episode,step=self.step)
        self._unconfirmed.discard(command['operation_id'])
        self.state='active'
        return {'receipt_id':identifier('receipt'),'operation_id':command['operation_id'],
            'request_id':command['request_id'],'status':'completed','received_at':utc_now(),
            'payload':payload(RECEIPT,{'step':self.step,'transition_available':True}),'feedback':[]}

    @staticmethod
    def _validate_transition(transition):
        canonical_json(transition)
        required={'observation','reward','terminated','truncated','info'}
        optional={'backend_done','end_cause'}
        if not isinstance(transition,dict) or not required<=set(transition) or set(transition)-required-optional:
            raise ValueError('Unexpected native transition envelope')
        if (transition['reward'] is not None and type(transition['reward']) not in (int,float) or type(transition['terminated']) is not bool
                or type(transition['truncated']) is not bool or not isinstance(transition['info'],dict)):
            raise ValueError('Invalid native transition types')
        if set(transition)&optional:
            if (not optional<=set(transition) or type(transition['backend_done']) is not bool
                    or transition['end_cause'] not in (None,'unclassified')
                    or (transition['end_cause']=='unclassified') != (transition['backend_done']
                        and not transition['terminated'] and not transition['truncated'])
                    or not transition['backend_done'] and (transition['terminated'] or transition['truncated'])):
                raise ValueError('Conflicting backend done and native termination classification')

    def finish(self):
        if self._summary is None:
            refs=[]
            capture_error=None
            if self._pending is not None:
                # A deadline/cancellation can occur after native step and before
                # observe. Retain the unconsumed public state as a declared
                # artifact instead of extending the EnvironmentSummary wire.
                try: refs.append(self.services.save_json(self._pending,NATIVE))
                except Exception as error: capture_error=error
            if self._reset_attempted and not self._close_attempted:
                self._close_attempted=True
                try: self._close()
                except Exception as error: self._close_error=error
            if self._close_error is not None:
                raise GymTSError('backend_failure','Interaction backend cleanup failed',stage='plugin',method='finish',
                    side_effect='possible',links={'pending_operations':sorted(self._unconfirmed),
                        'artifact_refs':refs,'pending_capture_failed':capture_error is not None}) from self._close_error
            if capture_error is not None:
                raise GymTSError('recording_failure','Could not retain an unconsumed native transition',
                    stage='plugin',method='finish',links={'pending_operations':sorted(self._unconfirmed)}) from capture_error
            self._summary={'session_id':self.session['session_id'] if self.session else None,
                'actual_scope':self.session['actual_scope'] if self.session else None,
                'last_cursor':self.cursor if self.session else None,
                'final_clock':clock(self.step,'step') if self.session else None,
                'end':self._terminal['end'] if self._terminal else None,'counts':copy.deepcopy(self._counts),
                'pending_operations':sorted(self._unconfirmed),'artifact_refs':refs,
                'backend_disposition':'closed' if self._reset_attempted else 'not_started'}
        self.state='closed'; return copy.deepcopy(self._summary)
