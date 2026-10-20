"""Public configuration helpers; execution and evaluation remain owned by GymTS."""
from .contracts import ALIGNMENT
from .semantics import TASK_METRICS


def scene(snapshot_ref, dataset_revision, sample_token, task_id, task_version, *,
          source_adapter="numeric-snapshot", source_options=None):
    return {"environment": {"protocol_version": "gymts.environment/1", "adapter": source_adapter,
        "version": "1.0.0", "source": {"kind": "dataset", "locator": "artifact://public-numeric-source",
            "revision": dataset_revision, "connection": {"artifact_refs": [snapshot_ref]}, "credential_ref": None},
        "mapping": {}, "options": {"sample_tokens": [sample_token], **(source_options or {})}},
        "task": {"plugin": "timeseries-qa", "version": "1.0.0", "params": {"task_id": task_id, "task_version": task_version}},
        "binding": {"variables": {"sample": {"source": "sample", "unit": "sample", "transform": None}}, "operations": {}}}


def scoring(task_id, task_version, *, outcome_views=()):
    return {"scorer": {"adapter": "timeseries-qa-scorer", "version": "1.0.0",
        "params": {"task_id": task_id, "task_version": task_version}},
        "outcomes": {"sources": list(outcome_views), "as_of": None},
        "alignment": {"schema_ref": ALIGNMENT, "keys": ["dataset_revision", "sample_token"],
            "matching": "exact", "params": {}, "duplicate_policy": "error"},
        "metrics": list(TASK_METRICS[task_id]),
        "evidence_requirements": {"min_scored": 1, "min_coverage": 1, "overrides": {}},
        "missing_outcome_policy": "report_insufficient"}
