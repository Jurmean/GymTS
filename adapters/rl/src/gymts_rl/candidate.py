"""Frozen per-Run Candidate capturing real local policy generation evidence."""
import copy
import io
from pathlib import Path

from gymts.contracts import GymTSError, digest, new_id, utc_now
from gymts.contracts.schema import OBJECT, SchemaRegistry, obj
from gymts.plugin_support import payload, unpack
from .policy import active_policy
from .checkpoint import BUNDLE, MANIFEST, PROVENANCE, MEDIA_TYPE


PROTOCOL = "gymts.task/rl-verifiable-qa/1"
INPUT = "gymts.rl/input/1"
OUTPUT = "gymts.rl/output/1"
PARAMS = "gymts.rl/local-hf-params/1"
POLICY = "gymts.rl/policy/1"
TOKENIZER = "gymts.rl/tokenizer/1"
CHAT_TEMPLATE = "gymts.rl/chat-template/1"
REQUEST = "gymts.rl/model-request/1"
RESPONSE = "gymts.rl/model-response/1"
EVIDENCE = "gymts.rl/rollout-evidence/1"


def candidate_schemas():
    return {PARAMS: obj({"seed": {"type": "integer", "minimum": 0},
                         "load": obj({"device": {"type": "string"},
                             "dtype": {"enum": ["float32", "float16", "bfloat16"]},
                             "base_model_path": {"type": "string"},
                             "trust_remote_code": {"type": "boolean"}}, required=[]),
                         "generation": obj({
                             "max_new_tokens": {"type": "integer", "minimum": 1},
                             "temperature": {"type": "number", "exclusiveMinimum": 0},
                             "top_p": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
                             "top_k": {"type": "integer", "minimum": 0},
                             "do_sample": {"type": "boolean"},
                             "enable_thinking": {"type": "boolean"}}, required=[])}, required=[]),
            **{ref: copy.deepcopy(OBJECT) for ref in (POLICY, TOKENIZER, CHAT_TEMPLATE, REQUEST, RESPONSE, EVIDENCE, MANIFEST, PROVENANCE)}}


