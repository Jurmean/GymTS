"""Content-addressed local artifacts with durable, immutable publication."""

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Dict
from uuid import uuid4

from gymts.contracts import GymTSError, canonical_json, digest


def storage_error(code: str, message: str, **details: Any) -> GymTSError:
    return GymTSError(code, message, stage="storage", run_id=details.pop("run_id", None), details=details)


def _publish(path: Path, content: bytes, root: Path) -> None:
    """Link a synced temporary file into place, without replacing old evidence."""
    directory = None
    temporary = None
    try:
        # Resolve each directory through an opened parent, refusing symlinks.
        # Checking Path.resolve() before a path-based write leaves a race in
        # which a directory can be replaced after the containment check.
        directory = os.open(str(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for name in path.relative_to(root).parts[:-1]:
            try:
                os.mkdir(name, dir_fd=directory)
                os.fsync(directory)
            except FileExistsError:
                pass
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        temporary = ".pending-" + uuid4().hex
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=directory)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        except FileExistsError:
            descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            with os.fdopen(descriptor, "rb") as stream:
                previous = stream.read()
            if previous != content:
                raise storage_error("conflict", "Immutable artifact already has different content", path=str(path))
        os.fsync(directory)
    except OSError as error:
        raise storage_error("persistence_failed", "Artifact could not be durably committed", path=str(path), reason=str(error)) from error
    finally:
        if directory is not None:
            try:
                if temporary is not None:
                    os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
            finally:
                os.close(directory)


class ArtifactStore:
    """Local CAS. Only references published by this store can be resolved.

    Paths and file: URLs are intentionally not accepted as ArtifactRef.uri.
    Import external content explicitly through save_artifact first.
    """

    def __init__(self, root: Any):
        operations = {os.open, os.mkdir, os.link, os.unlink}
        supported = (all(hasattr(os, flag) for flag in ("O_DIRECTORY", "O_NOFOLLOW"))
                     and operations.issubset(os.supports_dir_fd)
                     and os.link in os.supports_follow_symlinks)
        if not supported:
            raise storage_error("unsupported_capability", "The local artifact backend requires POSIX directory-relative operations and no-follow file access")
        self.root = Path(root).resolve()
        self.artifacts = self
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "blobs").mkdir(exist_ok=True)
        (self.root / "refs").mkdir(exist_ok=True)

    def save_artifact(self, content: bytes, metadata: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(content, bytes):
            raise storage_error("invalid_artifact", "Artifact content must be bytes")
        if not isinstance(metadata, dict):
            raise storage_error("invalid_artifact", "Artifact metadata must be a JSON object")
        try:
            metadata = json.loads(canonical_json(metadata))
        except (TypeError, ValueError) as error:
            raise storage_error("invalid_artifact", "Artifact metadata must contain finite JSON", reason=str(error)) from error
        media_type = metadata.get("media_type", "application/octet-stream")
        schema_ref = metadata.get("schema_ref")
        if not isinstance(media_type, str) or not media_type:
            raise storage_error("invalid_artifact", "media_type must be a nonempty string")
        if schema_ref is not None and (not isinstance(schema_ref, str) or not schema_ref):
            raise storage_error("invalid_artifact", "schema_ref must be a nonempty string or null")
        content_hash = hashlib.sha256(content).hexdigest()
        # Schema/media/source metadata also has an immutable identity. Equal bytes
        # may legitimately be interpreted under two explicitly fixed schemas.
        artifact_id = digest({"content_hash": content_hash, "metadata": metadata}).removeprefix("sha256:")
        reference = {
            "artifact_id": artifact_id,
            "revision": content_hash,
            "uri": "gymts-artifact://{}/{}".format(artifact_id, content_hash),
            "content_hash": content_hash,
            "media_type": media_type,
            "schema_ref": schema_ref,
            "size_bytes": len(content),
        }
        _publish(self._blob_path(content_hash), content, self.root)
        _publish(self._ref_path(artifact_id, content_hash), canonical_json({"reference": reference, "metadata": metadata}), self.root)
        return reference

    def save_json(self, value: Any, schema_ref: str) -> Dict[str, Any]:
        if not isinstance(schema_ref, str) or not schema_ref:
            raise storage_error("invalid_artifact", "Structured JSON requires schema_ref")
        try:
            data = canonical_json(value)
        except (TypeError, ValueError) as error:
            raise storage_error("invalid_artifact", "Artifact must contain finite JSON", reason=str(error)) from error
        return self.save_artifact(data, {"media_type": "application/json", "schema_ref": schema_ref})

    def _blob_path(self, content_hash: str) -> Path:
        return self.root / "blobs" / content_hash[:2] / content_hash

    def _ref_path(self, artifact_id: str, revision: str) -> Path:
        return self.root / "refs" / artifact_id / (revision + ".json")

    def _committed_content(self, ref: Dict[str, Any]) -> tuple:
        if not isinstance(ref, dict):
            raise storage_error("invalid_artifact", "ArtifactRef must be an object")
        required = {"artifact_id", "revision", "uri", "content_hash", "media_type", "schema_ref", "size_bytes"}
        if (set(ref) != required or not isinstance(ref["uri"], str)
                or not isinstance(ref["media_type"], str) or not ref["media_type"]
                or ref["schema_ref"] is not None and (not isinstance(ref["schema_ref"], str) or not ref["schema_ref"])
                or isinstance(ref["size_bytes"], bool) or not isinstance(ref["size_bytes"], int) or ref["size_bytes"] < 0):
            raise storage_error("invalid_artifact", "ArtifactRef fields do not describe a committed local artifact")
        artifact_id, revision = ref.get("artifact_id"), ref.get("revision")
        if not all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) for value in (artifact_id, revision)):
            raise storage_error("invalid_artifact", "Artifact identity is not a local content identity")
        manifest_path = self._ref_path(artifact_id, revision)
        try:
            # Ref metadata cannot be relabeled to evade schema or content checks.
            resolved_manifest = manifest_path.resolve(strict=True)
            resolved_manifest.relative_to(self.root / "refs")
            manifest = json.loads(resolved_manifest.read_bytes(), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            if not isinstance(manifest, dict) or not isinstance(manifest.get("reference", manifest), dict):
                raise storage_error("artifact_integrity", "Artifact manifest must contain an ArtifactRef object", artifact_id=artifact_id)
            expected = manifest.get("reference", manifest)
        except (OSError, ValueError) as error:
            raise storage_error("artifact_unavailable", "Artifact reference was not committed in this store", artifact_id=artifact_id) from error
        try:
            if canonical_json(ref) != canonical_json(expected):
                raise storage_error("artifact_integrity", "ArtifactRef differs from its immutable manifest", artifact_id=artifact_id)
            if "metadata" in manifest and digest({"content_hash": revision, "metadata": manifest["metadata"]}).removeprefix("sha256:") != artifact_id:
                raise storage_error("artifact_integrity", "Artifact metadata does not match its fixed identity", artifact_id=artifact_id)
        except (TypeError, ValueError) as error:
            raise storage_error("invalid_artifact", "Artifact reference must contain finite JSON") from error
        path = self._blob_path(revision)
        try:
            # Detect local tampering, including replacement by an external symlink.
            resolved = path.resolve(strict=True)
            resolved.relative_to(self.root / "blobs")
            data = resolved.read_bytes()
        except (OSError, ValueError) as error:
            raise storage_error("artifact_unavailable", "Artifact content is unavailable or outside this store", artifact_id=artifact_id) from error
        if len(data) != ref["size_bytes"] or hashlib.sha256(data).hexdigest() != ref["content_hash"]:
            raise storage_error("artifact_integrity", "Artifact bytes do not match the committed digest", artifact_id=artifact_id)
        return resolved, data

    def resolve(self, ref: Dict[str, Any]) -> Path:
        return self._committed_content(ref)[0]

    def read_json(self, ref: Dict[str, Any]) -> Any:
        if not isinstance(ref, dict) or ref.get("media_type") != "application/json" or not ref.get("schema_ref"):
            raise storage_error("invalid_artifact", "read_json requires a structured JSON artifact")
        try:
            # Decode the exact bytes whose hash was verified, rather than
            # reopening a path that could have changed after verification.
            return json.loads(self._committed_content(ref)[1], parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except (ValueError, UnicodeError) as error:
            raise storage_error("artifact_integrity", "Committed JSON cannot be decoded", reason=str(error)) from error

    def read_view(self, ref: Dict[str, Any]) -> Dict[str, Any]:
        """Read only declared sources using an explicit, small selector language.

        gymts.selection/1 supports all, json_pointer and rows. Other selectors
        must be implemented by a separate view adapter rather than ignored.
        """
        required = {"view_id", "revision", "source_refs", "selection", "as_of", "purpose"}
        if not isinstance(ref, dict) or not required.issubset(ref):
            raise storage_error("invalid_view", "DataViewRef is missing required fields")
        if ref["purpose"] not in {"prepare", "runtime", "evaluation", "dataset_build"}:
            raise storage_error("invalid_view", "Unknown DataViewRef purpose")
        if ref["as_of"] is not None:
            raise storage_error("unsupported_capability", "This JSON view adapter requires an already fixed source and does not implement temporal as_of filtering")
        selection = ref["selection"]
        if not isinstance(selection, dict):
            raise storage_error("invalid_view", "Selection Payload must be an object")
        if selection.get("schema_ref") != "gymts.selection/1":
            raise storage_error("unsupported_capability", "Unsupported view selection schema", schema_ref=selection.get("schema_ref"))
        if selection.get("storage") == "inline" and "value" in selection and "artifact_ref" not in selection:
            options = selection["value"]
        elif selection.get("storage") == "artifact" and "artifact_ref" in selection and "value" not in selection:
            options = self.read_json(selection["artifact_ref"])
        else:
            raise storage_error("invalid_view", "Selection Payload must use exactly one storage form")
        if not isinstance(options, dict):
            raise storage_error("invalid_view", "Selection must be an object")
        kind = options.get("kind")
        allowed = {"all": {"kind", "source_index"}, "json_pointer": {"kind", "source_index", "pointer"}, "rows": {"kind", "source_index", "start", "stop"}}
        if kind not in allowed or set(options) - allowed[kind]:
            raise storage_error("unsupported_capability", "Unknown selection kind or fields", kind=kind)
        index = options.get("source_index", 0)
        sources = ref["source_refs"]
        if not isinstance(sources, list) or isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(sources):
            raise storage_error("invalid_view", "Selection source_index is outside source_refs")
        value = self.read_json(sources[index])
        if kind == "json_pointer":
            pointer = options.get("pointer")
            if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
                raise storage_error("invalid_view", "pointer must be an RFC6901 JSON pointer")
            try:
                for segment in pointer.split("/")[1:] if pointer else []:
                    segment = segment.replace("~1", "/").replace("~0", "~")
                    if isinstance(value, list):
                        if not re.fullmatch(r"0|[1-9][0-9]*", segment):
                            raise ValueError("Invalid array index")
                        value = value[int(segment)]
                    else:
                        value = value[segment]
            except (KeyError, IndexError, TypeError, ValueError) as error:
                raise storage_error("invalid_view", "JSON pointer does not select a source value") from error
        elif kind == "rows":
            start, stop = options.get("start", 0), options.get("stop")
            if not isinstance(value, list) or isinstance(start, bool) or not isinstance(start, int) or start < 0 or (stop is not None and (isinstance(stop, bool) or not isinstance(stop, int) or stop < start)):
                raise storage_error("invalid_view", "rows requires a list and a nonnegative [start,stop) slice")
            value = value[start:stop]
        return {"schema_ref": "gymts.json/1" if kind == "json_pointer" else sources[index]["schema_ref"], "storage": "inline", "value": value}
