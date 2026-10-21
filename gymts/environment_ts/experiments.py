"""Local experiment organization over existing execution, data and evaluation APIs."""
from copy import deepcopy
import re

from gymts.contracts import GymTSError, canonical_json, digest
from gymts.contracts.organization import GROUP, REQUEST
from gymts.contracts.resources import POLICY
from gymts.environment_ts.data_sources import intersect_policies


def inherit_organization_inputs(spec, records, artifacts):
    """Carry declared stage data into every nested Run and evaluation plan."""
    organization = getattr(records, "organization", None)
    if organization is None or organization.context.get() is None:
        return spec
    attempt = organization.attempt(organization.context.get()["attempt_id"])
    inherited = artifacts.read_json(attempt["request_ref"]).get("provenance")
    if not inherited:
        return spec
    result = deepcopy(spec)
    provenance = result.setdefault("provenance", {"source_refs": [], "usage_policy_ref": None, "benchmark_definition_ref": None})
    for ref in inherited["source_refs"]:
        if ref not in provenance["source_refs"]:
            provenance["source_refs"].append(ref)
    policies = [artifacts.read_json(ref) for ref in (provenance["usage_policy_ref"], inherited["usage_policy_ref"]) if ref is not None]
    if policies:
        provenance["usage_policy_ref"] = artifacts.save_json(intersect_policies(policies), POLICY)
    return result


def _pointer(value, pointer, *, replacement=None, write=False):
    if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")) or re.search(r"~(?:[^01]|$)", pointer):
        raise GymTSError("invalid_config", "Bindings and outputs require JSON Pointers")
    if not pointer:
        if write:
            raise GymTSError("invalid_config", "A binding cannot replace the whole stage spec")
        return deepcopy(value)
    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]
    try:
        node = value
        for part in parts[:-1]:
            node = node[int(part)] if isinstance(node, list) else node[part]
        key = int(parts[-1]) if isinstance(node, list) else parts[-1]
        if write:
            node[key] = deepcopy(replacement)
            return value
        return deepcopy(node[key])
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise GymTSError("invalid_config", "JSON Pointer does not address the stage value", links={"pointer": pointer}) from error


def _ordered(stages):
    remaining = {stage["stage_id"]: stage for stage in stages}
    if len(remaining) != len(stages):
        raise GymTSError("conflict", "Stage IDs must be unique")
    ordered, completed = [], set()
    while remaining:
        ready = [stage for stage in remaining.values() if set(stage["depends_on"]) <= completed]
        if not ready:
            raise GymTSError("invalid_config", "Stage dependencies contain a cycle or unknown stage")
        for stage in ready:
            ordered.append(stage)
            completed.add(stage["stage_id"])
            del remaining[stage["stage_id"]]
    return ordered


