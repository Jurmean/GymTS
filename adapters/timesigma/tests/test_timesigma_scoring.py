"""Scorer boundaries and opt-in parity against the real native evaluator.

Injected .2/.8 values below are explicit contract fixtures, not TSAD metrics.
Set GYMTS_TIMESIGMA_NATIVE_TESTS=1 to use the fixed scientific environment.
"""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gymts.contracts import GymTSError, canonical_json
from gymts.contracts.schema import SchemaRegistry
from gymts_timesigma.contracts import ALIGNMENT, OUTCOME, PROTOCOL, RESULT
from gymts_timesigma.scoring import (
    DIAGNOSTICS_REF, METRIC_IDS, SCORER_PARAMS_REF, TimeSigmaOfficialScorer, scorer_schemas)


def body(schema, value):
    return {"schema_ref": schema, "storage": "inline", "value": copy.deepcopy(value)}


def alignment():
    return {"dataset_revision": "fixed-data-v1", "planning_unit_id": "frozen-unit"}


def result(curves=None):
    curves = curves if curves is not None else [
        {"curve_id": name, "scores": [0., 1., .5], "offset": 2, "raw_length": 5} for name in ("a", "b")]
    return {"result_id": "result-1", "status": "valid", "alignment_key": alignment(),
            "payload": body(RESULT, {**alignment(), "curves": curves, "evidence": {"source": "contract-fixture"}})}


def outcome(names=("a", "b"), identity=None, **extra):
    key = identity or alignment()
    return {"outcome_id": "outcome-1", "revision": "1", "alignment_key": key,
        "allowed_uses": ["evaluation"], "available_at": "2026-10-19T00:00:00Z", "recorded_at": "2026-10-19T00:00:00Z",
        "payload": body(OUTCOME, {**key, "curves": [{"curve_id": name, "labels": [0, 0, 0, 1, 0]} for name in names]}), **extra}


class Views:
    """Explicit readonly input snapshots; only new scoring artifacts are writable."""
    def __init__(self, results, outcomes):
        self.data = {"results": copy.deepcopy(results), "outcomes": copy.deepcopy(outcomes)}
        self.saved = {}

    def read_json(self, ref):
        if ref not in self.data:
            raise GymTSError("permission_denied", "Not an authorized snapshot")
        return copy.deepcopy(self.data[ref])

    def save_json(self, value, schema):
        canonical_json(value)
        schemas = SchemaRegistry()
        schemas.register(schema, scorer_schemas()[schema])
        schemas.validate(schema, value)
        reference = "saved-" + str(len(self.saved))
        self.saved[reference] = {"schema": schema, "value": copy.deepcopy(value)}
        return reference


