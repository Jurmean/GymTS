"""Per-planning-unit official TSAD evaluation, with frozen curve eligibility.

Only this evaluation adapter receives labels. The scientific worker evaluates
saved scores; it has no fitting or model execution entrypoint.
"""
import copy
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile

from gymts.contracts import GymTSError, canonical_json, parse_time
from gymts.contracts.schema import OBJECT, STRING, SchemaRegistry, array, nullable, obj
from gymts.plugin_support import component, unpack

from .contracts import ALIGNMENT, OUTCOME, PROTOCOL, RESULT, validate


METRIC_IDS = (
    "point-wise-f1", "reduced-length-f1", "event-wise-f1", "delay-reduced-length-f1",
    "point-wise-auprc", "reduced-length-auprc", "event-wise-auprc", "delay-reduced-length-auprc",
)
SCORER_PARAMS_REF = "gymts.timesigma/scorer-params/1"
ELIGIBILITY_SCHEMA_REF = "gymts.timesigma/curve-eligibility/1"
ITEM_SCORES_REF = "gymts.timesigma/item-scores/1"
DIAGNOSTICS_REF = "gymts.timesigma/scoring-diagnostics/1"
ELIGIBILITY_REF = component("timesigma.planned-evaluation-curves")


def scorer_schemas():
    return {
        SCORER_PARAMS_REF: obj({"source_repo": STRING, "python": STRING,
            "timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
            "dataset": STRING, "planning_unit_id": STRING,
            "evaluation_members": array(STRING, minItems=1, uniqueItems=True)},
            required=["source_repo", "python", "dataset", "planning_unit_id", "evaluation_members"]),
        ELIGIBILITY_SCHEMA_REF: obj({"dataset_revision": STRING, "planning_unit_id": STRING, "curve_id": STRING}),
        ITEM_SCORES_REF: obj({"records": array(OBJECT)}),
        DIAGNOSTICS_REF: obj({"dataset": STRING, "planning_unit_id": STRING,
            "dataset_revision": nullable(STRING), "evaluation_members": array(STRING),
            "aggregation": STRING, "native": nullable(OBJECT)}),
    }


def _fail(code, message, **links):
    raise GymTSError(code, message, stage="scoring", method="timesigma-official", links=links)


