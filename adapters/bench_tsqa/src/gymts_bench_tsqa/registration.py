"""Optional project registration through public GymTS extension points only."""
from gymts.contracts.schema import ARTIFACT, OBJECT, STRING, array, nullable, obj
from gymts.plugin_support import component
from .contracts import ALIGNMENT, INPUT, OUTCOME, OUTPUT, PROTOCOL, RESULT, TASK_PARAMS, domain_schemas
from .parsing import KINDS

RESOLVER_REF=component('tsqa.full-benchmark')
IMPORTER_REF=component('tsqa-jsonl-importer')


def register_bench_tsqa_plugins(registries,schemas):
    from .environment import TSQASnapshotEnvironment
    from .task import TSQATask
    from .scoring import TSQAReferenceScorer
    from .candidate import FirstChoiceCandidate, TSQAHTTPCandidate
    from .benchmark import TSQABenchmarkResolver
    for ref,definition in domain_schemas().items():
        schemas.register(ref,definition)
    schemas.register('gymts.tsqa/source/1',obj({'kind':{'const':'dataset'},'locator':STRING,'revision':STRING,
        'connection':obj({'artifact_refs':array(ARTIFACT,minItems=1,maxItems=1)}),'credential_ref':{'type':'null'}}))
    schemas.register('gymts.tsqa/empty/1',obj({}))
    schemas.register('gymts.tsqa/source-options/1',obj({'row_count':{'type':'integer','minimum':1},
        'task_kinds':array({'enum':list(KINDS)},minItems=1,uniqueItems=True)}))
    http=obj({'base_url':STRING,'model':STRING,'model_revision':STRING,
        'dialect':{'enum':list(TSQAHTTPCandidate.DIALECTS)},'timeout_seconds':{'type':'number','exclusiveMinimum':0},
        'max_tokens':{'type':'integer','minimum':1},'temperature':{'type':'number','minimum':0},
        'top_p':{'type':'number','exclusiveMinimum':0,'maximum':1},'api_key_env':nullable(STRING),
        'expected_system_fingerprint':nullable(STRING)},required=['base_url','model','model_revision','dialect'])
    schemas.register('gymts.tsqa/http-params/1',http)
    def manifest(name,protocols,params=None):
        return {'component_ref':component(name),'protocol_versions':protocols,'params_schema_ref':params,'origin_ref':None}
    item=manifest('tsqa-snapshot',['gymts.environment/1'])
    item.update(source_schema_ref='gymts.tsqa/source/1',mapping_schema_ref='gymts.tsqa/empty/1',
        options_schema_ref='gymts.tsqa/source-options/1')
    registries.environments.register(item,TSQASnapshotEnvironment,describe=TSQASnapshotEnvironment.describe_spec)
    item=manifest('tsqa-benchmark',['gymts.task/1',PROTOCOL],TASK_PARAMS)
    item.update(task_protocol_ref=PROTOCOL,input_schema_ref=INPUT,output_schema_ref=OUTPUT,result_schema_ref=RESULT,
        outcome_schema_ref=OUTCOME,alignment_schema_ref=ALIGNMENT)
    registries.tasks.register(item,TSQATask,describe=TSQATask.describe_spec,compatibility=TSQATask.compatibility)
    item=manifest('tsqa-reference-scorer',['gymts.scorer/1'],'gymts.tsqa/empty/1')
    item.update(supported_task_protocols=[PROTOCOL],supported_alignment_matchings=['exact'],
        result_schema_refs=[RESULT],outcome_schema_refs=[OUTCOME],metrics={metric:{
            'direction':'higher_better','unit':'ratio','requires_outcome':metric=='accuracy',
            'eligibility_ref':component('one-planned-tsqa-source-row'),'eligibility_schema_ref':ALIGNMENT}
            for metric in ('accuracy','format_valid')})
    registries.scorers.register(item,TSQAReferenceScorer)
    for name,factory,params in (('tsqa-first-choice',FirstChoiceCandidate,'gymts.tsqa/empty/1'),
            ('tsqa-http',TSQAHTTPCandidate,'gymts.tsqa/http-params/1')):
        item=manifest(name,['gymts.candidate/1',PROTOCOL],params)
        item.update(implementation_ref=component('gymts_bench_tsqa.candidate.'+factory.__name__,'0.1.0'),
            component_refs=[component('tsqa.single-answer')],supported_task_protocols=[PROTOCOL],
            input_schema_refs=[INPUT],output_schema_refs=[OUTPUT],supports_fit=False,fit_requires_targets=False,
            supports_update=False,model_revision_mode='fixed',capture_profiles=[])
        registries.candidates.register(item,factory)
    registries.benchmarks.register(RESOLVER_REF,TSQABenchmarkResolver())