class TimeSigmaScoringTests(unittest.TestCase):
    def setUp(self):
        self.params = {"source_repo": "fixture-not-executed", "python": "fixture-not-executed", "dataset": "TODS",
                       "planning_unit_id": "frozen-unit", "evaluation_members": ["a", "b"]}
        self.scorer = TimeSigmaOfficialScorer({"params": self.params})
        self.scoring = {"metrics": list(METRIC_IDS), "alignment": {"schema_ref": ALIGNMENT, "matching": "exact",
            "keys": ["dataset_revision", "planning_unit_id"], "duplicate_policy": "error"}}

    def call(self, rows=None, labels=None, native=None):
        views = Views([result()] if rows is None else rows, [outcome()] if labels is None else labels)
        with patch.object(self.scorer, "_run_native", side_effect=native or self.native_fixture) as invoked:
            report = self.scorer.score({"task_protocol_ref": PROTOCOL, "schema_ref": RESULT, "records_ref": "results"},
                {"schema_ref": OUTCOME, "records_ref": "outcomes"}, {"scoring": self.scoring, "services": views})
        return report, views, invoked

    @staticmethod
    def native_fixture(curves, metrics):
        values = {"a": .2, "b": .8}
        per_curve = [{"curve_id": row["curve_id"], "status": "scored", "reason": None,
                      "metrics": {name: values[row["curve_id"]] for name in metrics}} for row in curves]
        return {"metrics": {name: sum(values[row["curve_id"]] for row in curves) / len(curves) for name in metrics},
                "per_curve": per_curve, "provenance": {"evidence_origin": "synthetic_contract_fixture"}}

    def test_exact_official_metric_identifiers_and_strict_parameters(self):
        self.assertEqual(len(METRIC_IDS), 8)
        self.assertIn("point-wise-auprc", METRIC_IDS)
        self.scoring["metrics"] = ["point_f1"]
        with self.assertRaises(GymTSError):
            self.call()
        for extra in ({"evaluation_members": ["a", "a"]}, {"timeout_seconds": 0}, {"ignore_labels": True}):
            with self.subTest(extra=extra), self.assertRaises(GymTSError):
                TimeSigmaOfficialScorer({"params": {**self.params, **extra}})

    def test_complete_curves_remain_independent_and_inputs_are_not_mutated(self):
        rows, gold = [result()], [outcome()]
        before = copy.deepcopy((rows, gold))
        report, views, invoked = self.call(rows, gold)
        self.assertEqual((rows, gold), before)
        args = invoked.call_args.args[0]
        self.assertEqual([row["curve_id"] for row in args], ["a", "b"])
        self.assertTrue(all(len(row["labels"]) == 5 and len(row["scores"]) == 3 and row["offset"] == 2 for row in args))
        for value in report["metrics"].values():
            self.assertEqual(value, {"value": .5, "status": "ready", "counts": {
                "eligible": 2, "scored": 2, "missing": 0, "invalid": 0, "excluded": 0}, "reason": None})
        self.assertEqual(views.saved[report["diagnostics_ref"]]["schema"], DIAGNOSTICS_REF)

    def test_partial_labels_do_not_shrink_planned_denominator(self):
        report, _, invoked = self.call(labels=[outcome(("a",))])
        self.assertEqual(len(invoked.call_args.args[0]), 1)
        metric = report["metrics"][METRIC_IDS[0]]
        self.assertEqual(metric["value"], .2)
        self.assertEqual(metric["counts"], {"eligible": 2, "scored": 1, "missing": 1, "invalid": 0, "excluded": 0})

    def test_no_output_or_no_labels_keep_eligibility_and_do_not_execute_native(self):
        for rows, gold in (([], [outcome()]), ([result()], [])):
            with self.subTest(rows=bool(rows)):
                report, _, invoked = self.call(rows=rows, labels=gold)
                invoked.assert_not_called()
                for metric in report["metrics"].values():
                    self.assertIsNone(metric["value"])
                    self.assertEqual(metric["status"], "insufficient_evidence")
                    self.assertEqual(metric["counts"]["eligible"], 2)
                    self.assertEqual(metric["counts"]["missing"], 2)

    def test_invalid_container_preserves_two_invalid_planned_curves(self):
        item = result()
        item["status"] = "invalid"
        report, _, invoked = self.call(rows=[item])
        invoked.assert_not_called()
        self.assertEqual(report["metrics"][METRIC_IDS[0]]["counts"]["invalid"], 2)

    def test_labels_of_other_revision_or_planning_unit_cannot_match(self):
        for field in alignment():
            key = {**alignment(), field: "other"}
            report, _, invoked = self.call(labels=[outcome(identity=key)])
            invoked.assert_not_called()
            self.assertEqual(report["metrics"][METRIC_IDS[0]]["counts"]["missing"], 2)

    def test_evaluation_authorization_is_required(self):
        with self.assertRaises(GymTSError) as caught:
            self.call(labels=[outcome(allowed_uses=["training_export"])])
        self.assertEqual(caught.exception.code, "permission_denied")

    def test_duplicate_outcomes_reject_or_select_latest_by_normalized_time(self):
        first, later = outcome(), outcome(("a",), outcome_id="outcome-2", revision="2", available_at="2026-10-19T02:00:01+02:00")
        with self.assertRaises(GymTSError):
            self.call(labels=[first, later])
        self.scoring["alignment"]["duplicate_policy"] = "latest_available"
        report, _, _ = self.call(labels=[later, first])
        self.assertEqual(report["metrics"][METRIC_IDS[0]]["counts"]["missing"], 1)
        later["available_at"] = first["available_at"]
        with self.assertRaises(GymTSError):
            self.call(labels=[first, later])

    def test_order_extra_curves_nan_and_inconsistent_support_are_rejected(self):
        cases = []
        item = result(); item["payload"]["value"]["curves"].reverse(); cases.append(item)
        item = result(); item["payload"]["value"]["curves"][0]["offset"] = 1; cases.append(item)
        item = result(); item["payload"]["value"]["curves"][0]["scores"][0] = float("nan"); cases.append(item)
        item = result(); item["payload"]["value"]["curves"][0]["scores"][0] = True; cases.append(item)
        item = result(); item["alignment_key"]["planning_unit_id"] = "other"; cases.append(item)
        for row in cases:
            with self.subTest(row=row), self.assertRaises(GymTSError):
                self.call(rows=[row])

    def test_full_length_binary_labels_and_unique_member_ids_are_required(self):
        cases = []
        item = outcome(); item["payload"]["value"]["curves"][0]["labels"].pop(); cases.append(item)
        item = outcome(); item["payload"]["value"]["curves"][0]["labels"][0] = 2; cases.append(item)
        item = outcome(); item["payload"]["value"]["curves"].append(copy.deepcopy(item["payload"]["value"]["curves"][0])); cases.append(item)
        for labels in cases:
            with self.subTest(labels=labels), self.assertRaises(GymTSError):
                self.call(labels=[labels])

    def test_native_all_normal_exclusion_is_not_zero_score_or_smaller_eligibility(self):
        def excluded(curves, metrics):
            return {"metrics": {metric: None for metric in metrics}, "per_curve": [
                {"curve_id": row["curve_id"], "status": "excluded", "reason": "native_all_labels_normal",
                 "metrics": {metric: None for metric in metrics}} for row in curves]}
        report, _, _ = self.call(native=excluded)
        metric = report["metrics"][METRIC_IDS[0]]
        self.assertIsNone(metric["value"])
        self.assertEqual(metric["counts"], {"eligible": 2, "scored": 0, "missing": 0, "invalid": 0, "excluded": 2})

    def test_native_failures_and_nonfinite_metrics_are_not_fabricated_results(self):
        with self.assertRaises(GymTSError):
            self.call(native=lambda *args: (_ for _ in ()).throw(GymTSError("scorer_failure", "native failure")))
        def broken(curves, metrics):
            answer = self.native_fixture(curves, metrics)
            answer["metrics"][metrics[0]] = float("nan")
            return answer
        with self.assertRaises(GymTSError):
            self.call(native=broken)

    def test_worker_deadline_and_relative_paths_are_resolved_before_temporary_cwd(self):
        with patch("gymts_timesigma.scoring.subprocess.run", return_value=
                   subprocess.CompletedProcess([], 0, b'{"ok":true,"result":{"fixture":true}}', b"")) as invoked:
            self.scorer._run_native([], list(METRIC_IDS))
        request = json.loads(invoked.call_args.kwargs["input"])
        self.assertEqual(request["source_repo"], str(Path(self.params["source_repo"]).resolve()))
        self.assertEqual(invoked.call_args.args[0][1:], ["-m", "gymts_timesigma.scoring_worker"])
        self.assertNotIn("PYTHONPATH", invoked.call_args.kwargs["env"])
        with patch("gymts_timesigma.scoring.subprocess.run", side_effect=subprocess.TimeoutExpired("fixture", 1)):
            with self.assertRaises(GymTSError) as caught:
                self.scorer._run_native([], list(METRIC_IDS))
        self.assertEqual(caught.exception.code, "deadline_exceeded")

    def test_installed_evaluation_file_requires_matching_record_bytes(self):
        from gymts_timesigma.scoring_worker import _installed_hashes
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "Metrics.py"
            raw = b"# explicit installed-file test fixture\n"
            source.write_bytes(raw)
            expected = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode()
            record = SimpleNamespace(locate=lambda: source,
                hash=SimpleNamespace(mode="sha256", value=expected))
            distribution = SimpleNamespace(files=[record])
            self.assertEqual(_installed_hashes(distribution, [source]), {str(source): hashlib.sha256(raw).hexdigest()})
            source.write_bytes(raw + b"# tampered execution code\n")
            with self.assertRaisesRegex(ValueError, "RECORD"):
                _installed_hashes(distribution, [source])
            source.write_bytes(raw)
            for records in ([], [SimpleNamespace(locate=lambda: source, hash=None)]):
                with self.subTest(records=records), self.assertRaisesRegex(ValueError, "RECORD"):
                    _installed_hashes(SimpleNamespace(files=records), [source])


