"""External tutorial package. Importing it does not register a plugin."""

from gymts.contracts.schema import obj
from gymts.plugin_support import component

PROTOCOL = "gymts.task/forecast/1"
INPUT = "gymts.builtin/forecast-input/1"
OUTPUT = "gymts.builtin/forecast-output/1"
PARAMS = "example.minimal/drift-params/1"


def register(registries, schemas):
    from .candidate import DriftCandidate

    schemas.register(PARAMS, obj({"damping": {"type": "number", "minimum": 0, "maximum": 1}}, required=[]))
    registries.candidates.register({
        "component_ref": component("example-drift"),
        "protocol_versions": ["gymts.candidate/1", PROTOCOL],
        "params_schema_ref": PARAMS,
        "origin_ref": None,
        "implementation_ref": component("example.minimal.time-scaled-drift"),
        "component_refs": [],
        "supported_task_protocols": [PROTOCOL],
        "input_schema_refs": [INPUT],
        "output_schema_refs": [OUTPUT],
        "supports_fit": False,
        "fit_requires_targets": False,
        "supports_update": False,
        "model_revision_mode": "none",
        "capture_profiles": [],
    }, DriftCandidate)


__all__ = ["register"]
