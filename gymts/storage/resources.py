"""Portable immutable resource objects, definitions and explicit aliases.

The catalog has no active Run database. Objects can live on shared storage;
verified local cache files supply POSIX readers such as optional Parquet.
"""
import copy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from gymts.contracts import GymTSError, canonical_json
from gymts.contracts.resources import ASSET


def resource_error(message, code="invalid_config"):
    return GymTSError(code, message, stage="resource")


def content_revision(value):
    body = {key: item for key, item in value.items() if key != "revision"}
    return "sha256:" + hashlib.sha256(canonical_json(body)).hexdigest()


def _identity(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)*", value):
        raise resource_error("Resource IDs require safe namespace/name segments")
    if any(part in {".", ".."} for part in value.split("/")):
        raise resource_error("Resource identity cannot contain traversal")
    return value


@contextmanager
def _publication_lock(path):
    """Serialize cooperating POSIX writers on this host, not across hosts.

    Keep the sidecar inode after unlocking: deleting it would let a new writer
    lock a different inode while an existing writer still holds the old one.
    Shared object storage does not gain a distributed transaction from flock.
    """
    try:
        import fcntl
    except ImportError as error:
        raise resource_error("Resource publication requires POSIX local-writer locking", "unsupported_capability") from error
    lock_path = path.with_name("." + path.name + ".lock")
    with lock_path.open("a+b") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        except OSError as error:
            raise resource_error("Filesystem does not support required local publication locking", "unsupported_capability") from error
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _immutable_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with _publication_lock(path):
        # The check and commit must hold the same lock. A second existence
        # check without locking still permits concurrent alias replacement.
        if path.exists():
            if path.is_symlink() or path.read_bytes() != data:
                raise resource_error("Immutable resource identity conflicts with existing bytes", "conflict")
            return
        # Stage in the destination directory; readers see only complete bytes.
        descriptor, temporary = tempfile.mkstemp(prefix=".gymts-resource-", dir=str(path.parent))
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


class ResourceStore:
    _DIRECTORIES = {"dataset": "datasets", "benchmark": "autobench/benchmarks", "source": "sources"}
    _KEYS = {"dataset": "dataset_id", "benchmark": "benchmark_id", "source": "source_id"}
    def __init__(self, data_home, cache_home, schemas):
        self.root, self.cache = Path(data_home).expanduser(), Path(cache_home).expanduser()
        self.schemas = schemas

    def publish_asset(self, content, *, media_type):
        if not isinstance(content, bytes) or not isinstance(media_type, str) or not media_type:
            raise resource_error("Assets need exact bytes and a media type")
        checksum = hashlib.sha256(content).hexdigest()
        reference = {"uri": "gymts-data://sha256/" + checksum, "sha256": checksum,
                     "size_bytes": len(content), "media_type": media_type}
        self.schemas.validate(ASSET, reference)
        _immutable_write(self.root / "objects" / "sha256" / checksum[:2] / checksum, content)
        return reference

    def read_asset(self, reference):
        self.schemas.validate(ASSET, reference)
        checksum = reference["sha256"]
        if reference["uri"] != "gymts-data://sha256/" + checksum:
            raise resource_error("This resource store requires its content-addressed asset URI", "unsupported_capability")
        path = self.root / "objects" / "sha256" / checksum[:2] / checksum
        try:
            if path.is_symlink():
                raise resource_error("Resource objects cannot be symbolic links", "artifact_integrity")
            content = path.read_bytes()
        except OSError as error:
            raise resource_error("Resource object is unavailable", "artifact_unavailable") from error
        if len(content) != reference["size_bytes"] or hashlib.sha256(content).hexdigest() != checksum:
            raise resource_error("Resource object differs from its fixed digest", "artifact_integrity")
        return content

    def local_asset(self, reference):
        content = self.read_asset(reference)
        checksum = reference["sha256"]
        path = self.cache / "objects" / "sha256" / checksum[:2] / checksum
        _immutable_write(path, content)
        return path

    def _directory(self, kind, identity, config=None):
        base = self.root / self._DIRECTORIES[kind] / _identity(identity)
        return base / _identity(config) if config is not None else base

    def publish_definition(self, kind, definition, schema, *, aliases=()):
        value = copy.deepcopy(definition)
        revision = content_revision(value)
        if value.get("revision") not in (None, revision):
            raise resource_error("Definition revision differs from its canonical content", "conflict")
        value["revision"] = revision
        self.schemas.validate(schema, value)
        key = self._KEYS[kind]
        directory = self._directory(kind, value[key], value.get("config"))
        if isinstance(aliases, str):
            raise resource_error("Release labels must be supplied as a sequence")
        try:
            aliases = tuple(aliases)
        except TypeError as error:
            raise resource_error("Release labels must be supplied as a sequence") from error
        alias_data = canonical_json({"revision": revision})
        for alias in aliases:
            _identity(alias)
            if "/" in alias or alias in {"latest", "main", "master"}:
                raise resource_error("Aliases must be explicit immutable release labels")
            path = directory / "aliases" / (alias + ".json")
            if path.exists() and (path.is_symlink() or path.read_bytes() != alias_data):
                raise resource_error("Release label already identifies a different immutable revision", "conflict")
        data = canonical_json(value)
        _immutable_write(directory / "revisions" / revision.removeprefix("sha256:") / "manifest.json", data)
        for alias in aliases:
            _immutable_write(directory / "aliases" / (alias + ".json"), alias_data)
        return value

    def load_definition(self, kind, identity, revision, schema, *, config=None):
        directory = self._directory(kind, identity, config)
        if not isinstance(revision, str) or revision in {"latest", "main", "master", ""}:
            raise resource_error("Loading resources requires a fixed revision or explicit release label")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", revision):
            resolved = revision
        else:
            _identity(revision)
            if "/" in revision:
                raise resource_error("Invalid release label")
            try:
                resolved = json.loads((directory / "aliases" / (revision + ".json")).read_bytes())["revision"]
            except (OSError, ValueError, KeyError) as error:
                raise resource_error("Resource release label is not registered", "artifact_unavailable") from error
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", resolved):
            raise resource_error("Resource label has an invalid fixed revision", "artifact_integrity")
        try:
            value = json.loads((directory / "revisions" / resolved[7:] / "manifest.json").read_bytes())
        except (OSError, ValueError) as error:
            raise resource_error("Resource revision is unavailable", "artifact_unavailable") from error
        if isinstance(schema, (tuple, list)):
            schema_ref = value.get("protocol_version")
            if schema_ref not in schema:
                raise resource_error("Unsupported resource definition version", "schema_mismatch")
        else:
            schema_ref = schema
        self.schemas.validate(schema_ref, value)
        key = self._KEYS[kind]
        if (value[key] != identity or value.get("config") != config
                or value["revision"] != resolved or content_revision(value) != resolved):
            raise resource_error("Resource manifest does not match its fixed identity", "artifact_integrity")
        return value

    def definitions(self, kind, schema):
        directory = self.root / self._DIRECTORIES[kind]
        result = []
        if not directory.exists():
            return result
        for path in sorted(directory.glob("**/revisions/*/manifest.json")):
            try:
                item = json.loads(path.read_bytes())
                key = self._KEYS[kind]
                result.append(self.load_definition(kind, item[key], item["revision"], schema,
                                                   config=item.get("config")))
            except (ValueError, KeyError) as error:
                raise resource_error("Catalog contains an invalid manifest", "artifact_integrity") from error
        return result