class ExperimentOrganization:
    """Definitions are immutable; each actual stage invocation adds a new attempt.

    Executors are trusted adapter functions ``execute(spec, gym) -> JSON object``.
    The framework owns identities, bindings and evidence, not domain execution.
    """
    def __init__(self, gym):
        self.gym, self.store = gym, gym.records.organization
        self.catalog = gym.environment_ts.datasets
        self.executors = {}
        for name, executor in (("run", lambda spec, gym: gym.run(spec)),
                               ("evaluate", lambda spec, gym: gym.autobench.evaluate(spec)),
                               ("score", lambda spec, gym: gym.autobench.score(spec)),
                               ("capture", self._capture), ("publish-build", self._publish_build)):
            self.register_executor({"name": "gymts." + name, "version": "1.0.0", "origin_ref": None}, executor)

    @staticmethod
    def _capture(spec, gym):
        spec = deepcopy(spec)
        source = spec.pop("source_ref")
        return gym.environment_ts.datasets.capture_run(source_id=source["source_id"],
            revision=source["revision"], source_config=source["config"], **spec)

    @staticmethod
    def _publish_build(spec, gym):
        spec = deepcopy(spec)
        manifest = spec.pop("manifest")
        return gym.environment_ts.datasets.publish_build(manifest, **spec)

    def register_executor(self, reference, executor):
        self.gym.schemas.validate("gymts.component/1", reference)
        if reference["version"] in {"latest", "main", "master"} or not callable(executor):
            raise GymTSError("invalid_config", "An executor needs a fixed version and callable")
        key = (reference["name"], reference["version"])
        if key in self.executors:
            raise GymTSError("conflict", "Executor version is already registered")
        self.executors[key] = (deepcopy(reference), executor)

    def register(self, definition):
        item = deepcopy(definition)
        item.setdefault("protocol_version", GROUP)
        item.setdefault("revision", None)
        for stage in item.get("stages", []):
            for key, default in (("depends_on", []), ("inputs", {}), ("bindings", {}), ("outputs", {})):
                stage.setdefault(key, deepcopy(default))
            name = stage.get("executor_ref", {}).get("name")
            stage.setdefault("purpose", "evaluation" if name in ("gymts.evaluate", "gymts.score") else
                             "dataset_build" if name == "gymts.publish-build" else "runtime")
            if stage.get("executor_ref", {}).get("version") in {"latest", "main", "master"}:
                raise GymTSError("invalid_config", "Stage executors require fixed versions")
            for reference in stage["inputs"].values():
                kind = reference.get("kind")
                if kind == "dataset":
                    ref = reference["ref"]
                    manifest = self.catalog.load_manifest(ref["dataset_id"], revision=ref["revision"], config=ref["config"])
                    self.catalog.load_dataset(ref["dataset_id"], revision=manifest["revision"], config=ref["config"],
                                              split=ref["split"], purpose=stage["purpose"])
                    ref["revision"] = manifest["revision"]
                elif kind == "source":
                    ref = reference["ref"]
                    source = self.catalog.load_source(ref["source_id"], revision=ref["revision"], config=ref["config"])
                    if stage["purpose"] not in source["usage_policy"]["allowed_uses"]:
                        raise GymTSError("permission_denied", "Source policy forbids the declared stage purpose")
                    ref["revision"] = source["revision"]
                elif kind == "artifact":
                    self.gym.artifacts.resolve(reference["ref"])
                elif kind == "stage_output" and reference["stage_id"] not in stage["depends_on"]:
                    stage["depends_on"].append(reference["stage_id"])
            if set(stage["bindings"]) - set(stage["inputs"]):
                raise GymTSError("invalid_config", "Every binding must name a declared input")
            for pointer in list(stage["bindings"].values()) + list(stage["outputs"].values()):
                if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")) or re.search(r"~(?:[^01]|$)", pointer):
                    raise GymTSError("invalid_config", "Bindings and outputs require JSON Pointers")
        stages = _ordered(item.get("stages", []))
        lookup = {stage["stage_id"]: stage for stage in stages}
        for stage in stages:
            for reference in stage["inputs"].values():
                if reference["kind"] == "stage_output" and reference["output"] not in lookup[reference["stage_id"]]["outputs"]:
                    raise GymTSError("invalid_config", "A stage input names an undeclared output")
        expected = digest({key: value for key, value in item.items() if key != "revision"})
        if item["revision"] not in (None, expected):
            raise GymTSError("conflict", "Group revision differs from its canonical definition")
        item["revision"] = expected
        self.gym.schemas.validate(GROUP, item)
        self.store.register(item)
        return item

    def get(self, group_id, *, revision):
        return self.gym.artifacts.read_json(self.store.definition_ref(group_id, revision))

    def events(self, group_id, *, revision, after_seq=0):
        self.store.definition_ref(group_id, revision)
        return self.store.events(group_id, revision, after_seq=after_seq)

    def inspect(self, group_id, *, revision):
        definition = self.get(group_id, revision=revision)
        attempts = self.store.attempts(group_id, revision)
        latest = {attempt["stage_id"]: attempt for attempt in attempts}
        stages = []
        current = {}
        for stage in _ordered(definition["stages"]):
            attempt = latest.get(stage["stage_id"])
            dependencies = {key: current[key]["attempt_id"] for key in stage["depends_on"]}
            ready = all(current[key]["status"] == "succeeded" for key in stage["depends_on"])
            status = attempt["status"] if attempt else "pending" if ready else "blocked"
            if attempt and status == "succeeded" and (not ready or attempt["dependencies"] != dependencies):
                status = "stale"
            entry = {"stage_id": stage["stage_id"], "status": status,
                "attempt_id": attempt["attempt_id"] if attempt else None,
                "dependencies": dependencies, "ready": ready,
                "outputs": deepcopy(attempt["outputs"]) if attempt and status == "succeeded" else {}}
            current[stage["stage_id"]] = entry
            stages.append(entry)
        statuses = {stage["status"] for stage in stages}
        status = "running" if "running" in statuses else "succeeded" if statuses == {"succeeded"} else \
                 "failed" if statuses & {"failed", "cancelled", "interrupted"} else "pending"
        return {"group_id": group_id, "revision": revision, "name": definition["name"], "status": status,
            "definition_ref": self.store.definition_ref(group_id, revision), "stages": stages, "attempts": attempts,
            "runs": self.gym.records.list_runs(group_id=group_id, revision=revision)}

    def _request(self, definition, stage, state):
        inputs, datasets, sources = {}, [], []
        for name, reference in stage["inputs"].items():
            if reference["kind"] == "stage_output":
                value = state[reference["stage_id"]]["outputs"][reference["output"]]
            else:
                value = reference["ref"]
            inputs[name] = deepcopy(value)
            if isinstance(value, dict) and value.get("protocol_version") in ("gymts.source-dataset/1", "gymts.source-dataset/2"):
                manifest = self.catalog.load_manifest(value["dataset_id"], revision=value["revision"], config=value["config"])
                self.catalog.load_dataset(value["dataset_id"], revision=value["revision"], config=value["config"],
                    split=next(iter(manifest["splits"])), purpose=stage["purpose"])
                if value != manifest:
                    raise GymTSError("conflict", "A dataset output differs from its catalog revision")
                datasets.append(manifest)
            if isinstance(value, dict) and {"dataset_id", "config", "revision", "split"} <= set(value):
                ref = {key: value[key] for key in ("dataset_id", "config", "revision", "split")}
                manifest = self.catalog.load_manifest(ref["dataset_id"], revision=ref["revision"], config=ref["config"])
                self.catalog.load_dataset(ref["dataset_id"], revision=ref["revision"], config=ref["config"],
                                          split=ref["split"], purpose=stage["purpose"])
                datasets.append(manifest)
            if isinstance(value, dict) and {"source_id", "config", "revision"} <= set(value):
                source = self.catalog.load_source(value["source_id"], revision=value["revision"], config=value["config"])
                if stage["purpose"] not in source["usage_policy"]["allowed_uses"]:
                    raise GymTSError("permission_denied", "Source policy forbids the declared stage purpose")
                sources.append(source)
        spec = deepcopy(stage["spec"])
        for name, target in stage["bindings"].items():
            _pointer(spec, target, replacement=inputs[name], write=True)
        policies = [item["usage_policy"] for item in datasets + sources]
        inherited = {"source_refs": [self.gym.artifacts.save_json(item, item["protocol_version"]) for item in datasets + sources],
                     "usage_policy_ref": self.gym.artifacts.save_json(intersect_policies(policies), POLICY) if policies else None,
                     "benchmark_definition_ref": None}
        operation = stage["executor_ref"]["name"]
        if spec.get("protocol_version") in ("gymts.experiment/1", "gymts.evaluation/1", "gymts.score/1"):
            provenance = spec.setdefault("provenance", {"source_refs": [], "usage_policy_ref": None, "benchmark_definition_ref": None})
            for ref in inherited["source_refs"]:
                if ref not in provenance["source_refs"]:
                    provenance["source_refs"].append(ref)
            if provenance["usage_policy_ref"] is not None:
                policies.append(self.gym.artifacts.read_json(provenance["usage_policy_ref"]))
            if policies:
                provenance["usage_policy_ref"] = self.gym.artifacts.save_json(intersect_policies(policies), POLICY)
            if spec["protocol_version"] == "gymts.experiment/1":
                for source in sources:
                    spec = self.catalog.bind_source(spec, source["source_id"], revision=source["revision"], config=source["config"])
        dependencies = {key: state[key]["attempt_id"] for key in stage["depends_on"]}
        request = {"protocol_version": REQUEST, "binding_status": "resolved", "executor_ref": stage["executor_ref"],
            "purpose": stage["purpose"], "inputs": inputs, "provenance": inherited, "spec": spec,
            "datasets": [{key: item[key] for key in ("dataset_id", "config", "revision")} for item in datasets]}
        self.gym.schemas.validate(REQUEST, request)
        return request, dependencies

    def execute(self, group_id, *, revision, retry_failed=False, rerun=()):
        definition = self.get(group_id, revision=revision)
        state = self.inspect(group_id, revision=revision)
        if state["status"] == "running":
            raise GymTSError("conflict", "An attempt is still running; inspect it before recovery")
        rerun = set(rerun)
        if rerun - {stage["stage_id"] for stage in definition["stages"]}:
            raise GymTSError("invalid_config", "Unknown rerun stage")
        for stage in _ordered(definition["stages"]):
            state = {entry["stage_id"]: entry for entry in self.inspect(group_id, revision=revision)["stages"]}
            entry = state[stage["stage_id"]]
            selected = entry["status"] in ("pending", "stale", "blocked") or stage["stage_id"] in rerun or \
                       (retry_failed and entry["status"] in ("failed", "cancelled"))
            if not entry["ready"] or not selected:
                continue
            key = (stage["executor_ref"]["name"], stage["executor_ref"]["version"])
            # Binding failures are also attempts: the frozen stage remains available
            # even when no provider was opened or no Run could be created.
            try:
                request, dependencies = self._request(definition, stage, state)
            except Exception as error:
                attempt = self.store.begin(group_id, revision, stage["stage_id"],
                    {"protocol_version": REQUEST, "binding_status": "failed", "purpose": stage["purpose"],
                     "executor_ref": stage["executor_ref"], "spec": stage["spec"], "inputs": stage["inputs"], "datasets": [],
                     "provenance": {"source_refs": [], "usage_policy_ref": None, "benchmark_definition_ref": None}},
                    {key: state[key]["attempt_id"] for key in stage["depends_on"]}, expected_previous=entry["attempt_id"])
                self.store.finish(attempt["attempt_id"], status="failed", error=self._error(error))
                continue
            attempt = self.store.begin(group_id, revision, stage["stage_id"], request, dependencies,
                                       expected_previous=entry["attempt_id"])
            result_ref = None
            try:
                if key not in self.executors or self.executors[key][0] != stage["executor_ref"]:
                    raise GymTSError("unsupported_capability", "Install and register the stage executor's fixed version")
                with self.store.scope(attempt):
                    result = self.executors[key][1](deepcopy(request["spec"]), self.gym)
                if not isinstance(result, dict):
                    raise GymTSError("schema_mismatch", "A stage executor must return a JSON object")
                canonical_json(result)
                result_ref = self.gym.artifacts.save_json(result, result.get("protocol_version", "gymts.json/1"))
                if result.get("protocol_version") == "gymts.evaluation-report/1":
                    manifest = self.gym.artifacts.read_json(result["run_manifest_ref"])
                    self.store.reference_runs(attempt, [entry["run_id"] for entry in manifest["entries"] if entry["run_id"] is not None])
                outputs = {name: _pointer(result, pointer) for name, pointer in stage["outputs"].items()}
                status = result.get("status", "succeeded")
                if status not in ("succeeded", "completed", "failed", "cancelled"):
                    raise GymTSError("schema_mismatch", "A stage executor must return a terminal execution status")
                status = status if status in ("failed", "cancelled") else "succeeded"
                error = next(iter(result.get("errors", [])), None) if status != "succeeded" else None
                self.store.finish(attempt["attempt_id"], status=status, result_ref=result_ref, outputs=outputs, error=error)
            except Exception as error:
                self.store.finish(attempt["attempt_id"], status="failed", result_ref=result_ref, error=self._error(error))
            # BaseException deliberately leaves an open attempt. A new process
            # must inspect/reconcile it; live operations are never blindly resent.
        return self.inspect(group_id, revision=revision)

    @staticmethod
    def _error(error):
        return error.info if isinstance(error, GymTSError) else GymTSError("backend_failure",
            "Stage executor failed ({})".format(type(error).__name__), stage="experiment").info

    def recover(self, attempt_id, *, reason, adopt_run=False):
        if not isinstance(reason, str) or not reason.strip():
            raise GymTSError("invalid_config", "Recovery requires a recorded reason")
        attempt = self.store.attempt(attempt_id)
        if attempt["status"] != "running":
            raise GymTSError("conflict", "Only an open attempt can be recovered")
        if adopt_run:
            request = self.gym.artifacts.read_json(attempt["request_ref"])
            runs = self.gym.records.list_runs(attempt_id=attempt_id)
            if request["executor_ref"]["name"] != "gymts.run" or len(runs) != 1 or runs[0]["result_ref"] is None:
                raise GymTSError("invalid_state", "Adoption requires exactly one sealed Run from gymts.run")
            result = self.gym.records.get_run(runs[0]["run_id"])["result"]
            definition = self.get(attempt["group_id"], revision=attempt["revision"])
            stage = next(item for item in definition["stages"] if item["stage_id"] == attempt["stage_id"])
            outputs = {name: _pointer(result, pointer) for name, pointer in stage["outputs"].items()}
            return self.store.finish(attempt_id, status=result["status"], result_ref=runs[0]["result_ref"], outputs=outputs,
                error={"recovery_reason": reason})
        return self.store.finish(attempt_id, status="interrupted", error={"reason": reason,
            "side_effect": "unknown", "message": "Execution must be stopped externally before an explicit rerun"})

    def query(self, *, group_id=None, dataset_id=None, dataset_revision=None, status=None):
        matches = []
        for definition in self.store.definitions():
            if group_id is not None and definition["group_id"] != group_id:
                continue
            view = self.inspect(definition["group_id"], revision=definition["revision"])
            if status is not None and view["status"] != status:
                continue
            if dataset_id is not None:
                refs = [reference["ref"] for stage in definition["stages"] for reference in stage["inputs"].values()
                        if reference["kind"] == "dataset"]
                refs.extend(ref for run in view["runs"] for ref in run["datasets"])
                for attempt in view["attempts"]:
                    request = self.gym.artifacts.read_json(attempt["request_ref"])
                    refs.extend(request.get("datasets", []))
                    if attempt["result_ref"] is not None:
                        result = self.gym.artifacts.read_json(attempt["result_ref"])
                        if "dataset_id" in result:
                            refs.append(result)
                        if result.get("protocol_version") == "gymts.source-dataset/2":
                            refs.extend(result["lineage"]["parents"])
                        elif result.get("protocol_version") == "gymts.source-dataset/1" and result.get("features", {}).get("dataset_build"):
                            refs.extend(result["features"].get("parent_datasets", []))
                if not any(ref["dataset_id"] == dataset_id and (dataset_revision is None or ref["revision"] == dataset_revision) for ref in refs):
                    continue
            matches.append({key: view[key] for key in ("group_id", "revision", "name", "status", "definition_ref", "stages", "runs")})
        return matches
