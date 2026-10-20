"""Real native train-only fitting, frozen scoring and no-fit process replay.

Scientific imports live exclusively in this isolated process. Original Method
classes, checkpoint selection and fitted-artifact loaders are reused unchanged.
"""
import base64
import contextlib
import copy
import hashlib
import importlib
from importlib import metadata
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import sys
import tarfile
import tempfile
import traceback
from types import SimpleNamespace
from unittest.mock import patch

from gymts.contracts import canonical_json
from .contracts import IDENTITY_FIELDS, identity, validate_unit
from .runtime import EASYTSAD_REVISION, SOURCE_REVISION

BUNDLE_SCHEMA = "gymts.timesigma/model-bundle/1"


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(value))


def _component(value):
    if not isinstance(value, str) or not value or value in (".", "..") or any(char in value for char in ("/", "\\", "\x00")):
        raise ValueError("Native dataset/curve identifiers must be opaque single path components")
    return value


def _provenance(source):
    import timesigma
    import EasyTSAD
    actual = Path(timesigma.__file__).resolve()
    if not actual.is_relative_to(Path(source["repository"]).resolve()):
        raise ValueError("The imported TimeSigma module is outside the fixed checkout")
    installed = metadata.distribution("EasyTSAD")
    direct = json.loads(installed.read_text("direct_url.json") or "{}")
    revision = direct.get("vcs_info", {}).get("commit_id")
    if revision is None and direct.get("url", "").startswith("file://"):
        import subprocess
        from urllib.parse import unquote, urlparse
        root = unquote(urlparse(direct["url"]).path)
        result = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=15)
        revision = result.stdout.strip() if result.returncode == 0 else None
    if revision != EASYTSAD_REVISION:
        raise ValueError("EasyTSAD does not identify the fixed substrate revision")
    substrate = Path(EasyTSAD.__file__).resolve().parent
    selected = {"DataFactory/TSData.py", "DataFactory/LoadData.py", "DataFactory/TorchDataSet/PredictWindow.py",
                "Methods/__init__.py", "Methods/AR/__init__.py", "Methods/AR/AR.py", "Methods/AR/config.toml",
                "Exptools/EarlyStoppingTorch.py"}
    selected.update(str(path.relative_to(substrate)) for path in (substrate / "TrainingSchema").rglob("*.py"))
    installed_files = {str(path): path for path in installed.files}
    substrate_hashes = {}
    for relative in sorted(selected):
        raw = (substrate / relative).read_bytes()
        record = installed_files.get("EasyTSAD/" + relative)
        expected = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode()
        if record is None or record.hash is None or record.hash.mode != "sha256" or record.hash.value != expected:
            raise ValueError("EasyTSAD execution source differs from installed RECORD: " + relative)
        substrate_hashes[relative] = _hash(raw)
    native_files = ("algorithms/catalog.py", "algorithms/configuration.py", "algorithms/imports.py",
        "algorithms/checkpoint.py", "algorithms/artifacts.py", "algorithms/isolation_forest/__init__.py",
        "algorithms/isolation_forest/binding.py", "algorithms/isolation_forest/config.toml",
        "benchmark/artifacts.py", "benchmark/runtime.py")
    native_hashes = {name: _hash((actual.parent / name).read_bytes()) for name in native_files}
    return {**source, "pid": os.getpid(), "python_version": platform.python_version(), "device": "cpu",
            "native_file_hashes": {"EasyTSAD": substrate_hashes, "TimeSigma": native_hashes},
            "worker_source_sha256": _hash(Path(__file__).read_bytes()),
            "actual_modules": {"timesigma": str(actual), "EasyTSAD": str(Path(EasyTSAD.__file__).resolve())},
            "dependency_versions": {name: metadata.version(name) for name in
                ("numpy", "scipy", "scikit-learn", "joblib", "torch")}}


def _array(row):
    import numpy as np
    dtype = np.dtype(row.get("dtype", "float64"))
    if dtype.kind not in "fiu" or dtype.itemsize > 8:
        raise ValueError("Native scalar curves require a real numeric dtype of at most 64 bits")
    values = np.asarray(row["values"], dtype=dtype)
    if values.ndim != 1 or not values.size or not np.isfinite(values).all():
        raise ValueError("Native scalar curves must be nonempty, one-dimensional and finite")
    if dtype.kind in "iu" and any(original != int(converted) for original, converted in zip(row["values"], values)):
        raise ValueError("Curve dtype would truncate its supplied values")
    return values


