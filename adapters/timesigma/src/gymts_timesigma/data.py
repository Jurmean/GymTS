"""Freeze genuine local EasyTSAD arrays into separate training/test/gold artifacts.

No transforms, windows, fitting or label-based selection happen here. NumPy is
an optional import dependency; importing/registering the integration needs none.
"""
import hashlib
import io
import json
import math
from pathlib import Path
import re

from gymts.contracts import GymTSError, canonical_json, inline
from .contracts import (IMPORT_MANIFEST, PRIVATE, SCHEMAS, SNAPSHOT, TRAINING,
                        validate, validate_unit)

EASYTSAD_REVISION = "e7be92374a4543d7c52d6e34ef7047f4d6776be0"
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _error(message, **details):
    return GymTSError("invalid_dataset", message, stage="dataset_import", details=details)


def _sha(value):
    return "sha256:" + hashlib.sha256(value if isinstance(value, bytes) else canonical_json(value)).hexdigest()


def _name(value, label):
    if not isinstance(value, str) or not _NAME.fullmatch(value) or value in (".", ".."):
        raise _error(label + " must be a local opaque identifier")
    return value


def _numpy():
    try:
        import numpy
        return numpy
    except ImportError as exc:
        raise GymTSError("unsupported_capability", "Importing EasyTSAD .npy data requires optional NumPy") from exc


def _read(path, np, *, labels=False):
    if path.is_symlink() or not path.is_file():
        raise _error("EasyTSAD arrays must be regular local files", filename=path.name)
    raw = path.read_bytes()
    try:
        values = np.load(io.BytesIO(raw), allow_pickle=False)
    except (ValueError, OSError, EOFError) as exc:
        raise _error("Cannot load a finite numeric EasyTSAD array", filename=path.name) from exc
    if values.ndim != 1 or not values.size or values.dtype.kind not in ("biuf" if labels else "iuf") or not np.isfinite(values).all():
        raise _error("EasyTSAD arrays must be nonempty, finite, one-dimensional numeric arrays", filename=path.name)
    if labels and not np.isin(values, [0, 1]).all():
        raise _error("Evaluation labels must be binary", filename=path.name)
    return values, {"digest": _sha(raw), "dtype": str(values.dtype), "length": len(values), "size_bytes": len(raw)}


