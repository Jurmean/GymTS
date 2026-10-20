"""Isolated, labels-only official evaluator. No fit or inference operations."""
import base64
import contextlib
import hashlib
import importlib.metadata
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

SOURCE_REVISION = "5a953c1a84d0a442d1c41b17b4e8aba8c013be10"
EASYTSAD_REVISION = "e7be92374a4543d7c52d6e34ef7047f4d6776be0"


def _git(repository, *arguments):
    result = subprocess.run(["git", "-C", str(repository), *arguments], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError("Cannot inspect the fixed TimeSigma source checkout")
    return result.stdout.strip()


def _source(repository):
    repository = Path(repository).expanduser().resolve()
    if _git(repository, "rev-parse", "HEAD") != SOURCE_REVISION:
        raise ValueError("TimeSigma official evaluation needs the exact fixed source revision")
    origin = _git(repository, "remote", "get-url", "origin")
    if not re.fullmatch(r"(?:https://github\.com/|git@github\.com:)WithAnOrch1d/TimeSigma-GymTS(?:\.git)?/?", origin, re.I):
        raise ValueError("TimeSigma source does not originate from the selected repository")
    if _git(repository, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("TimeSigma tracked source is dirty")
    return repository


def _plain(value):
    if hasattr(value, "tolist"):
        return _plain(value.tolist())
    if hasattr(value, "item"):
        return _plain(value.item())
    if isinstance(value, dict):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(child) for child in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("The official evaluation returned a non-finite value")
    return value


def _installed_hashes(distribution, paths):
    """Verify actual evaluation bytes against the installed wheel's RECORD."""
    records = {Path(item.locate()).resolve(): item for item in distribution.files or []}
    hashes = {}
    for path in sorted({Path(value).resolve() for value in paths}):
        raw = path.read_bytes()
        record = records.get(path)
        expected = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode()
        if record is None or record.hash is None or record.hash.mode != "sha256" or record.hash.value != expected:
            raise ValueError("EasyTSAD evaluation source differs from installed RECORD: " + str(path))
        hashes[str(path)] = hashlib.sha256(raw).hexdigest()
    return hashes


def _evaluation_files(repository, distribution, callbacks, config_file):
    # EvalInterface/MetricInterface and concrete metric add/avg/to_dict classes
    # live in the loaded evaluation package, alongside the callback protocols
    # and their point-adjustment helpers. Bind all of those execution modules.
    evaluation_paths = {Path(module.__file__).resolve() for name, module in list(sys.modules.items())
        if (name == "EasyTSAD.Evaluations" or name.startswith("EasyTSAD.Evaluations."))
        and getattr(module, "__file__", None)}
    evaluation_paths.add(config_file)
    installed = _installed_hashes(distribution, evaluation_paths)
    other = [repository / "timesigma/benchmark/runner.py", repository / "timesigma/benchmark/leaderboard.py",
             Path(__file__).resolve(), Path(__file__).with_name("scoring.py").resolve()]
    files = {**installed, **{str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in other}}
    descriptions = []
    for callback in callbacks:
        kind = type(callback)
        path = Path(sys.modules[kind.__module__].__file__).resolve()
        if str(path) not in installed:
            raise ValueError("Official callback is outside the verified EasyTSAD evaluation files")
        descriptions.append({"name": callback.name, "class": kind.__module__ + "." + kind.__qualname__,
                             "source_file": str(path), "sha256": installed[str(path)]})
    return files, descriptions, installed


def evaluate(request):
    repository = _source(request["source_repo"])
    import numpy as np
    import toml
    import timesigma
    import EasyTSAD
    import EasyTSAD.Controller
    from EasyTSAD.Evaluations import Performance
    from timesigma.benchmark.runner import official_evaluations, leaderboard_items
    from timesigma.benchmark.leaderboard import OFFICIAL_METRIC_IDS

    if repository not in Path(timesigma.__file__).resolve().parents:
        raise ValueError("TimeSigma imported outside the selected checkout")
    distribution = importlib.metadata.distribution("EasyTSAD")
    direct = json.loads(distribution.read_text("direct_url.json") or "{}")
    dependency_revision = direct.get("vcs_info", {}).get("commit_id")
    if dependency_revision is None and direct.get("url", "").startswith("file://"):
        dependency_revision = _git(Path(direct["url"][7:]), "rev-parse", "HEAD")
    if dependency_revision != EASYTSAD_REVISION:
        raise ValueError("EasyTSAD is not installed from the pinned native dependency revision")
    metrics, dataset = request["metrics"], request["dataset"]
    if not metrics or any(name not in OFFICIAL_METRIC_IDS for name in metrics):
        raise ValueError("Unknown official TimeSigma metric identifier")
    paths = dict(zip(OFFICIAL_METRIC_IDS, [path for _, path in leaderboard_items(dataset)]))
    config_file = Path(EasyTSAD.Controller.__file__).with_name("GlobalCfg.toml")
    settings = toml.load(config_file)["EvalSetting"]
    margins = settings["margin"].get(dataset, settings["margin"]["default"]) if settings["use_margin"] else [0, 0]

    def select(raw):
        chosen = {}
        for metric in metrics:
            value = raw
            for key in paths[metric]:
                value = value[key]
            value = float(value)
            if not math.isfinite(value):
                raise ValueError("Official metric is not finite on this curve")
            chosen[metric] = value
        return chosen

    callbacks = official_evaluations()
    source_files, evaluation_classes, installed_files = _evaluation_files(repository, distribution, callbacks, config_file)
    by_name = {item["name"]: item for item in evaluation_classes}
    official_sources = {metric: {**by_name[paths[metric][0]], "native_result_path": list(paths[metric])}
                        for metric in metrics}
    average, per_curve, seen = None, [], set()
    for curve in request["curves"]:
        name = curve["curve_id"]
        if name in seen:
            raise ValueError("Duplicate evaluation curve")
        seen.add(name)
        scores, labels = np.asarray(curve["scores"], dtype=float), np.asarray(curve["labels"], dtype=float)
        if (scores.ndim != 1 or labels.ndim != 1 or not len(scores) or
                type(curve["raw_length"]) is not int or type(curve["offset"]) is not int or
                len(labels) != curve["raw_length"] or curve["offset"] < 0 or
                curve["offset"] + len(scores) != len(labels) or
                not np.isfinite(scores).all() or not np.isin(labels, [0, 1]).all()):
            raise ValueError("Official scores need finite one-dimensional values and complete binary labels with exact suffix support")
        performance = Performance("GymTS-frozen-scores", dataset, name, scores.copy(), labels.copy(), margins)
        if performance.all_label_normal:
            per_curve.append({"curve_id": name, "status": "excluded", "reason": "native_all_labels_normal",
                              "metrics": {metric: None for metric in metrics}})
            continue
        calculated, raw = performance.perform_eval(callbacks)
        per_curve.append({"curve_id": name, "status": "scored", "reason": None,
                          "metrics": select(raw), "native_evaluation": _plain(raw), "margins": margins})
        if average is None:
            average = calculated
        else:
            for total, current in zip(average, calculated):
                total.add(current)
    aggregate = {}
    for value in average or []:
        value.avg()
        aggregate.update(value.to_dict())
    values = select(aggregate) if average is not None else {metric: None for metric in metrics}
    _source(repository)
    after_files, after_classes, after_installed = _evaluation_files(repository, distribution, callbacks, config_file)
    if source_files != after_files or evaluation_classes != after_classes or installed_files != after_installed:
        raise ValueError("Official evaluation execution files changed during scoring")
    versions = {}
    for package in ("numpy", "toml", "EasyTSAD", "scikit-learn", "torch"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            pass
    return {"metrics": values, "per_curve": per_curve, "native_aggregate": _plain(aggregate),
            "provenance": {"source_repo": str(repository), "source_revision": SOURCE_REVISION,
                "easytsad_revision": dependency_revision, "timesigma_module": timesigma.__file__,
                "easytsad_module": EasyTSAD.__file__, "python": sys.executable,
                "python_version": sys.version.split()[0], "pid": os.getpid(), "dependency_versions": versions,
                "source_files": source_files, "evaluation_classes": evaluation_classes,
                "official_metric_sources": official_sources,
                "easytsad_record_verified_files": installed_files,
                "worker_source_sha256": source_files[str(Path(__file__).resolve())],
                "scoring_host_sha256": source_files[str(Path(__file__).with_name("scoring.py").resolve())],
                "training_calls": 0, "operation": "evaluate_frozen_scores"}}


def main():
    logs = io.StringIO()
    try:
        request = json.load(sys.stdin)
        with contextlib.redirect_stdout(logs):
            result = evaluate(request)
        response = {"ok": True, "result": _plain(result)}
    except Exception as exc:
        response = {"ok": False, "error": {"code": "scorer_failure", "message": str(exc), "type": type(exc).__name__}}
    sys.stdout.write(json.dumps(response, ensure_ascii=False, allow_nan=False))
    return 0 if response["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
