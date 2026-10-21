"""Optional TimeCopilot adapter; importing/registering it loads no native runtime."""


def register_timecopilot_plugins(registries, schemas):
    from .registration import register_timecopilot_plugins as register
    return register(registries, schemas)
