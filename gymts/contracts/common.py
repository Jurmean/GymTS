"""JSON wire contracts, stable identities and structured errors."""
from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def new_id(prefix: str = "id") -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def canonical_json(value: Any) -> bytes:
    active = set()
    def check(item):
        if item is None or type(item) in (str, int, bool):
            return
        if type(item) is float:
            if not math.isfinite(item):
                raise ValueError("JSON number must be finite")
            return
        if not isinstance(item, (dict, list)):
            raise TypeError("JSON value must use dictionaries, lists and scalars")
        if id(item) in active:
            raise ValueError("Circular JSON value")
        active.add(id(item))
        if isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                raise TypeError("JSON object keys must be strings")
            children = item.values()
        else:
            children = item
        for child in children:
            check(child)
        active.remove(id(item))
    check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


class GymTSError(Exception):
    def __init__(self, code: str, message: str, *, stage: str = "validation",
                 method: Optional[str] = None, run_id: Optional[str] = None,
                 links: Optional[dict] = None, details: Optional[dict] = None,
                 retryable: bool = False, side_effect: str = "none"):
        super().__init__(message)
        linked = dict(links or {})
        if details:
            linked.update(details)
        self.info = {"code": code, "stage": stage, "method": method, "message": message,
                     "run_id": run_id, "links": linked, "retryable": retryable,
                     "side_effect": side_effect}
        self.code, self.stage, self.run_id = code, stage, run_id

    def to_dict(self) -> dict:
        return dict(self.info)


def parse_time(value: Any) -> Any:
    if isinstance(value, bool):
        raise GymTSError("invalid_config", "Boolean is not a time point")
    if isinstance(value, int) and value >= 0:
        return value
    if not isinstance(value, str):
        raise GymTSError("invalid_config", "Time point must be RFC3339 or a nonnegative step")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone missing")
        return parsed.astimezone(timezone.utc)
    except ValueError as exc:
        raise GymTSError("invalid_config", "Invalid RFC3339 time point") from exc


def time_compare(left: Any, right: Any) -> int:
    a, b = parse_time(left), parse_time(right)
    if type(a) is not type(b):
        raise GymTSError("invalid_config", "Mixed clock domains")
    return (a > b) - (a < b)


def in_scope(point: Any, scope: dict) -> bool:
    return time_compare(point, scope["start"]) >= 0 and (
        scope["end"] is None or time_compare(point, scope["end"]) < 0)


def duration_seconds(value: str) -> float:
    if not isinstance(value, str):
        raise GymTSError("invalid_config", "Duration must be a string with units")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s|min|h|d)", value or "")
    if not match or float(match[1]) <= 0:
        raise GymTSError("invalid_config", "Duration requires a positive value and ms/s/min/h/d unit")
    seconds = float(match[1]) * {"ms": .001, "s": 1, "min": 60, "h": 3600, "d": 86400}[match[2]]
    if not math.isfinite(seconds):
        raise GymTSError("invalid_config", "Duration must be finite")
    return seconds


def shift_time(value: str, seconds: float) -> str:
    parsed = parse_time(value)
    if not isinstance(parsed, datetime):
        raise GymTSError("unsupported_capability", "Durations cannot be applied to a step clock")
    return (parsed + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def intersect_scope(left: dict, right: dict) -> dict:
    start = left["start"] if time_compare(left["start"], right["start"]) >= 0 else right["start"]
    ends = [v for v in (left["end"], right["end"]) if v is not None]
    end = None if not ends else min(ends, key=parse_time)
    if end is not None and time_compare(start, end) >= 0:
        raise GymTSError("invalid_request", "Requested scope has no overlap with actual scope")
    return {"start": start, "end": end}


def inline(value: Any, schema_ref: str = "gymts.json/1") -> Dict[str, Any]:
    return {"schema_ref": schema_ref, "storage": "inline", "value": value}

