"""Versioned dataset assets and reusable benchmark definitions.

These are resource protocols, not another execution or evaluation engine.
"""
from .schema import ARTIFACT, COMPONENT, OBJECT, STRING, array, nullable, obj

ASSET = "gymts.dataset-asset/1"
DATASET = "gymts.source-dataset/1"
DATASET_V2 = "gymts.source-dataset/2"
DATA_SOURCE = "gymts.data-source/1"
CAPTURE_ROW = "gymts.data-capture-row/1"
DATA_CAPTURE = "gymts.data-capture/1"
SOURCE_KINDS = ("static", "synthetic", "simulation", "live_testbed")
BENCHMARK = "gymts.autobench.benchmark/1"
POLICY = "gymts.source-usage-policy/1"
PROVENANCE = "gymts.resource-provenance/1"


def resource_schemas():
    asset = obj({"uri": STRING, "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                 "size_bytes": {"type": "integer", "minimum": 0}, "media_type": STRING})
    split = obj({"row_count": {"type": "integer", "minimum": 0}, "split_origin": STRING,
                 "input_indices": array({"type": "integer", "minimum": 0}, uniqueItems=True),
                 "target_indices": array({"type": "integer", "minimum": 0}, uniqueItems=True)})
    policy = obj({"allowed_uses": array({"enum": ["runtime", "evaluation", "training", "prepare", "dataset_build"]},
                                     minItems=1, uniqueItems=True), "training_allowed": {"type": "boolean"}})
    dataset = obj({"protocol_version": {"const": DATASET}, "dataset_id": STRING, "config": STRING,
                   "revision": STRING, "schema_ref": STRING, "reader_ref": COMPONENT, "features": OBJECT,
                   "splits": {"type": "object", "minProperties": 1, "additionalProperties": split},
                   "usage_policy": policy,
                   "source_files": array(obj({"name": STRING, "asset_ref": asset})),
                   "importer_ref": COMPONENT, "inputs": array(asset), "series": array(asset),
                   "targets": array(asset), "quality_report_ref": nullable(asset), "card_ref": nullable(asset)})
    dataset_ref = obj({"dataset_id": STRING, "config": STRING, "revision": STRING, "split": STRING})
    source_ref = obj({"source_id": STRING, "config": STRING, "revision": STRING})
    source = obj({"protocol_version": {"const": DATA_SOURCE}, "source_id": STRING, "config": STRING,
                  "revision": STRING, "kind": {"enum": list(SOURCE_KINDS)}, "provider_ref": COMPONENT,
                  "configuration": OBJECT, "recipe": nullable(OBJECT),
                  "reproducibility": obj({"mode": {"enum": ["snapshot", "seeded", "recorded"]},
                                           "seed": nullable({"type": "integer", "minimum": 0})}),
                  "usage_policy": policy, "parent_datasets": array(dataset_ref), "card_ref": nullable(asset)})
    dataset_v2 = obj({**dataset["properties"], "protocol_version": {"const": DATASET_V2},
                      "kind": {"enum": list(SOURCE_KINDS)},
                      "origin": obj({"source_ref": source_ref, "source_definition": asset}),
                      "lineage": obj({"parents": array(dataset_ref), "parent_manifests": array(asset),
                                      "capture": nullable(asset)}), "attachments": array(asset)})
    capture_row = obj({"event_id": STRING, "seq": {"type": "integer", "minimum": 0}, "kind": STRING,
                       "source_event_time": nullable({"anyOf": [STRING, {"type": "number"}]}),
                       "links": OBJECT, "value": OBJECT})
    capture = obj({"protocol_version": {"const": DATA_CAPTURE}, "run_id": STRING, "source_ref": source_ref,
        "source_trace_identity": OBJECT, "through_seq": {"type": "integer", "minimum": 0},
        "event_kinds": array(STRING), "status": {"enum": ["succeeded", "failed", "cancelled"]},
        "completion": STRING, "started_at": STRING, "ended_at": STRING, "requested_scope": OBJECT,
        "session": nullable(OBJECT), "actual_scope": nullable(OBJECT), "seed_used": nullable({"type": "integer"}),
        "ownership": nullable(STRING), "initial_clock": nullable(OBJECT), "last_observation_clock": nullable(OBJECT),
        "observation_count": {"type": "integer", "minimum": 0}, "environment_end": nullable(OBJECT),
        "environment_cleanup": nullable(OBJECT), "evidence_status": STRING})
    benchmark = obj({"protocol_version": {"const": BENCHMARK}, "benchmark_id": STRING, "revision": STRING,
                     "resolver_ref": COMPONENT, "datasets": array(dataset_ref, minItems=1),
                     "params": OBJECT, "card_ref": nullable(asset)})
    provenance = obj({"source_refs": array(ARTIFACT), "usage_policy_ref": nullable(ARTIFACT),
                      "benchmark_definition_ref": nullable(ARTIFACT)})
    return {ASSET: asset, DATASET: dataset, DATASET_V2: dataset_v2, DATA_SOURCE: source,
            CAPTURE_ROW: capture_row, DATA_CAPTURE: capture, BENCHMARK: benchmark, POLICY: policy, PROVENANCE: provenance}


def register_resource_schemas(schemas):
    for ref, definition in resource_schemas().items():
        schemas.register(ref, definition)
