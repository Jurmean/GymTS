#!/usr/bin/env python3
"""Build and exercise GymTS distributions without contacting a package index.

Run: python3 -B scripts/check_release.py [--output REPORT.json]

The current interpreter needs the declared build tools (setuptools and wheel).
Builds, extraction, virtual environments, and test stores live in a temporary
directory. Both wheel installations run outside the checkout with isolated
Python imports. This is a packaging and known-secret-pattern check, not a full
security audit or a guarantee about files a future Git commit will include.
"""

import argparse
import configparser
from email.parser import BytesParser
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile


class ReleaseError(Exception):
    pass


FORBIDDEN_PARTS = {
    "output", "outputs", "build", "dist", "__pycache__", "node_modules", ".git", ".venv",
    "venv", ".tox", ".nox", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".gymts", ".gymts-demo", ".codex-build", ".codex-finalizer", ".aws",
    ".ssh", ".azure",
}
FORBIDDEN_FILES = {
    ".DS_Store", ".env", ".netrc", ".pypirc", "credentials.json",
    "id_rsa", "id_ed25519",
}
FORBIDDEN_SUFFIXES = {
    ".pyc", ".pyo", ".pem", ".key", ".p12", ".pfx", ".sqlite",
    ".sqlite3", ".sqlite-wal", ".sqlite-shm", ".sqlite3-wal", ".sqlite3-shm",
    ".db-wal", ".db-shm",
}
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{36}\b"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{50,}\b"),
    re.compile(rb"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}\b"),
)

# This fixture is deliberately packaged separately and uses only the public
# GymTS plugin API. Its algorithm does not depend on any project adapter.
EXTERNAL_PLUGIN_SOURCE = '''
from datetime import datetime
from gymts.contracts import GymTSError, utc_now
from gymts.plugin_support import component, payload, unpack

PROTOCOL = "gymts.task/forecast/1"
OUTPUT = "gymts.builtin/forecast-output/1"

def parse(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

class LinearForecast:
    def __init__(self, spec):
        self.resources = None

    def prepare(self, context, training):
        if training is not None or context["learning"]["prepare"] != "load_only":
            raise GymTSError("unsupported_capability", "Fixture does not train")
        self.resources = context["resources"]
        return {"model_revision": None, "state_refs": [], "training_provenance_ref": None}

    def infer(self, task_input):
        values = unpack(task_input["payload"], self.resources)
        points = [(parse(time), value) for time, value, valid in zip(
            values["timestamps"], values["values"], values["valid_mask"])
            if valid and value is not None]
        prediction = None
        if len(points) >= 2:
            first_time = points[0][0]
            coordinates = [((time - first_time).total_seconds(), value)
                           for time, value in points]
            mean_time = sum(time for time, value in coordinates) / len(coordinates)
            mean_value = sum(value for time, value in coordinates) / len(coordinates)
            variance = sum((time - mean_time) ** 2 for time, value in coordinates)
            if variance:
                slope = sum((time - mean_time) * (value - mean_value)
                            for time, value in coordinates) / variance
                horizon = (parse(values["target_time"]) - first_time).total_seconds()
                prediction = mean_value + slope * (horizon - mean_time)
        return {"input_id": task_input["input_id"], "task_protocol_ref": PROTOCOL,
                "produced_at": utc_now(), "model_revision": None,
                "payload": payload(OUTPUT, {"prediction": prediction,
                    "reason": None if prediction is not None else "insufficient_points"})}

    def update(self, feedback):
        raise GymTSError("unsupported_capability", "Fixture does not update")

    def finish(self):
        return []

def register(registries, schemas):
    ref = component("release-linear", "1.0.0")
    registries.candidates.register({
        "component_ref": ref, "implementation_ref": ref, "component_refs": [],
        "protocol_versions": ["gymts.candidate/1", PROTOCOL],
        "params_schema_ref": "gymts.builtin/empty/1", "origin_ref": None,
        "supported_task_protocols": [PROTOCOL],
        "input_schema_refs": ["gymts.builtin/forecast-input/1"],
        "output_schema_refs": [OUTPUT], "supports_fit": False,
        "fit_requires_targets": False, "supports_update": False,
        "model_revision_mode": "none", "capture_profiles": []}, LinearForecast)
'''


