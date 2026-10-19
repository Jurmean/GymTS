"""Public, deterministic helpers for trusted GymTS v1 plugins.

These helpers do not create sessions, load integrations, or grant additional access.
Artifact payloads still require an authorized service supplied by the framework."""

import copy
import re
from datetime import datetime, timedelta, timezone

from gymts.contracts import GymTSError, new_id


def fail(code, message, method=None, **links):
    raise GymTSError(code, message, stage="plugin", method=method, links=links)


def component(name, version="1.0.0"):
    return {"name": name, "version": version, "origin_ref": None}


def payload(schema_ref, value):
    return {"schema_ref": schema_ref, "storage": "inline", "value": value}


def unpack(value, services=None):
    if value["storage"] == "inline":
        return copy.deepcopy(value["value"])
    if services is None:
        fail("permission_denied", "Artifact payload requires an authorized data service")
    return services.read_json(value["artifact_ref"])


def parse_time(value):
    if not isinstance(value, str):
        fail("invalid_request", "The replay environment requires RFC3339 timestamps")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail("invalid_request", "Invalid RFC3339 timestamp")
    if result.tzinfo is None:
        fail("invalid_request", "A timestamp requires an explicit timezone")
    return result.astimezone(timezone.utc)


def timestamp(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def duration(value):
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(ms|s|min|h)", value or "")
    if not match or float(match.group(1)) <= 0:
        fail("invalid_config", "Duration must be positive and use ms, s, min, or h")
    return timedelta(seconds=float(match.group(1)) * {"ms": .001, "s": 1, "min": 60, "h": 3600}[match.group(2)])


def empty_update(done=False):
    return {"inputs": [], "feedback": [], "closed_cases": [], "done": done}


def clock(now, domain="event_time", visible=None):
    return {"domain": domain, "now": now, "visible_until": now if visible is None else visible}


def end_info(reason="read_scope_end", terminated=False, truncated=False):
    return {"reason": reason, "terminated": terminated, "truncated": truncated, "detail": None}


def identifier(prefix):
    # Public ids are opaque; new_id's optional prefix is deliberately not assumed.
    return prefix + "-" + new_id()


__all__ = ["fail", "component", "payload", "unpack", "parse_time", "timestamp",
           "duration", "empty_update", "clock", "end_info", "identifier"]