def _split(raw, proportion):
    # Exact pinned TSData.buildfrom slicing, including Python's -0 behavior.
    if 0 < proportion < 1:
        count = int(len(raw) * proportion)
        return raw[:-count].copy(), raw[-count:].copy()
    return raw.copy(), raw.copy()


def _training_series(raw, params):
    """Run original TSData preprocessing on rawtrain, retaining its fit scaler."""
    import numpy as np
    from EasyTSAD.DataFactory import TSData
    module = importlib.import_module("EasyTSAD.DataFactory.TSData")
    train, valid = _split(raw, params["valid_proportion"])
    if not len(train) or not len(valid):
        raise ValueError("Native train/valid split contains an empty partition")
    # Native preprocessing unconditionally transforms .test. A discarded
    # training-derived carrier lets its original code run without any rawtest.
    data = TSData(train, valid, raw[:1].copy(), None, None, None, None)
    if params["diff_order"]:
        data.differential(params["diff_order"])
    captured = []
    if params["preprocess"] != "raw":
        name = "MinMaxScaler" if params["preprocess"] == "min-max" else "StandardScaler"
        constructor = getattr(module, name)
        def capture(*args, **kwargs):
            scaler = constructor(*args, **kwargs)
            captured.append(scaler)
            return scaler
        with patch.object(module, name, capture):
            data.min_max_norm() if params["preprocess"] == "min-max" else data.z_score_norm()
    for name in ("test", "train_label", "valid_label", "test_label", "info"):
        delattr(data, name)
    if not np.isfinite(data.train).all() or not np.isfinite(data.valid).all():
        raise ValueError("Native preprocessing produced nonfinite training values")
    return data, captured[0] if captured else None


def _testing_series(raw_train, raw_test, params, scaler):
    """Apply the saved native scaler with the source's exact differential/clip."""
    import numpy as np
    from EasyTSAD.DataFactory import TSData
    train, valid = _split(raw_train, params["valid_proportion"])
    data = TSData(train, valid, raw_test.copy(), None, None, None, None)
    if params["diff_order"]:
        data.differential(params["diff_order"])
    if scaler is not None:
        data.train = scaler.transform(data.train.reshape(-1, 1)).flatten()
        data.valid = scaler.transform(data.valid.reshape(-1, 1)).flatten()
        data.test = scaler.transform(data.test.reshape(-1, 1)).flatten()
        if params["preprocess"] == "min-max":
            data.valid = np.clip(data.valid, -2, 3)
            data.test = np.clip(data.test, -2, 3)
    for name in ("train_label", "valid_label", "test_label", "info"):
        delattr(data, name)
    return data


def _configuration(method, dataset, params):
    from timesigma.algorithms import get_method
    from timesigma.algorithms.configuration import resolve_configuration
    spec = get_method(method)
    defaults = resolve_configuration(spec.module, [dataset])[dataset]
    hyper = params.get("hyper_params", {})
    if set(hyper) - set(defaults["Model_Params"]):
        raise ValueError("Unknown native Method hyperparameter")
    settings = {"Data_Params": {"preprocess": params.get("preprocess", defaults["Data_Params"]["preprocess"]),
                "diff_order": params.get("diff_order", defaults["Data_Params"]["diff_order"])},
                "Model_Params": {**defaults["Model_Params"], **hyper}}
    spec.validate_parameters(settings["Model_Params"], defaults["Model_Params"])
    if method == "IsolationForest":
        from timesigma.algorithms.isolation_forest.binding import validate_data_configuration
        validate_data_configuration(settings)
        if params.get("seed", 1) != 1:
            raise ValueError("The native IsolationForest binding requires seed=1")
    else:
        for name in ("p", "epochs", "batch_size"):
            if type(settings["Model_Params"][name]) is not int or settings["Model_Params"][name] < 1:
                raise ValueError("AR p/epochs/batch_size must be positive integers")
        if settings["Model_Params"]["lr"] <= 0:
            raise ValueError("AR learning rate must be positive")
    return spec, settings


def _pack(root):
    files = [{"path": str(path.relative_to(root)), "sha256": _hash(path.read_bytes()), "size": path.stat().st_size}
             for path in sorted(root.rglob("*")) if path.is_file() and path.name != "bundle-manifest.json"]
    _write(root / "bundle-manifest.json", {"schema_ref": BUNDLE_SCHEMA, "files": files})
    content = io.BytesIO()
    with tarfile.open(fileobj=content, mode="w:gz") as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.add(path, arcname=str(path.relative_to(root)))
    return content.getvalue()


