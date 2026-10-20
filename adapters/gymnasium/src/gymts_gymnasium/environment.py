"""Versioned native Gymnasium reset/step with explicit JSON space projection."""
import copy
from gymts.contracts import GymTSError, canonical_json, digest
from gymts.plugin_support import fail
from gymts_interaction.environment import CachedInteractionEnvironment

def _json(value):
    if isinstance(value,dict):
        if any(not isinstance(k,str) for k in value):
            fail('unsupported_capability','JSON observation objects require string keys without coercion')
        return {k:_json(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)): return [_json(v) for v in value]
    if hasattr(value,'tolist'): return _json(value.tolist())
    if hasattr(value,'item'): return _json(value.item())
    if value is None or type(value) in (str,bool,int,float):
        canonical_json(value); return value
    fail('schema_mismatch','Native Gymnasium value has no supported JSON projection')

def _space(space):
    # Bounds may legitimately be infinite; retain them as strings in metadata.
    def bounds(value):
        import numpy as np
        data=np.asarray(value,dtype=object)
        def finite(item):
            if isinstance(item,list): return [finite(v) for v in item]
            number=float(item)
            return number if np.isfinite(number) else 'Infinity' if number>0 else '-Infinity'
        return finite(data.tolist())
    import gymnasium.spaces as spaces
    if isinstance(space,spaces.Discrete):
        return {'type':'Discrete','n':int(space.n),'start':int(space.start)}
    if isinstance(space,spaces.Box):
        return {'type':'Box','shape':list(space.shape),'dtype':str(space.dtype),
            'low':bounds(space.low),'high':bounds(space.high)}
    if isinstance(space,spaces.MultiDiscrete):
        return {'type':'MultiDiscrete','nvec':_json(space.nvec),'start':_json(space.start),'dtype':str(space.dtype)}
    if isinstance(space,spaces.MultiBinary):
        return {'type':'MultiBinary','shape':list(space.shape),'dtype':str(space.dtype)}
    if isinstance(space,spaces.Tuple): return {'type':'Tuple','spaces':[_space(v) for v in space.spaces]}
    if isinstance(space,spaces.Dict): return {'type':'Dict','spaces':{k:_space(v) for k,v in space.spaces.items()}}
    fail('unsupported_capability','Gymnasium space has no lossless supported JSON projection')

def environment_spec(env_id='FrozenLake-v1',*,kwargs=None,version='1.2.1',public_info_keys=()):
    options={'env_id':env_id,'kwargs':copy.deepcopy(kwargs or {}),'expected_gymnasium_version':version,
        'public_info_keys':list(public_info_keys)}
    identity={'gymnasium_version':version,'env_id':env_id,'kwargs':options['kwargs']}
    return {'protocol_version':'gymts.environment/1','adapter':'gymnasium','version':'1.0.0',
        'source':{'kind':'simulator','locator':'gymnasium://'+env_id,'revision':digest(identity),
            'connection':{},'credential_ref':None},'mapping':{},'options':options}

class GymnasiumEnvironment(CachedInteractionEnvironment):
    ADAPTER='gymnasium'

    def __init__(self,spec,services):
        super().__init__(spec,services); self.native=None

    @staticmethod
    def compatibility(context):
        spec=context['experiment']['scene']['environment']; options=spec['options']
        expected=environment_spec(options['env_id'],kwargs=options['kwargs'],
            version=options['expected_gymnasium_version'],public_info_keys=options['public_info_keys'])
        if spec['source']!=expected['source']:
            fail('conflict','Gymnasium source identity must match the versioned make configuration')
        if context['experiment']['execution']['scope']['start']!=0:
            fail('unsupported_capability','Gymnasium episodes start at zero')
        seed=context['experiment']['execution']['seed']
        if seed is not None and seed<0:
            fail('unsupported_capability','Gymnasium requires a nonnegative reset seed')
        if options['kwargs'].get('render_mode') not in (None,'rgb_array'):
            fail('unsupported_capability','Interactive rendering is not an evaluation backend')

    def _public_info(self,value):
        if not isinstance(value,dict): fail('schema_mismatch','Gymnasium info must be an object')
        return {key:_json(value[key]) for key in self.spec['options']['public_info_keys'] if key in value}

    def _reset(self,seed):
        import gymnasium
        options=self.spec['options']
        if gymnasium.__version__!=options['expected_gymnasium_version']:
            fail('conflict','Installed Gymnasium version differs from the fixed source revision')
        self.native=gymnasium.make(options['env_id'],**options['kwargs'])
        observation_space=_space(self.native.observation_space); action_space=_space(self.native.action_space)
        observation,info=self.native.reset(seed=seed)
        native_seed=int(self.native.unwrapped.np_random_seed)
        if seed is not None and native_seed!=seed:
            fail('unsupported_capability','Native Gymnasium reset did not retain the requested seed')
        identity={'gymnasium_version':gymnasium.__version__,'env_id':self.native.spec.id,
            'entry_point':str(self.native.spec.entry_point),'kwargs':copy.deepcopy(options['kwargs']),
            'max_episode_steps':self.native.spec.max_episode_steps,
            'source_revision':self.spec['source']['revision'],
            'native_seed':native_seed,
            'ownership':'created_env_instance','public_info_keys':list(options['public_info_keys'])}
        return {'observation':_json(observation),'info':self._public_info(info),'source_identity':identity,
            'observation_space':observation_space,'action_space':action_space}

    def _action(self,value,space):
        import gymnasium.spaces as spaces
        import numpy as np
        if isinstance(space,spaces.Discrete):
            if type(value) is not int: fail('schema_mismatch','Discrete action requires a JSON integer')
            native=value
        elif isinstance(space,(spaces.Box,spaces.MultiDiscrete,spaces.MultiBinary)):
            if not isinstance(value,list): fail('schema_mismatch','Array action requires a JSON array')
            native=np.asarray(value,dtype=space.dtype)
            if _json(native)!=value:
                fail('schema_mismatch','Native action conversion would change requested values')
        elif isinstance(space,spaces.Tuple):
            if not isinstance(value,list) or len(value)!=len(space.spaces):
                fail('schema_mismatch','Tuple action requires the complete JSON array')
            native=tuple(self._action(v,s) for v,s in zip(value,space.spaces))
        elif isinstance(space,spaces.Dict):
            if not isinstance(value,dict) or set(value)!=set(space.spaces):
                fail('schema_mismatch','Dict action requires the complete exact native fields')
            native={k:self._action(value[k],s) for k,s in space.spaces.items()}
        else: fail('unsupported_capability','Unsupported Gymnasium action space')
        if not space.contains(native): fail('invalid_request','Action is outside the native Gymnasium space')
        return native

    def _step(self,action):
        if set(action)!={'action'}: fail('schema_mismatch','Gymnasium command requires exactly the action field')
        native=self._action(action['action'],self.native.action_space)
        try:
            observation,reward,terminated,truncated,info=self.native.step(native)
            return {'observation':_json(observation),'reward':_json(reward),'terminated':_json(terminated),
                'truncated':_json(truncated),'info':self._public_info(info)}
        except GymTSError as error:
            # Native step has been dispatched. Projection errors must not claim
            # that no side effect occurred; boolean coercion is never a repair.
            raise GymTSError(error.code,str(error),stage='plugin',method='act',side_effect='possible') from error

    def _close(self):
        if self.native is not None:
            self.native.close(); self.native=None
