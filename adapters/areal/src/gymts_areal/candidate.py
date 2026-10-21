"""Bound synchronous host of a live native TIR episode, without trainer ownership."""
import copy
from pathlib import Path
import threading

from gymts.contracts import GymTSError, digest, utc_now
from gymts.plugin_support import component, payload, unpack
from gymts_rl.contracts import INPUT, OUTPUT, PROTOCOL
from .codec import project_completion
from .contracts import CODEC, EVENT, IDENTITY, PARAMS, PINNED_REVISION, ROLLOUT, TEMPLATE, TOKENIZER
from .tensors import validate_native_tensors
from .wire import receive, send

ACTIVE = threading.local()


class LiveTIRCandidate:
    @staticmethod
    def check_compatibility_spec(context):
        experiment = context["experiment"]
        candidate, learning = experiment["candidate"], experiment["execution"]["learning"]
        if (learning["prepare"] != "load_only" or learning["online"] != "frozen" or
                learning["training_view"] is not None or learning["training_targets"] is not None or
                candidate["artifact"] is not None or candidate["inherited_state"]):
            raise GymTSError("unsupported_capability", "AReaL owns policy updates between frozen Runs")
        params = candidate["params"]
        if params["native_revision"] != PINNED_REVISION:
            raise GymTSError("conflict", "Unsupported native AReaL revision")
        if params["policy_revision"] in ("", "latest", "main", "master"):
            raise GymTSError("invalid_config", "Native policy revision must be fixed")
        if experiment["recording"]["model_calls"] not in ("io", "native_rollout"):
            raise GymTSError("unsupported_capability", "Live TIR requires full model-call evidence")

    def __init__(self, spec):
        self.spec, self.params = copy.deepcopy(spec), copy.deepcopy(spec["params"])
        self.refs, self.state = [], "created"

    def _save(self, value, schema="gymts.json/1"):
        ref = self.resources.save_json(value, schema)
        self.refs.append(ref)
        return ref

    def prepare(self, context, training):
        if self.state != "created" or training is not None or self.spec.get("artifact") or self.spec.get("inherited_state"):
            raise GymTSError("unsupported_capability", "Live TIR Candidate only joins one external frozen-policy episode")
        self.channel = getattr(ACTIVE, "channel", None)
        if self.channel is None or self.channel.owner.bridge_id != self.params["bridge_id"]:
            raise GymTSError("unsupported_capability", "Live TIR Candidate requires the explicit native bridge coordinator")
        self.resources, self.traces = context["resources"], context["traces"]
        self.revision = self.params["policy_revision"]
        if self.channel.header["policy_revision"] != self.revision:
            raise GymTSError("conflict", "Native episode and declared frozen policy differ")
        identity = self.channel.header["identity"]
        self.identity_ref = self._save(identity, IDENTITY)
        tokenizer = copy.deepcopy(self.channel.header["tokenizer"])
        for filename, expected in tokenizer["files"].items():
            path = Path(tokenizer["directory"]) / filename
            import hashlib
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != expected:
                raise GymTSError("conflict", "Native tokenizer file changed before evidence capture")
            tokenizer.setdefault("file_refs", {})[filename] = self.resources.save_artifact(content,
                {"media_type": "application/octet-stream", "source_name": filename})
        self.tokenizer_ref = self._save(tokenizer, TOKENIZER)
        projection = self.params.get("prompt_projection_ref")
        if projection != identity.get("prompt_projection_ref"):
            raise GymTSError("conflict", "Native public prompt projection differs from the declared Candidate")
        if self.params.get("answer_codec_ref") != identity.get("answer_codec_ref"):
            raise GymTSError("conflict", "Native answer codec differs from the declared Candidate")
        self.template_ref = self._save({"template": tokenizer["chat_template"], "tokenizer_ref": self.tokenizer_ref,
                                      "prompt_projection_ref": projection}, TEMPLATE)
        self.terminal_tokens = [tokenizer.get("eos_token"), tokenizer.get("pad_token")]
        self.state = "prepared"
        return {"model_revision": self.revision, "state_refs": list(self.refs), "training_provenance_ref": None}

    @staticmethod
    def _error(message):
        return GymTSError("native_failure", message, stage="areal.native").to_dict()

    def _model_end(self, begun, ended):
        success = ended["status"] == "succeeded"
        request = begun["request"]
        response = ended.get("response")
        request_ref = begun["request_ref"]
        response_ref = self._save(response) if response is not None else None
        prompt = request["input_ids"]
        prompt_ref = self._save(prompt, "gymts.token-ids/1")
        output = response.get("output_tokens", []) if response else []
        output_ref = self._save(output, "gymts.token-ids/1") if output else None
        native_ref = self._save({"format": "areal.ModelRequest.input_ids/1", "input_ids": prompt,
            "attention_mask": [1] * len(prompt), "tokenizer_ref": self.tokenizer_ref,
            "chat_template_ref": self.template_ref}, "gymts.native-inputs/1")
        effective = request["effective_generation"]
        likelihood_ref = None
        if success and not output:
            raise GymTSError("capture_incomplete", "AReaL returned an empty successful native response")
        if output:
            if len(output) != len(response["output_logprobs"]):
                raise GymTSError("capture_incomplete", "AReaL returned incomplete native tokens/logprobs")
            likelihood_ref = self._save({"protocol_version": "gymts.logprobs/1", "source": "captured",
                "call_id": begun["call_id"], "attempt_id": begun["attempt_id"],
                "prompt_sequence_hash": digest(prompt), "response_sequence_hash": digest(output),
                "policy_ref": None, "policy_revision": self.revision, "distribution": "model",
                "values": response["output_logprobs"], "effective_params": effective,
                "computation_ref": None}, "gymts.logprobs/1")
        value = {"call_id": begun["call_id"], "attempt_id": begun["attempt_id"], "parent_call_id": None,
            "started_at": begun["at"], "ended_at": ended.get("at"), "status": ended["status"],
            "model_ref": self.params["model_ref"], "adapter_ref": component("areal-live-tir"),
            "policy_revision": self.revision, "request_ref": request_ref, "response_ref": response_ref,
            "requested_params": request["requested_generation"], "effective_params": effective,
            "tokenizer_ref": self.tokenizer_ref, "chat_template_ref": self.template_ref,
            "native_inputs_ref": native_ref, "prompt_token_ids_ref": prompt_ref,
            "response_token_ids_ref": output_ref, "logprobs_ref": likelihood_ref,
            "usage": {"prompt_tokens": len(prompt), "completion_tokens": len(output),
                      "native_policy_version": request["native_policy_version"],
                      "boundary": "one_native_backend_HTTP_segment; request_retries=1"},
            "error": self._error(ended["error"]) if ended.get("error") else None,
            "capture": {"requested_profile": self.traces.profile, "completeness": "complete", "missing_fields": {},
                "transforms": ([self.params[key] for key in ("prompt_projection_ref", "answer_codec_ref") if self.params.get(key)]),
                "acquired_fields": ["request_ref", "prompt_token_ids_ref", "native_inputs_ref"] +
                    (["response_ref"] if response_ref else []) + (["response_token_ids_ref", "logprobs_ref"] if output else [])}}
        return self.traces.record_model_call(value)

    def _tool_end(self, begun, ended):
        return self.traces.record_tool_call({"call_id": begun["call_id"], "attempt_id": begun["attempt_id"],
            "parent_call_id": begun.get("parent_call_id"), "tool_ref": component("areal.calculator", PINNED_REVISION),
            "started_at": begun["at"], "ended_at": ended.get("at"), "status": ended["status"],
            "arguments_ref": begun["request_ref"],
            "result_ref": self._save(ended["response"]) if "response" in ended else None,
            "error": self._error(ended["error"]) if ended.get("error") else None,
            "environment_request_id": None, "operation_id": None})

    def infer(self, task_input):
        if self.state != "prepared" or task_input["task_protocol_ref"] != PROTOCOL or task_input["payload"]["schema_ref"] != INPUT:
            raise GymTSError("schema_mismatch", "AReaL live TIR requires public verifiable QA input")
        sample = unpack(task_input["payload"], self.resources)
        if sample != self.channel.sample:
            raise GymTSError("conflict", "Native episode and authorized TaskInput differ")
        if {"reward_spec", "answer", "ground_truth", "gold", "target", "labels"}.intersection(sample):
            raise GymTSError("permission_denied", "Private training references must not enter native TIR inputs")
        stream, event_refs, events, active, calls = self.channel.stream, [], [], {}, []
        send(stream, {"kind": "execute", "sample": sample, "policy_revision": self.revision})
        sequence, reward, reward_ref, result = 0, None, None, None
        try:
            while True:
                event = receive(stream)
                sequence += 1
                if event.get("sequence") != sequence:
                    raise GymTSError("conflict", "Native TIR event sequence is discontinuous")
                event_refs.append(self._save(event, EVENT))
                events.append(event)
                kind = event["kind"]
                if kind in ("model_start", "tool_start"):
                    begun = copy.deepcopy(event)
                    begun["request_ref"] = self._save(event["request"])
                    active[event["call_id"]] = begun
                elif kind in ("model_end", "tool_end"):
                    begun = active.pop(event["call_id"])
                    calls.append(self._model_end(begun, event) if kind == "model_end" else self._tool_end(begun, event))
                elif kind == "reward_request":
                    reward, reward_ref = self.channel.owner.grade(sample, event, terminal_tokens=self.terminal_tokens)
                    send(stream, {"kind": "reward_result", "sequence": sequence, "value": reward, "audit_ref": reward_ref})
                    continue
                elif kind == "native_result":
                    result = event
                    break
                elif kind == "native_failure":
                    raise GymTSError("native_failure", event["error"], stage="areal.native")
                send(stream, {"kind": "ack", "sequence": sequence})
            if reward is None or reward_ref is None or active:
                raise GymTSError("capture_incomplete", "Native TIR finished without complete call/reward evidence")
            validation = validate_native_tensors(result["tensors"], events,
                expected_version=self.channel.header["native_policy_version"],
                max_length=self.channel.header["max_length"], reward=reward)
            projected, conversion = project_completion(result["completion"], sample["task_id"], self.terminal_tokens)
            rollout = {"schema_version": ROLLOUT, "sample": sample, "policy_revision": self.revision,
                "native_policy_version": self.channel.header["native_policy_version"],
                "identity_ref": self.identity_ref, "tokenizer_ref": self.tokenizer_ref, "chat_template_ref": self.template_ref,
                "native_events": event_refs, "formal_call_refs": calls, "native_tensors": result["tensors"],
                "reward": reward, "reward_audit_ref": reward_ref, "native_completion": result["completion"],
                "projected_completion": projected, "codec": CODEC, "codec_result": conversion, "validation": validation}
            self.rollout_ref = self._save(rollout, ROLLOUT)
            self.channel.rollout_ref = self.rollout_ref
            return {"input_id": task_input["input_id"], "task_protocol_ref": PROTOCOL, "produced_at": utc_now(),
                "model_revision": self.revision, "payload": payload(OUTPUT, {"raw_text": projected,
                    "evidence": {"native_rollout_ref": self.rollout_ref, "codec": CODEC,
                                 "native_tensor_sha256": validation["native_tensor_sha256"]}})}
        finally:
            for begun in active.values():
                unknown = {"status": "unknown", "at": None, "error": "Native episode ended before an acknowledged terminal call event"}
                calls.append(self._model_end(begun, unknown) if begun["kind"] == "model_start" else self._tool_end(begun, unknown))

    def update(self, feedback):
        raise GymTSError("unsupported_capability", "Native AReaL updates occur only after sealed Run consumption")

    def finish(self):
        self.state = "closed"
        return list(self.refs)
