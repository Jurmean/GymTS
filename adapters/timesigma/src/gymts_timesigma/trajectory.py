"""Portable, immutable evidence built on native RecordSnapshots and CAS refs.

An imported archive is historical evidence, not a newly executed GymTS Run.
It can be inspected offline and its model artifacts can be explicitly reused.
"""

import hashlib
import json
from pathlib import Path
import zipfile

from gymts.contracts import GymTSError, canonical_json, utc_now


ARCHIVE = "gymts.timesigma.evidence-archive/1"
_REF_KEYS = {"artifact_id", "revision", "uri", "content_hash", "media_type", "schema_ref", "size_bytes"}


def _references(value):
    if isinstance(value, dict):
        if set(value) == _REF_KEYS:
            yield value
        else:
            for item in value.values():
                yield from _references(item)
    elif isinstance(value, list):
        for item in value:
            yield from _references(item)


def describe_run(gym, run_id):
    """Use public records to expose preparation, sealing status and events."""
    run = gym.records.get_run(run_id)
    return {"run_id": run_id, "status": run["result"]["status"] if run["result"] else "running",
            "event_count": len(run["events"]), "preparation": run["preparation"],
            "resolved_spec_ref": run["resolved_spec_ref"], "result_ref": run["result_ref"],
            "trace_ref": run["execution_snapshot_ref"], "outcomes": gym.records.list_outcome_refs(run_id)}


def export_evidence(gym, run_ids, path, *, roots=()):
    """Freeze selected Runs and recursively include their exact CAS evidence.

    CAS metadata is part of ArtifactRef identity. Preserve its native manifest
    instead of changing identifiers during import. No database tables are copied
    and no historical execution is replayed into the destination record index.
    """
    target = Path(path)
    if target.exists():
        raise GymTSError("conflict", "Evidence archive already exists")
    snapshot = gym.records.snapshot(list(run_ids), {"outcomes_as_of": utc_now()})
    runs = []
    for frozen in snapshot["runs"]:
        original = gym.records.get_run(frozen["run_id"])
        # A fixed prefix never leaks a later final result or event.
        visible = frozen["result_ref"] is not None
        selected = [ref for ref in gym.records.list_outcome_refs(frozen["run_id"])
                    if ref in snapshot["outcome_refs"]]
        runs.append({"run_id": frozen["run_id"], "metadata": original["metadata"],
            "events": [event for event in original["events"] if event["seq"] <= frozen["through_seq"]],
            "event_refs": [ref for event, ref in zip(original["events"], original["event_refs"])
                           if event["seq"] <= frozen["through_seq"]],
            "result_ref": frozen["result_ref"],
            "trace_ref": original["execution_snapshot_ref"] if visible else None,
            "resolved_spec_ref": original["resolved_spec_ref"],
            "outcomes": gym.records.read_outcomes({"run_ids": [frozen["run_id"]],
                "outcome_refs": selected})})
        # Native outcomes are JSON CAS objects; republishing the same canonical
        # bytes and schema recovers their existing immutable ArtifactRef.
        runs[-1]["outcome_artifact_refs"] = [gym.artifacts.save_json(outcome, "gymts.outcome/1")
                                              for outcome in runs[-1]["outcomes"]]
        runs[-1]["metadata_ref"] = gym.artifacts.save_json(original["metadata"], "gymts.timesigma/run-metadata/1")
    body = {"schema_version": ARCHIVE, "captured_at": snapshot["captured_at"],
            "record_snapshot_ref": snapshot["snapshot_ref"], "runs": runs, "roots": list(roots)}
    # Bind the archive index to CAS too, including inline metadata and roots.
    body["index_ref"] = gym.artifacts.save_json(body, "gymts.timesigma/evidence-index/1")
    pending, found, blobs = list(_references(body)), {}, {}
    while pending:
        ref = pending.pop()
        key = (ref["artifact_id"], ref["revision"])
        if key in found:
            if found[key]["reference"] != ref:
                raise GymTSError("artifact_integrity", "Conflicting references in archive closure")
            continue
        content = gym.artifacts.resolve(ref).read_bytes()
        # Native CAS layout, version 1. Read only after resolve verified the ref.
        manifest_path = gym.artifacts.root / "refs" / ref["artifact_id"] / (ref["revision"] + ".json")
        manifest = json.loads(manifest_path.read_bytes())
        if manifest.get("reference") != ref or "metadata" not in manifest:
            raise GymTSError("artifact_integrity", "CAS manifest is missing its original metadata")
        found[key] = manifest
        blobs[ref["content_hash"]] = content
        pending.extend(_references(manifest["metadata"]))
        if ref["media_type"] == "application/json":
            pending.extend(_references(json.loads(content)))
    body["artifacts"] = [found[key] for key in sorted(found)]
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also prevents an archive from silently replacing evidence.
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", canonical_json(body))
        for name, content in sorted(blobs.items()):
            archive.writestr("blobs/" + name, content)
    return {"path": str(target.resolve()), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "record_snapshot_ref": snapshot["snapshot_ref"], "run_count": len(runs),
            "artifact_count": len(found), "schema_version": ARCHIVE}


