"""Pinned GSM8K plus genuine ChatTS generator data with private verifiers."""

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import urllib.request

from gymts.contracts import GymTSError, canonical_json
from .contracts import MANIFEST, PRIVATE, SNAPSHOT, SUMMARY_SCHEMA
from .rewards import extract_gsm8k_answer

GSM8K_REVISION = "3101c7d5072418e28b9008a6636bde82a006892c"
GSM8K_HASHES = {"train": "17f347dc51477c50d4efb83959dbb7c56297aba886e5544ee2aaed3024813465",
               "test": "3730d312f6e3440559ace48831e51066acaca737f6eabec99bccb9e4b3c39d14"}
CHATTS_REVISION = "695520a0abc3a6ee93de4b4eab962c7211623c18"
CHATTS_DATASET = "chatts-native-generated/v1"


def _hash(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical_json(value)).hexdigest()


def _error(message, **details):
    return GymTSError("invalid_dataset", message, stage="rl_dataset", details=details)


def cache_gsm8k(directory=None):
    """Download about 5 MB from the pinned official commit, verifying every byte."""
    directory = Path(directory or "/tmp/gymts-rl-sources/gsm8k-3101c7d").resolve()
    directory.mkdir(parents=True, exist_ok=True)
    result = {}
    for split in ("train", "test"):
        path = directory / (split + ".jsonl")
        if not path.exists():
            url = "https://raw.githubusercontent.com/openai/grade-school-math/" + GSM8K_REVISION + "/grade_school_math/data/" + path.name
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read(8_000_001)
            if len(data) > 8_000_000 or _hash(data) != GSM8K_HASHES[split]:
                raise _error("Official GSM8K download hash mismatch", split=split)
            # Publish only a verified, complete download; racing readers can use
            # the same immutable cache without observing partial JSONL.
            handle, temporary = tempfile.mkstemp(prefix="." + split, dir=str(directory))
            try:
                with os.fdopen(handle, "wb") as stream:
                    stream.write(data)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        data = path.read_bytes()
        if _hash(data) != GSM8K_HASHES[split]:
            raise _error("Cached GSM8K differs from official pinned bytes", path=str(path))
        result[split] = path
    return result


def _gsm8k(paths, seed, limits):
    public, private, questions = [], [], {}
    for source_split, split, limit in (("train", "train", limits[0]), ("test", "eval", limits[1])):
        rows = [json.loads(line) for line in paths[source_split].read_text(encoding="utf-8").splitlines()]
        indices = list(range(len(rows)))
        random.Random(_hash({"seed": seed, "source_split": source_split})).shuffle(indices)
        for index in indices[:limit]:
            row = rows[index]
            question, answer = row["question"], row["answer"]
            target, reason = extract_gsm8k_answer(answer)
            if reason is not None or not isinstance(question, str) or not question.strip():
                raise _error("Official GSM8K row is not a verifiable numeric question", source_split=source_split, index=index)
            group = _hash({"dataset": "gsm8k", "question": question.strip()})
            if group in questions:
                raise _error("Duplicate GSM8K question in selected rows or across official splits")
            questions[group] = split
            sample_id = _hash({"dataset": "gsm8k", "revision": GSM8K_REVISION, "source_split": source_split, "index": index})
            public.append({"sample_id": sample_id, "group_id": group, "dataset_id": "openai/gsm8k",
                "split": split, "task_id": "gsm8k.numeric", "messages": [{"role": "user", "content":
                    question + '\nSolve the problem. Finish with exactly one final line: #### <number>. Do not write anything after that line.'}],
                "timeseries": [], "series_names": [], "output_schema": {"type": "object", "properties": {"answer": {"type": "string"}},
                    "required": ["answer"], "additionalProperties": False}, "context": {"answer_format": "gsm8k-final-line/v1"}})
            private.append({"sample_id": sample_id, "group_id": group, "dataset_id": "openai/gsm8k", "split": split,
                "task_id": "gsm8k.numeric", "reward_spec": {"kind": "gsm8k_numeric", "ground_truth": target, "atol": 0, "rtol": 0},
                "provenance": {"source": "https://github.com/openai/grade-school-math", "revision": GSM8K_REVISION,
                    "official_split": source_split, "row_index": index, "row_sha256": _hash(row), "source_file_sha256": GSM8K_HASHES[source_split],
                    "answer_source": "official_human_reference"}})
    return public, private


