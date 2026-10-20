"""Convenience JSON; native GymTS still owns execution and evaluation."""
from gymts_interaction.experiments import evaluation_spec

UPSTREAM_COMMIT = 'f2b00027b63242df33fbbf3af693bbc7cbfa9955'


def echo_evaluation(base_url, *, sdk_version='0.9.1.dev0', steps=3):
    environment = {'protocol_version': 'gymts.environment/1',
        'adapter': 'openenv-websocket', 'version': '1.0.0',
        'source': {'kind': 'live', 'locator': 'OpenEnv official Echo',
            'revision': 'git:' + UPSTREAM_COMMIT,
            'connection': {'base_url': base_url, 'sdk_version': sdk_version,
                'deployment_identity': {'project': 'huggingface/OpenEnv',
                    'commit': UPSTREAM_COMMIT, 'environment': 'echo_env'},
                'connect_timeout_s': 5.0, 'message_timeout_s': 10.0,
                'max_message_size_mb': 10.0}, 'credential_ref': None},
        'mapping': {}, 'options': {'reset_options': {},
            'observation_space': {'type': 'object', 'schema': 'OpenEnv observation envelope'},
            'action_space': {'type': 'object', 'schema': 'OpenEnv CallToolAction'}}}
    candidate = {'adapter': 'interaction-sequence', 'version': '1.0.0',
        'artifact': None, 'inherited_state': [], 'params': {'repeat_last': False,
            'actions': [{'type': 'call_tool', 'tool_name': 'echo_message',
                'arguments': {'message': 'GymTS remote step ' + str(i + 1)}} for i in range(steps)]}}
    result = evaluation_spec(environment, candidate, scope_end=steps, seeds=(None,),
        name='OpenEnv official Echo persistent-session acceptance')
    result['cases'][0]['execution']['seed'] = None
    # MCP Echo supplies no per-action reward. Ask only for metrics supported
    # by its evidence, never fabricate a numeric reward.
    result['scoring']['metrics'] = ['episode_length', 'scope_limited']
    result['comparison']['gates'][1]['for_metric'] = 'episode_length'
    return result


def connect4_evaluation(base_url, *, sdk_version='0.9.1.dev0'):
    result = echo_evaluation(base_url, sdk_version=sdk_version)
    result['name'] = 'OpenEnv official Connect4 persistent-session acceptance'
    case = result['cases'][0]
    environment = case['scene']['environment']
    environment['source']['locator'] = 'OpenEnv official Connect4'
    environment['source']['connection']['deployment_identity']['environment'] = 'connect4_env'
    environment['options']['action_space'] = {'type': 'object', 'schema': 'OpenEnv Connect4Action'}
    case['execution']['scope']['end'] = 10
    case['execution']['limits']['max_turns_per_case'] = 10
    result['candidates'][0]['spec']['params']['actions'] = [
        {'column': column} for column in (0, 1, 0, 1, 0, 1, 0)]
    result['scoring']['metrics'] = ['episode_return', 'episode_length']
    result['comparison']['gates'][1]['for_metric'] = 'episode_return'
    return result
