"""Dataset discovery and public reading for EnvironmentTS.

Evaluation references are exposed only through an explicitly separate service
passed to AutoBenchTS benchmark resolvers. Neither service executes a model.
"""
import copy
import json

from gymts.contracts import canonical_json
from gymts.contracts.resources import DATASET, DATASET_V2
from gymts.storage.resources import content_revision, resource_error
from .data_sources import DataOrganization, intersect_policies


JSONL_READER = {"name": "gymts.jsonl-reader", "version": "1.0.0", "origin_ref": None}
PARQUET_READER = {"name": "gymts.parquet-reader", "version": "1.0.0", "origin_ref": None}


class JSONLReader:
    def read(self, store, assets):
        rows = []
        for asset in assets:
            if asset["media_type"] not in {"application/jsonl", "application/x-ndjson"}:
                raise resource_error("JSONL reader received another media type", "schema_mismatch")
            try:
                rows.extend(json.loads(line) for line in store.read_asset(asset).decode("utf-8").splitlines() if line.strip())
            except (ValueError, UnicodeError) as error:
                raise resource_error("Dataset JSONL cannot be decoded", "artifact_integrity") from error
        return rows


class ParquetReader:
    def read(self, store, assets):
        try:
            import pyarrow.parquet as parquet
        except ImportError as error:
            raise resource_error("Parquet reading requires the optional gymts[datasets] dependency", "unsupported_capability") from error
        rows = []
        for asset in assets:
            if asset["media_type"] not in {"application/vnd.apache.parquet", "application/x-parquet"}:
                raise resource_error("Parquet reader received another media type", "schema_mismatch")
            try:
                rows.extend(parquet.read_table(store.local_asset(asset)).to_pylist())
            except (OSError, ValueError) as error:
                raise resource_error("Dataset Parquet cannot be decoded", "artifact_integrity") from error
        return rows


_JSONL = JSONLReader()
_PARQUET = ParquetReader()


class AssetReadServices:
    """Only the exact shard references selected for this reader invocation."""
    def __init__(self, store, references):
        self._store = store
        self._allowed = {canonical_json(reference) for reference in references}

    def _check(self, reference):
        if canonical_json(reference) not in self._allowed:
            raise resource_error("Dataset reader requested an asset outside its selected view", "permission_denied")

    def read_asset(self, reference):
        self._check(reference)
        return self._store.read_asset(reference)

    def local_asset(self, reference):
        self._check(reference)
        return self._store.local_asset(reference)


class DatasetHandle:
    """A public dataset view. Raw source and answer assets are not returned."""
    def __init__(self, catalog, manifest, split, *, indices=None):
        self._catalog, self._manifest, self.split = catalog, copy.deepcopy(manifest), split
        self._indices, self._rows = indices, None

    @property
    def info(self):
        item = self._manifest
        result = {"dataset_id": item["dataset_id"], "config": item["config"], "revision": item["revision"],
                "split": self.split, "row_count": len(self), "schema_ref": item["schema_ref"],
                "features": copy.deepcopy(item["features"]), "usage_policy": copy.deepcopy(item["usage_policy"]),
                "selection": None if self._indices is None else list(self._indices)}
        if item["protocol_version"] == DATASET_V2:
            result.update({key: copy.deepcopy(item[key]) for key in ("kind", "origin", "lineage")})
        return result

    @property
    def features(self):
        return copy.deepcopy(self._manifest["features"])

    def __len__(self):
        return len(self._indices) if self._indices is not None else self._manifest["splits"][self.split]["row_count"]

    def _read(self):
        if self._rows is None:
            split = self._manifest["splits"][self.split]
            assets = [self._manifest["inputs"][index] for index in split["input_indices"]]
            rows = self._catalog._read(self._manifest["reader_ref"], assets)
            if len(rows) != split["row_count"]:
                raise resource_error("Public dataset row count differs from its fixed manifest", "artifact_integrity")
            for row in rows:
                self._catalog.schemas.validate(self._manifest["schema_ref"], row)
            if rows and all(isinstance(row, dict) and "sample_id" in row for row in rows):
                tokens = [canonical_json(row["sample_id"]) for row in rows]
                if len(tokens) != len(set(tokens)):
                    raise resource_error("Dataset sample IDs must preserve unique source-row identities", "conflict")
            self._rows = rows
        return self._rows

    def __getitem__(self, index):
        if isinstance(index, slice):
            return self.select(list(range(len(self)))[index])
        if type(index) is not int or not -len(self) <= index < len(self):
            raise IndexError(index)
        index %= len(self)
        return copy.deepcopy(self._read()[self._indices[index] if self._indices is not None else index])

    def __iter__(self):
        for index in range(len(self)):
            yield self[index]

    def select(self, indices):
        selected = list(indices)
        if any(type(index) is not int or not 0 <= index < len(self) for index in selected):
            raise resource_error("Dataset selection contains an invalid row index")
        if len(set(selected)) != len(selected):
            raise resource_error("Dataset views cannot duplicate source rows implicitly", "conflict")
        mapped = [self._indices[index] if self._indices is not None else index for index in selected]
        view = DatasetHandle(self._catalog, self._manifest, self.split, indices=mapped)
        view._rows = self._rows
        return view

    def filter(self, predicate):
        return self.select([index for index, row in enumerate(self) if predicate(row)])

    def iter_batches(self, batch_size=100):
        if type(batch_size) is not int or batch_size <= 0:
            raise resource_error("Dataset batch size must be a positive integer")
        for start in range(0, len(self), batch_size):
            yield [self[index] for index in range(start, min(start + batch_size, len(self)))]

    def sample_ids(self):
        return [row["sample_id"] for row in self]

    def read_series(self):
        return self._catalog._read(self._manifest["reader_ref"], self._manifest["series"])

    def read_asset(self, reference):
        """Read only this public view's input, series and captured attachments."""
        split = self._manifest["splits"][self.split]
        public = [self._manifest["inputs"][i] for i in split["input_indices"]]
        public += self._manifest["series"] + self._manifest.get("attachments", [])
        if reference not in public:
            raise resource_error("Asset is outside the public dataset view", "permission_denied")
        return self._catalog.store.read_asset(reference)

    def resolve_payload(self, value):
        """Read an explicitly portable capture reference without the Run store."""
        if isinstance(value, dict) and set(value) == {"dataset_asset_ref", "source_artifact_identity"}:
            content = self.read_asset(value["dataset_asset_ref"])
            media_type = value["dataset_asset_ref"]["media_type"]
            return json.loads(content) if media_type == "application/json" or media_type.endswith("+json") else content
        return copy.deepcopy(value)

    def read_capture(self):
        reference = self._manifest.get("lineage", {}).get("capture")
        return None if reference is None else json.loads(self._catalog.store.read_asset(reference))

    def to_hf(self):
        try:
            from datasets import Dataset
        except ImportError as error:
            raise resource_error("HF conversion requires the optional datasets package", "unsupported_capability") from error
        return Dataset.from_list(list(self))


