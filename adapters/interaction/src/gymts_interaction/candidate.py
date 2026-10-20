"""Small policies for conformance checks; production agents implement the same wire."""
import copy
from gymts.contracts import digest, utc_now
from gymts.plugin_support import fail, payload, unpack
from .contracts import OUTPUT, PROTOCOL

class SequenceCandidate:
    def __init__(self,spec):
        self.params=copy.deepcopy(spec['params']); self.index=0

    def prepare(self,context,training):
        if training is not None: fail('unsupported_capability','Sequence control policy does not train')
        self.revision=digest(self.params)
        return {'model_revision':self.revision,'state_refs':[],'training_provenance_ref':None}

    def infer(self,task_input):
        actions=self.params['actions']
        if self.index>=len(actions) and not self.params['repeat_last']:
            fail('invalid_state','Explicit action sequence is exhausted')
        action=copy.deepcopy(actions[min(self.index,len(actions)-1)]); self.index+=1
        return {'input_id':task_input['input_id'],'task_protocol_ref':PROTOCOL,'produced_at':utc_now(),
            'model_revision':self.revision,'payload':payload(OUTPUT,{'action':action})}

    def update(self,feedback): fail('unsupported_capability','Sequence control policy is frozen')
    def finish(self): return []

class FixedCandidate(SequenceCandidate):
    def __init__(self,spec):
        super().__init__({'params':{'actions':[spec['params']['action']],'repeat_last':True}})
