"""Optional Gymnasium environment adapter; discovery does not import Gymnasium."""
from .registration import register_gymnasium_plugins
from .environment import environment_spec

__all__=['register_gymnasium_plugins','environment_spec']