class EvaluationDataset:
    def __init__(self, public):
        self.public = public

    @property
    def info(self):
        return self.public.info

    def __len__(self):
        return len(self.public)

    def __getitem__(self, index):
        return self.public[index]

    def __iter__(self):
        return iter(self.public)

    def read_targets(self):
        manifest, catalog = self.public._manifest, self.public._catalog
        split = manifest["splits"][self.public.split]
        rows = catalog._read(manifest["reader_ref"], [manifest["targets"][i] for i in split["target_indices"]])
        if len(rows) != split["row_count"]:
            raise resource_error("Private reference row count differs from its fixed manifest", "artifact_integrity")
        if rows and all(isinstance(row, dict) and "sample_id" in row for row in rows):
            if len({canonical_json(row["sample_id"]) for row in rows}) != len(rows):
                raise resource_error("Private references contain duplicate sample IDs", "conflict")
            public_ids = set(self.public.sample_ids())
            selected = [row for row in rows if row["sample_id"] in public_ids]
            if len(selected) != len(self.public):
                raise resource_error("Private references do not align with all selected public rows", "artifact_integrity")
            return copy.deepcopy(selected)
        if self.public._indices is not None:
            rows = [rows[index] for index in self.public._indices]
        return copy.deepcopy(rows)


class EvaluationDatasets:
    """Explicit evaluation-only capability passed to benchmark resolvers."""
    def __init__(self, catalog):
        self._catalog = catalog

    def load_dataset(self, dataset_id, *, revision, config="default", split="test", purpose="evaluation"):
        if purpose != "evaluation":
            raise resource_error("Benchmark references require evaluation purpose", "permission_denied")
        public = self._catalog.load_dataset(dataset_id, revision=revision, config=config, split=split, purpose=purpose)
        return EvaluationDataset(public)


