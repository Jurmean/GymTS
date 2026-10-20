"""Isolated native worker; installed sktime must resolve to the fixed checkout."""
import contextlib
import copy
import hashlib
import importlib.metadata
import importlib.util
import json
import math
from pathlib import Path
import sys
import traceback

from gymts.contracts import canonical_json
from .source import PINNED_REVISION, git, resolve_source


def _load_file(name, path):
    path = Path(path).resolve()
    previous = sys.modules.get(name)
    if previous is not None:
        if not getattr(previous, "__file__", None) or Path(previous.__file__).resolve() != path:
            raise RuntimeError("Refusing to replace an unrelated module: " + name)
        return previous
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _load_playground(repository, tool):
    # Upstream's standalone Playground uses top-level imports. Load its exact
    # tracked files only inside this isolated worker; never extend sys.path.
    directory = Path(repository) / "playground"
    names = ["catalog"]
    if tool.startswith("labts."):
        names += ["metrics", "runners", "analyzer", "domain_runners", "user_algos", "hf_data"]
    for name in names:
        _load_file(name, directory / (name + ".py"))


def _check_catalog_plugins(repository):
    tracked = set(git(repository, "ls-files", "--", "playground/experiments").splitlines())
    for path in (repository / "playground/experiments").glob("*.py"):
        if path.relative_to(repository).as_posix() not in tracked or repository not in path.resolve().parents:
            raise ValueError("Registered catalog discovery cannot load untracked user code")


def _jsonable(value):
    if hasattr(value, "tolist"):
        return _jsonable(value.tolist())
    if hasattr(value, "item"):
        return _jsonable(value.item())
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _values(arguments, key="values", allow_missing=False):
    values = arguments.get(key)
    if not isinstance(values, list) or not values:
        raise ValueError(f"{key} must be a nonempty numeric list")
    for value in values:
        if value is None and allow_missing:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{key} must contain finite numbers" + (" or null" if allow_missing else ""))
    return values


def _execute_native(request):
    tool, arguments, params = request["tool"], request["arguments"], request["params"]
    if tool in ("labts.run", "labts.analyze"):
        arguments = copy.deepcopy(arguments)
        inner = arguments.get("params", {})
        if not isinstance(inner, dict):
            raise ValueError("Library experiment arguments.params must be an object")
        conflict = [name for name in params if name in inner and params[name] != inner[name]]
        if conflict:
            raise ValueError(f"Conflicting library params: {', '.join(conflict)}")
        arguments["params"] = {**inner, **params}
    elif tool in ("labts.catalog", "labts.metrics") and params:
        raise ValueError(f"{tool} does not accept estimator params; configure its documented arguments")
    import pandas as pd
    _load_playground(request["provenance"]["repository"], tool)
    # This is the fork's actual cached module-path loader, rather than a local
    # approximation of the requested library implementation.
    from catalog import import_estimator_class
    if tool in ("forecast.naive", "forecast.polynomial"):
        values = _values(arguments, allow_missing=True)
        horizons = arguments.get("horizons", [1])
        if not isinstance(horizons, list) or not horizons or any(isinstance(h, bool) or not isinstance(h, int) or h <= 0 for h in horizons):
            raise ValueError("horizons must be positive relative integer steps")
        entrypoint = ("sktime.forecasting.naive.NaiveForecaster" if tool == "forecast.naive" else
                      "sktime.forecasting.trend.PolynomialTrendForecaster")
        klass = import_estimator_class(entrypoint)
        estimator = klass(**params)
        predicted = estimator.fit(pd.Series(values, dtype="float64")).predict(fh=horizons)
        by_horizon = {int(index) - (len(values) - 1): value for index, value in predicted.items()}
        state = {"fitted_params": _jsonable(estimator.get_fitted_params(deep=True))}
        if hasattr(estimator, "regressor_"):
            regression = estimator.regressor_.steps[-1][1]
            state["coefficients"] = _jsonable(regression.coef_)
            state["intercept"] = _jsonable(regression.intercept_)
        return {"horizons": horizons, "predictions": [_jsonable(by_horizon[h]) for h in horizons],
                "estimator": entrypoint, "params": _jsonable(estimator.get_params(deep=False)),
                "fit_occurred": True, "fit_scope": "current_authorized_input_only", "fit_calls": 1,
                "fitted_state": state, "fitted_state_sha256": hashlib.sha256(canonical_json(state)).hexdigest(),
                "persistent_state_reused": False}
    if tool == "dataset.load":
        from sktime.datasets import load_airline, load_lynx, load_shampoo_sales
        if params:
            raise ValueError("Dataset loader accepts no model parameters")
        name = arguments.get("dataset", "airline")
        loaders = {"airline": load_airline, "lynx": load_lynx, "shampoo-sales": load_shampoo_sales}
        if name not in loaders or set(arguments) - {"dataset"}:
            raise ValueError("Use a vendored airline/lynx/shampoo-sales dataset")
        values = loaders[name]()
        return {"dataset": name, "name": str(values.name or name), "values": _jsonable(values),
                "index": [str(i) for i in values.index], "loader": loaders[name].__module__ + "." + loaders[name].__name__}
    if tool == "detect.threshold":
        values = _values(arguments)
        if "mode" in params and params["mode"] != "segments":
            raise ValueError("The GymTS wrapper preserves native segments; use mode=segments")
        if params.get("lower") not in (None, "-upper"):
            raise ValueError("This pinned ThresholdDetector only implements lower=None or '-upper'; explicit numeric lower is unsupported by its source")
        klass = import_estimator_class("sktime.detection.naive.ThresholdDetector")
        estimator = klass(**{**params, "mode": "segments"})
        native = estimator.fit_predict(pd.DataFrame(values))
        segments = [{"start": int(item.left), "end": int(item.right), "closed": item.closed} for item in native["ilocs"]]
        flags = [any(item["start"] <= index < item["end"] for item in segments) for index in range(len(values))]
        return {"segments": segments, "flags": flags, "last_anomaly": flags[-1], "native_output_kind": "half-open iloc segments", "estimator": "ThresholdDetector", "params": params}
    if tool == "analyze.seasonality":
        values = _values(arguments)
        method = params.get("method", "acf")
        names = {"acf": "SeasonalityACF", "periodogram": "SeasonalityPeriodogram"}
        if method not in names:
            raise ValueError("Seasonality method must be acf or periodogram")
        klass = import_estimator_class("sktime.param_est.seasonality." + names[method])
        estimator = klass(**{key: value for key, value in params.items() if key != "method"}).fit(pd.Series(values, dtype="float64"))
        return {"estimates": _jsonable(estimator.get_fitted_params()), "estimator": names[method], "series_length": len(values)}
    if tool == "distance.euclidean":
        import numpy as np
        from sktime.distances import distance
        x, y = _values(arguments, "x"), _values(arguments, "y")
        if len(x) != len(y):
            raise ValueError("Euclidean distance requires equal series lengths")
        return {"distance": float(distance(np.asarray(x, dtype=float), np.asarray(y, dtype=float), metric="euclidean", **params)), "metric": "euclidean"}
    if tool == "labts.catalog":
        from catalog import build_catalog
        if not isinstance(arguments.get("include_registered", False), bool):
            raise ValueError("include_registered must be a boolean")
        if arguments.get("include_registered"):
            _check_catalog_plugins(Path(request["provenance"]["repository"]))
        return _jsonable(build_catalog(include_registered=bool(arguments.get("include_registered", False))))
    if tool == "labts.run":
        from catalog import ENABLED_ALGORITHMS
        from runners import run_experiment
        selected = arguments.get("algorithm_id")
        if selected is not None and selected not in {entry["id"] for entry in ENABLED_ALGORITHMS}:
            raise ValueError("labts.run currently accepts pinned curated algorithm ids; untracked user plugins are not fixed library code")
        result = _jsonable(run_experiment(arguments))
        if result.get("status") in ("blocked", "error", "failed"):
            raise _NativeFailure(result)
        return result
    if tool == "labts.analyze":
        from analyzer import run_analysis
        result = _jsonable(run_analysis(arguments))
        if result.get("status") in ("blocked", "error", "failed"):
            raise _NativeFailure(result)
        return result
    if tool == "labts.metrics":
        from metrics import compute_metric, resolve_metrics
        task = arguments.get("task", "forecasting")
        context = arguments.get("context", {})
        entries = resolve_metrics(arguments.get("metrics", ["mae"]), task)
        return {"metrics": {entry["id"]: _jsonable(compute_metric(entry, task, context)) for entry in entries}, "definitions": entries}
    raise ValueError(f"Unknown LibraryTS tool: {tool}")