def _read_archive(path):
    """Validate the whole archive before publishing any destination references."""
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or "manifest.json" not in names:
            raise GymTSError("artifact_integrity", "Duplicate or missing archive entries")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("schema_version") != ARCHIVE:
            raise GymTSError("schema_mismatch", "Unknown evidence archive version")
        blobs, seen = {}, set()
        expected = {"manifest.json"}
        for item in manifest["artifacts"]:
            ref, metadata = item["reference"], item["metadata"]
            if set(ref) != _REF_KEYS:
                raise GymTSError("artifact_integrity", "Malformed archived ArtifactRef")
            key = (ref["artifact_id"], ref["revision"])
            if key in seen:
                raise GymTSError("artifact_integrity", "Duplicate archived artifact identity")
            seen.add(key)
            name = "blobs/" + ref["content_hash"]
            expected.add(name)
            data = archive.read(name)
            checksum = hashlib.sha256(data).hexdigest()
            artifact_id = hashlib.sha256(canonical_json({"content_hash": checksum, "metadata": metadata})).hexdigest()
            if (checksum != ref["content_hash"] or ref["revision"] != checksum
                    or ref["artifact_id"] != artifact_id or ref["size_bytes"] != len(data)
                    or ref["uri"] != "gymts-artifact://{}/{}".format(artifact_id, checksum)
                    or ref["media_type"] != metadata.get("media_type", "application/octet-stream")
                    or ref["schema_ref"] != metadata.get("schema_ref")):
                raise GymTSError("artifact_integrity", "Archived bytes or metadata differ from their identity")
            blobs[key] = data
        if set(names) != expected:
            raise GymTSError("artifact_integrity", "Unexpected or missing archive entry")
        # Check the reference closure, including JSON inside artifact blobs.
        references = list(_references({key: value for key, value in manifest.items() if key != "artifacts"}))
        for item in manifest["artifacts"]:
            ref = item["reference"]
            references.extend(_references(item["metadata"]))
            if ref["media_type"] == "application/json":
                references.extend(_references(json.loads(blobs[(ref["artifact_id"], ref["revision"])])))
        index = {(item["reference"]["artifact_id"], item["reference"]["revision"]): item["reference"]
                 for item in manifest["artifacts"]}
        if any(index.get((ref["artifact_id"], ref["revision"])) != ref for ref in references):
            raise GymTSError("artifact_integrity", "Evidence archive has an incomplete reference closure")
        def read(ref):
            return json.loads(blobs[(ref["artifact_id"], ref["revision"])])
        body = {key: value for key, value in manifest.items() if key not in {"artifacts", "index_ref"}}
        if read(manifest["index_ref"]) != body:
            raise GymTSError("artifact_integrity", "Archive index differs from its fixed CAS evidence")
        snapshot = read(manifest["record_snapshot_ref"])
        if ([run["run_id"] for run in snapshot["runs"]] != [run["run_id"] for run in manifest["runs"]]
                or snapshot["captured_at"] != manifest["captured_at"]):
            raise GymTSError("artifact_integrity", "Archive Run selection differs from the fixed RecordSnapshot")
        outcomes = set()
        for frozen, run in zip(snapshot["runs"], manifest["runs"]):
            if (run["result_ref"] != frozen["result_ref"] or len(run["events"]) != frozen["through_seq"]
                    or len(run["events"]) != len(run["event_refs"])
                    or read(run["metadata_ref"]) != run["metadata"]
                    or run["metadata"]["run_id"] != run["run_id"]
                    or run["metadata"]["resolved_spec_ref"] != run["resolved_spec_ref"]):
                raise GymTSError("artifact_integrity", "Archived Run metadata or event boundary changed")
            for sequence, (event, reference) in enumerate(zip(run["events"], run["event_refs"]), 1):
                if event != read(reference) or event["seq"] != sequence or event["run_id"] != run["run_id"]:
                    raise GymTSError("artifact_integrity", "Archived event differs from its original CAS record")
            if run["result_ref"] is not None:
                result = read(run["result_ref"])
                if (result["run_id"] != run["run_id"] or result["status"] != frozen["status"]
                        or result["trace_ref"] != run["trace_ref"] or read(run["trace_ref"])["events"] != run["events"]):
                    raise GymTSError("artifact_integrity", "Archived sealed result differs from its native execution trace")
            elif run["trace_ref"] is not None:
                raise GymTSError("artifact_integrity", "An execution prefix cannot expose a later sealed trace")
            if len(run["outcomes"]) != len(run["outcome_artifact_refs"]):
                raise GymTSError("artifact_integrity", "Archived outcome references are incomplete")
            for outcome, reference in zip(run["outcomes"], run["outcome_artifact_refs"]):
                if read(reference) != outcome:
                    raise GymTSError("artifact_integrity", "Archived outcome differs from its original CAS record")
                outcomes.add((outcome["outcome_id"], outcome["revision"]))
        if outcomes != {(item["outcome_id"], item["revision"]) for item in snapshot["outcome_refs"]}:
            raise GymTSError("artifact_integrity", "Archived outcomes differ from the fixed RecordSnapshot")
    return manifest, blobs


def inspect_archive(path):
    manifest, _ = _read_archive(path)
    return manifest


def import_evidence(gym, path):
    """Republish verified CAS identities, retaining Runs as imported evidence."""
    manifest, blobs = _read_archive(path)
    for item in manifest["artifacts"]:
        ref = item["reference"]
        imported = gym.artifacts.save_artifact(blobs[(ref["artifact_id"], ref["revision"])], item["metadata"])
        if imported != ref:
            raise GymTSError("artifact_integrity", "Imported CAS identity changed")
    reference = gym.artifacts.save_json(manifest, "gymts.timesigma/imported-evidence/1")
    return {"status": "imported_evidence", "archive_ref": reference,
            "record_snapshot_ref": manifest["record_snapshot_ref"],
            "run_ids": [run["run_id"] for run in manifest["runs"]],
            "artifact_count": len(manifest["artifacts"])}
