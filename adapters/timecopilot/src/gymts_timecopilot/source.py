"""Fixed upstream identity and explicit local, read-only checkout verification."""
import hashlib
from pathlib import Path
import subprocess

PINNED_REVISION = "961aa330f71afcf53a6ecf2d4b499cb39b44da3e"
REPOSITORY_URL = "https://github.com/AzulGarza/timecopilot"
NATIVE_VERSION = "0.0.38"
FORECASTERS = ("AutoETS", "AutoARIMA", "SeasonalNaive")
TOOLS = ("tsfeatures_tool", "cross_validation_tool", "forecast_tool", "detect_anomalies_tool")


def implementation_ref():
    return {"name": "timecopilot", "version": PINNED_REVISION, "origin_ref": None}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def checkout_identity(implementation):
    if implementation.get("revision", PINNED_REVISION) != PINNED_REVISION:
        raise ValueError("TimeCopilot requires the fixed supported native revision")
    root = Path(implementation["repository"]).expanduser().resolve(strict=True)
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args], text=True,
                                       stderr=subprocess.DEVNULL, timeout=20).strip()
    if git("rev-parse", "HEAD") != PINNED_REVISION:
        raise ValueError("Native checkout HEAD differs from the declared TimeCopilot revision")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise ValueError("Native TimeCopilot checkout has modified tracked files")
    modules = {str(path.relative_to(root)): sha256(path)
               for path in sorted((root / "timecopilot").rglob("*.py"))}
    if not modules:
        raise ValueError("Native TimeCopilot source files are absent")
    return {"repository": str(root), "repository_url": REPOSITORY_URL,
            "revision": PINNED_REVISION, "version": NATIVE_VERSION,
            "source_files_sha256": modules,
            "python": str(Path(implementation["python"]).expanduser().resolve(strict=True))}