def chatts_source_identity(source_repo):
    root = Path(source_repo).resolve()
    if not (root / "chatts/ts_generator/generate.py").is_file() or not (root / "config/datagen_config.yaml").is_file():
        raise _error("ChatTS native generator source is unavailable", source_repo=str(root))
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise _error("ChatTS generator requires a versioned source checkout")
    revision = result.stdout.strip()
    # Capture the actual code/config even when the caller intentionally works
    # with a different local revision. It is never labelled as the pinned one.
    files = sorted((root / "chatts/ts_generator").glob("*.py")) + [root / "config/datagen_config.yaml", root / "chatts/__init__.py"]
    hashes = {str(path.relative_to(root)): _hash(path.read_bytes()) for path in files if path.is_file()}
    return {"source_repo": str(root), "git_revision": revision, "expected_revision": CHATTS_REVISION,
            "matches_pinned_revision": revision == CHATTS_REVISION, "files_sha256": hashes, "code_tree_sha256": _hash(hashes)}


_GENERATE = r'''
import hashlib, importlib.metadata, json, random, sys
import numpy as np
from chatts.ts_generator.generate import generate_random_attributes, generate_time_series
seed, train_count, eval_count, length = map(int, sys.argv[1:])
rows = []
for split, count in [('train', train_count), ('eval', eval_count)]:
    for index in range(count):
        sample_seed = int.from_bytes(hashlib.sha256((str(seed)+':'+split+':'+str(index)).encode()).digest()[:4], 'big')
        random.seed(sample_seed)
        np.random.seed(sample_seed)
        attributes = generate_random_attributes(seq_len=length)
        series, attributes = generate_time_series(attributes, seq_len=length)
        rows.append({'split': split, 'index': index, 'seed': sample_seed,
                     'series': [round(float(value), 4) for value in np.asarray(series).reshape(-1)],
                     'attributes': attributes})
def convert(value):
    if isinstance(value, np.generic): return value.item()
    if isinstance(value, np.ndarray): return value.tolist()
    raise TypeError(type(value).__name__)
versions = {key: importlib.metadata.version(key) for key in ['numpy', 'scipy', 'PyYAML', 'tqdm']}
print('GYMTS_RL_GENERATED=' + json.dumps({'rows': rows, 'versions': versions}, default=convert, allow_nan=False))
'''


def generate_chatts(source_repo, *, python=None, seed=7, train_count=32, eval_count=8, sequence_length=64):
    """Call ChatTS's two native pure numerical functions in their own cwd."""
    if (type(seed) is not int or any(type(value) is not int or value < 0 for value in (train_count, eval_count))
            or type(sequence_length) is not int or not 32 <= sequence_length <= 4096):
        raise _error("Native generation requires integer seed/counts and length in [32,4096]")
    before = chatts_source_identity(source_repo)
    command = [str(python or sys.executable), "-B", "-c", _GENERATE, str(seed), str(train_count), str(eval_count), str(sequence_length)]
    result = subprocess.run(command, cwd=str(Path(source_repo).resolve()),
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), capture_output=True, text=True, timeout=300, check=False)
    if result.returncode != 0:
        raise _error("Native ChatTS numerical generation failed", stderr=result.stderr[-4000:])
    lines = [line[len("GYMTS_RL_GENERATED="):] for line in result.stdout.splitlines() if line.startswith("GYMTS_RL_GENERATED=")]
    if len(lines) != 1:
        raise _error("Native ChatTS generation did not emit one complete bundle")
    generated = json.loads(lines[0])
    expected = {(split, index) for split, count in (("train", train_count), ("eval", eval_count)) for index in range(count)}
    identities = [(row["split"], row["index"]) for row in generated["rows"]]
    if set(identities) != expected or len(identities) != len(expected):
        raise _error("Native generation output count differs from the requested split membership")
    after = chatts_source_identity(source_repo)
    if before != after:
        raise _error("ChatTS source changed during native generation")
    generated["source"] = before
    return generated


