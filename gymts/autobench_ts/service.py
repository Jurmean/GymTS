"""Fixed-plan evaluations and immutable rescoring of existing evidence."""
from copy import deepcopy
from datetime import datetime, timezone
import math
from typing import Any, Dict, List

from gymts.contracts import GymTSError, canonical_json, digest, new_id, utc_now
from .aggregation import COUNT_KEYS, aggregate, compare, empty_metric, gates, group_key


def _error(message: str, code: str = "invalid_config", **links: Any) -> GymTSError:
    return GymTSError(code, message, stage="evaluation", links=links)


def _object(value: Any, required: set, optional: set = frozenset(), path: str = "spec") -> Dict[str, Any]:
    if not isinstance(value, dict) or required - set(value) or set(value) - required - optional:
        raise _error("{} has missing or unknown fields".format(path), path=path)
    return value


def _number(value: Any, path: str, minimum: float = None, maximum: float = None) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise _error("{} must be finite numeric".format(path))
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise _error("{} is out of range".format(path))


def _integer(value: Any, path: str, minimum: int = 0) -> None:
    _number(value, path, minimum)
    if not isinstance(value, int):
        raise _error("{} must be an integer".format(path))


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise _error("Evaluation timestamps must be UTC RFC3339 strings")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
            raise ValueError("UTC required")
        return parsed
    except ValueError as exc:
        raise _error("Invalid UTC evaluation timestamp") from exc


def _tags(value: Any) -> dict:
    if not isinstance(value, dict) or any(not isinstance(key, str) or item is not None and not isinstance(item, (str, int, float, bool)) for key, item in value.items()):
        raise _error("Tags must map strings to JSON scalars")
    return value


class RestrictedScoringServices:
    """Read only the explicitly authorized view graph, and write new artifacts."""

    def __init__(self, artifacts: Any, refs: List[Dict[str, Any]]):
        self._artifacts = artifacts
        self._allowed = {canonical_json(ref) for ref in refs}

    def read_json(self, ref: Dict[str, Any]) -> Any:
        if canonical_json(ref) not in self._allowed:
            raise _error("Scorer attempted to read an undeclared artifact", "permission_denied")
        return self._artifacts.read_json(ref)

    def resolve(self, ref: Dict[str, Any]) -> Any:
        if canonical_json(ref) not in self._allowed:
            raise _error("Scorer attempted to resolve an undeclared artifact", "permission_denied")
        return self._artifacts.resolve(ref)

    def save_json(self, value: Any, schema_ref: str) -> Dict[str, Any]:
        ref = self._artifacts.save_json(value, schema_ref)
        self._allowed.add(canonical_json(ref))
        return ref

    def save_artifact(self, content: bytes, metadata: Dict[str, Any]) -> Dict[str, Any]:
        ref = self._artifacts.save_artifact(content, metadata)
        self._allowed.add(canonical_json(ref))
        return ref


