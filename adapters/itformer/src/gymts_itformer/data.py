"""Explicit preparation of official HDF5/JSONL into public and private views."""
import hashlib
import json
from pathlib import Path

from gymts.contracts import digest

from .contracts import DATA_REVISION


def file_identity(path):
    path = Path(path)
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            sha.update(block)
    return {"name": path.name, "bytes": path.stat().st_size, "sha256": sha.hexdigest()}


def flatten_questions(path):
    """Retain every QA, including multiple questions on the same signal/line."""
    rows = []
    with Path(path).open(encoding="utf-8") as stream:
        for line_no, line in enumerate(stream):
            row = json.loads(line)
            conversation = row["conversations"]
            if len(conversation) % 2:
                raise ValueError("Unpaired conversation at source line " + str(line_no))
            for offset in range(0, len(conversation), 2):
                question, answer = conversation[offset:offset + 2]
                if question["stage"] not in ["1", "2", "3", "4"]:
                    continue
                original_id = row["id"]
                if not (isinstance(original_id, str) or isinstance(original_id, list)
                        and original_id and all(isinstance(v, str) for v in original_id)):
                    raise ValueError("Signal id must preserve the native string/list format")
                rows.append({"source_line": line_no, "qa_offset": offset // 2,
                    "flattened_index": len(rows), "native_id": original_id,
                    "stage": int(question["stage"]), "form": question["attribute"],
                    "question": question["value"], "answer": answer["value"]})
    return rows


def select_indices(rows, per_stage=1):
    if type(per_stage) is not int or per_stage < 1:
        raise ValueError("per_stage must be a positive integer")
    counts = {stage: 0 for stage in range(1, 5)}
    chosen = []
    for row in rows:
        if counts[row["stage"]] < per_stage:
            chosen.append(row["flattened_index"])
            counts[row["stage"]] += 1
    if any(count != per_stage for count in counts.values()):
        raise ValueError("Not enough questions in every requested stage")
    return chosen


def prepare_view(h5_path, qa_path, output, *, indices=None, per_stage=1,
                 revision=DATA_REVISION, projection=None):
    """Preparation has gold access; source and Candidate receive public.json only.

    String IDs select a full sequence; list IDs concatenate the first tenth of
    each sequence. This is exactly the fixed upstream __getitem__ selection.
    """
    import h5py
    import numpy as np
    rows = flatten_questions(qa_path)
    chosen = select_indices(rows, per_stage) if indices is None else list(indices)
    if not chosen or len(set(chosen)) != len(chosen) or any(type(i) is not int or i < 0 or i >= len(rows) for i in chosen):
        raise ValueError("Indices must be nonempty unique flattened QA indices")
    identity = {"dataset_revision": revision, "h5": file_identity(h5_path), "qa": file_identity(qa_path),
        "view_version": "enginemt-lossless-public/1", "indices": chosen}
    projection_map = None
    if projection is not None:
        projection = json.loads(Path(projection).read_text()) if isinstance(projection, (str, Path)) else projection
        if (projection["kind"] != "derived-selected-official-hdf5" or projection["revision"] != revision
                or projection["derived_asset"] != identity["h5"] or projection["qa_asset"] != identity["qa"]
                or projection["selected_flattened_indices"] != chosen):
            raise ValueError("Derived HDF5 projection does not match the fixed assets and QA membership")
        projection_map = {item["original_signal_id"]: item["derived_zero_based_row"] for item in projection["signals"]}
        if len(projection_map) != len(projection["signals"]):
            raise ValueError("Duplicate original signal identity in HDF5 projection")
        identity["projection"] = projection
    public, targets = [], []
    with h5py.File(h5_path, "r") as stream:
        signal_data = stream["seq_data"]
        if len(signal_data.shape) != 3 or signal_data.shape[1:] != (600, 33):
            raise ValueError("Expected native seq_data shape (N, 600, 33); do not silently drop channels")
        identity["h5_shape"] = list(signal_data.shape)
        view_revision = digest(identity)
        for index in chosen:
            row = rows[index]
            native = row["native_id"]
            ids = [native] if isinstance(native, str) else native
            if any(not value.isdigit() or (value not in projection_map if projection_map is not None
                    else not 1 <= int(value) <= signal_data.shape[0]) for value in ids):
                raise ValueError("Signal ID is outside the official HDF5 array")
            def read_signal(value):
                return signal_data[projection_map[value] if projection_map is not None else int(value) - 1]
            if isinstance(native, str):
                signal = read_signal(native)
            else:
                signal = np.concatenate([read_signal(value)[:signal_data.shape[1] // 10] for value in native], axis=0)
            if not np.isfinite(signal).all():
                raise ValueError("Nonfinite source signal; no zero fallback is permitted")
            sample_id = digest({"view_revision": view_revision, "flattened_index": index,
                "source_line": row["source_line"], "qa_offset": row["qa_offset"], "signal_ids": ids}).removeprefix("sha256:")
            sample = {key: row[key] for key in ("source_line", "qa_offset", "flattened_index", "stage", "form", "question")}
            sample.update(sample_id=sample_id, signal_ids=ids, signal=signal.tolist(),
                signal_shape=list(signal.shape), projection_ref="itformer-native-h5-selection/1")
            public.append(sample)
            targets.append({"sample_id": sample_id, "answer": row["answer"], "stage": row["stage"],
                "reference_status": "known", "allowed_uses": ["evaluation"]})
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    files = {"public.json": {"dataset_revision": view_revision, "samples": public},
        "private-targets.json": {"dataset_revision": view_revision, "targets": targets},
        "provenance.json": dict(identity, view_revision=view_revision, total_flattened_qa=len(rows),
            selected_count=len(chosen), answer_policy="evaluation-only; excluded from public.json")}
    for name, value in files.items():
        path = output / name
        path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        if name == "private-targets.json":
            path.chmod(0o600)
    return files["provenance.json"]
