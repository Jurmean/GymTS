"""Turn sealed Environment evidence into portable, versioned data resources."""
import copy
import json
from pathlib import Path

from gymts.contracts import canonical_json
from gymts.contracts.resources import CAPTURE_ROW, DATA_CAPTURE
from gymts.storage.resources import resource_error
from .data_sources import intersect_policies


ENVIRONMENT_EVENTS = ("session", "environment_request", "observation", "environment_operation",
                      "environment_receipt", "environment_feedback")


class PortablePayloads:
    def __init__(self, catalog):
        self.catalog, self.references, self.attachments = catalog, {}, []

    def copy(self, value):
        if isinstance(value, list):
            return [self.copy(item) for item in value]
        if not isinstance(value, dict):
            return value
        if {"artifact_id", "revision", "uri", "content_hash", "media_type", "schema_ref", "size_bytes"}.issubset(value):
            key = canonical_json(value)
            if key not in self.references:
                content = Path(self.catalog.artifacts.resolve(value)).read_bytes()
                media_type = value["media_type"]
                if media_type == "application/json" or media_type.endswith("+json"):
                    content = canonical_json(self.copy(json.loads(content)))
                asset = self.catalog.publish_asset(content, media_type=media_type)
                if asset not in self.attachments:
                    self.attachments.append(asset)
                self.references[key] = {"dataset_asset_ref": asset, "source_artifact_identity": {
                    name: value[name] for name in ("content_hash", "revision", "schema_ref", "media_type", "size_bytes")}}
            return copy.deepcopy(self.references[key])
        return {key: self.copy(item) for key, item in value.items()}


def capture_run(catalog, run_id, *, source_id, revision, dataset_id, config, source_config,
                split, event_kinds, usage_policy, aliases):
    if catalog.records is None or catalog.artifacts is None:
        raise resource_error("Run capture needs records and artifact services", "unsupported_capability")
    run = catalog.records.get_run(run_id)
    if run["result"] is None or run["execution_snapshot_ref"] is None:
        raise resource_error("Only sealed Runs can become data snapshots", "invalid_state")
    source = catalog.load_source(source_id, revision=revision, config=source_config)
    spec = catalog.artifacts.read_json(run["resolved_spec_ref"])
    environment = spec["scene"]["environment"]
    if (environment["adapter"], environment["version"]) != (source["provider_ref"]["name"], source["provider_ref"]["version"]):
        raise resource_error("Captured Run used another Environment provider", "conflict")
    for key in ("source", "mapping", "options"):
        if key in source["configuration"] and environment[key] != source["configuration"][key]:
            raise resource_error("Captured Environment differs from its fixed source configuration", "conflict")
    if source["reproducibility"]["mode"] == "seeded" and spec["execution"]["seed"] != source["reproducibility"]["seed"]:
        raise resource_error("Captured Run used another source seed", "conflict")
    policies = [source["usage_policy"], usage_policy or source["usage_policy"]]
    prior_policy = spec.get("provenance", {}).get("usage_policy_ref")
    if prior_policy is not None:
        policies.append(catalog.artifacts.read_json(prior_policy))
    usage_policy = intersect_policies(policies)
    selection = sorted(set(ENVIRONMENT_EVENTS if event_kinds is None else event_kinds))
    if not selection or set(selection) - set(ENVIRONMENT_EVENTS):
        raise resource_error("Capture selects only public Environment events")
    portable, rows = PortablePayloads(catalog), []
    for event in run["events"]:
        kind = event["kind"]
        if kind not in selection and not (kind == "artifact" and "session" in selection):
            continue
        payload = event["payload"]
        value = payload["value"] if payload["storage"] == "inline" else catalog.artifacts.read_json(payload["artifact_ref"])
        if kind == "artifact":
            if value.get("role") != "session":
                continue
            kind, value = "session", value["value"]
        rows.append({"event_id": event["event_id"], "seq": event["seq"], "kind": kind,
            "source_event_time": event["source_event_time"], "links": copy.deepcopy(event["links"]),
            "value": portable.copy(value)})
    result, session = run["result"], run["session"]
    observations = [row for row in rows if row["kind"] == "observation"]
    capture = {"protocol_version": DATA_CAPTURE, "run_id": run_id,
        "source_ref": {key: source[key] for key in ("source_id", "config", "revision")},
        "source_trace_identity": {key: run["execution_snapshot_ref"][key] for key in ("content_hash", "revision", "schema_ref")},
        "through_seq": run["events"][-1]["seq"], "event_kinds": selection,
        "status": result["status"], "completion": result["completion"],
        "started_at": result["started_at"], "ended_at": result["ended_at"],
        "requested_scope": copy.deepcopy(spec["execution"]["scope"]),
        "session": portable.copy(session),
        "actual_scope": None if session is None else copy.deepcopy(session["actual_scope"]),
        "seed_used": None if session is None else session["seed_used"],
        "ownership": None if session is None else session["ownership"],
        "initial_clock": None if session is None else copy.deepcopy(session["clock"]),
        "last_observation_clock": None if not observations else observations[-1]["value"]["clock"],
        "observation_count": len(observations),
        "environment_end": portable.copy(result["summary"].get("environment_end")),
        "environment_cleanup": portable.copy(result["summary"].get("cleanup", {}).get("environment")),
        "evidence_status": result["evidence_status"]}
    capture_asset = catalog.publish_asset(canonical_json(capture), media_type="application/json")
    return catalog.register_snapshot(rows, dataset_id=dataset_id, config=config, split=split,
        source_ref={key: source[key] for key in ("source_id", "config", "revision")},
        schema_ref=CAPTURE_ROW, split_origin="sealed-environment-run", attachments=portable.attachments,
        capture=capture_asset, usage_policy=usage_policy,
        features={"capture_status": result["status"], "completion": result["completion"],
                  "observation_count": len(observations), "run_id": run_id}, aliases=aliases)
