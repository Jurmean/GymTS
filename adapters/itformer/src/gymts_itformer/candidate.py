"""Native frozen TLM Candidate with real token/IO evidence, no RL claims."""
import copy
from gymts.contracts import digest, utc_now
from gymts.plugin_support import component, fail, identifier, payload, unpack
from .contracts import INPUT, OUTPUT, PROTOCOL


class ITFormerCandidate:
    def __init__(self, spec):
        self.spec, self.params = copy.deepcopy(spec), copy.deepcopy(spec["params"])
        self.state, self.refs = "created", []

    def _save(self, value, schema="gymts.json/1"):
        ref = self.resources.save_json(value, schema)
        self.refs.append(ref)
        return ref

    def prepare(self, context, training):
        if self.state != "created":
            fail("invalid_state", "Candidate prepare may be called only once")
        if training is not None or context["learning"]["prepare"] != "load_only" or context["learning"]["online"] != "frozen":
            fail("unsupported_capability", "ITFormer Candidate supports frozen inference only")
        if self.spec.get("artifact") is not None or self.spec.get("inherited_state"):
            fail("unsupported_capability", "Use explicit fixed native checkpoint/base paths")
        self.resources, self.traces = context["resources"], context["traces"]
        if self.traces is None or self.traces.profile != "io":
            fail("invalid_config", "ITFormer requires recording.model_calls=io")
        from .runtime import load_native
        self.model, self.dataset_module, self.config, provenance = load_native(self.params)
        self.revision = digest(provenance)
        self.provenance_ref = self._save(provenance)
        self.tokenizer_ref = self._save({"base_files": provenance["base_model_files"],
            "class": type(self.model.tokenizer).__name__})
        self.template_ref = self._save({"chat_template": self.model.tokenizer.chat_template})
        self.state = "prepared"
        return {"model_revision": self.revision, "state_refs": [self.provenance_ref, self.tokenizer_ref, self.template_ref],
            "training_provenance_ref": None}

    def infer(self, task_input):
        if self.state != "prepared":
            fail("invalid_state", "Candidate infer requires prepared state")
        if task_input["task_protocol_ref"] != PROTOCOL or task_input["payload"]["schema_ref"] != INPUT:
            fail("schema_mismatch", "ITFormer Candidate requires public ITFormer QA inputs")
        from .runtime import preprocess_public
        import torch
        value = unpack(task_input["payload"], self.resources)
        if any(key in value for key in ("answer", "labels", "reference", "targets")):
            fail("permission_denied", "Candidate received private answer fields")
        started = utc_now()
        call_id, attempt_id = identifier("model-call"), identifier("attempt")
        params = {"max_new_tokens": self.params["max_new_tokens"], "do_sample": False,
            "num_beams": 1, "use_cache": False}
        request_ref = self._save({"public_sample": value, "generation": params,
            "native_preprocessing": "strict upstream TsQaDataset + DataCollator; empty dummy answer",
            "private_answer_available": False})
        call = {"call_id": call_id, "attempt_id": attempt_id, "parent_call_id": None,
            "started_at": started, "ended_at": None, "status": "unknown",
            "model_ref": component("ITFormer-with-external-Qwen", self.revision),
            "adapter_ref": component("gymts-itformer", "0.1.0"), "policy_revision": self.revision,
            "request_ref": request_ref, "response_ref": None, "requested_params": params,
            "effective_params": params, "tokenizer_ref": self.tokenizer_ref,
            "chat_template_ref": self.template_ref, "native_inputs_ref": None,
            "prompt_token_ids_ref": None, "response_token_ids_ref": None, "logprobs_ref": None,
            "usage": None, "error": None,
            "capture": {"requested_profile": "io", "acquired_fields": ["request_ref"],
                "missing_fields": {}, "transforms": [component("itformer-public-native-codec", "1")],
                "completeness": "complete"}}
        # Persist intent before preprocessing/generation; retries are absent.
        self._save({"attempt_intent": call, "input_id": task_input["input_id"],
            "note": "write-ahead intent, not an additional generation attempt"})
        try:
            batch = preprocess_public(value, self.model, self.dataset_module, self.config)
            native_inputs = {key: {"dtype": str(tensor.dtype), "shape": list(tensor.shape),
                "values": tensor.tolist()} for key, tensor in batch.items()}
            call["native_inputs_ref"] = self._save(native_inputs, "gymts.native-inputs/1")
            prompt_ids = batch["input_ids"][0].tolist()
            call["prompt_token_ids_ref"] = self._save(prompt_ids, "gymts.token-ids/1")
            batch = {key: tensor.to(self.params["device"]) for key, tensor in batch.items()}
            with torch.inference_mode():
                generated = self.model.generate(**batch, **params,
                    pad_token_id=self.model.tokenizer.pad_token_id,
                    eos_token_id=self.model.tokenizer.eos_token_id)
            sequence = generated[0].detach().cpu().tolist()
            if sequence[:len(prompt_ids)] != prompt_ids:
                raise ValueError("Native generation did not retain its actual input token prefix")
            response_ids = sequence[len(prompt_ids):]
            if not response_ids:
                raise ValueError("Native generation returned no response tokens")
            raw = self.model.tokenizer.decode(response_ids, skip_special_tokens=True)
            call["response_token_ids_ref"] = self._save(response_ids, "gymts.token-ids/1")
            call["response_ref"] = self._save({"raw_text": raw, "generated_ids": sequence,
                "response_token_count": len(response_ids), "limit_reached": len(response_ids) >= params["max_new_tokens"]})
            call.update(status="succeeded", ended_at=utc_now(), usage={"prompt_tokens": len(prompt_ids),
                "completion_tokens": len(response_ids), "source": "native generate token IDs"})
            call["capture"]["acquired_fields"] = [key for key in ("request_ref", "response_ref", "tokenizer_ref",
                "chat_template_ref", "native_inputs_ref", "prompt_token_ids_ref", "response_token_ids_ref") if call[key] is not None]
            self.traces.record_model_call(call)
            return {"input_id": task_input["input_id"], "task_protocol_ref": PROTOCOL,
                "produced_at": utc_now(), "model_revision": self.revision,
                "payload": payload(OUTPUT, {"raw_text": raw, "evidence": {
                    "native_generation": True, "call_id": call_id, "capture_profile": "io",
                    "provenance_ref": self.provenance_ref, "gold_access": False}})}
        except Exception as error:
            call.update(status="failed", ended_at=utc_now(), error={"code": "candidate_failure", "stage": "plugin",
                "method": "infer", "message": type(error).__name__ + ": " + str(error),
                "run_id": task_input["run_id"], "links": {}, "retryable": False, "side_effect": "none"})
            self.traces.record_model_call(call)
            raise

    def update(self, feedback):
        fail("unsupported_capability", "ITFormer Candidate does not train or update")

    def finish(self):
        if hasattr(self, "model"):
            self.model.to("cpu")
            del self.model
        self.state = "closed"
        return self.refs