def _unpack(encoded, expected_hash=None):
    raw = base64.b64decode(encoded, validate=True)
    if expected_hash and _hash(raw) != expected_hash:
        raise ValueError("Model bundle content hash mismatch")
    root = Path(tempfile.mkdtemp(prefix="gymts-timesigma-model-load-"))
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)) or len(members) > 100000 or sum(member.size for member in members) > 2 * 1024**3:
            raise ValueError("Model bundle has duplicate paths or exceeds extraction limits")
        for member in members:
            path = PurePosixPath(member.name)
            if not member.isfile() or path.is_absolute() or ".." in path.parts or "\\" in member.name or str(path) != member.name:
                raise ValueError("Model bundle contains an unsafe path/link")
        if "bundle-manifest.json" not in names or "plan.json" not in names:
            raise ValueError("Model bundle is missing its content manifest or fit plan")
        manifest = json.load(archive.extractfile("bundle-manifest.json"))
        expected = {row["path"]: row for row in manifest["files"]}
        if manifest.get("schema_ref") != BUNDLE_SCHEMA or len(expected) != len(manifest["files"]) or set(expected) != set(names) - {"bundle-manifest.json"}:
            raise ValueError("Model bundle manifest does not cover its exact files")
        for member in members:
            content = archive.extractfile(member).read()
            if member.name in expected and (len(content) != expected[member.name]["size"] or _hash(content) != expected[member.name]["sha256"]):
                raise ValueError("Model bundle file digest differs from its manifest")
            target = root.joinpath(*PurePosixPath(member.name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    return root, _hash(raw)


def fit(payload, source):
    import numpy as np
    import joblib
    from EasyTSAD.Controller import TSADController  # native import order
    from timesigma.algorithms.imports import import_method
    from timesigma.benchmark.artifacts import _Unit, _capture_unit
    from timesigma.benchmark.runtime import seed_runtime
    training = validate_unit(payload["training"], training=True)
    _component(training["dataset"])
    for curve in training["preprocessing_members"]:
        _component(curve)
    params = payload["params"]
    if params["method"] not in ("AR", "IsolationForest"):
        raise ValueError("This split adapter supports AR and IsolationForest only")
    provenance = _provenance(source)
    lengths = payload["evaluation_lengths"]
    if set(lengths) != set(training["evaluation_members"]) or any(type(n) is not int or n < 1 for n in lengths.values()):
        raise ValueError("Native preparation requires declared evaluation lengths, never evaluation values")
    spec, settings = _configuration(params["method"], training["dataset"], params)
    if not spec.capability(training["schema"]).supported:
        raise ValueError("Method does not support the requested native Schema")
    preprocess = {**settings["Data_Params"], "valid_proportion": params.get("valid_proportion", .2)}
    root = Path(tempfile.mkdtemp(prefix="gymts-timesigma-model-fit-"))
    _write(root / "job/run.json", {"seed": params.get("seed", 1), "dataset": {"revision": training["dataset_revision"]}, "easytsad_revision": EASYTSAD_REVISION})
    loaded, scalers, counts = {}, {}, {}
    for index, row in enumerate(training["curves"]):
        raw = _array(row)
        np.save(root / f"raw-{index}.npy", raw, allow_pickle=False)
        series, scaler = _training_series(raw, preprocess)
        loaded[row["curve_id"]] = series
        scalers[row["curve_id"]] = scaler
        counts[row["curve_id"]] = {"raw_train": len(raw), "train_points": len(series.train), "valid_points": len(series.valid), "dtype": str(raw.dtype)}
    joblib.dump(scalers, root / "scalers.pkl")
    fitted = {curve: loaded[curve] for curve in training["training_members"]}
    class LengthOnly:
        def __init__(self, count): self.count = count
        def __len__(self): return self.count
        def __getitem__(self, key): raise AssertionError("prepare cannot read test values")
    testing = {curve: SimpleNamespace(test=LengthOnly(lengths[curve])) for curve in training["evaluation_members"]}
    klass = getattr(import_method(spec.module), spec.method_name)
    seed_runtime(params.get("seed", 1))
    model = klass(copy.deepcopy(settings["Model_Params"]))
    if any(sum(spec.sample_spec.count(len(getattr(series, phase)), model) for series in fitted.values()) == 0 for phase in ("train", "valid")):
        raise ValueError("Native train/validation partitions have no Method samples")
    split = None
    if training["schema"] == "zero_shot":
        split = SimpleNamespace(as_dict=lambda: {"dataset": training["dataset"], "training_curves": training["training_members"],
            "held_out_curves": training["evaluation_members"], "enumerated_curves": training["preprocessing_members"],
            "membership_source": "explicit_frozen_gymts_planning_unit"})
    unit = _Unit(root / "job/Results/ModelArtifacts", spec, training["schema"], training["dataset"],
                 training["training_members"][0] if training["schema"] == "naive" else None, fitted, testing, settings, split)
    with patch.object(klass, "test_phase", side_effect=AssertionError("prepare cannot score")):
        _capture_unit(unit, model, lambda: model.train_valid_phase(next(iter(fitted.values()))) if training["schema"] == "naive" else model.train_valid_phase_all_in_one(fitted))
    metadata_file = unit.directory / "metadata.json"
    native_metadata = json.loads(metadata_file.read_text())
    provenance.update(phase="prepare_fit", training_members=training["training_members"],
        preprocessing_members=training["preprocessing_members"], evaluation_values_read=False, native_training_calls=1,
        test_available=False, evaluation_metadata="public lengths only; LengthOnly rejects value access",
        training_objects_have_test=False, training_objects_have_labels=False,
        per_curve_counts=counts, preprocessing="original TSData transforms; discarded rawtrain-derived carrier; saved fitted scalers",
        native_sample_counts=native_metadata["sample_counts"])
    plan = {"identity": identity(training), "params": params, "configuration": settings, "preprocessing": preprocess,
            "evaluation_lengths": lengths, "metadata_path": str(metadata_file.relative_to(root)),
            "curve_indices": {row["curve_id"]: i for i, row in enumerate(training["curves"])}, "provenance": provenance}
    _write(root / "plan.json", plan)
    state = {"preprocess": preprocess, "members": training["preprocessing_members"], "scaler_classes": {
        curve: None if scaler is None else type(scaler).__module__ + "." + type(scaler).__name__ for curve, scaler in scalers.items()},
        "fit_members": training["training_members"], "per_curve_counts": counts, "test_values_used": False,
        "serialized_state": {"bundle_path": "scalers.pkl", "sha256": _hash((root / "scalers.pkl").read_bytes())}}
    _write(root / "preprocessing-state.json", state)
    bundle = _pack(root)
    return {"bundle_base64": base64.b64encode(bundle).decode(), "model_revision": _hash(bundle),
            "preprocessing_state": state, "training_provenance": provenance, "identity": identity(training),
            "evaluation_lengths": lengths, "work_dir": str(root)}


def inspect_bundle(payload, source):
    root, revision = _unpack(payload["bundle_base64"], payload.get("model_revision"))
    plan = json.loads((root / "plan.json").read_text())
    _check_plan(plan)
    actual = _provenance(source)
    if not _same_runtime(plan["provenance"], actual):
        raise ValueError("Model bundle implementation/runtime differs from the fitted execution")
    return {"model_revision": revision, "identity": plan["identity"], "evaluation_lengths": plan["evaluation_lengths"],
            "method": plan["params"]["method"], "fitted_params": plan["params"],
            "preprocessing_state": json.loads((root / "preprocessing-state.json").read_text()),
            "training_provenance": plan["provenance"], "configuration": plan["configuration"],
            "provenance": {**actual, "phase": "load_only", "native_training_calls": 0}, "native_training_calls": 0, "work_dir": str(root)}


def _same_runtime(fitted, actual):
    return all(fitted.get(key) == actual.get(key) for key in (
        "revision", "easytsad_revision", "python_version", "dependency_versions", "native_file_hashes", "worker_source_sha256"))


def _check_plan(plan):
    _component(plan["identity"]["dataset"])
    for curve in plan["identity"]["preprocessing_members"]:
        _component(curve)
    relative = plan["metadata_path"]
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative or str(path) != relative or not relative.startswith("job/Results/ModelArtifacts/"):
        raise ValueError("Model bundle fit plan has an unsafe artifact path")
    indices = plan["curve_indices"]
    if set(indices) != set(plan["identity"]["preprocessing_members"]) or any(type(index) is not int or index < 0 for index in indices.values()):
        raise ValueError("Model bundle fit plan has invalid raw-training references")


def score(payload, source):
    import numpy as np
    import joblib
    from contextlib import ExitStack
    from EasyTSAD.Controller import TSADController
    from EasyTSAD.DataFactory import TSData
    from timesigma.algorithms import get_method
    from timesigma.algorithms.artifacts import load_model_artifact
    from timesigma.algorithms.imports import import_method
    from timesigma.benchmark.runtime import seed_runtime
    test = validate_unit(payload["input"])
    root, revision = _unpack(payload["bundle_base64"], payload.get("model_revision"))
    plan = json.loads((root / "plan.json").read_text())
    _check_plan(plan)
    provenance = _provenance(source)
    if identity(test) != plan["identity"] or plan["provenance"]["revision"] != provenance["revision"]:
        raise ValueError("Test planning unit/source differs from the fitted state")
    if not _same_runtime(plan["provenance"], provenance):
        raise ValueError("Scoring runtime/source bytes differ from the fitted state")
    spec = get_method(plan["params"]["method"])
    klass = getattr(import_method(spec.module), spec.method_name)
    scalers = joblib.load(root / "scalers.pkl")
    seed_runtime(plan["params"].get("seed", 1))
    model = klass(copy.deepcopy(plan["configuration"]["Model_Params"]))
    curves, digests = [], {}
    with ExitStack() as stack:
        for method in ("train_valid_phase", "train_valid_phase_all_in_one"):
            stack.enter_context(patch.object(klass, method, side_effect=AssertionError("Scoring/replay cannot train")))
        for scaler in scalers.values():
            if scaler is not None:
                stack.enter_context(patch.object(scaler, "fit", side_effect=AssertionError("Frozen preprocessing cannot refit")))
        if not load_model_artifact(model, spec, root / plan["metadata_path"], schema=test["schema"], configuration=plan["configuration"]):
            raise ValueError("Native fitted model was not restored")
        for row in test["curves"]:
            curve, raw = row["curve_id"], _array(row)
            if len(raw) != plan["evaluation_lengths"][curve]:
                raise ValueError("Actual rawtest length differs from the declared frozen planning unit")
            # Reuse the exact native differential operation. Only .test is used
            # by the native scoring method; these rawtrain copies are not fitted.
            raw_train = np.load(root / f"raw-{plan['curve_indices'][curve]}.npy", allow_pickle=False)
            data = _testing_series(raw_train, raw, plan["preprocessing"], scalers[curve])
            model.test_phase(data)
            scores = np.asarray(model.anomaly_score())
            if scores.ndim != 1 or not 0 < len(scores) <= len(raw) or not np.isfinite(scores).all():
                raise ValueError("Native Method produced invalid scores")
            filename = root / f"score-{len(curves)}.npy"
            np.save(filename, scores, allow_pickle=False)
            digests[curve] = {"dtype": str(scores.dtype), "shape": list(scores.shape), "sha256": _hash(scores.tobytes()),
                              "file_sha256": _hash(filename.read_bytes())}
            curves.append({"curve_id": curve, "scores": scores.tolist(), "offset": len(raw) - len(scores), "raw_length": len(raw)})
    if payload.get("expected_score_digests") is not None and digests != payload["expected_score_digests"]:
        raise ValueError("Fresh-process replay scores differ byte-for-byte from the original scoring")
    if payload.get("previous_pid") == os.getpid():
        raise ValueError("Replay must use an independent process")
    provenance.update(phase="replay" if payload.get("expected_score_digests") is not None else "score",
        training_members=test["training_members"], evaluation_members=test["evaluation_members"],
        preprocessing_members=test["preprocessing_members"], native_training_calls=0, scaler_fit_calls=0,
        per_curve_counts={row["curve_id"]: {"raw_test": row["raw_length"], "score_count": len(row["scores"]),
            "offset": row["offset"]} for row in curves})
    return {"dataset_revision": test["dataset_revision"], "planning_unit_id": test["planning_unit_id"], "curves": curves,
            "model_revision": revision, "score_digests": digests, "provenance": provenance, "training_pid": plan["provenance"]["pid"],
            "native_training_calls": 0, "scaler_fit_calls": 0, "fresh_process": True,
            "bitwise_equal": payload.get("expected_score_digests") is not None, "work_dir": str(root)}


def main():
    try:
        request = json.load(sys.stdin)
        operations = {"fit": fit, "inspect": inspect_bundle, "score": score, "replay": score}
        if request["operation"] not in operations:
            raise ValueError("Unknown native worker operation")
        with contextlib.redirect_stdout(sys.stderr):
            result = operations[request["operation"]](request["payload"], request["source"])
        response = {"ok": True, "result": result}
    except Exception as error:
        response = {"ok": False, "error": {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}}
    sys.stdout.buffer.write(canonical_json(response) + b"\n")


if __name__ == "__main__":
    main()