def check_member(name, data=None):
    """Reject unsafe paths and common unpublished local material; never echo data."""
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or re.match(r"^[A-Za-z]:", name):
        raise ReleaseError("Unsafe archive member path: " + name)
    for part in path.parts:
        if (part in FORBIDDEN_PARTS or part.startswith((".gymts-", ".chart-data-"))
                or part in FORBIDDEN_FILES or part.startswith(".env.")
                or fnmatch.fnmatchcase(part, "service-account*.json")):
            raise ReleaseError("Unpublished local file in archive: " + name)
    if any(path.name.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES):
        raise ReleaseError("Unpublished file type in archive: " + name)
    if data is not None and any(pattern.search(data) for pattern in SECRET_PATTERNS):
        raise ReleaseError("Possible credential in archive member: " + name)


def inspect_archive(path, expected_modules):
    members = {}
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                check_member(member.filename)
                if member.is_dir():
                    continue
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ReleaseError("Symbolic link in wheel: " + member.filename)
                data = archive.read(member)
                check_member(member.filename, data)
                members[member.filename] = data
        module_names = {name for name in members if name.startswith("gymts/") and name.endswith(".py")}
        metadata_names = [name for name in members if name.endswith(".dist-info/METADATA")]
        if "gymts/py.typed" not in members or len(metadata_names) != 1:
            raise ReleaseError("Wheel is missing its type marker or unique package metadata")
        for name in members:
            if not name.startswith("gymts/") and ".dist-info/" not in name:
                raise ReleaseError("Unexpected top-level wheel member: " + name)
        metadata = BytesParser().parsebytes(members[metadata_names[0]])
        if metadata["Requires-Python"] != ">=3.9":
            raise ReleaseError("Wheel Python requirement must match the supported minimum")
        for dependency in metadata.get_all("Requires-Dist", []):
            if ";" not in dependency or "extra" not in dependency.split(";", 1)[1]:
                raise ReleaseError("Unexpected mandatory runtime dependency")
    else:
        with tarfile.open(path, "r:gz") as archive:
            for member in archive.getmembers():
                check_member(member.name)
                if member.isdir():
                    continue
                if not member.isfile():
                    raise ReleaseError("Non-regular source archive member: " + member.name)
                data = archive.extractfile(member).read()
                check_member(member.name, data)
                members[member.name] = data
        roots = {PurePosixPath(name).parts[0] for name in members}
        if len(roots) != 1:
            raise ReleaseError("Source archive must have one root directory")
        prefix = next(iter(roots)) + "/"
        members = {name[len(prefix):]: data for name, data in members.items()}
        module_names = {name for name in members if name.startswith("gymts/") and name.endswith(".py")}
        required = {"README.md", "setup.cfg", "pyproject.toml", "MANIFEST.in",
                    "scripts/check_release.py", "examples/forecast_experiment.json",
                    "tests/test_runner.py", "gymts/py.typed"}
        if not required.issubset(members):
            raise ReleaseError("Source archive is missing runnable source, tests, or examples")
    if any("adapters" in PurePosixPath(name).parts for name in members):
        raise ReleaseError("Core distribution must not include project adapter packages")
    if module_names != expected_modules:
        raise ReleaseError("Distribution Python modules differ from the source package")
    return {"file": path.name, "files": len(members), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def command(args, cwd):
    environment = os.environ.copy()
    # Isolated top-level imports also need to remain isolated when regression
    # tests launch child interpreters without -I.
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run([str(arg) for arg in args], cwd=str(cwd),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            env=environment)
    if result.returncode:
        raise ReleaseError("Command failed: " + " ".join(map(str, args)) + "\n" + result.stdout[-10000:])
    return result.stdout


def snapshot_ignore(directory, names):
    ignored = []
    for name in names:
        if (name in FORBIDDEN_PARTS or name in {"build", "dist"}
                or name == "adapters" or name.endswith(".egg-info") or name.startswith((".gymts-", ".chart-data-"))
                or name.endswith((".pyc", ".pyo"))):
            ignored.append(name)
    return ignored


def build(source, destination, kind):
    code = ("import setuptools.build_meta as backend; "
            "print(backend.build_" + kind + "(" + repr(str(destination)) + "))")
    output = command([sys.executable, "-B", "-c", code], source)
    filename = output.strip().splitlines()[-1]
    result = destination / filename
    if not result.is_file():
        raise ReleaseError("Build backend did not return a distribution file")
    return result


def extract_source(archive_path, destination):
    # inspect_archive has already rejected absolute paths, traversal, and links.
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            check_member(member.name)
            if not (member.isfile() or member.isdir()):
                raise ReleaseError("Non-regular source archive member")
        archive.extractall(destination)
    roots = list(destination.iterdir())
    if len(roots) != 1 or not roots[0].is_dir():
        raise ReleaseError("Source distribution must extract to a single directory")
    return roots[0]


def install_and_test(wheel, source, work, full_tests):
    environment = work / "venv"
    command([sys.executable, "-B", "-m", "venv", str(environment)], work)
    python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    console = environment / ("Scripts/gymts.exe" if sys.platform == "win32" else "bin/gymts")
    command([python, "-I", "-B", "-m", "pip", "--isolated", "--disable-pip-version-check",
             "install", "--no-index", "--no-deps",
             "--no-compile", wheel], work)
    command([python, "-I", "-B", "-c",
             "import gymts, importlib.metadata; from pathlib import Path; "
             "assert 'site-packages' in Path(gymts.__file__).parts; "
             "assert gymts.__version__ == importlib.metadata.version('gymts')"], work)
    command([console, "--help"], work)
    command([python, "-I", "-B", "-c",
             "from gymts import GymTS; from importlib.metadata import distribution; "
             "assert GymTS.available_integrations() == []; "
             "assert {entry.name for entry in distribution('gymts').entry_points "
             "if entry.group == 'console_scripts'} == {'gymts'}"], work)
    example = source / "examples" / "counter_experiment.json"
    result = json.loads(command([python, "-I", "-B", "-m", "gymts", "--store", work / "store",
                                 "run", example], work))
    if result.get("status") != "succeeded" or result["summary"]["counts"]["operations"] != 3:
        raise ReleaseError("Installed counter example did not complete three operations")
    details = {"isolated_import": True, "console_scripts": 1, "counter_operations": 3, "project_plugins_bundled": False}
    if full_tests:
        # Copy tests and their fixtures, without the source package, to prevent a
        # successful import from the checkout from masking broken wheel contents.
        verification = work / "verification"
        verification.mkdir()
        for name in ("tests", "examples", "scripts"):
            shutil.copytree(source / name, verification / name, ignore=snapshot_ignore)
        output = command([python, "-I", "-B", "-m", "unittest", "discover", "-s",
                          verification / "tests", "-q"], work)
        match = re.search(r"Ran (\d+) tests?", output)
        if not match:
            raise ReleaseError("Installed regression run did not report its test count")
        details["installed_regression_tests"] = int(match.group(1))
        skipped = re.search(r"OK \(skipped=(\d+)\)", output)
        details["installed_regression_skipped"] = int(skipped.group(1)) if skipped else 0
        details["installed_regression_passed"] = (details["installed_regression_tests"]
                                                   - details["installed_regression_skipped"])
        details["external_plugin_install"] = test_external_plugin(python, source, work)
    return details


def test_external_plugin(python, source, work):
    project = work / "external-plugin-project"
    project.mkdir()
    (project / "gymts_release_linear.py").write_text(EXTERNAL_PLUGIN_SOURCE, encoding="utf-8")
    (project / "README.md").write_text("Temporary local release-check integration fixture.\n", encoding="utf-8")
    (project / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["setuptools>=58", "wheel"]\n'
        'build-backend = "setuptools.build_meta"\n', encoding="utf-8")
    (project / "setup.cfg").write_text(
        '[metadata]\nname = gymts-release-linear-fixture\nversion = 1.0.0\n'
        '[options]\npy_modules = gymts_release_linear\npython_requires = >=3.9\n'
        '[options.entry_points]\ngymts.integrations =\n'
        '    release-linear = gymts_release_linear:register\n', encoding="utf-8")
    distributions = project / "dist"
    distributions.mkdir()
    wheel = build(project, distributions, "wheel")
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            check_member(name, archive.read(name))
    command([python, "-I", "-B", "-m", "pip", "--isolated", "--disable-pip-version-check",
             "install", "--no-index", "--no-deps", "--no-compile", wheel], work)
    code = '''
import json
from datetime import datetime
from pathlib import Path
import sys
from gymts import GymTS
example = json.loads(Path(sys.argv[1]).read_text())
with GymTS(sys.argv[2]) as gym:
    assert not gym.enabled_integrations
    assert "gymts_release_linear" not in sys.modules
    catalog = gym.available_integrations()
    assert any(item["name"] == "release-linear" for item in catalog)
    assert "gymts_release_linear" not in sys.modules
    assert not any(item["component_ref"]["name"] == "release-linear"
                   for item in gym.registries.candidates.manifests())
    baseline = gym.run(example)
    assert baseline["status"] == "succeeded", baseline
    assert "gymts_release_linear" not in sys.modules
    gym.enable_integration("release-linear")
    assert "gymts_release_linear" in sys.modules
    example["candidate"]["adapter"] = "release-linear"
    result = gym.run(example)
    assert result["status"] == "succeeded", result
    records = gym.artifacts.read_json(result["result_ref"])
    assert records
    start = datetime.fromisoformat("2026-01-01T00:00:00+00:00")
    for record in records:
        assert record["status"] == "valid"
        target = datetime.fromisoformat(record["alignment_key"]["target_time"].replace("Z", "+00:00"))
        expected = (target - start).total_seconds() / 60
        assert record["payload"]["value"]["prediction"] == expected
    print(json.dumps({"metadata_discovery_without_load": True, "explicit_enable": True,
                      "forecast_results": len(records), "independent_linear_predictions_exact": True,
                      "public_sdk_only": True}))
'''
    details = json.loads(command([python, "-I", "-B", "-c", code,
                                  source / "examples" / "forecast_experiment.json",
                                  work / "external-plugin-store"], work))
    command([python, "-I", "-B", "-m", "pip", "--isolated", "--disable-pip-version-check",
             "uninstall", "--yes", "gymts-release-linear-fixture"], work)
    code = '''
import importlib.util
import json
from pathlib import Path
import sys
from gymts import GymTS
assert importlib.util.find_spec("gymts_release_linear") is None
with GymTS(sys.argv[2]) as gym:
    assert not any(item["name"] == "release-linear" for item in gym.available_integrations())
    assert gym.run(json.loads(Path(sys.argv[1]).read_text()))["status"] == "succeeded"
'''
    command([python, "-I", "-B", "-c", code, source / "examples" / "forecast_experiment.json",
             work / "after-plugin-removal"], work)
    details["uninstall_preserves_core_run"] = True
    details["distribution"] = "gymts-release-linear-fixture==1.0.0"
    return details


def check_release(root):
    config = configparser.ConfigParser()
    config.read(root / "setup.cfg", encoding="utf-8")
    expected = {path.relative_to(root).as_posix() for path in (root / "gymts").rglob("*.py")}
    with tempfile.TemporaryDirectory(prefix="gymts-release-") as temporary:
        work = Path(temporary)
        source = work / "source"
        shutil.copytree(root, source, symlinks=True, ignore=snapshot_ignore)
        for directory in ("gymts", "examples", "tests", "scripts"):
            if any(path.is_symlink() for path in (source / directory).rglob("*")):
                raise ReleaseError("Distribution inputs must not contain symbolic links")
        distributions = work / "distributions"
        distributions.mkdir()
        sdist = build(source, distributions, "sdist")
        sdist_report = inspect_archive(sdist, expected)
        wheel = build(source, distributions, "wheel")
        wheel_report = inspect_archive(wheel, expected)
        extracted = work / "extracted"
        extracted.mkdir()
        rebuilt_source = extract_source(sdist, extracted)
        rebuilt_dir = work / "rebuilt"
        rebuilt_dir.mkdir()
        rebuilt_wheel = build(rebuilt_source, rebuilt_dir, "wheel")
        rebuilt_report = inspect_archive(rebuilt_wheel, expected)
        direct_work, rebuilt_work = work / "direct-install", work / "sdist-install"
        direct_work.mkdir()
        rebuilt_work.mkdir()
        direct = install_and_test(wheel, source, direct_work, False)
        rebuilt = install_and_test(rebuilt_wheel, rebuilt_source, rebuilt_work, True)
        external_plugin = rebuilt.pop("external_plugin_install")
        license_files = [path.name for path in root.iterdir()
                         if path.is_file() and path.name.upper().startswith(("LICENSE", "LICENCE", "COPYING"))]
        return {"status": "passed", "version": config["metadata"]["version"],
                "python": sys.version.split()[0], "offline": True,
                "distributions": {"sdist": sdist_report, "wheel": wheel_report,
                                  "wheel_rebuilt_from_sdist": rebuilt_report},
                "direct_wheel_install": direct, "sdist_wheel_install": rebuilt,
                "external_plugin_install": external_plugin,
                "release_decisions": [] if license_files else ["Choose an appropriate license before public release"],
                "scope": "Distribution contents and isolated installations; not a Git index or full secret audit"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional JSON report; no distributions are kept")
    args = parser.parse_args()
    try:
        report = check_release(Path(__file__).resolve().parents[1])
    except (ReleaseError, OSError, ValueError, ImportError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
