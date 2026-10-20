"""Fixed implementation identities, independent of tasks and candidates."""
import hashlib
import re
from pathlib import Path
import subprocess
import sys

from gymts.contracts import GymTSError

REPOSITORY_URL = "https://github.com/NetmanAIOps/sktime"
PINNED_REVISION = "080f4c3c3695f239e328548bac7d7a3ef7aa9127"

TOOLS = {
    "forecast.naive": {"entrypoint": "sktime.forecasting.naive.NaiveForecaster.fit/predict", "source": "sktime/forecasting/naive/_naive.py", "task": "forecasting"},
    "forecast.polynomial": {"entrypoint": "sktime.forecasting.trend.PolynomialTrendForecaster.fit/predict", "source": "sktime/forecasting/trend/_polynomial_trend_forecaster.py", "task": "forecasting"},
    "detect.threshold": {"entrypoint": "sktime.detection.naive.ThresholdDetector.fit_predict", "source": "sktime/detection/naive/_threshold.py", "task": "anomaly_detection"},
    "analyze.seasonality": {"entrypoint": "sktime.param_est.seasonality.SeasonalityACF.fit/get_fitted_params", "source": "sktime/param_est/seasonality.py", "task": "analysis"},
    "distance.euclidean": {"entrypoint": "sktime.distances.distance", "source": "sktime/distances/_distance.py", "task": "distance"},
    "labts.catalog": {"entrypoint": "playground.catalog.build_catalog", "source": "playground/catalog.py", "task": "catalog"},
    "labts.run": {"entrypoint": "playground.runners.run_experiment", "source": "playground/runners.py", "task": "standalone_library_experiment"},
    "labts.analyze": {"entrypoint": "playground.analyzer.run_analysis", "source": "playground/analyzer.py", "task": "analysis"},
    "labts.metrics": {"entrypoint": "playground.metrics.resolve_metrics/compute_metric", "source": "playground/metrics.py", "task": "scoring"},
    "dataset.load": {"entrypoint": "sktime.datasets.load_airline/load_lynx/load_shampoo_sales", "source": "sktime/datasets/_single_problem_loaders.py", "task": "data"},
}

# These declarations belong to this external provider, not to GymTS core.
# Current-input tools consume only explicit caller values. Native per-call fit
# remains an ordinary transient computation; it does not open another dataset.
for _name in ("forecast.naive", "forecast.polynomial", "detect.threshold",
              "analyze.seasonality", "distance.euclidean"):
    TOOLS[_name].update(allowed_scopes=["current_input", "standalone"],
                        effect="compute_current_input")
for _name, _effect in {
        "labts.catalog": "inspect_external_catalog",
        "labts.run": "run_standalone_experiment",
        "labts.analyze": "read_external_data_and_analyze",
        "labts.metrics": "evaluate_supplied_values",
        "dataset.load": "read_external_data"}.items():
    TOOLS[_name].update(allowed_scopes=["standalone"], effect=_effect)
del _name, _effect


def implementation_ref(name="LibraryTS"):
    return {"name": name, "version": PINNED_REVISION, "origin_ref": REPOSITORY_URL + "/tree/" + PINNED_REVISION}


def tool_ref(name):
    if name not in TOOLS:
        raise GymTSError("unsupported_capability", "Unknown LibraryTS tool: " + str(name))
    return {"name": TOOLS[name]["entrypoint"], "version": PINNED_REVISION,
            "origin_ref": REPOSITORY_URL + "/blob/" + PINNED_REVISION + "/" + TOOLS[name]["source"]}


def git(repository, *arguments):
    try:
        result = subprocess.run(["git", "-C", str(repository), *arguments], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GymTSError("invalid_config", "Cannot inspect fixed LibraryTS source", stage="libraryts.source") from error
    if result.returncode:
        raise GymTSError("invalid_config", "LibraryTS source inspection failed", stage="libraryts.source")
    return result.stdout.strip()


def resolve_source(implementation, tool):
    tool_ref(tool)
    if not isinstance(implementation, dict) or set(implementation) - {"repository", "revision", "python"}:
        raise GymTSError("invalid_config", "Use explicit LibraryTS repository/revision/python configuration")
    if not implementation.get("repository"):
        raise GymTSError("invalid_config", "LibraryTS requires an explicit fixed source repository")
    repository = Path(implementation["repository"]).expanduser().resolve()
    expected = implementation.get("revision", PINNED_REVISION)
    if expected != PINNED_REVISION or git(repository, "rev-parse", "HEAD") != expected:
        raise GymTSError("conflict", "LibraryTS requires its registered fixed commit", stage="libraryts.source")
    remote = git(repository, "remote", "get-url", "origin")
    if not re.fullmatch(r"(?:https://github\.com/|git@github\.com:)NetmanAIOps/sktime(?:\.git)?/?", remote, re.I):
        raise GymTSError("conflict", "LibraryTS source origin differs from the selected repository")
    if git(repository, "status", "--porcelain", "--untracked-files=no"):
        raise GymTSError("conflict", "LibraryTS tracked source is dirty")
    source = repository / TOOLS[tool]["source"]
    if not source.is_file():
        raise GymTSError("unsupported_capability", "Fixed LibraryTS tool source is missing")
    version_file = repository / "sktime/__init__.py"
    match = re.search(r'^__version__\s*=\s*[\'"]([^\'"]+)[\'"]', version_file.read_text(), re.M)
    if match is None:
        raise GymTSError("conflict", "LibraryTS has no fixed source version")
    python = implementation.get("python", sys.executable)
    if not isinstance(python, str) or not python:
        raise GymTSError("invalid_config", "LibraryTS python must identify an interpreter")
    if "/" in python:
        python = str(Path(python).expanduser().absolute())
    return {"repository": str(repository), "repository_url": REPOSITORY_URL, "revision": expected,
            "python": python, "package_version": match.group(1), "tool": tool,
            "entrypoint": TOOLS[tool]["entrypoint"], "source": TOOLS[tool]["source"],
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