class LocalHFCandidate:
    """A Run loads a fixed artifact, or freezes a legacy resident training policy."""

    def __init__(self, spec, policy=None):
        self.spec = copy.deepcopy(spec)
        params = spec.get("params", {})
        if not isinstance(params, dict) or set(params) - {"seed", "generation", "load"}:
            raise GymTSError("invalid_config", "Local RL Candidate accepts generation, load settings and a legacy seed")
        schemas = SchemaRegistry()
        schemas.register(PARAMS, candidate_schemas()[PARAMS])
        schemas.validate(PARAMS, params)
        self.params = {"generation": {}, "load": {}, **copy.deepcopy(params)}
        self.policy = policy
        self.resources = self.traces = None
        self.state, self.refs, self.calls = "created", [], 0
        self._checkpoint_temporary = None
        self._artifact_policy = False

    @staticmethod
    def compatibility(context):
        """Check declared configuration only; no model, CAS or live policy IO."""
        spec = context["experiment"]
        candidate = spec["candidate"]
        params = candidate.get("params", {})
        schemas = SchemaRegistry()
        schemas.register(PARAMS, candidate_schemas()[PARAMS])
        schemas.validate(PARAMS, params)
        if candidate.get("inherited_state"):
            raise GymTSError("unsupported_capability", "RL checkpoint candidates require one complete artifact")
        artifact = candidate.get("artifact")
        if artifact is not None:
            if artifact["schema_ref"] != BUNDLE or artifact["media_type"] != MEDIA_TYPE:
                raise GymTSError("schema_mismatch", "Expected an RL checkpoint archive")
            if "seed" in params:
                raise GymTSError("invalid_config", "Checkpoint sampling seed belongs to execution")
        learning = spec["execution"]["learning"]
        if learning["prepare"] != "load_only" or learning["online"] != "frozen":
            raise GymTSError("unsupported_capability", "TRL owns updates outside frozen Candidate runs")
        if spec["recording"]["model_calls"] not in {"io", "native_rollout"}:
            raise GymTSError("unsupported_capability", "Native RL Candidate requires enabled model-call capture")

    def _save(self, value, schema):
        ref = self.resources.save_json(value, schema)
        self.refs.append(ref)
        return ref

    def prepare(self, context, training_view):
        if self.state != "created":
            raise GymTSError("invalid_state", "Local RL Candidate prepares only once")
        if training_view is not None or context["learning"]["prepare"] != "load_only" or context["learning"]["online"] != "frozen":
            raise GymTSError("unsupported_capability", "Local RL Candidate captures a frozen policy; TRL owns optimizer updates between Runs")
        if self.spec.get("inherited_state"):
            raise GymTSError("unsupported_capability", "Use one complete checkpoint bundle as CandidateSpec.artifact")
        self.resources, self.traces = context["resources"], context.get("traces")
        if self.traces is None:
            raise GymTSError("unsupported_capability", "Native RL rollout requires enabled model-call capture")
        self.training_provenance_ref = None
        artifact = self.spec.get("artifact")
        if artifact is not None:
            if "seed" in self.params:
                raise GymTSError("invalid_config", "Checkpoint candidates take sampling seed from execution, not candidate identity")
            if self.policy is not None:
                raise GymTSError("invalid_config", "A checkpoint candidate cannot also receive a resident policy")
            from .checkpoint import load_checkpoint_policy
            self.policy, self.training_provenance_ref, self._checkpoint_temporary = load_checkpoint_policy(
                self.resources, artifact, **self.params["load"])
            self._artifact_policy = True
            self.refs.append(self.training_provenance_ref)
        else:
            self.policy = self.policy or active_policy()
        # Existing explicit seed parameters preserve historical runs. New specs
        # use the Run seed and never change Candidate identity per repetition.
        execution_seed = context.get("execution_seed")
        if "seed" in self.params:
            self.seed = self.params["seed"]
        elif execution_seed is not None:
            self.seed = execution_seed
        elif context.get("rng") is not None:
            self.seed = context["rng"].getrandbits(63)
        else:
            self.seed = 1  # Compatibility for old direct Candidate API callers.
        self.revision = self.policy.revision
        policy_ref = self._save({"family": self.policy.family, "policy_revision": self.revision,
            "model_path": self.policy.model_path, "checkpoint_identity": self.policy.identity,
            "loadable_weights_in_artifact": bool(self._artifact_policy and self.policy.identity.get("base_embedded")),
            "checkpoint_bundle_ref": artifact}, POLICY)
        tokenizer = self.policy.tokenizer_manifest()
        tokenizer["files"] = {}
        if self.policy.model_path:
            root = Path(getattr(self.policy, "tokenizer_path", self.policy.model_path))
            for name in ("tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
                         "added_tokens.json", "vocab.json", "merges.txt", "tokenizer.model"):
                path = root / name
                if path.is_file():
                    ref = self.resources.save_artifact(path.read_bytes(),
                        {"media_type": "application/octet-stream", "source_name": name})
                    self.refs.append(ref)
                    tokenizer["files"][name] = ref
        self.tokenizer_ref = self._save(tokenizer, TOKENIZER)
        self.chat_template_ref = self._save({"template": self.policy.tokenizer.chat_template,
            "tokenizer_ref": self.tokenizer_ref}, CHAT_TEMPLATE)
        self.state = "prepared"
        return {"model_revision": self.revision, "state_refs": [policy_ref, self.tokenizer_ref, self.chat_template_ref],
                "training_provenance_ref": self.training_provenance_ref}

    def _native_inputs(self, generated, sample):
        import numpy as np

        from gymts.environment_ts.capture import NATIVE_INPUTS
        tensors = {}
        for name, tensor in generated["tensor_bundle"].items():
            dtype = str(tensor.dtype).removeprefix("torch.")
            if dtype == "bfloat16":
                import torch
                array = tensor.view(torch.uint16).numpy()
            else:
                array = tensor.numpy()
            stream = io.BytesIO()
            np.save(stream, array, allow_pickle=False)
            ref = self.resources.save_artifact(stream.getvalue(),
                {"media_type": "application/x-npy", "logical_dtype": dtype, "tensor_name": name})
            self.refs.append(ref)
            tensors[name] = {"artifact_ref": ref, "dtype": dtype, "shape": list(tensor.shape)}
        return self._save({"format": "npy", "tensors": tensors,
            "processor": {"class": type(self.policy.processor).__name__ if self.policy.processor is not None else None,
                          "family": self.policy.family, "checkpoint_revision": self.revision,
                          "timeseries_encoding": "native_processor" if self.policy.family == "chatts" else "full_precision_json_in_prompt"},
            "sample_id": sample["sample_id"], "series_names": sample.get("series_names", [])}, NATIVE_INPUTS)

    def infer(self, task_input):
        from gymts.environment_ts.capture import TOKEN_IDS, LOGPROBS

        if self.state != "prepared":
            raise GymTSError("invalid_state", "Local RL Candidate is not prepared")
        if self.policy.revision != self.revision:
            raise GymTSError("conflict", "Policy revision changed during a frozen Run")
        if task_input["task_protocol_ref"] != PROTOCOL or task_input["payload"]["schema_ref"] != INPUT:
            raise GymTSError("schema_mismatch", "Local RL Candidate requires the verifiable QA protocol")
        sample = unpack(task_input["payload"], self.resources)
        forbidden = {"reward_spec", "ground_truth", "answer", "labels", "gold", "target"}
        if forbidden.intersection(sample):
            raise GymTSError("permission_denied", "Private reward fields must not enter a policy input")
        self.calls += 1
        call_id, attempt_id = new_id(), new_id()
        started = utc_now()
        seed = self.seed + self.calls - 1
        request_ref = self._save({"sample": sample, "generation": self.params["generation"], "seed": seed}, REQUEST)
        common = {"call_id": call_id, "attempt_id": attempt_id, "parent_call_id": None,
            "started_at": started, "model_ref": self.policy.model_ref, "adapter_ref": self.policy.adapter_ref,
            "policy_revision": self.revision, "request_ref": request_ref,
            "requested_params": {**self.params["generation"], "seed": seed},
            "tokenizer_ref": self.tokenizer_ref, "chat_template_ref": self.chat_template_ref}
        recorded = False
        try:
            generated = self.policy.generate(sample, seed, self.params["generation"])
            if generated["policy_revision"] != self.revision or self.policy.revision != self.revision:
                raise GymTSError("conflict", "Policy changed during native generation")
            prompt_ref = self._save(generated["prompt_ids"], TOKEN_IDS)
            completion_ref = self._save(generated["completion_ids"], TOKEN_IDS)
            native_ref = self._native_inputs(generated, sample)
            effective = generated["effective_params"]
            likelihood = {"protocol_version": LOGPROBS, "source": "captured", "call_id": call_id,
                "attempt_id": attempt_id, "prompt_sequence_hash": digest(generated["prompt_ids"]),
                "response_sequence_hash": digest(generated["completion_ids"]),
                "policy_ref": None, "policy_revision": self.revision,
                "effective_params": effective, "computation_ref": None}
            raw_ref = self._save({**likelihood, "distribution": "model", "values": generated["raw_model_logprobs"]}, LOGPROBS)
            sampling_ref = self._save({**likelihood, "distribution": "sampling", "values": generated["sampling_logprobs"]}, LOGPROBS)
            response_ref = self._save({"raw_text": generated["response"], "finish_reason": generated["finish_reason"],
                "completion_ids_ref": completion_ref, "rendered_prompt": generated["rendered_prompt"]}, RESPONSE)
            usage = {"prompt_tokens": len(generated["prompt_ids"]), "completion_tokens": len(generated["completion_ids"])}
            call = {**common, "ended_at": utc_now(), "status": "succeeded", "response_ref": response_ref,
                "effective_params": effective, "native_inputs_ref": native_ref,
                "prompt_token_ids_ref": prompt_ref, "response_token_ids_ref": completion_ref,
                "logprobs_ref": sampling_ref, "usage": usage, "error": None}
            call["capture"] = {"requested_profile": self.traces.profile,
                "acquired_fields": sorted(key for key, value in call.items() if value is not None),
                "missing_fields": {}, "transforms": [], "completeness": "complete"}
            call_ref = self.traces.record_model_call(call)
            recorded = True
            self.refs.append(call_ref)
            evidence = {"model_call_ref": call_ref, "native_inputs_ref": native_ref,
                "prompt_token_ids_ref": prompt_ref, "response_token_ids_ref": completion_ref,
                "raw_model_logprobs_ref": raw_ref, "sampling_logprobs_ref": sampling_ref,
                "policy_revision": self.revision, "finish_reason": generated["finish_reason"], "usage": usage}
            evidence_ref = self._save(evidence, EVIDENCE)
            return {"input_id": task_input["input_id"], "task_protocol_ref": PROTOCOL,
                    "produced_at": utc_now(), "model_revision": self.revision,
                    "payload": payload(OUTPUT, {"raw_text": generated["response"],
                                               "evidence": {**evidence, "evidence_ref": evidence_ref}})}
        except Exception as error:
            if recorded:
                raise
            value = error.to_dict() if isinstance(error, GymTSError) else GymTSError(
                "candidate_failure", "Local policy generation failed", details={"type": type(error).__name__, "reason": str(error)}).to_dict()
            failed = {**common, "ended_at": utc_now(), "status": "failed", "response_ref": None,
                "effective_params": {}, "native_inputs_ref": None, "prompt_token_ids_ref": None,
                "response_token_ids_ref": None, "logprobs_ref": None, "usage": None, "error": value,
                "capture": {"requested_profile": self.traces.profile, "acquired_fields": ["request_ref"],
                    "missing_fields": {"response_ref": "generation_or_capture_failed", "prompt_token_ids_ref": "generation_or_capture_failed",
                                       "response_token_ids_ref": "generation_or_capture_failed", "logprobs_ref": "generation_or_capture_failed",
                                       "native_inputs_ref": "generation_or_capture_failed"},
                    "transforms": [], "completeness": "partial"}}
            self.refs.append(self.traces.record_model_call(failed))
            raise

    def update(self, feedback):
        raise GymTSError("unsupported_capability", "TRL owns policy updates between frozen GymTS Runs")

    def finish(self):
        self.state = "finished"
        if self._checkpoint_temporary is not None:
            self._checkpoint_temporary.cleanup()
            self._checkpoint_temporary = None
        if self._artifact_policy:
            self.policy = None
        return list(self.refs)


__all__ = ["LocalHFCandidate", "candidate_schemas", "PARAMS", "POLICY", "TOKENIZER", "CHAT_TEMPLATE", "REQUEST", "RESPONSE", "EVIDENCE"]