class _NativeFailure(Exception):
    def __init__(self, output):
        self.output = output
        super().__init__(str(output.get("error", output.get("message", "Native library failure"))))


def execute(request):
    source = request["provenance"]
    implementation = {key: source[key] for key in ("repository", "revision", "python")}
    if resolve_source(implementation, request["tool"]) != source:
        raise ValueError("LibraryTS source changed before native execution")
    import sktime
    repository = Path(source["repository"])
    if not Path(sktime.__file__).resolve().is_relative_to(repository / "sktime"):
        raise ValueError("Installed sktime is outside the selected fixed checkout; explicitly install that source package")
    result = _execute_native(request)
    loaded = {}
    aliases = {"catalog", "metrics", "runners", "analyzer", "domain_runners", "user_algos", "hf_data"}
    for name, module in list(sys.modules.items()):
        if not (name == "sktime" or name.startswith("sktime.") or name in aliases or name.startswith("experiments.")):
            continue
        filename = getattr(module, "__file__", None)
        if filename is None:
            continue
        path = Path(filename).resolve()
        if not path.is_relative_to(repository):
            raise ValueError("Native module is outside the fixed checkout: " + name)
        loaded[name] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    if resolve_source(implementation, request["tool"]) != source:
        raise ValueError("LibraryTS source changed during native execution")
    versions = {}
    for name in ("numpy", "pandas", "scikit-base", "scikit-learn", "scipy", "joblib", "packaging", "statsmodels", "numba"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    result["provenance"] = {**source, "loaded_modules": loaded, "versions": versions,
                            "sktime_version": sktime.__version__,
                            "worker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    return _jsonable(result)


def main():
    try:
        request = json.load(sys.stdin)
        with contextlib.redirect_stdout(sys.stderr):
            result = execute(request)
        response = {"ok": True, "output": result}
    except Exception as error:
        response = {"ok": False, "error": {"type": type(error).__name__, "message": str(error),
                    "native_output": getattr(error, "output", None), "traceback": traceback.format_exc()}}
    print(json.dumps(response, ensure_ascii=False, allow_nan=False))
    return 0 if response["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
