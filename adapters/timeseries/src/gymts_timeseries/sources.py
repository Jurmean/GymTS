"""Publish immutable numerical source assets without a task or model dependency."""
import copy
from pathlib import Path

from gymts.contracts import digest

from .contracts import CSV, SNAPSHOT, validate_snapshot


def publish_snapshot(gym, samples, dataset_revision=None):
    revision = dataset_revision or digest(samples).removeprefix("sha256:")
    snapshot = validate_snapshot({"schema_version": SNAPSHOT, "dataset_revision": revision,
                                  "samples": copy.deepcopy(list(samples))})
    ref = gym.artifacts.save_json(snapshot, SNAPSHOT)
    return {"dataset_revision": revision, "snapshot_ref": ref, "sample_tokens": [row["sample_token"] for row in samples]}


def csv_revision(ref, context):
    return digest({"csv_content_hash": ref["content_hash"], "context": context}).removeprefix("sha256:")


def import_csv(gym, path, *, context=None):
    """Import the exact CSV bytes; parsing remains the CSV Environment's job.

    Public context is supplied explicitly, for example a forecast horizon. A
    file import never invents labels, task IDs, train splits or model messages.
    """
    context = copy.deepcopy(context or {})
    ref = gym.artifacts.save_artifact(Path(path).read_bytes(), {"media_type": "text/csv", "schema_ref": CSV})
    return {"dataset_revision": csv_revision(ref, context), "source_ref": ref, "context": context}
