"""Explicit installed-wheel and local-model identities; no model imports."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import zipfile


def file_hash(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(16 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def freeze_core(wheel, output):
    import gymts
    wheel = Path(wheel).resolve(strict=True)
    base = Path(gymts.__file__).resolve().parent.parent
    with zipfile.ZipFile(wheel) as archive:
        files = {name: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()
                 if name.startswith("gymts/") and not name.endswith("/")}
    if not files or any(file_hash(base / name) != expected for name, expected in files.items()):
        raise ValueError("Installed core bytes do not match the explicitly supplied wheel")
    actual = {str(path.relative_to(base)) for path in (base / "gymts").rglob("*")
              if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"}
    if actual != set(files):
        raise ValueError("Installed core file inventory differs from the supplied wheel")
    result = {"core_version": importlib.metadata.version("gymts"), "wheel": str(wheel),
              "wheel_sha256": file_hash(wheel), "installed_files": files}
    Path(output).write_text(json.dumps(result, indent=2) + "\n")
    return result


def verify_core(identity):
    import gymts
    frozen = json.loads(Path(identity).read_text())
    base = Path(gymts.__file__).resolve().parent.parent
    if not frozen["installed_files"] or any(file_hash(base / name) != expected
                                            for name, expected in frozen["installed_files"].items()):
        raise ValueError("Loaded core differs from the explicit frozen wheel identity")
    return {"core_path": str(Path(gymts.__file__).resolve()), "wheel_sha256": frozen["wheel_sha256"],
            "verified_files": len(frozen["installed_files"])}


def model_identity(directory):
    # Reuse the RL adapter's structural safetensors validation and exact file hash convention.
    from gymts_rl.policy import checkpoint_identity
    return checkpoint_identity(directory)