def _chatts(generated, sequence_length):
    public, private, seen = [], [], set()
    for row in generated["rows"]:
        series = row["series"]
        if len(series) != sequence_length or any(type(v) not in (int, float) or not math.isfinite(v) for v in series):
            raise _error("Native ChatTS produced invalid numerical series")
        series_hash = _hash(series)
        if series_hash in seen:
            raise _error("Repeated ChatTS series would contaminate grouping")
        seen.add(series_hash)
        group = _hash({"dataset": CHATTS_DATASET, "series_sha256": series_hash})
        sample_id = _hash({"group_id": group, "task": "numeric_summary"})
        public.append({"sample_id": sample_id, "group_id": group, "dataset_id": CHATTS_DATASET, "split": row["split"],
            "task_id": "chatts.numeric_summary", "messages": [{"role": "user", "content":
                'Analyze this time series of length ' + str(sequence_length) + ': <ts><ts/>. Return only a JSON object with exactly four numeric keys: "mean", "min", "max", "last". Use the arithmetic mean over every point, the minimum, the maximum, and the final point. Numerical tolerance is 0.001 + 0.001 * abs(reference).'}],
            "timeseries": [series], "series_names": ["series_0"], "output_schema": copy.deepcopy(SUMMARY_SCHEMA),
            "context": {"answer_format": "numeric-summary-json/v1", "sequence_length": sequence_length}})
        target = {"mean": math.fsum(series) / len(series), "min": min(series), "max": max(series), "last": series[-1]}
        scale = max(max(series) - min(series), 1e-6)
        private.append({"sample_id": sample_id, "group_id": group, "dataset_id": CHATTS_DATASET, "split": row["split"],
            "task_id": "chatts.numeric_summary", "reward_spec": {"kind": "numeric_summary", "ground_truth": target,
                "atol": .001, "rtol": .001, "scale": scale},
            "provenance": {"answer_source": "computed_from_native_generated_series", "series_sha256": series_hash,
                "generator_seed": row["seed"], "generator_index": row["index"], "generator_attributes": row["attributes"],
                "generator": "chatts.ts_generator.generate:generate_random_attributes+generate_time_series", "source": generated["source"],
                "dependency_versions": generated["versions"], "rounding_decimals": 4}})
    return public, private