@unittest.skipUnless(os.environ.get("GYMTS_TIMESIGMA_NATIVE_TESTS") == "1", "Enable the fixed native TimeSigma scoring environment")
class NativeTimeSigmaScoringTests(unittest.TestCase):
    def test_official_worker_matches_native_eight_protocols_and_never_trains(self):
        repository = Path(os.environ.get("GYMTS_TIMESIGMA_REPO", "/tmp/gymts-timesigma-source"))
        python = os.environ.get("GYMTS_TIMESIGMA_PYTHON", "/tmp/gymts-timesigma-model-venv/bin/python")
        self.assertTrue(repository.is_dir())
        scorer = TimeSigmaOfficialScorer({"params": {"source_repo": str(repository), "python": python,
            "dataset": "TODS", "planning_unit_id": "native-unit", "evaluation_members": ["curve", "normal"]}})
        scores, labels = [0., .1, .2, 1., .8, .3], [0, 0, 0, 0, 0, 1, 1, 0]
        curves = [{"curve_id": "curve", "scores": scores, "labels": labels, "raw_length": 8, "offset": 2},
                  {"curve_id": "normal", "scores": scores, "labels": [0]*8, "raw_length": 8, "offset": 2}]
        answer = scorer._run_native(curves, list(METRIC_IDS))
        reference = """
import json,sys,numpy as np,toml
from pathlib import Path
import EasyTSAD.Controller
from EasyTSAD.Evaluations import Performance
from timesigma.benchmark.runner import official_evaluations,leaderboard_items
from timesigma.benchmark.leaderboard import OFFICIAL_METRIC_IDS
r=json.load(sys.stdin)
s=toml.load(Path(EasyTSAD.Controller.__file__).with_name('GlobalCfg.toml'))['EvalSetting']
p=Performance('independent-reference','TODS','curve',np.asarray(r['scores']),np.asarray(r['labels']),s['margin']['TODS'])
calculated,raw=p.perform_eval(official_evaluations())
out={}
for metric,(_,keys) in zip(OFFICIAL_METRIC_IDS,leaderboard_items('TODS')):
    value=raw
    for key in keys: value=value[key]
    out[metric]=float(value)
aggregate={}
for value in calculated:
    value.avg()
    aggregate.update(value.to_dict())
print(json.dumps({'metrics':out,'native_aggregate':aggregate}))
"""
        environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        environment["CUDA_VISIBLE_DEVICES"] = ""
        native = subprocess.run([python, "-c", reference], input=json.dumps({"scores": scores, "labels": labels}),
                                text=True, capture_output=True, check=True, env=environment, timeout=180)
        reference_value = json.loads(native.stdout)
        self.assertEqual(answer["metrics"], reference_value["metrics"])
        self.assertEqual(answer["native_aggregate"], reference_value["native_aggregate"])
        self.assertEqual(answer["per_curve"][1]["status"], "excluded")
        self.assertEqual(answer["provenance"]["training_calls"], 0)
        self.assertEqual(answer["provenance"]["source_revision"], "5a953c1a84d0a442d1c41b17b4e8aba8c013be10")
        provenance = answer["provenance"]
        self.assertEqual(set(provenance["official_metric_sources"]), set(METRIC_IDS))
        self.assertGreaterEqual(len({row["class"] for row in provenance["evaluation_classes"]}), 7)
        installed = provenance["easytsad_record_verified_files"]
        for suffix in ("Evaluations/__init__.py", "Evaluations/Metrics.py", "Evaluations/Performance.py",
                       "Evaluations/utils.py", "Controller/GlobalCfg.toml"):
            self.assertTrue(any(path.endswith(suffix) for path in installed), suffix)
        for metric, source in provenance["official_metric_sources"].items():
            self.assertEqual(source["sha256"], installed[source["source_file"]])
            self.assertTrue(source["native_result_path"], metric)
        import gymts_timesigma.scoring_worker as installed_worker
        worker = Path(installed_worker.__file__).resolve()
        host = worker.with_name("scoring.py")
        self.assertEqual(provenance["worker_source_sha256"], hashlib.sha256(worker.read_bytes()).hexdigest())
        self.assertEqual(provenance["scoring_host_sha256"], hashlib.sha256(host.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
