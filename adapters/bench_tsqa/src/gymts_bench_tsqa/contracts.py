"""Neutral, lossless public benchmark questions and private reference contracts."""
from gymts.contracts.schema import OBJECT, STRING, array, nullable, obj
from .parsing import KINDS, PARSER_REF, PROJECTION_REF

PROTOCOL = 'gymts.task/tsqa-benchmark/1'
PUBLIC = 'gymts.tsqa/public-sample/1'
SNAPSHOT = 'gymts.tsqa/snapshot/1'
INPUT = 'gymts.tsqa/input/1'
OUTPUT = 'gymts.tsqa/output/1'
RESULT = 'gymts.tsqa/result/1'
OUTCOME = 'gymts.tsqa/outcome/1'
ALIGNMENT = 'gymts.tsqa/alignment/1'
CONTEXT = 'gymts.tsqa/context/1'
TOKEN = 'gymts.tsqa/sample-id/1'
TASK_PARAMS = 'gymts.tsqa/task-params/1'


def domain_schemas():
    token = {'type':'string','pattern':'^[0-9a-f]{64}$'}
    series = obj({'name':STRING,'values':array({'type':'number'},minItems=1)})
    choice = obj({'id':STRING,'text':STRING})
    projection = obj({'series_index':{'type':'integer','minimum':0},
        'original_start':{'type':'integer','minimum':0}, 'original_end':{'type':'integer','minimum':0},'reference':STRING})
    public = obj({'sample_id':token,'dataset_id':STRING,'source_row':{'type':'integer','minimum':0},
        'task_kind':{'enum':list(KINDS)},'question_original':STRING,'question':STRING,
        'series':array(series,minItems=1),'choices':array(choice),'attachment_projection':array(projection),
        'projection_ref':{'const':PROJECTION_REF},'context':OBJECT})
    known = lambda kind,answer: obj({'reference_status':{'const':'known'},'reference_answer':answer,
        'reference_kind':{'const':kind},'reason':{'type':'null'}})
    outcome = {'anyOf':[known('mcq_label',{'type':'string','pattern':'^[A-F]$'}),
        known('boolean',{'enum':['True','False']}),
        known('text_choice',{'type':'string','pattern':'^choice_[1-4]$'}),
        obj({'reference_status':{'const':'unknown'},'reference_answer':{'type':'null'},
            'reference_kind':{'enum':list(KINDS)},'reason':STRING})]}
    return {PUBLIC:public, INPUT:public, SNAPSHOT:obj({'dataset_revision':STRING,'samples':array(public,minItems=1)}),
        OUTPUT:obj({'raw_text':{'type':'string'},'evidence':OBJECT}),
        RESULT:obj({'raw_text':{'type':'string'},'parsed':nullable(obj({'answer':{'type':'string'}})),
            'reason':nullable(STRING),'parser_ref':{'const':PARSER_REF}}), OUTCOME:outcome,
        ALIGNMENT:obj({'dataset_revision':STRING,'sample_id':token}), TOKEN:token,
        CONTEXT:obj({'dataset_revision':STRING,'sample_count':{'type':'integer','minimum':1}}),
        TASK_PARAMS:obj({'task_kind':{'enum':list(KINDS)}})}
