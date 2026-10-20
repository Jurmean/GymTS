"""Jurmean GymTS Candidate lifecycle for genuinely split native TSAD methods."""
import base64
import copy
import hashlib

from gymts.contracts import GymTSError, utc_now
from gymts.contracts.schema import OBJECT, STRING, SchemaRegistry, obj
from gymts.plugin_support import fail, payload, unpack
from .contracts import IDENTITY_FIELDS, INPUT, OUTPUT, PROTOCOL, TRAINING, identity, validate_answer, validate_unit
from .runtime import TimeSigmaRuntime

PARAMS = "gymts.timesigma/native-params/1"
BUNDLE = "gymts.timesigma/model-bundle/1"
CALL = "gymts.timesigma/native-call/1"
PREPROCESSING = "gymts.timesigma/preprocessing-state/1"
TRAINING_PROVENANCE = "gymts.timesigma/training-provenance/1"
SCORING_EVIDENCE = "gymts.timesigma/scoring-evidence/1"
SUPPORTED_PARAMS = {"source_repo", "python", "method", "hyper_params", "preprocess", "diff_order",
                    "valid_proportion", "seed", "timeout_seconds"}


def candidate_schemas():
    return {PARAMS: obj({"source_repo": STRING, "python": STRING, "method": {"enum": ["AR", "IsolationForest"]},
        "hyper_params": OBJECT, "preprocess": {"enum": ["raw", "min-max", "z-score"]},
        "diff_order": {"type": "integer", "minimum": 0},
        "valid_proportion": {"type": "number", "minimum": 0, "exclusiveMaximum": 1},
        "seed": {"type": "integer", "minimum": 0}, "timeout_seconds": {"type": "number", "exclusiveMinimum": 0}},
        required=["source_repo", "python", "method"]),
        **{ref: copy.deepcopy(OBJECT) for ref in (BUNDLE, CALL, PREPROCESSING, TRAINING_PROVENANCE, SCORING_EVIDENCE)}}


