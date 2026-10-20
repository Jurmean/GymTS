"""Native vendored datasets become task-neutral public numerical snapshots."""
from gymts.contracts import GymTSError, digest
from gymts_timeseries.sources import publish_snapshot
from .tools import LibraryTSTools


def load_dataset(gym, implementation, *, dataset="airline", cutoff=None, horizon=12, context_window=None):
    """Separate observed prefix from private future values without choosing a task.

    Source context declares the relative forecast horizon. The same snapshot
    may be bound to another domain Task; the source creates no TaskInput or
    model messages, and its holdout is never inside the public snapshot.
    """
    gym.enable_integration("libraryts")
    tools = LibraryTSTools(gym.artifacts, implementation)
    call = tools.call("dataset.load", {"dataset": dataset})
    native = call["output"]
    values = native["values"]
    if type(horizon) is not int or horizon < 1:
        raise GymTSError("invalid_config", "Dataset horizon must be a positive integer")
    cutoff = len(values) - horizon if cutoff is None else cutoff
    if type(cutoff) is not int or cutoff < 2 or cutoff + horizon > len(values):
        raise GymTSError("invalid_config", "Dataset cutoff must leave observed history and the complete requested holdout")
    if context_window is not None and (type(context_window) is not int or context_window < 2):
        raise GymTSError("invalid_config", "Context window must be an integer >=2")
    start = 0 if context_window is None else max(0, cutoff - context_window)
    facts = {"series": [{"name": native["name"], "values": values[start:cutoff]}],
             "context": {"horizon": horizon},
             "annotations": {"dataset": dataset, "loader": native["loader"], "start_index": start,
                             "cutoff_index": cutoff, "source_revision": native["provenance"]["revision"]}}
    token = digest(facts).removeprefix("sha256:")
    revision = digest({"dataset": dataset, "values": values, "index": native["index"],
                       "library_revision": native["provenance"]["revision"]}).removeprefix("sha256:")
    published = publish_snapshot(gym, [dict(facts, sample_token=token)], revision)
    private_ref = gym.artifacts.save_json({"dataset_revision": revision, "sample_token": token,
        "dataset": dataset, "cutoff_index": cutoff, "values": values[cutoff:cutoff+horizon],
        "source_index": native["index"][cutoff:cutoff+horizon], "allowed_uses": ["evaluation"]},
        "gymts.libraryts/dataset-holdout/1")
    provenance_ref = gym.artifacts.save_json(native["provenance"], "gymts.libraryts/source-provenance/1")
    return dict(published, private_ref=private_ref, provenance_ref=provenance_ref, loader_call_ref=call["call_ref"])
