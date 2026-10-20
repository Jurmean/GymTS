"""Native call evidence must bind real identities and survive failed runs."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import GymTSError, digest, new_id, utc_now
from gymts.environment_ts.capture import LOGPROBS, MODEL_CALL, NATIVE_INPUTS, TOKEN_IDS, TOOL_CALL
from gymts.plugins.forecast import ForecastCandidate


ROOT = Path(__file__).resolve().parents[1]


def component(name):
    return {"name": name, "version": "1.0.0", "origin_ref": None}


class CapturingCandidate(ForecastCandidate):
    mutate_call = None
    mutate_probabilities = None
    skip_capture = False
    bad_output = False
    fail_after_capture = False
    capture_tool = False
    mutate_tool = None
    swallow_capture_error = False
    observations = []

    def prepare(self, context, training):
        result = super().prepare(context, training)
        self.traces = context["traces"]
        result["model_revision"] = "fixture-weights-17"
        return result

    def save_call(self, task_input):
        prompt, response = [7, 11, 19], [23, 2]
        save = self.resources.save_json
        call_id, attempt_id = new_id("call"), new_id("attempt")
        params = {"temperature": 1.0, "top_p": 1.0, "top_k": 0, "seed": 7}
        probabilities = {"protocol_version": LOGPROBS, "source": "captured", "call_id": call_id,
            "attempt_id": attempt_id, "prompt_sequence_hash": digest(prompt), "response_sequence_hash": digest(response),
            "values": [-0.25, -0.75], "policy_ref": None, "policy_revision": "fixture-weights-17",
            "distribution": "sampling", "effective_params": params, "computation_ref": None}
        if self.mutate_probabilities:
            self.mutate_probabilities(probabilities)
        request = save({"input_id": task_input["input_id"]})
        result = save({"raw_text": "fixture response"})
        now = utc_now()
        call = {"call_id": call_id, "attempt_id": attempt_id, "parent_call_id": None,
            "status": "succeeded", "started_at": now, "ended_at": now,
            "model_ref": component("fixture-local-policy"), "adapter_ref": component("fixture-candidate"),
            "policy_revision": "fixture-weights-17", "request_ref": request, "response_ref": result,
            "requested_params": params, "effective_params": params,
            "tokenizer_ref": save({"vocabulary_revision": "fixture-v1"}),
            "chat_template_ref": save({"template": "fixture-v1"}),
            "native_inputs_ref": save({"input_ids": prompt, "attention_mask": [1, 1, 1]}, NATIVE_INPUTS),
            "prompt_token_ids_ref": save(prompt, TOKEN_IDS), "response_token_ids_ref": save(response, TOKEN_IDS),
            "logprobs_ref": save(probabilities, LOGPROBS), "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            "error": None, "capture": {"requested_profile": self.traces.profile,
                "acquired_fields": ["request_ref", "response_ref", "tokenizer_ref", "chat_template_ref",
                    "native_inputs_ref", "prompt_token_ids_ref", "response_token_ids_ref", "logprobs_ref"],
                "missing_fields": {}, "transforms": [], "completeness": "complete"}}
        if self.mutate_call:
            self.mutate_call(call)
        reference = self.traces.record_model_call(call)
        self.observations.append({"binding": self.traces.context, "reference": reference, "call": call})
        if self.capture_tool:
            tool = {"call_id": new_id("tool"), "attempt_id": new_id("attempt"),
                "parent_call_id": call_id, "tool_ref": component("fixture-calculator"),
                "started_at": now, "ended_at": now, "status": "succeeded", "arguments_ref": request,
                "result_ref": result, "error": None, "environment_request_id": None, "operation_id": None}
            if self.mutate_tool:
                self.mutate_tool(tool)
            self.traces.record_tool_call(tool)

    def infer(self, task_input):
        if self.traces is not None and not self.skip_capture:
            try:
                self.save_call(task_input)
            except GymTSError:
                if not self.swallow_capture_error:
                    raise
        if self.fail_after_capture:
            raise RuntimeError("private model exception")
        if self.bad_output:
            return {"invalid_native_output": ["preserve", "verbatim"]}
        output = super().infer(task_input)
        output["model_revision"] = "fixture-weights-17"
        return output


class ModelCaptureContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.gym = GymTS(self.temporary.name)
        self.spec = json.loads((ROOT / "examples/forecast_experiment.json").read_text())
        self.spec["execution"]["limits"]["max_inputs"] = 1
        self.spec["recording"]["model_calls"] = "native_rollout"
        self.spec["candidate"]["adapter"] = "fixture-capture"
        self.candidate = type("TestCapturingCandidate", (CapturingCandidate,), {"observations": []})
        manifest = self.gym.registries.candidates.resolve("last-value", "1.0.0")
        manifest["component_ref"] = component("fixture-capture")
        manifest["model_revision_mode"] = "fixed"
        manifest["capture_profiles"] = ["io", "native_rollout"]
        self.gym.registries.candidates.register(manifest, self.candidate)

    def tearDown(self):
        self.gym.close()
        self.temporary.cleanup()

    def events(self, result, kind):
        return [event for event in self.gym.records.get_run(result["run_id"])["events"] if event["kind"] == kind]

    def unpack(self, event):
        body = event["payload"]
        return body["value"] if body["storage"] == "inline" else self.gym.artifacts.read_json(body["artifact_ref"])

    def test_native_capture_uses_actual_runner_binding_and_formal_artifacts(self):
        result = self.gym.run(self.spec)
        self.assertEqual("succeeded", result["status"], result)
        self.assertEqual("complete", result["evidence_status"])
        event, output_event = self.events(result, "model_call")[0], self.events(result, "candidate_output")[0]
        self.assertEqual(MODEL_CALL, event["payload"]["schema_ref"])
        self.assertEqual("artifact", event["payload"]["storage"])
        call = self.unpack(event)
        self.assertEqual(result["run_id"], call["run_id"])
        self.assertEqual(output_event["links"]["input_id"], call["input_id"])
        self.assertEqual(output_event["links"]["output_id"], call["output_id"])
        self.assertLess(event["seq"], output_event["seq"])
        probabilities = self.gym.artifacts.read_json(call["logprobs_ref"])
        self.assertEqual(2, len(probabilities["values"]))
        self.assertEqual([23, 2], self.gym.artifacts.read_json(call["response_token_ids_ref"]))
        self.assertIn(event["payload"]["artifact_ref"], result["artifact_refs"])

    def test_none_profile_keeps_the_existing_candidate_context(self):
        self.spec["recording"]["model_calls"] = "none"
        result = self.gym.run(self.spec)
        self.assertEqual("succeeded", result["status"])
        self.assertFalse(self.events(result, "model_call"))
        self.assertEqual("complete", result["evidence_status"])

    def test_io_profile_does_not_require_unavailable_native_tokens(self):
        def io_only(call):
            for field in ("tokenizer_ref", "chat_template_ref", "native_inputs_ref", "prompt_token_ids_ref",
                          "response_token_ids_ref", "logprobs_ref", "policy_revision"):
                call[field] = None
            call["capture"]["acquired_fields"] = ["request_ref", "response_ref"]
        self.spec["recording"]["model_calls"] = "io"
        self.candidate.mutate_call = staticmethod(io_only)
        result = self.gym.run(self.spec)
        self.assertEqual("succeeded", result["status"], result)
        call = self.unpack(self.events(result, "model_call")[0])
        self.assertIsNone(call["prompt_token_ids_ref"])
        self.assertIsNone(call["policy_revision"])

    def test_native_probabilities_are_required_by_the_target_trainer_not_every_profile(self):
        def no_probabilities(call):
            call["logprobs_ref"] = None
            call["capture"]["acquired_fields"].remove("logprobs_ref")
        self.candidate.mutate_call = staticmethod(no_probabilities)
        result = self.gym.run(self.spec)
        self.assertEqual("succeeded", result["status"], result)
        call = self.unpack(self.events(result, "model_call")[0])
        self.assertIsNotNone(call["response_token_ids_ref"])
        self.assertIsNone(call["logprobs_ref"])

    def test_undeclared_profile_is_rejected_before_prepare(self):
        self.spec["candidate"]["adapter"] = "last-value"
        report = self.gym.validate(self.spec)
        self.assertFalse(report["valid"])
        self.assertEqual("unsupported_capability", report["issues"][0]["code"])

    def test_no_call_evidence_preserves_raw_output_then_fails(self):
        self.candidate.skip_capture = True
        result = self.gym.run(self.spec)
        self.assertEqual("failed", result["status"])
        self.assertEqual("incomplete", result["evidence_status"])
        self.assertEqual(1, len(self.events(result, "candidate_output")))
        self.assertEqual(1, result["summary"]["counts"]["outputs"])
        self.assertEqual("capture_incomplete", result["errors"][0]["code"])

    def test_missing_capture_can_mark_incomplete_without_discarding_results(self):
        self.candidate.skip_capture = True
        self.spec["recording"]["on_capture_failure"] = "mark_incomplete"
        result = self.gym.run(self.spec)
        self.assertEqual("succeeded", result["status"], result)
        self.assertEqual("incomplete", result["evidence_status"])
        self.assertEqual(1, len(self.events(result, "task_result")))

    def test_probability_length_hash_and_policy_revision_mismatches_are_rejected(self):
        cases = (
            lambda p: p.update(values=[-0.25]),
            lambda p: p.update(response_sequence_hash=digest([100, 200])),
            lambda p: p.update(prompt_sequence_hash=digest([100, 200])),
            lambda p: p.update(policy_revision="different-weights"),
            lambda p: p.update(attempt_id="different-attempt"),
            lambda p: p.update(effective_params={"temperature": 0.5}),
            lambda p: p.update(source="recomputed"),
        )
        for mutate in cases:
            with self.subTest(mutate=mutate):
                self.candidate.mutate_probabilities = staticmethod(mutate)
                result = self.gym.run(self.spec)
                self.assertEqual("failed", result["status"])
                self.assertEqual("incomplete", result["evidence_status"])
                self.assertFalse(self.events(result, "model_call"))
                self.assertTrue(any(event["links"].get("role") == "rejected_model_call"
                                    for event in self.events(result, "artifact")))

    def test_bound_output_identity_cannot_be_forged(self):
        self.candidate.mutate_call = staticmethod(lambda c: c.update(output_id="made-up-output"))
        result = self.gym.run(self.spec)
        self.assertEqual("failed", result["status"])
        self.assertEqual("capture_incomplete", result["errors"][0]["code"])
        self.assertFalse(self.events(result, "model_call"))

    def test_partial_capture_preserves_call_and_obeys_failure_policy(self):
        self.candidate.mutate_call = staticmethod(lambda c: c["capture"].update(
            completeness="partial", missing_fields={"processor_tensor": "not supplied"}))
        result = self.gym.run(self.spec)
        self.assertEqual("failed", result["status"])
        self.assertEqual(1, len(self.events(result, "model_call")))
        self.spec["recording"]["on_capture_failure"] = "mark_incomplete"
        result = self.gym.run(self.spec)
        self.assertEqual("succeeded", result["status"], result)
        self.assertEqual("incomplete", result["evidence_status"])

    def test_candidate_cannot_override_fail_run_by_catching_capture_error(self):
        self.candidate.mutate_probabilities = staticmethod(lambda p: p.update(values=[]))
        self.candidate.swallow_capture_error = True
        result = self.gym.run(self.spec)
        self.assertEqual("failed", result["status"])
        self.assertEqual("incomplete", result["evidence_status"])
        self.assertEqual(1, len(self.events(result, "candidate_output")))

    def test_invalid_capture_can_mark_incomplete_and_preserve_rejected_evidence(self):
        self.candidate.mutate_probabilities = staticmethod(lambda p: p.update(values=[]))
        self.spec["recording"]["on_capture_failure"] = "mark_incomplete"
        result = self.gym.run(self.spec)
        self.assertEqual("succeeded", result["status"], result)
        self.assertEqual("incomplete", result["evidence_status"])
        self.assertFalse(self.events(result, "model_call"))
        self.assertTrue(any(event["links"].get("role") == "rejected_model_call"
                            for event in self.events(result, "artifact")))

    def test_illegal_raw_candidate_output_does_not_discard_captured_call(self):
        self.candidate.bad_output = True
        result = self.gym.run(self.spec)
        self.assertEqual("failed", result["status"])
        self.assertEqual(1, len(self.events(result, "model_call")))
        self.assertEqual({"invalid_native_output": ["preserve", "verbatim"]},
                         self.unpack(self.events(result, "candidate_output")[0]))

    def test_invocation_failure_retains_the_committed_model_call(self):
        self.candidate.fail_after_capture = True
        result = self.gym.run(self.spec)
        self.assertEqual("failed", result["status"])
        self.assertEqual(1, len(self.events(result, "model_call")))
        self.assertEqual("candidate_failure", result["errors"][0]["code"])
        self.assertNotIn("private model exception", json.dumps(result))

    def test_failed_model_attempt_and_its_request_are_retained(self):
        def failed(call):
            call.update(status="failed", response_ref=None,
                        error=GymTSError("candidate_failure", "Native generation failed", stage="infer").to_dict())
            call["capture"]["acquired_fields"].remove("response_ref")
        self.candidate.mutate_call = staticmethod(failed)
        self.candidate.fail_after_capture = True
        result = self.gym.run(self.spec)
        call = self.unpack(self.events(result, "model_call")[0])
        self.assertEqual("failed", call["status"])
        self.assertIsNotNone(call["request_ref"])
        self.assertIsNone(call["response_ref"])

    def test_ordinary_tool_call_links_the_model_attempt_and_real_output(self):
        self.candidate.capture_tool = True
        result = self.gym.run(self.spec)
        self.assertEqual("succeeded", result["status"], result)
        model, tool = self.unpack(self.events(result, "model_call")[0]), self.unpack(self.events(result, "tool_call")[0])
        self.assertEqual(TOOL_CALL, tool["protocol_version"])
        self.assertEqual(model["call_id"], tool["parent_call_id"])
        self.assertEqual(model["output_id"], tool["output_id"])

    def test_environment_tool_cannot_claim_an_operation_outside_runner(self):
        self.candidate.capture_tool = True
        self.candidate.mutate_tool = staticmethod(lambda t: t.update(
            operation_id="unexecuted-operation", environment_request_id="unexecuted-request"))
        result = self.gym.run(self.spec)
        self.assertEqual("failed", result["status"])
        self.assertEqual("incomplete", result["evidence_status"])
        self.assertFalse(self.events(result, "tool_call"))

    def test_frozen_snapshot_retains_call_and_sealed_execution_identity(self):
        result = self.gym.run(self.spec)
        snapshot = self.gym.records.snapshot([result["run_id"]], {"outcome_refs": []})
        before = self.gym.artifacts.read_json(snapshot["snapshot_ref"])
        reference = self.events(result, "model_call")[0]["payload"]["artifact_ref"]
        call_before = self.gym.artifacts.read_json(reference)
        self.gym.run(self.spec)
        page = self.gym.records.read_events(result["run_id"], {"snapshot_ref": snapshot["snapshot_ref"],
                                                              "kinds": ["model_call"]})
        self.assertEqual(reference, page["events"][0]["payload"]["artifact_ref"])
        self.assertEqual(before, self.gym.artifacts.read_json(snapshot["snapshot_ref"]))
        self.assertEqual(call_before, self.gym.artifacts.read_json(reference))

    def test_append_failure_stops_before_output_or_a_later_infer(self):
        self.spec["execution"]["limits"]["max_inputs"] = 3
        self.spec["recording"]["on_capture_failure"] = "mark_incomplete"
        append = self.gym.records.append
        calls = []
        def fail_model_event(run_id, events):
            if any(event["kind"] == "model_call" for event in events):
                calls.append(run_id)
                raise OSError("injected persistence failure")
            return append(run_id, events)
        with patch.object(self.gym.records, "append", fail_model_event):
            with self.assertRaises(GymTSError) as caught:
                self.gym.run(self.spec)
        self.assertEqual("recording_failure", caught.exception.code)
        self.assertEqual(1, len(calls))
        run = self.gym.records.get_run(calls[0])
        self.assertIsNone(run["result"])
        self.assertFalse(any(event["kind"] == "candidate_output" for event in run["events"]))

    def test_artifact_failure_is_not_downgraded_to_optional_capture_loss(self):
        save = self.gym.artifacts.save_json
        def fail_call(value, schema_ref="gymts.json/1"):
            if schema_ref == MODEL_CALL:
                raise OSError("injected CAS failure")
            return save(value, schema_ref)
        self.spec["recording"]["on_capture_failure"] = "mark_incomplete"
        with patch.object(self.gym.artifacts, "save_json", fail_call):
            with self.assertRaises(GymTSError) as caught:
                self.gym.run(self.spec)
        self.assertEqual("recording_failure", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
