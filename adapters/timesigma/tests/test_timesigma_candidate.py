"""Native lifecycle contracts; real scientific tests require explicit opt-in."""
import base64
import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from gymts.contracts import GymTSError, canonical_json, inline
from gymts.contracts.schema import SchemaRegistry, register_core_schemas
from gymts.environment_ts.services import RestrictedServices
from gymts.storage import ArtifactStore
from gymts_timesigma.candidate import (
    BUNDLE, CALL, PARAMS, TimeSigmaCandidate, candidate_schemas)
from gymts_timesigma.contracts import (
    CONTEXT, INPUT, PROTOCOL, TRAINING, identity, timesigma_schemas)
from gymts_timesigma.runtime import TimeSigmaRuntime
from gymts_timesigma.worker import _same_runtime, _unpack



def fixture(schema="naive", *, training):
    fitted = ["001"] if schema == "naive" else ["b", "a"] if schema == "all_in_one" else ["fit"]
    evaluated = ["held"] if schema == "zero_shot" else fitted
    preprocessing = fitted + evaluated if schema == "zero_shot" else fitted
    members = preprocessing if training else evaluated
    size = 80 if training else 48
    return {"dataset_revision": "explicit-synthetic-fixture", "planning_unit_id": "fixture-" + schema,
        "dataset": "TODS", "schema": schema, "training_members": fitted, "evaluation_members": evaluated,
        "preprocessing_members": preprocessing,
        "curves": [{"curve_id": member, "dtype": "float64", "values": [math.sin(index / 5) + position
            + (8 if not training and 20 <= index < 25 else 0) for index in range(size)]}
            for position, member in enumerate(members)]}


