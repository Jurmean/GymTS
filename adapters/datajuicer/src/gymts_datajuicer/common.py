"""Strict, deterministic domain serialization, usable in the isolated worker."""
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
import os


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else dumps(value).encode()).hexdigest()


def loads(value):
    def pairs(items):
        out = {}
        for key, item in items:
            if key in out:
                raise ValueError("Duplicate JSON key: " + key)
            out[key] = item
        return out
    return json.loads(value, object_pairs_hook=pairs,
        parse_constant=lambda token: (_ for _ in ()).throw(ValueError("Nonfinite JSON: " + token)))


def write_json(path, value):
    Path(path).write_text(dumps(value) + "\n", encoding="utf-8")


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def append_jsonl(path, value):
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write(dumps(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def native_rows(dataset):
    # Round-trip rejects nonfinite or non-JSON native values instead of silently
    # changing them. All configured operators use ordinary JSON-compatible data.
    return loads(dumps(dataset.to_list()))


def row_identity(row):
    return {"sample_id": row["sample_id"], "family_id": row["family_id"],
            "row_sha256": sha(row)}


def validate_source(rows):
    if not isinstance(rows, list) or not rows or len(rows) > 256:
        raise ValueError("Source must contain 1..256 explicitly selected training rows")
    seen = set()
    for row in rows:
        if set(row) != {"sample_id", "family_id", "split", "series", "operation", "text"}:
            raise ValueError("Public source fields must exclude references and private metadata")
        if row["split"] != "train" or row["operation"] not in {"min", "max", "mean"}:
            raise ValueError("Data-Juicer only accepts train split and declared numeric operations")
        if not isinstance(row["sample_id"], str) or row["sample_id"] in seen:
            raise ValueError("Each original row requires a unique stable sample_id")
        if not isinstance(row["family_id"], str) or not row["family_id"] or not isinstance(row["text"], str):
            raise ValueError("Invalid family/text")
        if not isinstance(row["series"], list) or not row["series"] or any(
            type(x) not in (int, float) or not math.isfinite(x) for x in row["series"]):
            raise ValueError("Public series must be finite numeric values")
        seen.add(row["sample_id"])
    return rows


def source_row(series, *, family_id, sample_id, operation="max"):
    """Public prompt contains the series and query contract, never an oracle."""
    text = ("Create one question-and-answer DATASET ENTRY from the time series below. "
            "Do not answer with only an assistant value. Your output MUST include BOTH literal prefixes "
            "Human: and Assistant:, in that order. No explanations, markdown, or other text. "
            "Use this exact output template, replacing each placeholder with the input's real "
            "operation, family_id and computed numeric answer:\n"
            'Human:{"operation":"<operation>","family_id":"<family_id>"}'
            'Assistant:{"value":<computed number>}\n'
            "Input (copy operation and family_id exactly; compute value from series):\n" + dumps({"family_id": family_id,
                "series": series, "operation": operation}))
    row = dict(sample_id=sample_id, family_id=family_id, split="train", series=series,
               operation=operation, text=text)
    validate_source([row])
    return row
