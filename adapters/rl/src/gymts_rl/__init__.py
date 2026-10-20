"""Optional, verifiable language-model reinforcement-learning rollouts.

Scientific and model dependencies are imported only by explicitly used backends.
"""


def register_rl_plugins(registries, schemas):
    from .registration import register_rl_plugins as register
    return register(registries, schemas)


__all__ = ["register_rl_plugins"]