class CandidateFixtures(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.store = ArtifactStore(self.root / "artifacts")
        self.schemas = SchemaRegistry()
        register_core_schemas(self.schemas)
        for ref, schema in {**timesigma_schemas(), **candidate_schemas()}.items():
            self.schemas.register(ref, schema)

    def params(self, method="IsolationForest"):
        return {"source_repo": "/mock-fixed-source", "python": "/mock-python", "method": method}

    def prepare_context(self, params, schema="naive", artifact=None):
        training, test = fixture(schema, training=True), fixture(schema, training=False)
        spec = {"adapter": "timesigma-native", "version": "1.0.0", "params": params,
                "artifact": artifact, "inherited_state": []}
        if artifact is None:
            source = self.store.save_json(training, TRAINING)
            view = {"view_id": "rawtrain", "revision": source["revision"], "source_refs": [source],
                    "selection": inline({"kind": "all"}, "gymts.selection/1"), "as_of": None, "purpose": "prepare"}
        else:
            view = None
        resources = RestrictedServices(self.store, refs=[artifact], views=[view], purpose="prepare", schemas=self.schemas)
        public = {**identity(training), "evaluation_lengths": {row["curve_id"]: len(row["values"]) for row in test["curves"]}}
        context = {"run_id": "run-fixture", "candidate_spec": spec, "resources": resources, "traces": None,
                   "learning": {"prepare": "fit" if artifact is None else "load_only", "online": "frozen"},
                   "training_targets": None, "session_context": inline(public, CONTEXT)}
        task_input = {"input_id": "input-fixture", "task_protocol_ref": PROTOCOL, "payload": inline(test, INPUT)}
        return spec, context, view, task_input

    def mocked_native(self, schema="naive"):
        bundle = b"explicit mock model artifact, not a real scientific result"
        revision = hashlib.sha256(bundle).hexdigest()
        training = fixture(schema, training=True)
        test = fixture(schema, training=False)
        def call(operation, request):
            if operation == "fit":
                self.assertEqual(request["training"], training)
                self.assertNotIn("test", request)
                self.assertEqual(request["evaluation_lengths"], {row["curve_id"]: 48 for row in test["curves"]})
                return {"bundle_base64": base64.b64encode(bundle).decode(), "model_revision": revision,
                    "preprocessing_state": {"members": training["preprocessing_members"], "test_values_used": False},
                    "training_provenance": {"revision": "fixed-source", "pid": 100, "test_available": False},
                    "identity": identity(training), "evaluation_lengths": {row["curve_id"]: 48 for row in test["curves"]}}
            if operation == "inspect":
                return {"model_revision": revision, "identity": identity(training), "evaluation_lengths": {row["curve_id"]: 48 for row in test["curves"]},
                        "method": "IsolationForest", "fitted_params": {}, "preprocessing_state": {"members": training["preprocessing_members"]},
                        "training_provenance": {"revision": "fixed-source", "pid": 100, "test_available": False},
                        "configuration": {"Data_Params": {"preprocess": "raw", "diff_order": 0}, "Model_Params": {}}}
            curves = [{"curve_id": row["curve_id"], "scores": [abs(point) for point in row["values"]], "offset": 0,
                       "raw_length": len(row["values"])} for row in test["curves"]]
            digests = {row["curve_id"]: hashlib.sha256(canonical_json(row["scores"])).hexdigest() for row in curves}
            return {"model_revision": revision, "curves": curves, "score_digests": digests,
                "provenance": {"pid": 102 if operation == "replay" else 101}, "training_pid": 100,
                "native_training_calls": 0, "scaler_fit_calls": 0, "bitwise_equal": operation == "replay", "fresh_process": True}
        return call


class TimeSigmaCandidateTests(CandidateFixtures):
    def test_frozen_runtime_compares_actual_native_and_adapter_bytes(self):
        frozen = {key: {"file": "hash"} if key in ("dependency_versions", "native_file_hashes") else "fixed"
                  for key in ("revision", "easytsad_revision", "python_version", "dependency_versions", "native_file_hashes", "worker_source_sha256")}
        self.assertTrue(_same_runtime(frozen, copy.deepcopy(frozen)))
        for key in ("native_file_hashes", "worker_source_sha256"):
            changed = {**frozen, key: "changed bytes, unchanged version"}
            self.assertFalse(_same_runtime(frozen, changed))

    def test_real_prepare_contract_is_fit_before_first_test_and_scoring_is_frozen(self):
        spec, context, training, task_input = self.prepare_context(self.params())
        candidate = TimeSigmaCandidate(spec)
        with patch.object(candidate.runtime, "call", side_effect=self.mocked_native()) as native:
            prepared = candidate.prepare(context, training)
            self.assertEqual(set(prepared), {"model_revision", "state_refs", "training_provenance_ref"})
            self.assertEqual(native.call_args_list[0].args[0], "fit")
            self.assertEqual(prepared["model_revision"], candidate.bundle_ref["content_hash"])
            self.assertFalse(self.store.read_json(prepared["training_provenance_ref"])["test_available"])
            result = candidate.infer(task_input)
            self.assertEqual([call.args[0] for call in native.call_args_list], ["fit", "score", "replay"])
            self.assertEqual(result["model_revision"], prepared["model_revision"])
            self.assertTrue(result["payload"]["value"]["evidence"]["bitwise_equal"])
            self.assertEqual(result["payload"]["value"]["curves"][0]["curve_id"], "001")
        saved = candidate.finish()
        self.assertEqual(saved, candidate.finish())
        self.assertTrue(all(self.store.resolve(ref).is_file() for ref in saved))
        with self.assertRaises(GymTSError): candidate.infer(task_input)

    def test_fitting_seed_preserves_explicit_legacy_parameters_and_uses_context_for_new_specs(self):
        for explicit, requested, effective, source in ((None, 23, 23, "execution_context"),
                (17, 23, 17, "legacy_candidate_parameter"), (None, None, 1, "legacy_default")):
            with self.subTest(explicit=explicit, requested=requested):
                parameters = self.params(method="AR")
                if explicit is not None:
                    parameters["seed"] = explicit
                spec, context, training, _ = self.prepare_context(parameters)
                context["execution_seed"] = requested
                candidate = TimeSigmaCandidate(spec)
                with patch.object(candidate.runtime, "call", side_effect=self.mocked_native()) as native:
                    prepared = candidate.prepare(context, training)
                self.assertEqual(effective, native.call_args_list[0].args[1]["params"]["seed"])
                provenance = self.store.read_json(prepared["training_provenance_ref"])
                self.assertEqual({"requested_execution_seed": requested, "effective_training_seed": effective,
                                  "seed_source": source}, provenance["randomness"])
                self.assertEqual(parameters, candidate.spec["params"])

    def test_zero_shot_preprocessing_members_are_distinct_from_fit_members(self):
        spec, context, training, task_input = self.prepare_context(self.params(), "zero_shot")
        candidate = TimeSigmaCandidate(spec)
        with patch.object(candidate.runtime, "call", side_effect=self.mocked_native("zero_shot")):
            candidate.prepare(context, training)
            output = candidate.infer(task_input)["payload"]["value"]
        self.assertEqual([row["curve_id"] for row in output["curves"]], ["held"])
        self.assertEqual(self.store.read_json(candidate.preprocessing_ref)["members"], ["fit", "held"])

    def test_load_only_restores_content_fixed_artifact_without_fitting(self):
        bundle = b"explicit mock model artifact, not a real scientific result"
        artifact = self.store.save_artifact(bundle, {"media_type": "application/gzip", "schema_ref": BUNDLE})
        spec, context, training, task_input = self.prepare_context(self.params(), artifact=artifact)
        candidate = TimeSigmaCandidate(spec)
        with patch.object(candidate.runtime, "call", side_effect=self.mocked_native()) as native:
            prepared = candidate.prepare(context, training)
            self.assertIsNone(prepared["training_provenance_ref"])
            candidate.infer(task_input)
        self.assertEqual([call.args[0] for call in native.call_args_list], ["inspect", "score", "replay"])

    def test_failure_keeps_started_request_and_native_logs_in_cas(self):
        spec, context, training, _ = self.prepare_context(self.params())
        candidate = TimeSigmaCandidate(spec)
        def failed(operation, request):
            self.assertEqual(self.store.read_json(candidate.refs[0])["phase"], "started")
            raise GymTSError("candidate_failure", "Native process failed", stage="fit", details={
                "stderr": "actual native fixture traceback", "worker_envelope": {"ok": False, "error": {"type": "ValueError"}}})
        with patch.object(candidate.runtime, "call", side_effect=failed), self.assertRaises(GymTSError) as error:
            candidate.prepare(context, training)
        self.assertEqual(error.exception.code, "candidate_failure")
        refs = candidate.finish()
        self.assertEqual(len(refs), 2)
        failure = self.store.read_json(refs[-1])
        self.assertEqual(failure["error"]["links"]["stderr"], "actual native fixture traceback")
        self.assertIn("response_ref", error.exception.to_dict()["links"])

    def test_unsupported_fields_private_values_and_changed_unit_fail_before_calls(self):
        for name in ("operators", "ensemble_ref", "pipeline", "unknown"):
            with self.subTest(name=name), self.assertRaises(GymTSError) as error:
                TimeSigmaCandidate({"params": {**self.params(), name: None}})
            self.assertEqual(error.exception.code, "unsupported_capability")
        spec, context, training, task_input = self.prepare_context(self.params())
        candidate = TimeSigmaCandidate(spec)
        with patch.object(candidate.runtime, "call", side_effect=self.mocked_native()) as native:
            candidate.prepare(context, training)
            task_input["payload"]["value"]["labels"] = [0, 1]
            with self.assertRaises(GymTSError): candidate.infer(task_input)
            del task_input["payload"]["value"]["labels"]
            task_input["payload"]["value"]["planning_unit_id"] = "different-unit"
            with self.assertRaises(GymTSError): candidate.infer(task_input)
            self.assertEqual(native.call_count, 1)
        with self.assertRaises(GymTSError): candidate.update({})

    def test_bundle_extraction_rejects_links_traversal_and_missing_manifest(self):
        for name, link in (("../escape", False), ("link", True), ("plan.json", False)):
            content = io.BytesIO()
            with tarfile.open(fileobj=content, mode="w:gz") as archive:
                member = tarfile.TarInfo(name)
                if link:
                    member.type = tarfile.SYMTYPE
                    member.linkname = "/tmp/outside"
                    archive.addfile(member)
                else:
                    member.size = 2
                    archive.addfile(member, io.BytesIO(b"{}"))
            with self.subTest(name=name), self.assertRaises(ValueError):
                _unpack(base64.b64encode(content.getvalue()).decode())


@unittest.skipUnless(os.environ.get("GYMTS_TIMESIGMA_NATIVE_TESTS") == "1", "Set GYMTS_TIMESIGMA_NATIVE_TESTS=1 for real isolated CPU integration")
class TimeSigmaNativeCandidateTests(CandidateFixtures):
    def params(self, method="IsolationForest"):
        params = {"source_repo": os.environ.get("GYMTS_TIMESIGMA_REPO", "/tmp/gymts-timesigma-source"),
                  "python": os.environ.get("GYMTS_TIMESIGMA_PYTHON", "/tmp/gymts-timesigma-model-venv/bin/python"), "method": method}
        if method == "AR": params["hyper_params"] = {"p": 4, "epochs": 2, "batch_size": 8}
        return params

    def test_native_ar_prepare_fit_score_and_load_only(self):
        params = self.params("AR")
        spec, context, training, task_input = self.prepare_context(params)
        candidate = TimeSigmaCandidate(spec)
        prepared = candidate.prepare(context, training)
        provenance = self.store.read_json(prepared["training_provenance_ref"])
        self.assertFalse(provenance["test_available"])
        self.assertFalse(provenance["training_objects_have_test"])
        self.assertFalse(provenance["training_objects_have_labels"])
        self.assertEqual(provenance["native_training_calls"], 1)
        output = candidate.infer(task_input)
        self.assertEqual(output["payload"]["value"]["curves"][0]["offset"], 4)
        artifact = candidate.bundle_ref
        candidate.finish()
        loaded_spec, loaded_context, _, loaded_input = self.prepare_context(params, artifact=artifact)
        loaded = TimeSigmaCandidate(loaded_spec)
        self.assertIsNone(loaded.prepare(loaded_context, None)["training_provenance_ref"])
        replay = loaded.infer(loaded_input)
        self.assertEqual(output["model_revision"], replay["model_revision"])
        self.assertEqual(output["payload"]["value"]["curves"], replay["payload"]["value"]["curves"])

    def test_native_isolation_forest_all_three_schemas(self):
        for schema in ("naive", "all_in_one", "zero_shot"):
            with self.subTest(schema=schema):
                spec, context, training, task_input = self.prepare_context(self.params(), schema)
                candidate = TimeSigmaCandidate(spec)
                candidate.prepare(context, training)
                output = candidate.infer(task_input)["payload"]["value"]
                self.assertEqual([row["curve_id"] for row in output["curves"]], fixture(schema, training=False)["evaluation_members"])
                self.assertTrue(output["evidence"]["bitwise_equal"])
                self.assertEqual(output["evidence"]["native_training_calls_during_infer"], 0)
                self.assertNotEqual(output["evidence"]["training_pid"], output["evidence"]["score_provenance"]["pid"])
                candidate.finish()

    def test_native_loader_preprocessing_matches_split_train_valid_and_test_exactly(self):
        # NumPy is imported only in the explicitly selected scientific interpreter.
        program = r'''
import os, tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
from EasyTSAD.Controller import TSADController
from EasyTSAD.DataFactory.LoadData import load_data
from timesigma.benchmark.label_free import label_free_loading
from gymts_timesigma.worker import _array, _training_series, _testing_series
root=Path(tempfile.mkdtemp(prefix="gymts-preprocess-parity-")); os.chdir(root)
integers=[2**53+1,2**63-1]
assert _array({"values":integers,"dtype":"int64"}).tolist()==integers
directory=root/"data/UTS/TODS/0"; directory.mkdir(parents=True)
checked=0
for dtype in (np.float32,np.float64):
    raw=np.asarray([np.sin(i/5)+i/40 for i in range(80)],dtype=dtype)
    test=np.asarray([np.sin(i/5)+(50 if 15<i<20 else 0) for i in range(48)],dtype=dtype)
    np.save(directory/"train.npy",raw); np.save(directory/"test.npy",test)
    for preprocessing in ("raw","min-max","z-score"):
        for order in (0,1,2):
            controller=TSADController(log_level="error")
            controller.set_dataset(datasets="TODS",dirname=str(root/"data"),dataset_type="UTS",specify_curves=True,curve_names=["0"])
            with label_free_loading(): native=load_data(controller.dc,preprocessing,order)["TODS"]["0"]
            params={"preprocess":preprocessing,"diff_order":order,"valid_proportion":.2}
            training,scaler=_training_series(raw,params)
            assert not hasattr(training,"test") and not hasattr(training,"train_label")
            if scaler is None: scored=_testing_series(raw,test,params,scaler)
            else:
                with patch.object(scaler,"fit",side_effect=AssertionError("cannot refit")): scored=_testing_series(raw,test,params,scaler)
            for field in ("train","valid"):
                assert getattr(training,field).dtype==getattr(native,field).dtype
                assert getattr(training,field).tobytes()==getattr(native,field).tobytes()
            for field in ("train","valid","test"):
                assert getattr(scored,field).dtype==getattr(native,field).dtype
                assert getattr(scored,field).tobytes()==getattr(native,field).tobytes()
            checked+=1
print("native_preprocessing_parity_cases="+str(checked))
'''
        params = self.params()
        environment = {"PATH": os.environ.get("PATH", ""),
                       "CUDA_VISIBLE_DEVICES": "", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"}
        result = subprocess.run([params["python"], "-c", program], capture_output=True, text=True, env=environment, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("native_preprocessing_parity_cases=18", result.stdout)


if __name__ == "__main__":
    unittest.main()