def _records(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("records", "results", "outcomes", "items"):
            if isinstance(value.get(key), list):
                return value[key]
    _fail("schema_mismatch", "TimeSigma scoring snapshot must contain a records list")


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


class TimeSigmaOfficialScorer:
    def __init__(self, spec):
        self.params = copy.deepcopy(spec.get("params", {}))
        schemas = SchemaRegistry()
        schemas.register(SCORER_PARAMS_REF, scorer_schemas()[SCORER_PARAMS_REF])
        schemas.validate(SCORER_PARAMS_REF, self.params)
        self.params.setdefault("timeout_seconds", 180)

    def validate_scoring(self, scoring):
        alignment = scoring["alignment"]
        if (alignment["schema_ref"] != ALIGNMENT or alignment["matching"] != "exact" or
                len(alignment["keys"]) != 2 or
                set(alignment["keys"]) != {"dataset_revision", "planning_unit_id"}):
            _fail("unsupported_capability", "Official TSAD evaluation requires exact dataset/planning-unit alignment")
        if alignment["duplicate_policy"] not in ("error", "latest_available"):
            _fail("unsupported_capability", "Unsupported TSAD duplicate policy")
        metrics = scoring["metrics"]
        if not metrics or len(set(metrics)) != len(metrics) or any(metric not in METRIC_IDS for metric in metrics):
            _fail("unsupported_capability", "Use the original TimeSigma official metric identifiers")

    def _run_native(self, curves, metrics):
        repository = str(Path(self.params["source_repo"]).expanduser().resolve())
        python = self.params["python"]
        if os.path.sep in python:
            # Keep the venv launcher rather than resolving its interpreter link.
            python = str(Path(python).expanduser().absolute())
        request = {"source_repo": repository, "dataset": self.params["dataset"],
                   "curves": curves, "metrics": metrics}
        environment = dict(os.environ)
        for name in tuple(environment):
            if re.search(r"api.?key|access.?token|secret|password|authorization", name, re.I):
                environment.pop(name)
        environment.update(PYTHONNOUSERSITE="1", PYTHONUNBUFFERED="1", CUDA_VISIBLE_DEVICES="")
        environment.pop("PYTHONPATH", None)
        for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
            environment[name] = "1"
        try:
            with tempfile.TemporaryDirectory(prefix="gymts-timesigma-score-") as cwd:
                result = subprocess.run([python, "-m", "gymts_timesigma.scoring_worker"],
                    input=canonical_json(request), capture_output=True, env=environment, cwd=cwd,
                    timeout=self.params["timeout_seconds"])
        except subprocess.TimeoutExpired:
            _fail("deadline_exceeded", "Official TimeSigma evaluation timed out")
        except OSError:
            _fail("unsupported_capability", "The configured TimeSigma scientific interpreter is unavailable")
        try:
            response = json.loads(result.stdout)
        except (ValueError, UnicodeError):
            _fail("scorer_failure", "Official TimeSigma evaluation returned invalid JSON", exit_code=result.returncode)
        if result.returncode or not isinstance(response, dict) or not response.get("ok"):
            detail = response.get("error", {}) if isinstance(response, dict) else {}
            _fail(detail.get("code", "scorer_failure"), detail.get("message", "Official TimeSigma evaluation failed"))
        return response["result"]

    def score(self, results, outcomes, context):
        scoring, services = context["scoring"], context["services"]
        self.validate_scoring(scoring)
        if results["task_protocol_ref"] != PROTOCOL or results["schema_ref"] != RESULT:
            _fail("schema_mismatch", "TimeSigma scorer received a different task/result contract")
        if outcomes["schema_ref"] != OUTCOME:
            _fail("schema_mismatch", "TimeSigma scorer received a different outcome contract")
        rows = _records(services.read_json(results["records_ref"]))
        if len(rows) > 1:
            _fail("schema_mismatch", "A TSAD planning unit has at most one container result")
        members = self.params["evaluation_members"]
        metric_ids = scoring["metrics"]
        counts = {"eligible": len(members), "scored": 0, "missing": 0, "invalid": 0, "excluded": 0}
        item_rows, native_curves, revision = [], [], None
        predicted, truth, result_id = {}, {}, None
        invalid_result = False
        if rows:
            row = rows[0]
            result_id = row["result_id"]
            if row["status"] != "valid":
                invalid_result = True
            else:
                if row["payload"]["schema_ref"] != RESULT:
                    _fail("schema_mismatch", "Result payload has a different schema")
                answer = unpack(row["payload"], services)
                validate(RESULT, answer)
                revision = answer["dataset_revision"]
                expected_key = {"dataset_revision": revision, "planning_unit_id": self.params["planning_unit_id"]}
                if answer["planning_unit_id"] != self.params["planning_unit_id"] or row["alignment_key"] != expected_key:
                    _fail("schema_mismatch", "Result identity differs from its frozen planning unit")
                if [curve["curve_id"] for curve in answer["curves"]] != members:
                    _fail("schema_mismatch", "Result curves differ from ordered evaluation members")
                for curve in answer["curves"]:
                    if curve["offset"] + len(curve["scores"]) != curve["raw_length"]:
                        _fail("schema_mismatch", "Score support must be the exact declared suffix")
                    predicted[curve["curve_id"]] = curve
                matches = []
                for outcome in _records(services.read_json(outcomes["records_ref"])):
                    if "evaluation" not in outcome.get("allowed_uses", []):
                        _fail("permission_denied", "Outcome is not authorized for evaluation")
                    if outcome["alignment_key"] == expected_key:
                        matches.append(outcome)
                if len(matches) > 1:
                    if scoring["alignment"]["duplicate_policy"] == "error":
                        _fail("conflict", "Duplicate TSAD outcome for a planning unit")
                    order = lambda item: (parse_time(item["available_at"]), parse_time(item["recorded_at"]))
                    matches.sort(key=order)
                    if order(matches[-1]) == order(matches[-2]):
                        _fail("conflict", "Latest TSAD outcome is ambiguous")
                if matches:
                    selected = matches[-1]
                    if selected["payload"]["schema_ref"] != OUTCOME:
                        _fail("schema_mismatch", "Outcome payload has a different schema")
                    gold = unpack(selected["payload"], services)
                    validate(OUTCOME, gold)
                    if any(gold[name] != expected_key[name] for name in expected_key):
                        _fail("schema_mismatch", "Outcome container disagrees with its alignment key")
                    for curve in gold["curves"]:
                        name = curve["curve_id"]
                        if name not in members or name in truth:
                            _fail("schema_mismatch", "Outcome curves must be unique evaluation members")
                        truth[name] = {**curve, "outcome_id": selected["outcome_id"], "outcome_revision": selected["revision"]}
        for name in members:
            item = {"curve_id": name, "dataset_revision": revision, "planning_unit_id": self.params["planning_unit_id"],
                    "result_id": result_id, "metrics": {}, "status": "invalid" if invalid_result else "missing",
                    "reason": "invalid_result" if invalid_result else "missing_result" if not rows else "missing_outcome"}
            if invalid_result:
                counts["invalid"] += 1
            elif name not in predicted or name not in truth:
                counts["missing"] += 1
            else:
                prediction, labels = predicted[name], truth[name]["labels"]
                if len(labels) != prediction["raw_length"]:
                    _fail("schema_mismatch", "Official labels must cover the complete original test curve")
                native_curves.append({**prediction, "labels": labels})
                item.update(outcome_id=truth[name]["outcome_id"], outcome_revision=truth[name]["outcome_revision"])
            item_rows.append(item)
        native = self._run_native(native_curves, metric_ids) if native_curves else None
        if native is not None:
            evaluated = native.get("per_curve", [])
            if [item.get("curve_id") for item in evaluated] != [item["curve_id"] for item in native_curves]:
                _fail("scorer_failure", "Native evaluator returned different curve identities")
            indexed = {item["curve_id"]: item for item in evaluated}
            for item in item_rows:
                if item["curve_id"] not in indexed:
                    continue
                actual = indexed[item["curve_id"]]
                status = actual.get("status")
                if status not in ("scored", "excluded"):
                    _fail("scorer_failure", "Native evaluator returned an unknown curve status")
                if (set(actual.get("metrics", {})) != set(metric_ids) or
                        any(not _finite(value) if status == "scored" else value is not None
                            for value in actual["metrics"].values())):
                    _fail("scorer_failure", "Native evaluator returned inconsistent per-curve metrics")
                item.update(status=status, reason=actual.get("reason"), metrics=copy.deepcopy(actual["metrics"]))
                counts[status] += 1
            if set(native.get("metrics", {})) != set(metric_ids):
                _fail("scorer_failure", "Native evaluator returned different metric identifiers")
        metrics = {}
        for metric in metric_ids:
            value = native["metrics"][metric] if native else None
            if value is not None and not _finite(value):
                _fail("scorer_failure", "Official evaluator returned a non-finite metric")
            if bool(counts["scored"]) != (value is not None):
                _fail("scorer_failure", "Official metric availability disagrees with scored curve count")
            metrics[metric] = {"value": value, "status": "ready" if value is not None else "insufficient_evidence",
                "counts": copy.deepcopy(counts), "reason": None if value is not None else "no_officially_scored_curves"}
        return {"metrics": metrics, "item_scores_ref": services.save_json({"records": item_rows}, ITEM_SCORES_REF),
            "diagnostics_ref": services.save_json({"dataset": self.params["dataset"], "planning_unit_id": self.params["planning_unit_id"],
                "dataset_revision": revision, "evaluation_members": members,
                "aggregation": "native curve evaluation and MetricInterface.add/avg; no concatenation", "native": native}, DIAGNOSTICS_REF)}


TimeSigmaScorer = TimeSigmaOfficialScorer
