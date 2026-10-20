"""JSON interaction semantics shared by independent external environment adapters."""
from gymts.contracts.schema import OBJECT, STRING, nullable, obj

PROTOCOL = 'gymts.task/interaction-control/1'
INPUT = 'gymts.interaction/input/1'
OUTPUT = 'gymts.interaction/output/1'
RESULT = 'gymts.interaction/result/1'
ALIGNMENT = 'gymts.interaction/alignment/1'
NATIVE = 'gymts.interaction/state/1'
CONTEXT = 'gymts.interaction/context/1'
ACTION = 'gymts.interaction/action/1'
RECEIPT = 'gymts.interaction/receipt/1'
TOKEN = 'gymts.interaction/state-token/1'
STEP = {'type':'integer','minimum':0}

def domain_schemas():
    state = obj({'episode_id':STRING,'step':STEP,'observation':{},
        'reward':nullable({'type':'number'}),'terminated':{'type':'boolean'},
        'truncated':{'type':'boolean'},'info':OBJECT,
        'backend_done':{'type':'boolean'},'end_cause':nullable({'enum':['unclassified']})},
        required=['episode_id','step','observation','reward','terminated','truncated','info'])
    return {TOKEN:STEP, ACTION:OBJECT,
        RECEIPT:obj({'step':STEP,'transition_available':{'type':'boolean'}}),
        NATIVE:state,
        CONTEXT:obj({'source_identity':OBJECT,'observation_space':OBJECT,'action_space':OBJECT}),
        INPUT:state, OUTPUT:obj({'action':OBJECT}),
        RESULT:obj({'state':state,'action':OBJECT}),
        ALIGNMENT:obj({'episode_id':STRING,'step':STEP})}
