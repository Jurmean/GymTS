"""Bounded HTTPS range projection of official HDF5; no zero-filled originals."""
import hashlib
import io
import json
from pathlib import Path
import re
import urllib.request

from .contracts import DATA_REVISION
from .data import file_identity, flatten_questions, select_indices

REPO = "pandalin98/EngineMT-QA"
QA_SHA256 = "d9960b9f16554453a509087aab9f26263d14c6513d699ac7d9cf7a2835f13113"
QA_BYTES = 16961495


def prepare_official(output, *, qa_path=None, per_stage=2):
    """One explicit preparation command; downloads only fixed QA + H5 ranges."""
    from .data import prepare_view
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if qa_path is None:
        qa_path = output / "test_qa.jsonl"
        if not qa_path.exists():
            url = "https://huggingface.co/datasets/" + REPO + "/resolve/" + DATA_REVISION + "/test_qa.jsonl"
            try:
                with urllib.request.urlopen(url, timeout=90) as response:
                    content = response.read(QA_BYTES + 1)
            except Exception as error:
                raise OSError("Official QA download failed: " + type(error).__name__) from None
            if len(content) != QA_BYTES or hashlib.sha256(content).hexdigest() != QA_SHA256:
                raise ValueError("Official QA content differs from the fixed LFS identity")
            qa_path.write_bytes(content)
    qa_path = Path(qa_path)
    identity = file_identity(qa_path)
    if identity["bytes"] != QA_BYTES or identity["sha256"] != QA_SHA256:
        raise ValueError("Provided QA file differs from the fixed official LFS identity")
    projection = project_official(qa_path, output / "projected", per_stage=per_stage)
    return prepare_view(output / "projected/selected-signals.h5", qa_path, output / "view",
        per_stage=per_stage, projection=projection)


class RangeFile(io.RawIOBase):
    def __init__(self, url, size, *, max_bytes=64 * 1024 * 1024, max_requests=512):
        super().__init__()
        self.url, self.size, self.position = url, size, 0
        self.max_bytes, self.max_requests = max_bytes, max_requests
        self.receipts, self.total = [], 0
        self.cache = {}

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        point = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset
        if point < 0:
            raise ValueError("Negative source HDF5 seek")
        self.position = point
        return point

    def read(self, size=-1):
        size = min(size if size >= 0 else self.size - self.position, self.size - self.position)
        if size <= 0:
            return b""
        start, end = self.position, self.position + size - 1
        key = (start, end)
        if key not in self.cache:
            if self.total + size > self.max_bytes or len(self.receipts) >= self.max_requests:
                raise ValueError("Official HDF5 range budget exceeded")
            request = urllib.request.Request(self.url, headers={"Range": "bytes=" + str(start) + "-" + str(end),
                "Accept-Encoding": "identity"})
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    actual = response.headers.get("Content-Range", "")
                    expected = "bytes " + str(start) + "-" + str(end) + "/" + str(self.size)
                    if response.status != 206 or actual != expected:
                        raise ValueError("Official server did not honor the exact requested byte range")
                    value = response.read(size + 1)
                    # Reuse the official redirect privately; signed CDN URLs
                    # are intentionally never written to evidence or errors.
                    self.url = response.geturl()
            except ValueError:
                raise
            except Exception as error:
                raise OSError("Official HDF5 range read failed: " + type(error).__name__) from None
            if len(value) != size:
                raise ValueError("Incomplete official HDF5 byte range")
            self.cache[key] = value
            self.total += size
            self.receipts.append({"start": start, "end_inclusive": end, "bytes": size,
                "sha256": hashlib.sha256(value).hexdigest()})
        self.position += size
        return self.cache[key]

    def readinto(self, buffer):
        value = self.read(len(buffer))
        buffer[:len(value)] = value
        return len(value)


def project_official(qa_path, output, *, per_stage=2, revision=DATA_REVISION):
    import h5py
    import numpy as np
    if revision != DATA_REVISION:
        raise ValueError("Only the fixed official dataset snapshot is supported")
    origin = "https://huggingface.co/datasets/" + REPO
    pointer_url = origin + "/raw/" + revision + "/time_series_data.h5"
    with urllib.request.urlopen(pointer_url, timeout=60) as response:
        pointer = response.read(1024).decode("ascii")
    sha_match, size_match = re.search(r"oid sha256:([0-9a-f]{64})", pointer), re.search(r"size ([0-9]+)", pointer)
    if not pointer.startswith("version https://git-lfs.github.com/spec/v1") or not sha_match or not size_match:
        raise ValueError("Official HDF5 LFS identity could not be established")
    size = int(size_match.group(1))
    rows = flatten_questions(qa_path)
    indices = select_indices(rows, per_stage)
    ids = sorted({value for i in indices for value in (
        [rows[i]["native_id"]] if isinstance(rows[i]["native_id"], str) else rows[i]["native_id"])}, key=int)
    reader = RangeFile(origin + "/resolve/" + revision + "/time_series_data.h5", size)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    target = output / "selected-signals.h5"
    raw_signals = []
    with h5py.File(reader, "r") as source, h5py.File(target, "w") as derived:
        values = source["seq_data"]
        shape = list(values.shape)
        if shape != [118921, 600, 33]:
            raise ValueError("Fixed official HDF5 shape differs")
        result = derived.create_dataset("seq_data", shape=(len(ids), 600, 33), dtype=values.dtype)
        for position, signal_id in enumerate(ids):
            signal = values[int(signal_id) - 1]
            if not np.isfinite(signal).all():
                raise ValueError("Official selected signal contains nonfinite values")
            result[position] = signal
            raw_signals.append({"original_signal_id": signal_id, "original_zero_based_row": int(signal_id) - 1,
                "derived_zero_based_row": position, "shape": list(signal.shape), "dtype": str(signal.dtype),
                "raw_c_order_sha256": hashlib.sha256(np.ascontiguousarray(signal).tobytes()).hexdigest(),
                "native_float32_sha256": hashlib.sha256(np.ascontiguousarray(signal, dtype=np.float32).tobytes()).hexdigest()})
    result = {"kind": "derived-selected-official-hdf5", "repo": REPO, "revision": revision,
        "original_file": "time_series_data.h5", "original_lfs_sha256": sha_match.group(1), "original_bytes": size,
        "original_shape": shape, "whole_original_downloaded": False, "whole_lfs_hash_recomputed": False,
        "range_authentication": "HTTPS fixed-revision origin; each actual range hashed, not a Merkle inclusion proof",
        "derived_asset": file_identity(target), "qa_asset": file_identity(qa_path),
        "selected_flattened_indices": indices, "signals": raw_signals,
        "byte_ranges": reader.receipts, "total_range_bytes": reader.total}
    (output / "projection.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