def _write(path, value):
    with Path(path).open("xb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def prepare_dataset(gym, output_dir, *, gsm8k_dir=None, chatts_source="/zzr/scripts/ChatTS", python=None,
                    seed=7, train_limit=128, eval_limit=32, chatts_train=32, chatts_eval=8, sequence_length=64):
    """Publish public CAS snapshots, private reward specs and TRL-ready JSONL.

    Official GSM8K test rows remain evaluation-only. Synthetic train/eval rows
    use independent seeds and content-hash groups. Existing output is immutable.
    """
    for name, value in (("train_limit", train_limit), ("eval_limit", eval_limit), ("chatts_train", chatts_train), ("chatts_eval", chatts_eval)):
        if type(value) is not int or value < 0:
            raise _error(name + " must be a nonnegative integer")
    if type(seed) is not int or type(sequence_length) is not int or not 32 <= sequence_length <= 4096:
        raise _error("seed must be integer and sequence_length must be in [32,4096]")
    if train_limit > 7473 or eval_limit > 1319 or train_limit + eval_limit + chatts_train + chatts_eval == 0:
        raise _error("Requested GSM8K sample count exceeds its official split, or all sources are empty")
    output = Path(output_dir).resolve()
    if output.exists():
        raise _error("RL dataset output already exists", path=str(output))
    public, private, sources = [], [], {}
    if train_limit + eval_limit:
        paths = cache_gsm8k(gsm8k_dir)
        public, private = _gsm8k(paths, seed, (train_limit, eval_limit))
        sources["gsm8k"] = {"revision": GSM8K_REVISION, "files_sha256": GSM8K_HASHES, "license": "MIT",
                            "official_counts": {"train": 7473, "test": 1319}}
    if chatts_train + chatts_eval:
        generated = generate_chatts(chatts_source, python=python, seed=seed, train_count=chatts_train, eval_count=chatts_eval, sequence_length=sequence_length)
        visible, hidden = _chatts(generated, sequence_length)
        public.extend(visible)
        private.extend(hidden)
        sources["chatts"] = {"source": generated["source"], "versions": generated["versions"], "license": "MIT",
            "dataset_id": CHATTS_DATASET, "recipe": "native-numerical-generation+computed-summary/v1"}
    random.Random(seed).shuffle(public)
    groups = {split: {row["group_id"] for row in public if row["split"] == split} for split in ("train", "eval")}
    if groups["train"] & groups["eval"] or len({row["sample_id"] for row in public}) != len(public):
        raise _error("Training and evaluation identities overlap")
    revision = _hash({"schema_version": MANIFEST, "seed": seed, "public": public, "private": private, "sources": sources})
    snapshot = {"schema_version": SNAPSHOT, "dataset_revision": revision, "samples": public}
    gym.schemas.validate(SNAPSHOT, snapshot)
    snapshot_ref = gym.artifacts.save_json(snapshot, SNAPSHOT)
    private_ref = gym.artifacts.save_json({"schema_version": PRIVATE, "dataset_revision": revision, "samples": private}, PRIVATE)
    hidden = {row["sample_id"]: row for row in private}
    rows = {split: [] for split in ("train", "eval")}
    for sample in public:
        # TRL reads only prompt for generation; the verifier is a separate extra
        # column supplied to reward functions. No reference answer is in prompt.
        rows[sample["split"]].append(dict(copy.deepcopy(sample), prompt=copy.deepcopy(sample["messages"]),
            reward_spec=copy.deepcopy(hidden[sample["sample_id"]]["reward_spec"]), dataset_revision=revision))
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="." + output.name + "-", dir=str(output.parent)))
    try:
        files = {}
        for split in ("train", "eval"):
            name = split + ".jsonl"
            data = b"".join(canonical_json(row) + b"\n" for row in rows[split])
            _write(staging / name, data)
            files[name] = {"sha256": _hash(data), "size_bytes": len(data), "row_count": len(rows[split])}
        counts = {split: len(rows[split]) for split in rows}
        manifest = {"schema_version": MANIFEST, "dataset_revision": revision, "seed": seed, "status": "prompt_source_ready",
            "sources": sources, "counts": counts, "dataset_counts": {dataset: {split: sum(row["dataset_id"] == dataset for row in rows[split]) for split in rows} for dataset in sorted({r["dataset_id"] for r in public})},
            "group_disjoint": True, "official_test_training_allowed": False, "files": files,
            "snapshot_ref": snapshot_ref, "private_ref": private_ref,
            "train_sample_ids": [row["sample_id"] for row in rows["train"]], "eval_sample_ids": [row["sample_id"] for row in rows["eval"]]}
        manifest_ref = gym.artifacts.save_json(manifest, MANIFEST)
        _write(staging / "manifest.json", canonical_json(dict(manifest, manifest_ref=manifest_ref)) + b"\n")
        if output.exists():
            raise _error("RL dataset output appeared during preparation")
        os.rename(staging, output)
        return dict(manifest, manifest_ref=manifest_ref, output_dir=str(output), train_path=str(output / "train.jsonl"), eval_path=str(output / "eval.jsonl"))
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


__all__ = ["GSM8K_REVISION", "CHATTS_REVISION", "cache_gsm8k", "generate_chatts", "prepare_dataset"]
