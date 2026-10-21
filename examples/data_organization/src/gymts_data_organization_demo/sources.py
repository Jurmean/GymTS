"""Project-specific source formats and recipe execution stay outside the core."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from gymts.contracts import digest

POLICY = {"allowed_uses": ["runtime", "evaluation"], "training_allowed": False}


def numerical_sample(values, *, name, horizon):
    """Public observations and evaluation-only future are separate records."""
    sample = {"sample_token": digest({"name": name, "values": values[:-horizon], "horizon": horizon}).removeprefix("sha256:"),
        "series": [{"name": name, "values": list(values[:-horizon])}],
        "context": {"horizon": horizon}, "annotations": {"source_name": name}}
    target = {"sample_token": sample["sample_token"], "expected_output": {"forecast": list(values[-horizon:])}}
    return sample, target


def materialize(gym, dataset):
    """Recreate a Run-local domain view using only the persistent public dataset."""
    from gymts_timeseries.contracts import SNAPSHOT
    rows = list(dataset)
    revision = digest({"samples": rows})
    snapshot = {"schema_version": SNAPSHOT, "dataset_revision": revision, "samples": rows}
    return gym.artifacts.save_json(snapshot, SNAPSHOT), revision


def source_definition(source_id, kind, environment, *, recipe, seed=None, parents=()):
    mode = "recorded" if kind == "live_testbed" else "snapshot" if kind == "static" else "seeded"
    # The numerical source is materialized from ResourceStore by dataset ID.
    # Its transient ArtifactRef is deliberately absent from this configuration.
    configuration = {key: environment[key] for key in ("mapping", "options")}
    if kind in ("simulation", "live_testbed"):
        configuration["source"] = environment["source"]
    return {"protocol_version": "gymts.data-source/1", "source_id": source_id,
        "config": "default", "revision": None, "kind": kind,
        "provider_ref": {"name": environment["adapter"], "version": environment["version"], "origin_ref": None},
        "configuration": configuration, "recipe": recipe,
        "reproducibility": {"mode": mode, "seed": seed}, "usage_policy": dict(POLICY),
        "parent_datasets": list(parents), "card_ref": None}


def generate_chatts(repository, python, output, *, seed=27, length=40):
    """Invoke the genuine declared ChatTS checkout, with no GymTS source fallback."""
    code = r'''
import hashlib,json,random,sys,numpy as np
from pathlib import Path
from chatts.ts_generator.generate import generate_random_attributes,generate_time_series
seed,length=int(sys.argv[1]),int(sys.argv[2]);random.seed(seed);np.random.seed(seed)
attributes=generate_random_attributes(seq_len=length)
values,attributes=generate_time_series(attributes,seq_len=length)
values=[float(v) for v in np.asarray(values).reshape(-1)]
source=Path('chatts/ts_generator/generate.py')
print(json.dumps({'values':values,'seed':seed,'length':length,'generator':str(source.resolve()),
 'generator_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}))
'''
    env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR") if key in os.environ}
    env.update(CUDA_VISIBLE_DEVICES="", PYTHONDONTWRITEBYTECODE="1", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    result = subprocess.run([python, "-B", "-c", code, str(seed), str(length)], cwd=repository,
        env=env, capture_output=True, text=True, timeout=120)
    Path(output).write_text(result.stderr)
    result.check_returncode()
    value = json.loads(result.stdout)
    recipe = {key: value[key] for key in ("seed", "length", "generator", "generator_sha256")}
    root = Path(repository)
    files = sorted((root/"chatts/ts_generator").rglob("*.py")) + [root/"config/datagen_config.yaml"]
    recipe["native_files_sha256"] = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    revision = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    recipe["native_git_revision"] = revision.stdout.strip()
    return value["values"], recipe
