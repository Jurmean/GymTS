"""Versioned dataset assets and reusable benchmark definitions.

These are resource protocols, not another execution or evaluation engine.
"""
from .schema import ARTIFACT, COMPONENT, OBJECT, STRING, array, nullable, obj

ASSET = "gymts.dataset-asset/1"
DATASET = "gymts.source-dataset/1"
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
    benchmark = obj({"protocol_version": {"const": BENCHMARK}, "benchmark_id": STRING, "revision": STRING,
                     "resolver_ref": COMPONENT, "datasets": array(dataset_ref, minItems=1),
                     "params": OBJECT, "card_ref": nullable(asset)})
    provenance = obj({"source_refs": array(ARTIFACT), "usage_policy_ref": nullable(ARTIFACT),
                      "benchmark_definition_ref": nullable(ARTIFACT)})
    return {ASSET: asset, DATASET: dataset, BENCHMARK: benchmark, POLICY: policy, PROVENANCE: provenance}


def register_resource_schemas(schemas):
    for ref, definition in resource_schemas().items():
        schemas.register(ref, definition)
