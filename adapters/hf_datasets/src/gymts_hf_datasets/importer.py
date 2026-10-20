"""Explicit resource preparation through real HF Datasets, outside Run planning.

Only non-executable csv/json/parquet builders are supported. Hub sources name
exact files and an immutable commit; local sources name exact files or a saved
Dataset directory. Original bytes and the transformation recipe are preserved.
"""
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import tempfile

from gymts.contracts import canonical_json, digest
from gymts.environment_ts.datasets import JSONL_READER
from gymts.plugin_support import fail
from .contracts import IMPORTER_REF, PROJECTION, PUBLIC, RESOLVER_REF

EVALUATION_POLICY = {"allowed_uses": ["evaluation"], "training_allowed": False}
FORMATS = {"parquet", "json", "csv"}


def _runtime():
    try:
        import datasets
    except ImportError as error:
        fail("unsupported_capability", "Install gymts-hf-datasets[runtime] for source preparation")
    return datasets


def _file(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        fail("invalid_config", "HF source must consist of explicit regular files, without symlinks")
    return path


def _source(source, cache_dir):
    """Return a materialized HF Dataset, exact original bytes and public recipe."""
    datasets = _runtime()
    if not isinstance(source, dict) or source.get("mode") not in {"hub", "save_to_disk", "local_files"}:
        fail("invalid_config", "Source requires hub, save_to_disk or local_files mode")
    mode, split = source["mode"], source.get("split")
    if not isinstance(split, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", split):
        fail("invalid_config", "Source must name a complete split; select rows explicitly with sample_indices")
    if mode == "save_to_disk":
        if set(source) != {"mode", "path", "split"}:
            fail("invalid_config", "save_to_disk source requires exactly mode/path/split")
        root = Path(source["path"])
        if not root.is_dir() or root.is_symlink():
            fail("invalid_config", "save_to_disk source must name a local dataset directory")
        paths = sorted(root.rglob("*"))
        if any(path.is_symlink() for path in paths):
            fail("invalid_config", "Saved dataset source cannot contain symlinks")
        files = [(path.relative_to(root).as_posix(), _file(path).read_bytes()) for path in paths if path.is_file()]
        if not files:
            fail("invalid_config", "Saved dataset directory is empty")
        # Load the very bytes that will be hashed/published. A user editing the
        # original directory concurrently cannot change the frozen data view.
        with tempfile.TemporaryDirectory(prefix="gymts-hf-saved-") as temporary:
            for name, body in files:
                copied = Path(temporary) / name
                copied.parent.mkdir(parents=True, exist_ok=True)
                copied.write_bytes(body)
            dataset = datasets.load_from_disk(temporary, keep_in_memory=True)
        if isinstance(dataset, datasets.DatasetDict):
            if split not in dataset:
                fail("invalid_config", "Saved DatasetDict does not contain the explicitly requested split")
            dataset = dataset[split]
        elif split != "data":
            fail("invalid_config", "An unsplit saved Dataset must explicitly use split='data'")
        recipe = {"mode": mode, "split": split, "datasets_version": datasets.__version__}
    else:
        expected = {"mode", "format", "files", "split"}
        if mode == "hub":
            expected |= {"repo_id", "revision"}
        if set(source) != expected or source.get("format") not in FORMATS:
            fail("invalid_config", "File sources require exact mode/format/files/split, and hub repo_id/revision")
        names = source["files"]
        if not isinstance(names, list) or not names or any(not isinstance(name, str) for name in names):
            fail("invalid_config", "Source files must be a nonempty explicit ordered list")
        if len(names) != len(set(names)):
            fail("invalid_config", "Duplicate source files are not allowed")
        if mode == "hub":
            revision = source["revision"]
            if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
                fail("invalid_config", "HF Hub source requires a full immutable 40-character commit SHA")
            if any(PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
                   or any(char in name for char in "*?[") for name in names):
                fail("invalid_config", "Hub files must be exact relative paths, without wildcards or parent traversal")
            from huggingface_hub import hf_hub_download
            paths = [Path(hf_hub_download(source["repo_id"], name, repo_type="dataset", revision=revision,
                        cache_dir=str(Path(cache_dir) / "hub"), token=False)) for name in names]
            # Hub cache uses content-addressed symlinks. Read only these paths
            # returned by the Hub client; user-selected local symlinks are rejected.
            files = [(name, path.read_bytes()) for name, path in zip(names, paths)]
            recipe = {"mode": mode, "repo_id": source["repo_id"], "revision": revision,
                      "files": names, "format": source["format"], "split": split,
                      "datasets_version": datasets.__version__}
        else:
            paths = [_file(name) for name in names]
            files = [(str(index) + "-" + path.name, path.read_bytes()) for index, path in enumerate(paths)]
            recipe = {"mode": mode, "format": source["format"], "split": split,
                      "datasets_version": datasets.__version__}
        with tempfile.TemporaryDirectory(prefix="gymts-hf-files-") as temporary:
            copied = []
            for index, (name, body) in enumerate(files):
                path = Path(temporary) / (str(index) + "-" + Path(name).name)
                path.write_bytes(body)
                copied.append(str(path))
            dataset = datasets.load_dataset(source["format"], data_files={split: copied}, split=split,
                keep_in_memory=True, cache_dir=str(Path(cache_dir) / "datasets"))
    if not isinstance(dataset, datasets.Dataset):
        fail("unsupported_capability", "Source preparation requires a materialized HF Dataset")
    recipe["files"] = [{"name": name, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}
                       for name, body in files]
    recipe["hf_features"] = dataset.features.to_dict()
    recipe["source_row_count"] = len(dataset)
    return dataset, files, recipe


def freeze_dataset(gym, dataset_id, source, *, series_column, horizon, context_length,
                   sample_indices=None, config="default", aliases=(), cache_dir="/tmp/gymts-hf-preparation"):
    """Freeze explicit final-tail forecasting views; references are evaluation-only.

    This version intentionally supports evaluation resources only. It does not
    reinterpret official splits or authorize any training source automatically.
    """
    if (not isinstance(series_column, str) or not series_column or type(horizon) is not int or horizon < 1
            or type(context_length) is not int or context_length < 1):
        fail("invalid_config", "Projection needs a series column and positive integer horizon/context_length")
    dataset, files, recipe = _source(source, cache_dir)
    if series_column not in dataset.column_names:
        fail("invalid_config", "HF source does not contain the declared series column")
    indices = list(range(len(dataset))) if sample_indices is None else list(sample_indices)
    if not indices or any(type(index) is not int or index < 0 or index >= len(dataset) for index in indices):
        fail("invalid_config", "Select a nonempty explicit set of valid source rows")
    if len(indices) != len(set(indices)):
        fail("conflict", "Source row selection cannot duplicate observations")
    recipe.update(projection_ref=PROJECTION, series_column=series_column, horizon=horizon,
                  context_length=context_length, sample_indices=indices,
                  selection_policy="explicit_indices" if sample_indices is not None else "all_rows",
                  official_split=source["split"], private_reference_policy="final_horizon_evaluation_only")
    source_identity = digest(recipe)
    public, targets, lengths = [], [], []
    for index in indices:
        values = dataset[index][series_column]
        if not isinstance(values, (list, tuple)) or len(values) < horizon + context_length:
            fail("schema_mismatch", "Every selected series must contain the declared context plus held-out horizon")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
            fail("schema_mismatch", "Selected series values must be finite one-dimensional numeric observations")
        token = digest({"source": source_identity, "source_row": index}).split(":", 1)[-1]
        public.append({"sample_id": token, "dataset_id": dataset_id, "source_row": index,
                       "history": list(values[-(context_length + horizon):-horizon]), "horizon": horizon,
                       "series_column": series_column, "projection_ref": PROJECTION})
        targets.append({"sample_id": token, "values": list(values[-horizon:]), "allowed_uses": ["evaluation"]})
        lengths.append(len(values))
    for row in public:
        gym.schemas.validate(PUBLIC, row)
    catalog = gym.environment_ts.datasets
    def asset(body, media="application/json"):
        return catalog.publish_asset(body, media_type=media)
    def rows(items):
        return asset(b"\n".join(canonical_json(row) for row in items) + b"\n", "application/x-ndjson")
    input_ref, target_ref = rows(public), rows(targets)
    source_files = [{"name": name, "asset_ref": asset(body, "application/octet-stream")} for name, body in files]
    source_files.append({"name": "gymts-freeze-recipe.json", "asset_ref": asset(canonical_json(recipe))})
    quality = {"source_row_count": len(dataset), "selected_row_count": len(public), "source_lengths": lengths,
               "dropped_rows": [], "projection": recipe, "reference_access": "evaluation_only"}
    return catalog.register_dataset({"protocol_version": "gymts.source-dataset/1", "dataset_id": dataset_id,
        "config": config, "revision": None, "schema_ref": PUBLIC, "reader_ref": JSONL_READER,
        "features": {"history": "sequence[number]", "horizon": "int64", "projection_ref": PROJECTION},
        "splits": {"test": {"row_count": len(public), "split_origin": "explicit_evaluation_view_of_" + source["split"],
                            "input_indices": [0], "target_indices": [0]}}, "usage_policy": EVALUATION_POLICY,
        "source_files": source_files, "importer_ref": IMPORTER_REF, "inputs": [input_ref], "series": [],
        "targets": [target_ref], "quality_report_ref": asset(canonical_json(quality)), "card_ref": None}, aliases=aliases)


def register_benchmark(gym, dataset_id, *, revision, benchmark_id=None, config="default", aliases=()):
    return gym.autobench.register_benchmark({"protocol_version": "gymts.autobench.benchmark/1",
        "benchmark_id": benchmark_id or dataset_id, "revision": None, "resolver_ref": RESOLVER_REF,
        "datasets": [{"dataset_id": dataset_id, "config": config, "revision": revision, "split": "test"}],
        "params": {"projection_ref": PROJECTION, "scope": "all_frozen_rows", "metrics": ["mae"]},
        "card_ref": None}, aliases=aliases)