def _recordable(value):
    """Keep the exact binary request identity without duplicating bundle bytes."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key == "bundle_base64":
                raw = base64.b64decode(item, validate=True)
                result["bundle_content"] = {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
            else:
                result[key] = _recordable(item)
        return result
    if isinstance(value, list):
        return [_recordable(item) for item in value]
    return value


class TimeSigmaCandidate:
    @staticmethod
    def check_compatibility_spec(context):
        experiment = context["experiment"]
        candidate, learning = experiment["candidate"], experiment["execution"]["learning"]
        if learning["online"] != "frozen" or learning["training_targets"] is not None or candidate["inherited_state"]:
            fail("unsupported_capability", "Native unsupervised TimeSigma uses frozen execution without targets or inherited state")
        if learning["prepare"] == "fit":
            effective_seed = candidate["params"].get("seed", experiment["execution"]["seed"])
            effective_seed = 1 if effective_seed is None else effective_seed
            if type(effective_seed) is not int or effective_seed < 0:
                fail("invalid_config", "Native TimeSigma fitting needs a nonnegative integer seed")
            if candidate["params"]["method"] == "IsolationForest" and effective_seed != 1:
                fail("unsupported_capability", "The fixed native IsolationForest binding supports only fitting seed=1")
            if candidate["artifact"] is not None:
                fail("invalid_config", "Native fitting cannot also load a model artifact")
            view = learning["training_view"]
            if view is None or len(view["source_refs"]) != 1 or view["source_refs"][0]["schema_ref"] != TRAINING:
                fail("schema_mismatch", "Native fitting requires a declared TimeSigma training source")
        elif learning["prepare"] == "load_only":
            artifact = candidate["artifact"]
            if artifact is None:
                fail("invalid_config", "load_only requires a fixed native model bundle")
            if artifact["schema_ref"] != BUNDLE:
                fail("schema_mismatch", "load_only requires the native TimeSigma model bundle schema")

    def __init__(self, spec):
        self.spec = copy.deepcopy(spec)
        parameters = self.spec.get("params", {})
        if not isinstance(parameters, dict):
            fail("invalid_config", "Native TimeSigma params must be an object", "configure")
        if set(parameters) - SUPPORTED_PARAMS:
            fail("unsupported_capability", "Unsupported native TimeSigma parameters", "configure",
                 unsupported=sorted(set(parameters) - SUPPORTED_PARAMS))
        registry = SchemaRegistry()
        registry.register(PARAMS, candidate_schemas()[PARAMS])
        registry.validate(PARAMS, parameters)
        self.provided = set(parameters)
        self.params = {"hyper_params": {}, "valid_proportion": .2, "seed": 1, "timeout_seconds": 600, **parameters}
        self.state, self.refs = "created", []
        self.resources = self.context = None
        self.runtime = TimeSigmaRuntime(self.params)
        self.bundle = self.bundle_ref = self.preprocessing_ref = self.training_ref = None

    def _save(self, value, schema):
        ref = self.resources.save_json(value, schema)
        self.refs.append(ref)
        return ref

    def _call(self, operation, request):
        request_ref = self._save({"operation": operation, "phase": "started", "captured_at": utc_now(),
                                  "request": _recordable(request)}, CALL)
        try:
            result = self.runtime.call(operation, request)
        except Exception as error:
            error_value = error.to_dict() if isinstance(error, GymTSError) else {"type": type(error).__name__}
            response_ref = self._save({"operation": operation, "phase": "failed", "request_ref": request_ref,
                                       "captured_at": utc_now(), "error": error_value}, CALL)
            raise GymTSError(getattr(error, "code", "candidate_failure"), "TimeSigma native operation failed", stage=operation,
                             links={"request_ref": request_ref, "response_ref": response_ref, "native_error": error_value}) from error
        response_ref = self._save({"operation": operation, "phase": "completed", "request_ref": request_ref,
                                   "captured_at": utc_now(), "result": _recordable(result)}, CALL)
        return result, response_ref

    def prepare(self, context, training):
        if self.state != "created":
            fail("invalid_state", "Native Candidate prepares once", "prepare")
        self.context, self.resources = context, context["resources"]
        learning = context["learning"]
        if learning["online"] != "frozen" or context.get("training_targets") is not None:
            fail("unsupported_capability", "Native unsupervised detector supports frozen execution without training targets", "prepare")
        if self.spec.get("inherited_state"):
            fail("unsupported_capability", "Use one explicit native model bundle instead of inherited state", "prepare")
        requested_seed = context.get("execution_seed")
        if learning["prepare"] == "fit":
            if "seed" in self.provided:
                seed_source = "legacy_candidate_parameter"
            elif requested_seed is not None:
                if type(requested_seed) is not int or requested_seed < 0:
                    fail("invalid_config", "Native TimeSigma fitting needs a nonnegative execution seed", "prepare")
                self.params["seed"] = requested_seed
                seed_source = "execution_context"
            else:
                seed_source = "legacy_default"
            self.randomness = {"requested_execution_seed": requested_seed,
                "effective_training_seed": self.params["seed"], "seed_source": seed_source}
            if training is None or self.spec.get("artifact") is not None:
                fail("invalid_config", "Native fitting requires raw training and no loaded model artifact", "prepare")
            training_payload = self.resources.read_view(training)
            if training_payload["schema_ref"] != TRAINING:
                fail("schema_mismatch", "Native fitting requires the TimeSigma training schema", "prepare")
            body = validate_unit(unpack(training_payload, self.resources), training=True)
            public = unpack(context["session_context"], self.resources)
            if any(public.get(key) != body[key] for key in IDENTITY_FIELDS):
                fail("schema_mismatch", "Training planning unit differs from the public session", "prepare")
            result, _ = self._call("fit", {"params": self.params, "training": body,
                                           "evaluation_lengths": public["evaluation_lengths"]})
            self.bundle = base64.b64decode(result["bundle_base64"], validate=True)
            self.revision = hashlib.sha256(self.bundle).hexdigest()
            if self.revision != result["model_revision"]:
                fail("conflict", "Fitted model content differs from its published revision", "prepare")
            self.bundle_ref = self.resources.save_artifact(self.bundle, {"media_type": "application/gzip", "schema_ref": BUNDLE,
                "kind": "timesigma_native_model", "source_revision": result["training_provenance"]["revision"]})
            self.refs.append(self.bundle_ref)
            self.preprocessing_ref = self._save({**result["preprocessing_state"], "model_bundle_ref": self.bundle_ref}, PREPROCESSING)
            self.training_ref = self._save({**result["training_provenance"], "training_view": training,
                                            "model_bundle_ref": self.bundle_ref, "model_revision": self.revision,
                                            "randomness": copy.deepcopy(self.randomness)}, TRAINING_PROVENANCE)
            provenance = self.training_ref
        elif learning["prepare"] == "load_only":
            if training is not None or self.spec.get("artifact") is None:
                fail("invalid_config", "load_only requires a fixed native model bundle and no training view", "prepare")
            self.bundle_ref = self.spec["artifact"]
            if self.bundle_ref["schema_ref"] != BUNDLE:
                fail("schema_mismatch", "load_only artifact is not a native TimeSigma model bundle", "prepare")
            self.bundle = self.resources.resolve(self.bundle_ref).read_bytes()
            self.revision = hashlib.sha256(self.bundle).hexdigest()
            result, _ = self._call("inspect", {"bundle_base64": base64.b64encode(self.bundle).decode(), "model_revision": self.revision})
            if result["model_revision"] != self.revision:
                fail("conflict", "Loaded model content differs from its published revision", "prepare")
            if result["method"] != self.params["method"]:
                fail("conflict", "Loaded model method differs from the Candidate", "prepare")
            for key in ("preprocess", "diff_order"):
                if key in self.provided and self.params[key] != result["configuration"]["Data_Params"][key]:
                    fail("conflict", "load_only cannot replace saved preprocessing", "prepare")
            for key in ("seed", "valid_proportion"):
                if key in self.provided and self.params[key] != result["fitted_params"].get(key, {"seed": 1, "valid_proportion": .2}[key]):
                    fail("conflict", "load_only cannot replace the saved fitting protocol", "prepare")
            if any(value != result["configuration"]["Model_Params"].get(key) for key, value in self.params["hyper_params"].items()):
                fail("conflict", "load_only cannot replace saved model parameters", "prepare")
            self.refs.append(self.bundle_ref)
            self.randomness = {"requested_execution_seed": requested_seed,
                "effective_training_seed": result["fitted_params"].get("seed", 1), "seed_source": "saved_model_bundle"}
            self.preprocessing_ref = self._save({**result["preprocessing_state"], "model_bundle_ref": self.bundle_ref}, PREPROCESSING)
            self.training_ref = self._save({**result["training_provenance"], "restored_not_fitted": True,
                                            "model_bundle_ref": self.bundle_ref, "randomness": copy.deepcopy(self.randomness)}, TRAINING_PROVENANCE)
            provenance = None
        else:
            fail("unsupported_capability", "Native Candidate supports fit and load_only", "prepare")
        self.identity, self.lengths = result["identity"], result["evaluation_lengths"]
        self.state = "prepared"
        return {"model_revision": self.revision, "state_refs": copy.deepcopy(self.refs), "training_provenance_ref": provenance}

    def infer(self, task_input):
        if self.state != "prepared":
            fail("invalid_state", "Native Candidate accepts one planning unit after prepare", "infer")
        if task_input["task_protocol_ref"] != PROTOCOL or task_input["payload"]["schema_ref"] != INPUT:
            fail("schema_mismatch", "Native Candidate requires the TimeSigma TSAD input protocol", "infer")
        body = validate_unit(unpack(task_input["payload"], self.resources))
        if identity(body) != self.identity:
            fail("conflict", "Test planning unit differs from the fitted model", "infer")
        if any(len(row["values"]) != self.lengths[row["curve_id"]] for row in body["curves"]):
            fail("conflict", "Rawtest lengths differ from the declared fitted planning unit", "infer")
        request = {"bundle_base64": base64.b64encode(self.bundle).decode(), "model_revision": self.revision, "input": body}
        self.state = "scoring"
        scored, score_ref = self._call("score", request)
        replay, replay_ref = self._call("replay", {**request, "expected_score_digests": scored["score_digests"],
                                                   "previous_pid": scored["provenance"]["pid"]})
        if scored["model_revision"] != self.revision or replay["model_revision"] != self.revision:
            fail("conflict", "Scoring changed the prepared model revision", "infer")
        if replay["native_training_calls"] or replay["scaler_fit_calls"] or not replay["bitwise_equal"] or scored["provenance"]["pid"] == replay["provenance"]["pid"]:
            fail("candidate_failure", "Native replay did not prove independent no-fit byte equality", "infer")
        evidence = {"model_bundle_ref": self.bundle_ref, "model_revision": self.revision,
                    "preprocessing_state_ref": self.preprocessing_ref, "training_provenance_ref": self.training_ref,
                    "score_call_ref": score_ref, "replay_call_ref": replay_ref,
                    "score_provenance": scored["provenance"], "replay_provenance": replay["provenance"],
                    "training_pid": scored["training_pid"], "randomness": copy.deepcopy(self.randomness),
                    "native_training_calls_during_infer": 0,
                    "scaler_fit_calls_during_infer": 0, "fresh_process": True, "bitwise_equal": True}
        evidence_ref = self._save(evidence, SCORING_EVIDENCE)
        answer = {"dataset_revision": body["dataset_revision"], "planning_unit_id": body["planning_unit_id"],
                  "curves": scored["curves"], "evidence": {**evidence, "evidence_ref": evidence_ref}}
        validate_answer(answer, body)
        self.state = "scored"
        return {"input_id": task_input["input_id"], "task_protocol_ref": PROTOCOL, "produced_at": utc_now(),
                "model_revision": self.revision, "payload": payload(OUTPUT, answer)}

    def update(self, feedback):
        fail("unsupported_capability", "Native detector has no online update protocol", "update")

    def finish(self):
        self.state = "closed"
        return copy.deepcopy(self.refs)