class AutoBenchTS:
    """Core synchronous evaluator. Scorers are registered, versioned plugins."""

    def __init__(self, environment_ts: Any, scorers: Any, schemas: Any, records: Any, artifacts: Any):
        self.environment_ts, self.scorers, self.schemas = environment_ts, scorers, schemas
        self.records, self.artifacts = records, artifacts

    def _save(self, value: Any, schema: str, evaluation_id: str, evidence: list) -> dict:
        try:
            ref = self.artifacts.save_json(value, schema)
        except Exception as exc:
            raise _error("Unable to commit evaluation artifact", "recording_failure",
                         evaluation_id=evaluation_id, confirmed_refs=list(evidence)) from exc
        evidence.append(ref)
        return ref

    def _common(self, spec: dict, mode: str) -> tuple:
        common = {"protocol_version", "name", "purpose", "baseline_id", "scoring", "comparison", "failure_policy"}
        fields = {"cases", "candidates", "repetitions"} if mode == "evaluate" else {"runs", "previous_evaluation_id"}
        _object(spec, common | fields)
        try:
            canonical_json(spec)
        except (TypeError, ValueError) as exc:
            raise _error("Evaluation configuration must contain finite JSON") from exc
        protocol = "gymts.evaluation/1" if mode == "evaluate" else "gymts.score/1"
        if spec["protocol_version"] != protocol:
            raise _error("Unsupported evaluation protocol", "unsupported_capability")
        if spec["purpose"] not in {"development", "regression", "acceptance"}:
            raise _error("Unknown evaluation purpose")
        if spec["name"] is not None and not isinstance(spec["name"], str):
            raise _error("name must be string or null")
        if spec["baseline_id"] is not None and (not isinstance(spec["baseline_id"], str) or not spec["baseline_id"]):
            raise _error("baseline_id must be nonempty string or null")
        scoring = _object(spec["scoring"], {"scorer", "outcomes", "alignment", "metrics", "evidence_requirements", "missing_outcome_policy"}, path="scoring")
        scorer = _object(scoring["scorer"], {"adapter", "version", "params"}, path="scorer")
        manifest = self.scorers.resolve(scorer["adapter"], scorer["version"])
        if manifest.get("params_schema_ref"):
            self.schemas.validate(manifest["params_schema_ref"], scorer["params"])
        requested = scoring["metrics"]
        if not isinstance(requested, list) or not requested or any(not isinstance(metric, str) for metric in requested) or len(set(requested)) != len(requested):
            raise _error("metrics must be nonempty unique IDs")
        if any(metric not in manifest["metrics"] for metric in requested):
            raise _error("Metric not declared by ScorerManifest", "unsupported_capability")
        for metric in requested:
            declaration = manifest["metrics"][metric]
            if not declaration.get("eligibility_ref") or not declaration.get("eligibility_schema_ref"):
                raise _error("Metric lacks fixed eligibility contract", "schema_mismatch", metric_id=metric)
        if scoring["missing_outcome_policy"] != "report_insufficient":
            raise _error("Unsupported missing outcome policy", "unsupported_capability")
        requirement = _object(scoring["evidence_requirements"], {"min_scored", "min_coverage"}, {"overrides"}, "evidence_requirements")
        requirement.setdefault("overrides", {})
        if not isinstance(requirement["overrides"], dict) or set(requirement["overrides"]) - set(requested):
            raise _error("Evidence overrides reference unknown metrics")
        for item in [requirement] + list(requirement["overrides"].values()):
            _object(item, {"min_scored", "min_coverage"}, {"overrides"} if item is requirement else set(), "evidence requirement")
            _integer(item["min_scored"], "min_scored")
            _number(item["min_coverage"], "min_coverage", 0, 1)
        outcome = _object(scoring["outcomes"], {"sources", "as_of"}, path="outcomes")
        if not isinstance(outcome["sources"], list):
            raise _error("Outcome sources must be a list")
        if outcome["as_of"] is not None:
            _timestamp(outcome["as_of"])
        for view in outcome["sources"]:
            self.schemas.validate("gymts.view/1", view)
            if view.get("purpose") != "evaluation":
                raise _error("Outcome view must authorize evaluation", "permission_denied")
            if view.get("as_of") is not None:
                _timestamp(view["as_of"])
        alignment = _object(scoring["alignment"], {"schema_ref", "keys", "matching", "params", "duplicate_policy"}, path="alignment")
        if alignment["matching"] not in {"exact", "interval", "tolerance"} or alignment["duplicate_policy"] not in {"error", "latest_available"}:
            raise _error("Unknown alignment policy")
        supported = manifest.get("supported_alignment_matchings", manifest.get("supported_matchings"))
        if supported is not None and alignment["matching"] not in supported:
            raise _error("Scorer does not support the requested alignment matching", "unsupported_capability")
        if not isinstance(alignment["params"], dict):
            raise _error("Alignment params must be an object")
        if not isinstance(alignment["keys"], list) or not alignment["keys"] or any(not isinstance(key, str) for key in alignment["keys"]) or len(set(alignment["keys"])) != len(alignment["keys"]):
            raise _error("Alignment keys must be unique nonempty strings")
        comparison = _object(spec["comparison"], {"group_by", "repetition_aggregation", "aggregation", "baseline_method", "gates"}, path="comparison")
        if comparison["repetition_aggregation"] not in {"none", "mean"} or comparison["aggregation"] not in {"none", "macro_mean"}:
            raise _error("Unsupported aggregation", "unsupported_capability")
        if comparison["baseline_method"] not in {"difference", "relative_change"}:
            raise _error("Unknown baseline comparison method")
        groups = comparison["group_by"]
        if not isinstance(groups, list) or "evaluation_case_id" not in groups or any(not isinstance(field, str) or field != "evaluation_case_id" and not field.startswith("tags.") for field in groups) or len(set(groups)) != len(groups):
            raise _error("group_by must contain evaluation_case_id and optional tags fields")
        if not isinstance(comparison["gates"], list):
            raise _error("gates must be a list")
        for gate in comparison["gates"]:
            _object(gate, {"metric", "target", "candidate_ids", "for_metric", "operator", "threshold", "scope"}, path="gate")
            if gate["metric"] not in requested + ["run_failure_rate", "scored_coverage"]:
                raise _error("Gate metric not requested")
            if gate["target"] not in {"absolute", "difference", "relative_change"} or gate["operator"] not in {"ge", "gt", "le", "lt"} or gate["scope"] not in {"aggregate", "all_groups"}:
                raise _error("Unknown gate policy")
            if gate["scope"] == "aggregate" and comparison["aggregation"] == "none":
                raise _error("Aggregate gate requires macro_mean aggregation")
            if gate["metric"] in {"run_failure_rate", "scored_coverage"} and gate["target"] != "absolute":
                raise _error("Built-in gate values support only absolute target")
            if gate["metric"] == "scored_coverage":
                if gate["for_metric"] not in requested:
                    raise _error("Coverage gate requires for_metric")
            elif gate["for_metric"] is not None:
                raise _error("for_metric is only valid for coverage gates")
            if gate["target"] != "absolute" and spec["baseline_id"] is None:
                raise _error("Difference gate requires baseline")
            _number(gate["threshold"], "gate threshold")
        failure = _object(spec["failure_policy"], {"partial_results", "invalid_result_policy"}, path="failure_policy")
        if failure["partial_results"] not in {"include", "exclude"} or failure["invalid_result_policy"] not in {"report", "abort"}:
            raise _error("Unknown failure policy")
        return scoring, comparison, manifest

    def _task(self, experiment: dict, scorer: dict) -> dict:
        task_spec = experiment["scene"]["task"]
        task = self.environment_ts.tasks.resolve(task_spec["plugin"], task_spec["version"])
        if task["task_protocol_ref"] not in scorer["supported_task_protocols"] or task["result_schema_ref"] not in scorer["result_schema_refs"] or task["outcome_schema_ref"] is not None and task["outcome_schema_ref"] not in scorer["outcome_schema_refs"]:
            raise _error("Scorer does not support this task/schema", "schema_mismatch")
        return task

    def _unit(self, experiment: dict, spec_ref: dict, task: dict, **identity: Any) -> dict:
        return {**identity, "seed": experiment["execution"].get("seed"), "resolved_spec_ref": spec_ref,
                "task_protocol_ref": task["task_protocol_ref"], "result_schema_ref": task["result_schema_ref"]}

    def _check_units(self, units: list, experiments: dict, scorer: dict, spec: dict) -> None:
        if not units:
            raise _error("Evaluation must contain at least one expected unit")
        identities, homogeneous = {}, set()
        combinations = set()
        for unit in units:
            experiment = experiments[unit["unit_id"]]
            task = self._task(experiment, scorer)
            homogeneous.add((task["task_protocol_ref"], task["result_schema_ref"], task["outcome_schema_ref"]))
            alignment = spec["scoring"]["alignment"]
            if task.get("alignment_schema_ref") is not None:
                if alignment["schema_ref"] != task["alignment_schema_ref"]:
                    raise _error("Scoring alignment schema differs from task", "schema_mismatch")
                if hasattr(self.schemas, "resolve"):
                    alignment_schema = self.schemas.resolve(task["alignment_schema_ref"])
                    declared_keys = scorer.get("alignment_keys", {}).get(alignment["matching"])
                    required_keys = set(declared_keys if declared_keys is not None else alignment_schema.get("required", []))
                    if required_keys - set(alignment["keys"]):
                        raise _error("Alignment omits task matching keys", "schema_mismatch", missing_keys=sorted(required_keys - set(alignment["keys"])))
                    if alignment_schema.get("additionalProperties") is False and set(alignment["keys"]) - set(alignment_schema.get("properties", {})):
                        raise _error("Alignment contains undeclared task keys", "schema_mismatch")
            # Include fit/preparation identity, but not repetition seed or fitted outputs.
            candidate = experiment["candidate"]
            candidate_manifest = self.environment_ts.candidates.resolve(candidate["adapter"], candidate["version"])
            fingerprint = digest({"spec": candidate, "implementation": candidate_manifest["implementation_ref"],
                                  "prepare": experiment["execution"]["learning"]})
            candidate_id = unit["candidate_id"]
            if candidate_id in identities and identities[candidate_id] != fingerprint:
                raise _error("candidate_id groups different candidate/preparation identities", "conflict", candidate_id=candidate_id)
            identities[candidate_id] = fingerprint
            combination = (unit["evaluation_case_id"], candidate_id, unit["repetition"])
            if combination in combinations:
                raise _error("Repeated evaluation condition must have unique repetition", "conflict")
            combinations.add(combination)
            for field in spec["comparison"]["group_by"]:
                if field.startswith("tags.") and field[5:] not in unit["tags"]:
                    raise _error("Missing group tag", field=field)
        if len(homogeneous) != 1:
            raise _error("Heterogeneous task/schema evaluation requires separate reports", "schema_mismatch")
        if spec["baseline_id"] is not None and spec["baseline_id"] not in identities:
            raise _error("Baseline candidate is not selected")
        for gate in spec["comparison"]["gates"]:
            selected = gate["candidate_ids"]
            if selected is not None and (not isinstance(selected, list) or not selected or any(not isinstance(candidate, str) for candidate in selected) or len(set(selected)) != len(selected) or set(selected) - set(identities)):
                raise _error("Gate references unknown or repeated candidates")

    def evaluate(self, spec: dict) -> dict:
        spec = deepcopy(spec)
        scoring, comparison, scorer = self._common(spec, "evaluate")
        if not isinstance(spec["cases"], list) or not spec["cases"] or not isinstance(spec["candidates"], list) or not spec["candidates"]:
            raise _error("cases and candidates must be nonempty lists")
        repeated = _object(spec["repetitions"], {"count", "seeds"}, path="repetitions")
        _integer(repeated["count"], "repetitions.count", 1)
        if not isinstance(repeated["seeds"], list) or len(repeated["seeds"]) != repeated["count"]:
            raise _error("repetitions.seeds must match count")
        for seed in repeated["seeds"]:
            if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
                raise _error("seed must be integer or null")
        cases, candidates = set(), set()
        units, experiments = [], {}
        for candidate in spec["candidates"]:
            _object(candidate, {"candidate_id", "spec"}, path="candidate")
            if not isinstance(candidate["candidate_id"], str) or not candidate["candidate_id"] or candidate["candidate_id"] in candidates:
                raise _error("Candidate IDs must be unique nonempty strings")
            candidates.add(candidate["candidate_id"])
        for case in spec["cases"]:
            _object(case, {"evaluation_case_id", "scene", "execution", "recording"}, {"tags"}, "case")
            case.setdefault("tags", {})
            if not isinstance(case["evaluation_case_id"], str) or not case["evaluation_case_id"] or case["evaluation_case_id"] in cases:
                raise _error("Evaluation case IDs must be unique nonempty strings")
            _tags(case["tags"])
            cases.add(case["evaluation_case_id"])
            for candidate in spec["candidates"]:
                for repetition, seed in enumerate(repeated["seeds"]):
                    experiment = {"protocol_version": "gymts.experiment/1", "name": spec["name"], "purpose": spec["purpose"],
                                  "scene": deepcopy(case["scene"]), "candidate": deepcopy(candidate["spec"]),
                                  "execution": deepcopy(case["execution"]), "recording": deepcopy(case["recording"]), "extensions": {}}
                    if seed is not None:
                        experiment["execution"]["seed"] = seed
                    validation = self.environment_ts.validate(experiment)
                    if not validation["valid"]:
                        raise _error("Evaluation experiment failed validation", issues=validation["issues"])
                    resolved_ref = validation["resolved_spec_ref"]
                    experiment = self.artifacts.read_json(resolved_ref)
                    task = self._task(experiment, scorer)
                    unit = self._unit(experiment, resolved_ref, task, unit_id=new_id("unit"),
                                      evaluation_case_id=case["evaluation_case_id"], candidate_id=candidate["candidate_id"],
                                      repetition=repetition, tags=case["tags"])
                    units.append(unit)
                    experiments[unit["unit_id"]] = experiment
        self._check_units(units, experiments, scorer, spec)
        return self._execute(spec, units, experiments, scorer, {})

    def score(self, spec: dict) -> dict:
        spec = deepcopy(spec)
        scoring, comparison, scorer = self._common(spec, "score")
        if spec["previous_evaluation_id"] is not None and not isinstance(spec["previous_evaluation_id"], str):
            raise _error("previous_evaluation_id must be string or null")
        if not isinstance(spec["runs"], list):
            raise _error("runs must be a list")
        units, experiments, selected, run_ids, unit_ids = [], {}, {}, set(), set()
        for selection in spec["runs"]:
            _object(selection, {"unit_id", "evaluation_case_id", "candidate_id", "repetition", "run_id", "unavailable_reason"}, {"unit_spec_ref", "tags"}, "RunSelection")
            selection.setdefault("unit_spec_ref", None)
            selection.setdefault("tags", {})
            _tags(selection["tags"])
            for field in ("unit_id", "evaluation_case_id", "candidate_id"):
                if not isinstance(selection[field], str) or not selection[field]:
                    raise _error("{} must be a nonempty string".format(field))
            _integer(selection["repetition"], "repetition")
            if selection["unit_id"] in unit_ids:
                raise _error("unit_id is duplicated", "conflict")
            unit_ids.add(selection["unit_id"])
            run_id = selection["run_id"]
            if run_id is None:
                if not isinstance(selection["unavailable_reason"], str) or not selection["unavailable_reason"] or selection["unit_spec_ref"] is None:
                    raise _error("Missing run needs unavailable_reason and unit_spec_ref")
                ref, run = selection["unit_spec_ref"], None
            else:
                if not isinstance(run_id, str) or not run_id or run_id in run_ids:
                    raise _error("Run IDs must be unique nonempty strings", "conflict")
                run_ids.add(run_id)
                run = self.records.get_run(run_id)
                ref = run.get("resolved_spec_ref") or run["metadata"]["resolved_spec_ref"]
                if selection["unit_spec_ref"] is not None and canonical_json(ref) != canonical_json(selection["unit_spec_ref"]):
                    raise _error("unit_spec_ref differs from actual Run", "conflict")
            experiment = self.artifacts.read_json(ref)
            task = self._task(experiment, scorer)
            unit = self._unit(experiment, ref, task, unit_id=selection["unit_id"],
                              evaluation_case_id=selection["evaluation_case_id"], candidate_id=selection["candidate_id"],
                              repetition=selection["repetition"], tags=selection["tags"])
            units.append(unit)
            experiments[unit["unit_id"]] = experiment
            selected[unit["unit_id"]] = (run, selection["unavailable_reason"])
        self._check_units(units, experiments, scorer, spec)
        return self._execute(spec, units, experiments, scorer, selected)

    def _outcomes(self, spec: dict, outcome_schema: Any, evaluation_id: str, evidence: list) -> tuple:
        scoring = spec["scoring"]
        cutoff = scoring["outcomes"]["as_of"] or utc_now()
        cutoff_time = _timestamp(cutoff)
        records, source_refs, identities = [], [], {}
        for view in scoring["outcomes"]["sources"]:
            value = self.artifacts.read_view(view)
            rows = self._payload(value)
            if isinstance(rows, dict) and "outcomes" in rows:
                rows = rows["outcomes"]
            if not isinstance(rows, list):
                raise _error("Outcome source must contain OutcomeRecord list", "schema_mismatch")
            effective_cutoff = min(cutoff_time, _timestamp(view["as_of"])) if view.get("as_of") is not None else cutoff_time
            source_refs.extend(view["source_refs"])
            for row in rows:
                required = {"outcome_id", "revision", "alignment_key", "payload", "event_time", "available_at", "recorded_at", "source_ref", "supersedes_ref", "allowed_uses"}
                _object(row, required, path="OutcomeRecord")
                if _timestamp(row["available_at"]) > effective_cutoff or _timestamp(row["recorded_at"]) > effective_cutoff:
                    continue
                uses = row["allowed_uses"]
                if not isinstance(uses, list) or any(not isinstance(use, str) or use not in {"evaluation", "training_export", "online_feedback"} for use in uses) or len(set(uses)) != len(uses):
                    raise _error("Outcome allowed_uses must list unique supported purposes", "schema_mismatch")
                if "evaluation" not in uses:
                    raise _error("Outcome does not authorize evaluation", "permission_denied", outcome_id=row["outcome_id"])
                self.schemas.validate("gymts.artifact/1", row["source_ref"])
                if hasattr(self.artifacts, "resolve"):
                    self.artifacts.resolve(row["source_ref"])
                else:
                    self.artifacts.read_json(row["source_ref"])
                if outcome_schema is not None:
                    if row["payload"].get("schema_ref") != outcome_schema:
                        raise _error("Outcome Payload schema differs from task", "schema_mismatch")
                    self.schemas.validate(outcome_schema, self._payload(row["payload"]))
                self.schemas.validate(scoring["alignment"]["schema_ref"], row["alignment_key"])
                key = (row["outcome_id"], row["revision"])
                previous = identities.get(key)
                if previous is not None:
                    if canonical_json(previous) != canonical_json(row):
                        raise _error("Same outcome revision has conflicting content", "conflict")
                    continue
                identities[key] = row
                records.append(row)
        aligned = {}
        keys = scoring["alignment"]["keys"]
        for row in records:
            if any(key not in row["alignment_key"] for key in keys):
                raise _error("Outcome missing alignment key", "schema_mismatch")
            alignment = canonical_json({key: row["alignment_key"][key] for key in keys})
            if alignment not in aligned:
                aligned[alignment] = row
                continue
            if scoring["alignment"]["duplicate_policy"] == "error":
                raise _error("Duplicate outcome alignment", "conflict")
            previous = aligned[alignment]
            current_time = (_timestamp(row["available_at"]), _timestamp(row["recorded_at"]))
            previous_time = (_timestamp(previous["available_at"]), _timestamp(previous["recorded_at"]))
            if current_time == previous_time:
                raise _error("Ambiguous latest outcome alignment", "conflict")
            if current_time > previous_time:
                aligned[alignment] = row
        rows_ref = self._save(list(aligned.values()), "gymts.outcome-records/1", evaluation_id, evidence)
        view = {"schema_ref": outcome_schema, "as_of": cutoff, "source_refs": source_refs, "records_ref": rows_ref}
        ref = self._save(view, "gymts.outcome-view/1", evaluation_id, evidence)
        return {"view_ref": ref, **view}, list(aligned.values())

    def _payload(self, payload: dict) -> Any:
        if not isinstance(payload, dict):
            raise _error("Payload must be an object", "schema_mismatch")
        if payload.get("storage") == "inline" and "value" in payload and "artifact_ref" not in payload:
            return payload["value"]
        if payload.get("storage") == "artifact" and "artifact_ref" in payload and "value" not in payload:
            if payload["artifact_ref"].get("schema_ref") != payload.get("schema_ref"):
                raise _error("Payload and artifact schemas differ", "schema_mismatch")
            return self.artifacts.read_json(payload["artifact_ref"])
        raise _error("Payload must use exactly one storage form", "schema_mismatch")

    def _results(self, unit: dict, run: Any, execution: dict, spec: dict) -> tuple:
        if run is None or run.get("result") is None:
            return [], [], "run_unavailable"
        result = run["result"]
        events = run.get("events")
        if events is None:
            snapshot = self.artifacts.read_json(run["execution_snapshot_ref"])
            events = snapshot.get("events", []) if isinstance(snapshot, dict) else snapshot
        rows = self.artifacts.read_json(result["result_ref"])
        if isinstance(rows, dict) and "results" in rows:
            rows = rows["results"]
        if not isinstance(rows, list):
            raise _error("Run result_ref must contain TaskResult list", "schema_mismatch")
        # Exclusion is a selection decision; evidence still remains in the fixed view.
        excluded = execution["status"] != "succeeded" and spec["failure_policy"]["partial_results"] == "exclude"
        identities = set()
        for row in rows:
            _object(row, {"result_id", "run_id", "case_id", "turn_id", "input_id", "output_id", "task_protocol_ref",
                          "decision_time", "alignment_key", "status", "payload"}, path="TaskResult")
            if not isinstance(row["result_id"], str) or not row["result_id"]:
                raise _error("TaskResult requires a nonempty result_id", "schema_mismatch")
            if row["result_id"] in identities:
                raise _error("Run contains a repeated TaskResult identity", "conflict", result_id=row["result_id"])
            identities.add(row["result_id"])
            if row.get("task_protocol_ref") != unit["task_protocol_ref"] or row.get("run_id") != run["run_id"]:
                raise _error("TaskResult identity differs from its Run", "schema_mismatch")
            self.schemas.validate(spec["scoring"]["alignment"]["schema_ref"], row["alignment_key"])
            if any(key not in row["alignment_key"] for key in spec["scoring"]["alignment"]["keys"]):
                raise _error("TaskResult is missing a scoring alignment key", "schema_mismatch")
            payload = row.get("payload", {})
            if payload.get("schema_ref") != unit["result_schema_ref"]:
                raise _error("TaskResult Payload schema differs from task", "schema_mismatch")
            self.schemas.validate(unit["result_schema_ref"], self._payload(payload))
            if row.get("status") not in {"valid", "invalid"}:
                raise _error("TaskResult has invalid status", "schema_mismatch")
            if row["status"] == "invalid" and spec["failure_policy"]["invalid_result_policy"] == "abort":
                raise _error("Task supplied an invalid result", "schema_mismatch")
        return [{**row, "unit_id": unit["unit_id"]} for row in rows], events, "partial_results_excluded" if excluded else None

    @staticmethod
    def _refs(value: Any) -> list:
        refs = []
        if isinstance(value, dict):
            if {"artifact_id", "revision", "uri"}.issubset(value):
                refs.append(value)
            else:
                for item in value.values():
                    refs.extend(AutoBenchTS._refs(item))
        elif isinstance(value, list):
            for item in value:
                refs.extend(AutoBenchTS._refs(item))
        return refs

    def _metric(self, result: dict, excluded: bool) -> dict:
        _object(result, {"value", "status", "counts", "reason"}, path="MetricResult")
        if result["status"] not in {"ready", "insufficient_evidence", "error"}:
            raise _error("Unknown metric status", "schema_mismatch")
        counts = _object(result["counts"], set(COUNT_KEYS), path="MetricCounts")
        for key, value in counts.items():
            _integer(value, "counts." + key)
        if counts["eligible"] != sum(counts[key] for key in COUNT_KEYS if key != "eligible"):
            raise _error("Metric eligible count differs from scored+missing+invalid+excluded", "schema_mismatch")
        if result["value"] is not None:
            _number(result["value"], "metric value")
        if result["status"] == "ready" and result["value"] is None or result["status"] != "ready" and result["value"] is not None:
            raise _error("Metric value must be numeric exactly when ready", "schema_mismatch")
        if result["status"] == "ready" and counts["scored"] == 0:
            raise _error("A ready metric requires at least one scored item", "schema_mismatch")
        if result["reason"] is not None and not isinstance(result["reason"], str):
            raise _error("Metric reason must be string or null", "schema_mismatch")
        result = deepcopy(result)
        if excluded:
            result["counts"] = {"eligible": counts["eligible"], "scored": 0, "missing": 0, "invalid": 0, "excluded": counts["eligible"]}
            result.update(value=None, status="insufficient_evidence", reason="partial_results_excluded")
        if result["counts"]["eligible"] == 0:
            result.update(value=None, status="insufficient_evidence", reason="empty_eligible_set")
        return result

    def _execute(self, spec: dict, units: list, experiments: dict, scorer_manifest: dict, selected: dict) -> dict:
        evaluation_id, created_at, evidence = new_id("evaluation"), utc_now(), []
        spec_ref = self._save(spec, spec["protocol_version"], evaluation_id, evidence)
        component_refs = [scorer_manifest["component_ref"]]
        for experiment in experiments.values():
            task_spec, candidate_spec = experiment["scene"]["task"], experiment["candidate"]
            task_manifest = self.environment_ts.tasks.resolve(task_spec["plugin"], task_spec["version"])
            candidate_manifest = self.environment_ts.candidates.resolve(candidate_spec["adapter"], candidate_spec["version"])
            component_refs.extend([task_manifest["component_ref"], candidate_manifest["implementation_ref"]])
            if candidate_manifest.get("component_ref"):
                component_refs.append(candidate_manifest["component_ref"])
            component_refs.extend(candidate_manifest.get("component_refs", []))
            if hasattr(self.environment_ts, "registries"):
                env_spec = experiment["scene"]["environment"]
                component_refs.append(self.environment_ts.registries.environments.resolve(env_spec["adapter"], env_spec["version"])["component_ref"])
        component_refs = list({canonical_json(ref): ref for ref in component_refs}.values())
        plan = {"protocol_version": "gymts.evaluation-plan/1", "evaluation_id": evaluation_id,
                "spec_ref": spec_ref, "resolved_component_refs": component_refs,
                "expected_units": units, "created_at": created_at}
        plan_ref = self._save(plan, plan["protocol_version"], evaluation_id, evidence)
        executions, run_records, errors = [], {}, []
        evaluation_cancelled = False
        for unit in units:
            run, error, unavailable = None, None, None
            if spec["protocol_version"] == "gymts.evaluation/1" and evaluation_cancelled:
                status, run_id, run_ref = "not_started", None, None
                error = _error("Evaluation cancelled before this unit started", "invalid_state").info
            elif spec["protocol_version"] == "gymts.evaluation/1":
                try:
                    result = self.environment_ts.run(experiments[unit["unit_id"]])
                    run = self.records.get_run(result["run_id"])
                    run_ref = self._save(result, "gymts.run-result/1", evaluation_id, evidence)
                    status, run_id = result["status"], result["run_id"]
                    if status != "succeeded":
                        error = next(iter(result.get("errors", [])), None)
                except Exception as exc:
                    if isinstance(exc, GymTSError) and exc.code == "recording_failure" and exc.info["links"].get("evaluation_id"):
                        raise
                    error = self._exception(exc, "run")
                    status, run_id, run_ref = "failed", error.get("run_id"), None
                    if run_id:
                        try:
                            run = self.records.get_run(run_id)
                        except Exception:
                            pass
            else:
                run, unavailable = selected[unit["unit_id"]]
                result = run.get("result") if run is not None else None
                if result is None:
                    status, run_id, run_ref = "not_started", run["run_id"] if run else None, None
                    error = _error(unavailable or "Run is not sealed", "invalid_state").info
                else:
                    status, run_id = result["status"], result["run_id"]
                    error = next(iter(result.get("errors", [])), None) if status != "succeeded" else None
                    run_ref = self._save(result, "gymts.run-result/1", evaluation_id, evidence)
            if status not in {"succeeded", "failed", "cancelled", "not_started"}:
                raise _error("Run returned an invalid status", "schema_mismatch", evaluation_id=evaluation_id)
            if status == "cancelled" and spec["protocol_version"] == "gymts.evaluation/1":
                evaluation_cancelled = True
            if error:
                errors.append(error)
            executions.append({"unit_id": unit["unit_id"], "run_id": run_id, "status": status,
                               "run_result_ref": run_ref, "error": error})
            run_records[unit["unit_id"]] = run
        manifest = {"protocol_version": "gymts.run-manifest/1", "evaluation_id": evaluation_id, "entries": executions}
        manifest_ref = self._save(manifest, manifest["protocol_version"], evaluation_id, evidence)
        result_view_refs, metric_entries, outcome_view = [], [], None
        workflow_status, reasons = "completed", ["evaluation_cancelled"] if evaluation_cancelled else []
        try:
            run_ids = [entry["run_id"] for entry in executions if entry["run_id"] is not None and run_records[entry["unit_id"]] is not None]
            snapshot = self.records.snapshot(run_ids, {"through_seq": None, "outcomes_as_of": spec["scoring"]["outcomes"]["as_of"], "outcome_refs": None})
            evidence.append(snapshot["snapshot_ref"])
            task = self._task(experiments[units[0]["unit_id"]], scorer_manifest)
            outcome_view, outcome_records = self._outcomes(spec, task["outcome_schema_ref"], evaluation_id, evidence)
            scorer = self.scorers.create(spec["scoring"]["scorer"])
            for unit, execution in zip(units, executions):
                rows, events, exclusion = self._results(unit, run_records[unit["unit_id"]], execution, spec)
                rows_ref = self._save(rows, "gymts.evaluation-results/1", evaluation_id, evidence)
                events_ref = self._save(events, "gymts.evaluation-events/1", evaluation_id, evidence)
                view = {"unit_id": unit["unit_id"], "task_protocol_ref": unit["task_protocol_ref"], "schema_ref": unit["result_schema_ref"],
                        "run_manifest_ref": manifest_ref, "records_ref": rows_ref, "event_snapshot_ref": events_ref,
                        "selection": {"schema_ref": "gymts.result-selection/1", "storage": "inline", "value": {
                            "unit_id": unit["unit_id"], "partial_results": spec["failure_policy"]["partial_results"],
                            "excluded_reason": exclusion, "eligibility_refs": {metric: scorer_manifest["metrics"][metric]["eligibility_ref"] for metric in spec["scoring"]["metrics"]}}}}
                view_ref = self._save(view, "gymts.result-view/1", evaluation_id, evidence)
                result_view_refs.append(view_ref)
                view = {"view_ref": view_ref, **view}
                allowed = [view_ref, rows_ref, events_ref, manifest_ref, plan_ref, outcome_view["view_ref"], outcome_view["records_ref"]]
                allowed.extend(self._refs(rows))
                allowed.extend(self._refs(events))
                allowed.extend(self._refs(outcome_records))
                context = {"evaluation_id": evaluation_id, "unit": deepcopy(unit), "plan_ref": plan_ref,
                           "scoring": deepcopy(spec["scoring"]), "services": RestrictedScoringServices(self.artifacts, allowed)}
                if exclusion == "run_unavailable":
                    for metric in spec["scoring"]["metrics"]:
                        metric_entries.append({"level": "unit", "candidate_id": unit["candidate_id"],
                                               "group_key": group_key(unit, spec["comparison"]), "unit_id": unit["unit_id"],
                                               "repetition": unit["repetition"], "metric_id": metric,
                                               "result": empty_metric("run_unavailable")})
                    continue
                try:
                    scores = scorer.score(view, outcome_view, context)
                    _object(scores, {"metrics", "item_scores_ref", "diagnostics_ref"}, path="ScoreResult")
                    if not isinstance(scores["metrics"], dict) or set(scores["metrics"]) != set(spec["scoring"]["metrics"]):
                        raise _error("Scorer must return exactly the requested metrics", "schema_mismatch")
                    for ref in (scores["item_scores_ref"], scores["diagnostics_ref"]):
                        if ref is not None:
                            if hasattr(self.artifacts, "resolve"):
                                self.artifacts.resolve(ref)
                            else:
                                self.artifacts.read_json(ref)
                            evidence.append(ref)
                    for metric, result in scores["metrics"].items():
                        result = self._metric(result, exclusion == "partial_results_excluded")
                        if scorer_manifest["metrics"][metric]["requires_outcome"] and not outcome_records and result["counts"]["scored"]:
                            raise _error("Outcome-dependent metric claimed scores without outcome evidence", "schema_mismatch")
                        if exclusion == "run_unavailable":
                            result = empty_metric("run_unavailable")
                        metric_entries.append({"level": "unit", "candidate_id": unit["candidate_id"],
                                               "group_key": group_key(unit, spec["comparison"]), "unit_id": unit["unit_id"],
                                               "repetition": unit["repetition"], "metric_id": metric, "result": result})
                except Exception as exc:
                    raise _error("Scorer failed: {}".format(type(exc).__name__), "scorer_failure", unit_id=unit["unit_id"], cause=getattr(exc, "info", None)) from exc
        except Exception as exc:
            if isinstance(exc, GymTSError) and exc.code == "recording_failure" and exc.info["links"].get("evaluation_id"):
                raise
            workflow_status = "failed"
            errors.append(self._exception(exc, "score"))
            reasons.append("scorer_failure" if isinstance(exc, GymTSError) and exc.code == "scorer_failure" else "evaluation_evidence_failure")
        obtained = {(entry["unit_id"], entry["metric_id"]) for entry in metric_entries}
        for unit in units:
            for metric in spec["scoring"]["metrics"]:
                if (unit["unit_id"], metric) not in obtained:
                    metric_entries.append({"level": "unit", "candidate_id": unit["candidate_id"],
                                           "group_key": group_key(unit, spec["comparison"]), "unit_id": unit["unit_id"],
                                           "repetition": unit["repetition"], "metric_id": metric,
                                           "result": empty_metric("evaluation_aborted" if workflow_status == "failed" else "run_unavailable")})
        grouped = aggregate(units, metric_entries, spec["scoring"], spec["comparison"])
        metric_entries.extend(grouped)
        comparisons = compare(grouped, spec["baseline_id"], spec["comparison"]["baseline_method"])
        gate_results = gates(units, executions, grouped, spec["comparison"], spec["baseline_id"])
        if any(gate["status"] == "fail" for gate in gate_results):
            verdict = "fail"
        elif workflow_status == "failed" or any(entry["result"]["status"] != "ready" for entry in grouped) or any(gate["status"] != "pass" for gate in gate_results):
            verdict = "insufficient_evidence"
        elif gate_results:
            verdict = "pass"
        else:
            verdict = "insufficient_evidence"
        if not spec["comparison"]["gates"]:
            reasons.append("no_acceptance_gate")
        if any(entry["result"]["status"] != "ready" for entry in grouped):
            reasons.append("insufficient_metric_evidence")
        report = {"protocol_version": "gymts.evaluation-report/1", "evaluation_id": evaluation_id,
                  "previous_evaluation_id": spec.get("previous_evaluation_id"), "status": workflow_status,
                  "created_at": created_at, "plan_ref": plan_ref, "run_manifest_ref": manifest_ref,
                  "result_view_refs": result_view_refs, "outcome_view_ref": outcome_view["view_ref"] if outcome_view else None,
                  "scorer_ref": scorer_manifest["component_ref"], "metrics": metric_entries, "comparisons": comparisons,
                  "gate_results": gate_results, "coverage": {"expected_units": len(units),
                    "succeeded_runs": sum(entry["status"] == "succeeded" for entry in executions),
                    "failed_runs": sum(entry["status"] == "failed" for entry in executions),
                    "cancelled_runs": sum(entry["status"] == "cancelled" for entry in executions),
                    "not_started_units": sum(entry["status"] == "not_started" for entry in executions)},
                  "verdict": verdict, "reasons": reasons, "evidence_refs": list(evidence), "errors": errors}
        self.last_report_ref = self._save(report, report["protocol_version"], evaluation_id, evidence)
        return report

    @staticmethod
    def _exception(exc: Exception, method: str) -> dict:
        if isinstance(exc, GymTSError):
            return exc.info
        return GymTSError("backend_failure", "Evaluation {} failed ({})".format(method, type(exc).__name__),
                          stage="evaluation", method=method).info