def _load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    if path.is_symlink() or not path.is_file():
        raise _error("Frozen membership must be a regular local JSON file")
    try:
        return json.loads(path.read_bytes(), object_pairs_hook=unique,
                          parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
    except (ValueError, UnicodeError) as exc:
        raise _error("Frozen membership is not strict finite JSON") from exc


def native_zero_shot_split(dataset, members, *, membership_path=None):
    """Preserve the pinned native dict_split shuffle/ceil rule, seed=1, p=.5.

    A supplied canonical Memory file remains authoritative for its member order.
    Otherwise the enumerated source names are frozen before the native shuffle;
    a private RandomState reproduces np.random.seed(1)/shuffle without touching
    the host process's global RNG state.
    """
    np = _numpy()
    if membership_path is not None:
        path = Path(membership_path).expanduser().resolve()
        document = _load_json(path)
        if document.get("schema") != "zero_shot" or document.get("dataset_type") != "UTS":
            raise _error("Frozen membership has an incompatible native Schema")
        matches = [row for row in document.get("datasets", []) if isinstance(row, dict) and row.get("dataset") == dataset]
        if len(matches) != 1:
            raise _error("Frozen membership must contain exactly one selected dataset")
        split = matches[0]
        for key in ("enumerated_curves", "training_curves", "held_out_curves"):
            values = split.get(key)
            if not isinstance(values, list) or not values or any(not isinstance(v, str) for v in values) or len(set(values)) != len(values):
                raise _error("Frozen membership lists must be nonempty and unique")
        fitted, evaluated, preprocessed = (split[key] for key in ("training_curves", "held_out_curves", "enumerated_curves"))
        if (type(split.get("random_seed")) is not int or split["random_seed"] != 1 or
                isinstance(split.get("proportion"), bool) or split.get("proportion") != .5 or
                set(preprocessed) != set(members) or set(fitted) & set(evaluated) or
                set(fitted) | set(evaluated) != set(members)):
            raise _error("Frozen membership differs from the source or pinned seed/proportion")
        provenance = {"kind": "frozen_native_membership_file", "digest": _sha(path.read_bytes())}
    else:
        preprocessed = list(members)
        order = list(members)
        np.random.RandomState(1).shuffle(order)
        boundary = math.ceil(.5 * len(order))
        fitted, evaluated = order[:boundary], order[boundary:]
        if not fitted or not evaluated:
            raise _error("ZERO_SHOT requires both training and held-out members")
        provenance = {"kind": "native_dict_split_on_frozen_enumeration"}
    return {"dataset": dataset, "enumerated_curves": list(preprocessed), "training_curves": list(fitted),
            "held_out_curves": list(evaluated), "random_seed": 1, "proportion": .5,
            "implementation": "EasyTSAD.TrainingSchema.ZeroShot.dict_split", "easytsad_revision": EASYTSAD_REVISION,
            "provenance": provenance}


def import_dataset(gym, dataset_root, *, dataset="TODS", schema="naive", curve_id=None,
                   source_repo=None, zero_shot_membership=None, seed=1):
    """Import one complete native planning unit without exposing private labels.

    dataset_root is the EasyTSAD root containing UTS/<dataset>. Existing .npy
    bytes are hashed and retained in a manifest; values and original dtype are
    copied into content-addressed JSON. No source filesystem path reaches the
    public training/test payloads. training_ref is an ArtifactRef; use an
    explicit purpose=prepare DataViewRef to authorize fitting.
    """
    np = _numpy()
    _name(dataset, "dataset")
    if schema not in SCHEMAS or type(seed) is not int or seed != 1:
        raise _error("Use a native Schema and the pinned seed=1")
    root = Path(dataset_root).expanduser().resolve()
    directory = root / "UTS" / dataset
    if not directory.is_dir() or directory.is_symlink() or (root / "UTS").is_symlink():
        raise _error("Expected a local EasyTSAD UTS/<dataset> directory")
    member_paths = sorted(path for path in directory.iterdir() if path.is_dir())
    if not member_paths or any(path.is_symlink() for path in member_paths):
        raise _error("Dataset must contain regular curve directories")
    members = [_name(path.name, "curve") for path in member_paths]
    arrays, files, paths = {}, {}, {}
    for curve in members:
        arrays[curve] = {}
        for phase in ("train", "test"):
            path = directory / curve / (phase + ".npy")
            arrays[curve][phase], record = _read(path, np)
            key = curve + "/" + phase + ".npy"
            files[key], paths[key] = record, path
    split = None
    if schema == "naive":
        selected = curve_id if curve_id is not None else members[0]
        if selected not in members:
            raise _error("NAIVE curve is absent from the selected source")
        training = evaluated = preprocessed = [selected]
    elif schema == "all_in_one":
        if curve_id is not None:
            raise _error("Only NAIVE accepts a single selected curve")
        training = evaluated = preprocessed = list(members)
    else:
        if curve_id is not None:
            raise _error("ZERO_SHOT membership cannot be replaced by a selected curve")
        membership = zero_shot_membership
        if membership is None and source_repo is not None:
            membership = Path(source_repo).expanduser().resolve() / "examples/handoff/sample/agent-memory/zero-shot-membership.json"
        split = native_zero_shot_split(dataset, members, membership_path=membership)
        training, evaluated, preprocessed = (split[key] for key in ("training_curves", "held_out_curves", "enumerated_curves"))
    dataset_revision = _sha({"dataset": dataset, "raw_arrays": files})
    planning_unit_id = _sha({"dataset_revision": dataset_revision, "schema": schema,
        "training_members": training, "evaluation_members": evaluated, "preprocessing_members": preprocessed})
    common = {"dataset_revision": dataset_revision, "planning_unit_id": planning_unit_id, "dataset": dataset,
              "schema": schema, "training_members": training, "evaluation_members": evaluated,
              "preprocessing_members": preprocessed}
    def series(selected, phase):
        return [{"curve_id": curve, "values": arrays[curve][phase].tolist(), "dtype": str(arrays[curve][phase].dtype)} for curve in selected]
    training_data = {**common, "curves": series(preprocessed, "train")}
    snapshot = {**common, "curves": series(evaluated, "test")}
    validate_unit(training_data, training=True)
    validate_unit(snapshot)
    gold, label_files = [], {}
    for curve in evaluated:
        path = directory / curve / "test_label.npy"
        labels, record = _read(path, np, labels=True)
        if len(labels) != len(arrays[curve]["test"]):
            raise _error("Labels must cover the complete original test curve")
        key = curve + "/test_label.npy"
        label_files[key], paths[key] = record, path
        gold.append({"curve_id": curve, "labels": labels.astype(int).tolist()})
    private = {"dataset_revision": dataset_revision, "planning_unit_id": planning_unit_id,
        "outcome": {"dataset_revision": dataset_revision, "planning_unit_id": planning_unit_id, "curves": gold},
        "provenance": {"source_kind": "published_or_user_local_ground_truth", "label_files": label_files}}
    validate(PRIVATE, private)
    # Confirm all inputs again before publishing any apparently complete import.
    for key, path in paths.items():
        if _sha(path.read_bytes()) != (files.get(key) or label_files[key])["digest"]:
            raise _error("Source changed during dataset import")
    training_ref = gym.artifacts.save_json(training_data, TRAINING)
    snapshot_ref = gym.artifacts.save_json(snapshot, SNAPSHOT)
    private_ref = gym.artifacts.save_json(private, PRIVATE)
    manifest = {**common, "seed": seed, "array_files": files, "zero_shot_split": split,
        "native_validation": {"train_proportion": 1, "valid_proportion": .2, "arrays_are_unsplit": True},
        "normalization_visibility": {"raw_train_members": preprocessed, "model_fit_members": training,
            "heldout_train_use": "native_per_curve_preprocessing_only" if schema == "zero_shot" else "none",
            "strict_inductive_zero_shot": False if schema == "zero_shot" else None},
        "training_ref": training_ref, "snapshot_ref": snapshot_ref, "private_ref": private_ref}
    manifest_ref = gym.artifacts.save_json(manifest, IMPORT_MANIFEST)
    return {**common, "training_ref": training_ref, "snapshot_ref": snapshot_ref, "private_ref": private_ref,
            "manifest_ref": manifest_ref}


def training_view(imported):
    """Make the explicit preparation capability without adding private sources."""
    reference = imported["training_ref"]
    return {"view_id": "timesigma-training-" + imported["planning_unit_id"], "revision": reference["revision"],
        "source_refs": [reference], "selection": inline({"kind": "all", "source_index": 0}, "gymts.selection/1"),
        "as_of": None, "purpose": "prepare"}
