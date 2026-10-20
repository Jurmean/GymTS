"""Explicit model-specific supervised rendering, separate from source decoding."""
import copy

from gymts_timeseries.task import make_task_input

from .data import export_sft as export_legacy_sft
from .neutral_candidate import encode_input


def export_sft(gym, imported, output_dir, eval_fraction=0.2, seed=7):
    source = gym.artifacts.read_json(imported["snapshot_ref"])
    private = gym.artifacts.read_json(imported["private_ref"])
    gold = {row["sample_token"]: row for row in private["samples"]}
    rendered = []
    for sample in source["samples"]:
        truth = gold[sample["sample_token"]]
        value = make_task_input(sample, truth["task_id"], truth["task_version"])
        rendered.append({"sample_token": sample["sample_token"], "task_id": truth["task_id"],
            "task_version": truth["task_version"], "model_input": encode_input(value, native=True)})
    # The existing supervised exporter retains its original model-specific row
    # contract. This is an explicit rendering artifact, never a Source payload.
    snapshot_ref = gym.artifacts.save_json({"schema_version": "gymts.chatts.snapshot/1",
        "dataset_revision": imported["dataset_revision"], "samples": rendered}, "gymts.chatts.snapshot/1")
    view = copy.deepcopy(imported)
    view["snapshot_ref"] = snapshot_ref
    return export_legacy_sft(gym, view, output_dir, eval_fraction=eval_fraction, seed=seed)
