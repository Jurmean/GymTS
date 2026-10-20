"""Register only the OpenEnv source; tasks/scorers belong to neutral adapters."""
from gymts.contracts.schema import OBJECT, STRING, nullable, obj
from gymts.plugin_support import component
from .environment import AUDIT, OpenEnvEnvironment


def register_openenv_plugins(registries, schemas):
    from gymts_interaction.contracts import domain_schemas
    for ref, schema in domain_schemas().items():
        schemas.register(ref, schema)
    positive = {'type': 'number', 'exclusiveMinimum': 0}
    schemas.register('gymts.openenv/source/1', obj({
        'kind': {'const': 'live'}, 'locator': STRING, 'revision': STRING,
        'connection': obj({'base_url': STRING, 'sdk_version': STRING,
            'deployment_identity': OBJECT, 'connect_timeout_s': positive,
            'message_timeout_s': positive, 'max_message_size_mb': positive}),
        'credential_ref': nullable(STRING)}))
    schemas.register('gymts.openenv/options/1', obj({'reset_options': OBJECT,
        'observation_space': OBJECT, 'action_space': OBJECT}))
    schemas.register('gymts.openenv/empty/1', obj({}))
    schemas.register(AUDIT, obj({'protocol_version': {'const': AUDIT},
        'sequence': {'type': 'integer', 'minimum': 0}, 'transport': STRING,
        'sdk_version': STRING, 'source_revision': STRING,
        'deployment_identity': OBJECT, 'identity_verification': STRING,
        'request': OBJECT, 'response': nullable(OBJECT), 'error': nullable(STRING),
        'duration_s': {'type': 'number', 'minimum': 0}}))
    registries.environments.register({
        'component_ref': component(OpenEnvEnvironment.ADAPTER),
        'protocol_versions': ['gymts.environment/1'], 'params_schema_ref': None,
        'origin_ref': None, 'source_schema_ref': 'gymts.openenv/source/1',
        'mapping_schema_ref': 'gymts.openenv/empty/1',
        'options_schema_ref': 'gymts.openenv/options/1',
    }, OpenEnvEnvironment)