class DatasetCatalog(DataOrganization):
    def __init__(self, store, readers, schemas, *, artifacts=None, records=None):
        self.store, self.readers, self.schemas = store, readers, schemas
        self.artifacts, self.records = artifacts, records
        readers.register(JSONL_READER, _JSONL)
        readers.register(PARQUET_READER, _PARQUET)

    def publish_asset(self, content, *, media_type):
        return self.store.publish_asset(content, media_type=media_type)

    def publish_build(self, build, *, reader_ref, dataset_id=None, config="default",
                      usage_policy=None, parents=(), aliases=()):
        """Persist a fixed training export and its evidence independently of Run CAS."""
        from .data_publish import publish_build
        return publish_build(self, build, reader_ref=reader_ref, dataset_id=dataset_id, config=config,
            usage_policy=usage_policy, parents=parents, aliases=aliases)

    def register_dataset(self, manifest, *, aliases=()):
        item = copy.deepcopy(manifest)
        item["revision"] = content_revision(item)
        if manifest.get("revision") not in (None, item["revision"]):
            raise resource_error("Dataset revision differs from its canonical manifest", "conflict")
        schema = item.get("protocol_version")
        if schema not in (DATASET, DATASET_V2):
            raise resource_error("Unsupported dataset definition version", "schema_mismatch")
        self.schemas.validate(schema, item)
        policy = item["usage_policy"]
        if not policy["training_allowed"] and set(policy["allowed_uses"]) & {"training", "prepare", "dataset_build"}:
            raise resource_error("A non-training dataset cannot authorize training uses", "permission_denied")
        if item["reader_ref"]["version"] in {"latest", "main", "master"} or item["importer_ref"]["version"] in {"latest", "main", "master"}:
            raise resource_error("Dataset readers and importers require fixed versions")
        for split in item["splits"].values():
            if (any(index >= len(item["inputs"]) for index in split["input_indices"])
                    or any(index >= len(item["targets"]) for index in split["target_indices"])):
                raise resource_error("Dataset split references a missing shard")
            if split["row_count"] and not split["input_indices"]:
                raise resource_error("Nonempty splits need public input shards")
        assets = item["inputs"] + item["series"] + item["targets"] + [entry["asset_ref"] for entry in item["source_files"]]
        assets += [item[key] for key in ("quality_report_ref", "card_ref") if item[key] is not None]
        if schema == DATASET_V2:
            origin = item["origin"]
            source = self.load_source(origin["source_ref"]["source_id"], revision=origin["source_ref"]["revision"],
                                      config=origin["source_ref"]["config"])
            fixed, parents = self._parents(item["lineage"]["parents"])
            if (source["kind"] != item["kind"] or source["revision"] != origin["source_ref"]["revision"]
                    or fixed != item["lineage"]["parents"]
                    or any(ref not in fixed for ref in source["parent_datasets"])):
                raise resource_error("Dataset origin or fixed parent lineage differs from its source", "conflict")
            if json.loads(self.store.read_asset(origin["source_definition"])) != source:
                raise resource_error("Dataset source asset differs from its fixed source", "conflict")
            if ([json.loads(self.store.read_asset(ref)) for ref in item["lineage"]["parent_manifests"]] != parents):
                raise resource_error("Dataset parent assets differ from their fixed manifests", "conflict")
            policy = intersect_policies([item["usage_policy"], source["usage_policy"]] + [p["usage_policy"] for p in parents])
            if (set(policy["allowed_uses"]) != set(item["usage_policy"]["allowed_uses"])
                    or policy["training_allowed"] != item["usage_policy"]["training_allowed"]):
                raise resource_error("Dataset cannot broaden source or parent usage", "permission_denied")
            assets += item["attachments"] + [item["origin"]["source_definition"]] + item["lineage"]["parent_manifests"]
            if item["lineage"]["capture"] is not None:
                assets.append(item["lineage"]["capture"])
        for reference in assets:
            self.store.read_asset(reference)
        return self.store.publish_definition("dataset", item, schema, aliases=aliases)

    def list_datasets(self):
        result = []
        for item in self.store.definitions("dataset", (DATASET, DATASET_V2)):
            row = {key: copy.deepcopy(item[key]) for key in ("dataset_id", "config", "revision", "schema_ref", "splits", "usage_policy")}
            if item["protocol_version"] == DATASET_V2:
                row.update(kind=item["kind"], origin={"source_ref": copy.deepcopy(item["origin"]["source_ref"])})
            result.append(row)
        return result

    def load_dataset(self, dataset_id, *, revision, config="default", split="test", purpose="runtime"):
        item = self.load_manifest(dataset_id, revision=revision, config=config)
        if split not in item["splits"]:
            raise resource_error("Dataset does not provide the requested split", "permission_denied")
        policy = item["usage_policy"]
        if purpose in {"training", "prepare", "dataset_build"}:
            if not policy["training_allowed"] or not set(policy["allowed_uses"]) & {purpose, "training"}:
                raise resource_error("Dataset is not authorized for training or preparation", "permission_denied")
        elif purpose == "evaluation":
            if "evaluation" not in policy["allowed_uses"]:
                raise resource_error("Dataset is not authorized for evaluation", "permission_denied")
        elif purpose == "runtime":
            if not set(policy["allowed_uses"]) & {"runtime", "evaluation"}:
                raise resource_error("Dataset public inputs are not authorized for runtime", "permission_denied")
        else:
            raise resource_error("Unsupported dataset purpose")
        return DatasetHandle(self, item, split)

    def _read(self, reader_ref, assets):
        return self.readers.resolve(reader_ref).read(AssetReadServices(self.store, assets), copy.deepcopy(assets))
