"""Provider-specific config schemas; no Prometheus names enter the core."""
from gymts.contracts.schema import ARTIFACT, OBJECT, STRING, nullable, obj
from gymts.plugin_support import component

SOURCE = "gymts.prometheus/source/1"
MAPPING = "gymts.prometheus/mapping/1"
OPTIONS = "gymts.prometheus/options/1"
CONTEXT = "gymts.prometheus/session/1"
HTTP = "gymts.prometheus/http-evidence/1"


def register_prometheus(registries, schemas):
    from .environment import PrometheusEnvironment
    query = obj({"expression": STRING,
        "labels": {"type": "object", "additionalProperties": STRING}}, required=["expression"])
    schemas.register(SOURCE, obj({"kind": {"const": "live"}, "locator": STRING,
        "revision": nullable(STRING), "credential_ref": {"type": "null"},
        "connection": obj({"base_url": STRING,
            "queries": {"type": "object", "minProperties": 1, "additionalProperties": query},
            "timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
            "token_env": STRING}, required=["base_url", "queries"])}))
    schemas.register(MAPPING, obj({"variables": {"type": "object", "minProperties": 1,
        "additionalProperties": obj({"unit": STRING})}}))
    schemas.register(OPTIONS, obj({"entity": STRING,
        "step_seconds": {"type": "number", "exclusiveMinimum": 0},
        "max_response_bytes": {"type": "integer", "minimum": 1024}}, required=["step_seconds"]))
    schemas.register(CONTEXT, OBJECT)
    schemas.register(HTTP, OBJECT)
    registries.environments.register({"component_ref": component("prometheus-live"),
        "protocol_versions": ["gymts.environment/1"], "params_schema_ref": None, "origin_ref": None,
        "source_schema_ref": SOURCE, "mapping_schema_ref": MAPPING, "options_schema_ref": OPTIONS},
        PrometheusEnvironment)
