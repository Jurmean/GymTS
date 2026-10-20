"""Register neutral contracts without importing any external environment project."""
from gymts.contracts.schema import OBJECT, array, obj
from gymts.plugin_support import component
from .contracts import ALIGNMENT, INPUT, OUTPUT, PROTOCOL, RESULT, domain_schemas

def register_interaction_plugins(registries,schemas):
    from .candidate import FixedCandidate, SequenceCandidate
    from .scoring import EpisodeScorer, METRICS
    from .task import ControlTask
    for name,schema in domain_schemas().items(): schemas.register(name,schema)
    schemas.register('gymts.interaction/empty/1',obj({}))
    schemas.register('gymts.interaction/fixed-params/1',obj({'action':OBJECT}))
    schemas.register('gymts.interaction/sequence-params/1',obj({'actions':array(OBJECT,minItems=1),
        'repeat_last':{'type':'boolean'}}))
    def manifest(name,protocols,params):
        return {'component_ref':component(name),'protocol_versions':protocols,'params_schema_ref':params,'origin_ref':None}
    item=manifest('interaction-control',['gymts.task/1',PROTOCOL],'gymts.interaction/empty/1')
    item.update(task_protocol_ref=PROTOCOL,input_schema_ref=INPUT,output_schema_ref=OUTPUT,
        result_schema_ref=RESULT,outcome_schema_ref=None,alignment_schema_ref=ALIGNMENT)
    registries.tasks.register(item,ControlTask,describe=ControlTask.describe_spec,compatibility=ControlTask.compatibility)
    for name,factory,params in [('interaction-fixed',FixedCandidate,'gymts.interaction/fixed-params/1'),
            ('interaction-sequence',SequenceCandidate,'gymts.interaction/sequence-params/1')]:
        item=manifest(name,['gymts.candidate/1',PROTOCOL],params)
        item.update(implementation_ref=component('gymts_interaction.candidate.'+factory.__name__,'0.1.0'),
            component_refs=[],supported_task_protocols=[PROTOCOL],input_schema_refs=[INPUT],
            output_schema_refs=[OUTPUT],supports_fit=False,fit_requires_targets=False,supports_update=False,
            model_revision_mode='fixed',capture_profiles=[])
        registries.candidates.register(item,factory)
    item=manifest('interaction-episode-scorer',['gymts.scorer/1'],'gymts.interaction/empty/1')
    item.update(supported_task_protocols=[PROTOCOL],supported_alignment_matchings=['exact'],
        result_schema_refs=[RESULT],outcome_schema_refs=[],metrics={metric:{
            'direction':'lower_better' if metric in ('episode_length','truncated','scope_limited') else 'higher_better',
            'unit':'reward' if metric=='episode_return' else 'steps' if metric=='episode_length' else 'ratio',
            'requires_outcome':False,'eligibility_ref':component('one-planned-interaction-episode'),
            'eligibility_schema_ref':ALIGNMENT} for metric in METRICS})
    registries.scorers.register(item,EpisodeScorer)
