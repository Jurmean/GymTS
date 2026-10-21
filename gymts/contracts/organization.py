"""Project-independent experiment definitions and append-only attempt records."""
from .schema import ARTIFACT, COMPONENT, OBJECT, STRING, array, nullable, obj

GROUP = "gymts.experiment-group/1"
ATTEMPT = "gymts.stage-attempt/1"
EVENT = "gymts.experiment-event/1"
REQUEST = "gymts.stage-request/1"


def register_organization_schemas(schemas):
    dataset = obj({"dataset_id": STRING, "config": STRING, "revision": STRING, "split": STRING})
    source = obj({"source_id": STRING, "config": STRING, "revision": STRING})
    reference = {"oneOf": [
        obj({"kind": {"const": "dataset"}, "ref": dataset}),
        obj({"kind": {"const": "source"}, "ref": source}),
        obj({"kind": {"const": "artifact"}, "ref": ARTIFACT}),
        obj({"kind": {"const": "stage_output"}, "stage_id": STRING, "output": STRING})]}
    stage = obj({"stage_id": STRING, "executor_ref": COMPONENT, "spec": OBJECT,
        "depends_on": array(STRING, uniqueItems=True),
        "purpose": {"enum": ["runtime", "evaluation", "training", "prepare", "dataset_build"]},
        "inputs": {"type": "object", "additionalProperties": reference},
        "bindings": {"type": "object", "additionalProperties": STRING},
        "outputs": {"type": "object", "additionalProperties": {"type": "string"}}})
    schemas.register(GROUP, obj({"protocol_version": {"const": GROUP}, "group_id": STRING,
        "revision": STRING, "name": STRING, "stages": array(stage, minItems=1)}))
    from .resources import PROVENANCE, resource_schemas
    schemas.register(REQUEST, obj({"protocol_version": {"const": REQUEST}, "executor_ref": COMPONENT,
        "purpose": {"enum": ["runtime", "evaluation", "training", "prepare", "dataset_build"]},
        "binding_status": {"enum": ["resolved", "failed"]}, "inputs": OBJECT, "spec": OBJECT,
        "datasets": array(obj({"dataset_id": STRING, "config": STRING, "revision": STRING})),
        "provenance": resource_schemas()[PROVENANCE]}))
    schemas.register(ATTEMPT, obj({"protocol_version": {"const": ATTEMPT}, "attempt_id": STRING,
        "group_id": STRING, "revision": STRING, "stage_id": STRING,
        "ordinal": {"type": "integer", "minimum": 1},
        "status": {"enum": ["running", "succeeded", "failed", "cancelled", "interrupted"]},
        "started_at": STRING, "ended_at": nullable(STRING),
        "definition_ref": ARTIFACT, "request_ref": ARTIFACT,
        "dependencies": {"type": "object", "additionalProperties": STRING},
        "result_ref": nullable(ARTIFACT), "outputs": OBJECT, "error": nullable(OBJECT)}))
    schemas.register(EVENT, obj({"protocol_version": {"const": EVENT}, "group_id": STRING,
        "revision": STRING, "seq": {"type": "integer", "minimum": 1},
        "event_id": STRING, "recorded_at": STRING, "kind": STRING,
        "attempt_id": nullable(STRING), "record_ref": ARTIFACT}))
