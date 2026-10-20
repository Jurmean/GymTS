"""Model-owned codecs: a transparent first-choice baseline and explicit HTTP deployments."""
import copy
import json

from gymts.contracts import utc_now
from gymts.http_candidate import FrozenJSONHTTPCandidate
from gymts.plugin_support import fail, payload, unpack
from .contracts import INPUT, OUTPUT, PROTOCOL


def _input(task_input,resources):
    if task_input['task_protocol_ref']!=PROTOCOL or task_input['payload']['schema_ref']!=INPUT:
        fail('schema_mismatch','Model codec requires the neutral TSQA benchmark input')
    return unpack(task_input['payload'],resources)


class FirstChoiceCandidate:
    """A deliberately trivial baseline. Never receives or reads references."""
    REVISION='tsqa-first-choice/1.0.0'

    def __init__(self,spec):
        self.spec=copy.deepcopy(spec); self.state='created'

    def prepare(self,context,training):
        if self.state!='created':
            fail('invalid_state','First-choice baseline already prepared')
        if (training is not None or context['learning']['prepare']!='load_only'
                or context['learning']['online']!='frozen' or self.spec.get('artifact') is not None
                or self.spec.get('inherited_state')):
            fail('unsupported_capability','First-choice baseline supports frozen load_only inference')
        self.resources=context['resources']; self.state='prepared'
        return {'model_revision':self.REVISION,'state_refs':[],'training_provenance_ref':None}

    def infer(self,task_input):
        if self.state!='prepared':
            fail('invalid_state','First-choice baseline requires prepare')
        sample=_input(task_input,self.resources)
        choices=sample['choices']
        choice=choices[0] if choices else None
        answer=(choice['text'] if sample['task_kind']=='text_choice' else choice['id']) if choice else 'UNRESOLVED'
        return {'input_id':task_input['input_id'],'task_protocol_ref':PROTOCOL,'produced_at':utc_now(),
            'model_revision':self.REVISION,'payload':payload(OUTPUT,{'raw_text':'\\answer{'+answer+'}',
                'evidence':{'algorithm':'first-public-choice','reference_access':False,'model_calls':'not_applicable'}})}

    def update(self,feedback):
        fail('unsupported_capability','First-choice baseline has no online updates')

    def finish(self):
        self.state='closed'; return []


class TSQAHTTPCandidate(FrozenJSONHTTPCandidate):
    TASK_PROTOCOL_REF=PROTOCOL
    OUTPUT_SCHEMA_REF=OUTPUT
    DIALECTS=('text-json-series','chatts-native')
    KIND='tsqa_benchmark_http'
    NORMALIZATION='none'

    def _load_input(self,task_input):
        return _input(task_input,self.resources)

    def _representation_metadata(self):
        return {'question_policy':'original-complete-lossless-series-projection/1',
            'input_numeric_precision':'json-roundtrip-no-truncation','external_weights_verified':False}

    def _wire(self,sample):
        if self.params['dialect']=='chatts-native':
            message=sample['question_original']
        else:
            # Neutral references occur at the original attachment positions. Their
            # values are supplied in full, preserving order, names and precision.
            attachments=[{'reference':projection['reference'],**series}
                for projection,series in zip(sample['attachment_projection'],sample['series'])]
            message=sample['question']+'\n\nReferenced time-series observations (JSON):\n'+json.dumps(
                attachments,ensure_ascii=False,separators=(',',':'),allow_nan=False)
        wire={'model':self.model,'messages':[{'role':'user','content':message}],
            'temperature':self.params['temperature'],'top_p':self.params['top_p'],'max_tokens':self.params['max_tokens'],
            'stream':False}
        if self.params['dialect']=='chatts-native':
            wire['timeseries']=[item['values'] for item in sample['series']]
        return wire
