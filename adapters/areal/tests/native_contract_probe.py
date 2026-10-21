"""CPU-only original TIR/calculator probe with explicitly scripted model responses.

This tests the native protocol boundary, not real model quality or training.
Requires the fixed native environment and already prepared public/private data.
"""
import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from gymts import GymTS
from areal.api import ModelResponse
from areal.api.cli_args import GenerationHyperparameters
from areal.engine.sglang_remote import SGLangBackend
from gymts_areal.bridge import BridgeService
from gymts_areal.native_workflow import SealedTIRWorkflow
from gymts_areal.wire import sha


class ScriptedNativeBackendEngine:
    def __init__(self, tokenizer, disconnect=None):
        self.backend = SGLangBackend()
        self.config = SimpleNamespace(request_retries=1)
        self.tokenizer, self.index = tokenizer, 0
        self.disconnect = disconnect

    def get_version(self): return 0

    async def agenerate(self, request):
        self.backend.build_generation_request(request, with_lora=False, version=0)
        if self.disconnect is not None:
            self.disconnect()
            raise RuntimeError("Intentional CPU native disconnect fixture after captured model_start")
        text = ["Use the calculator. <calculator>", "2+3</calculator>", "The calculator returned five. \\boxed{5}"][self.index]
        self.index += 1
        ids = self.tokenizer.encode(text, add_special_tokens=False)
        if self.index == 3:
            ids.append(self.tokenizer.eos_token_id)
        result = self.backend.parse_generation_response({"meta_info": {"finish_reason": {"type": "stop"},
            "output_token_logprobs": [[-0.5, token, None] for token in ids]}})
        return ModelResponse(input_tokens=list(request.input_ids), output_tokens=result.output_tokens,
            output_logprobs=result.output_logprobs, output_versions=[0] * len(ids), stop_reason="stop")


def main():
    parser = argparse.ArgumentParser()
    for option in ("store", "prepared", "output", "model"): parser.add_argument("--" + option, required=True)
    parser.add_argument("--disconnect", action="store_true")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    with GymTS(args.store, integrations=["rl", "areal"]) as gym:
        prepared = json.loads(Path(args.prepared).read_text())
        sample = next(row for row in gym.artifacts.read_json(prepared["snapshot_ref"])["samples"]
                      if row["split"] == "train" and row["task_id"] == "gsm8k.numeric")
        service = BridgeService(gym, prepared, output / "bridge", max_episodes=1).start()
        revision = "cpu-scripted-contract-fixture-not-a-model-revision"
        service.policy_version({"kind": "policy_version", "bridge_id": service.bridge_id,
            "native_policy_version": 0, "policy_revision": revision, "identity": {"scripted_cpu_test": True}})
        try:
            workflow = SealedTIRWorkflow(gconfig=GenerationHyperparameters(max_new_tokens=128, max_tokens=4096), tokenizer=args.model,
                tir_config={"max_turns": 2, "max_length": 4096, "tool_timeout": 30, "enable_tools": "calculator", "is_chat_model": True},
                bridge_socket=str(service.path), bridge_id=service.bridge_id, policy_revision=revision,
                model_ref={"name": "scripted-native-probe", "version": revision, "origin_ref": None},
                policy_identity={"scripted_cpu_test": True})
            if args.disconnect:
                try:
                    asyncio.run(workflow.arun_episode(ScriptedNativeBackendEngine(workflow.tokenizer, lambda: workflow.client.close()), sample))
                except (RuntimeError, ValueError, OSError):
                    pass
                else:
                    raise AssertionError("CPU disconnect fixture unexpectedly succeeded")
                service.close()
                summary = service.summary()
                if len(summary["episodes"]) != 1 or summary["episodes"][0]["status"] != "failed":
                    raise AssertionError("Disconnected episode was omitted from the drained parent")
                failed = gym.records.get_run(summary["episodes"][0]["run_id"])
                if failed["result_ref"] is None or summary["drain_status"] != "sealed_handlers_drained":
                    raise AssertionError("Disconnected native Run did not seal before store shutdown")
                (output / "result.json").write_text(json.dumps({"status": "passed", "real_model": False,
                    "intentional_disconnect": True, "failed_run_sealed_before_close": True, "summary": summary}, indent=2) + "\n")
                return
            tensors = asyncio.run(workflow.arun_episode(ScriptedNativeBackendEngine(workflow.tokenizer), sample))
            summary = service.summary()
            if len(summary["episodes"]) != 1 or summary["episodes"][0]["status"] != "succeeded" or not summary["episodes"][0]["manifest_ref"]:
                raise AssertionError("Original TIR probe did not produce one sealed manifest")
            entry = summary["episodes"][0]
            from gymts.plugin_support import unpack
            tools = [unpack(event["payload"], gym.artifacts) for event in gym.records.get_run(entry["run_id"])["events"]
                     if event["kind"] == "tool_call"]
            if len(tools) != 1 or tools[0]["status"] != "succeeded":
                raise AssertionError("Original TIR probe did not actually dispatch the native calculator")
            from gymts_areal.tensors import encode_tensors
            if sha(encode_tensors(tensors)) != entry["native_tensor_sha256"]:
                raise AssertionError("Original TIR probe did not consume identical sealed tensors")
            summary["episodes"][0].pop("native_tensors")
            (output / "result.json").write_text(json.dumps({"status": "passed", "real_model": False,
                "scripted_model_responses": 3, "original_native_TIR_and_calculator": True,
                "sealed_manifest_handoff": True, "summary": summary}, indent=2) + "\n")
        finally:
            service.close()


if __name__ == "__main__": main()
