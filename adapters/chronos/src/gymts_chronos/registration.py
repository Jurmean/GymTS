"""Only public SDK registration; no framework modifications or project defaults."""
from gymts.contracts.schema import OBJECT, STRING, obj
from gymts.plugin_support import component
from gymts_timeseries.contracts import ALIGNMENT, domain_schemas
from .contracts import INPUT, OUTPUT, RESULT, OUTCOME, PROTOCOL, METRICS, UPSTREAM


def register(registries, schemas):
    from .candidate import ChronosCandidate
    from .scoring import DistributionScorer
    from .task import DistributionTask
    for reference, definition in domain_schemas().items():
        schemas.register(reference, definition)
    schemas.register(INPUT, obj({'series': {'type': 'array', 'items': OBJECT, 'minItems': 1}, 'context': OBJECT}))
    schemas.register(OUTPUT, obj({'raw_text': STRING, 'evidence': OBJECT}))
    schemas.register(RESULT, OBJECT)
    schemas.register(OUTCOME, obj({'targets': OBJECT}))
    schemas.register('gymts.chronos/checkpoint-archive/1', OBJECT)
    schemas.register('gymts.chronos/empty/1', obj({}))
    schemas.register('gymts.chronos/params/1', obj({
        'model_dir': STRING, 'model_sha256': STRING, 'python': STRING, 'device': {'enum': ['cpu', 'cuda:0']},
        'timeout_seconds': {'type': 'number', 'exclusiveMinimum': 0},
        'fit': obj({'steps': {'type': 'integer', 'minimum': 1, 'maximum': 10000},
                    'horizon': {'type': 'integer', 'minimum': 1, 'maximum': 512},
                    'context_length': {'type': 'integer', 'minimum': 2},
                    'batch_size': {'type': 'integer', 'minimum': 1},
                    'learning_rate': {'type': 'number', 'exclusiveMinimum': 0}})}, required=['model_dir','python']))
    registries.tasks.register({'component_ref': component('forecast-distribution'),
        'protocol_versions': ['gymts.task/1', PROTOCOL], 'params_schema_ref': 'gymts.chronos/empty/1',
        'origin_ref': None, 'task_protocol_ref': PROTOCOL, 'input_schema_ref': INPUT,
        'output_schema_ref': OUTPUT, 'result_schema_ref': RESULT, 'outcome_schema_ref': OUTCOME,
        'alignment_schema_ref': ALIGNMENT}, DistributionTask)
    registries.candidates.register({'component_ref': component('chronos2'),
        'protocol_versions': ['gymts.candidate/1', PROTOCOL], 'params_schema_ref': 'gymts.chronos/params/1',
        'origin_ref': None, 'implementation_ref': component('amazon-science.chronos-forecasting', UPSTREAM),
        'component_refs': [], 'supported_task_protocols': [PROTOCOL], 'input_schema_refs': [INPUT],
        'output_schema_refs': [OUTPUT], 'supports_fit': True, 'fit_requires_targets': False,
        'supports_update': False, 'model_revision_mode': 'fixed', 'capture_profiles': ['io']}, ChronosCandidate)
    registries.scorers.register({'component_ref': component('distribution-scorer'),
        'protocol_versions': ['gymts.scorer/1'], 'params_schema_ref': 'gymts.chronos/empty/1',
        'origin_ref': None, 'supported_task_protocols': [PROTOCOL], 'supported_alignment_matchings': ['exact'],
        'result_schema_refs': [RESULT], 'outcome_schema_refs': [OUTCOME], 'metrics': {name: {
            'direction': 'higher_better' if name == 'coverage_80' else 'lower_better',
            'unit': 'ratio' if name == 'coverage_80' else 'value', 'requires_outcome': True,
            'eligibility_ref': component('one-planned-forecast-window'), 'eligibility_schema_ref': ALIGNMENT}
            for name in METRICS}}, DistributionScorer)
