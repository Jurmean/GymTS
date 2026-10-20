from gymts.contracts.schema import OBJECT, STRING, array, obj
from gymts.plugin_support import component

def register_gymnasium_plugins(registries,schemas):
    from .environment import GymnasiumEnvironment
    schemas.register('gymts.gymnasium/source/1',obj({'kind':{'const':'simulator'},'locator':STRING,
        'revision':STRING,'connection':obj({}),'credential_ref':{'type':'null'}}))
    schemas.register('gymts.gymnasium/mapping/1',obj({}))
    schemas.register('gymts.gymnasium/options/1',obj({'env_id':STRING,'kwargs':OBJECT,
        'expected_gymnasium_version':STRING,'public_info_keys':array(STRING,uniqueItems=True)}))
    manifest={'component_ref':component('gymnasium'),'protocol_versions':['gymts.environment/1'],
        'params_schema_ref':None,'origin_ref':None,'source_schema_ref':'gymts.gymnasium/source/1',
        'mapping_schema_ref':'gymts.gymnasium/mapping/1','options_schema_ref':'gymts.gymnasium/options/1'}
    registries.environments.register(manifest,GymnasiumEnvironment,describe=GymnasiumEnvironment.describe_spec,
        compatibility=GymnasiumEnvironment.compatibility)
