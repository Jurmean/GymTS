"""Strict native tensor/turn identity, independent of Torch on the host."""
import math
import struct

from .wire import sha

FIELDS = ("input_ids", "logprobs", "loss_mask", "versions", "attention_mask", "rewards")


def encode_tensors(values):
    return {name: {"dtype": str(tensor.dtype).removeprefix("torch."), "shape": list(tensor.shape),
                   "values": tensor.detach().cpu().tolist()} for name, tensor in values.items()}


def decode_tensors(encoded):
    import torch
    allowed = {"int64": torch.int64, "float32": torch.float32, "float64": torch.float64, "bool": torch.bool}
    result = {}
    for name, descriptor in encoded.items():
        if descriptor["dtype"] not in allowed:
            raise ValueError("Unsupported native training tensor dtype")
        value = torch.tensor(descriptor["values"], dtype=allowed[descriptor["dtype"]])
        if list(value.shape) != descriptor["shape"]:
            raise ValueError("Native training tensor shape differs from its descriptor")
        result[name] = value
    return result


def _f32(value):
    return struct.unpack("f", struct.pack("f", value))[0]


def validate_native_tensors(tensors, events, *, expected_version, max_length, reward):
    if set(tensors) != set(FIELDS) | {"is_truncated"}:
        raise ValueError("Native TIR tensor fields differ from the supported training schema")
    arrays = {name: tensors[name]["values"] for name in FIELDS}
    dtypes = {"input_ids": "int64", "loss_mask": "int64", "versions": "int64", "attention_mask": "bool",
              "logprobs": "float32", "rewards": "float32", "is_truncated": "bool"}
    if any(tensors[name]["dtype"] != dtype for name, dtype in dtypes.items()):
        raise ValueError("Native TIR tensor dtype differs from the supported original workflow")
    if any(tensors[name]["shape"][:1] != [1] for name in FIELDS):
        raise ValueError("One logical native TIR episode must have one tensor row")
    seq = arrays["input_ids"][0]
    if not 1 <= len(seq) <= max_length or any(type(x) is not int or x < 0 for x in seq):
        raise ValueError("Invalid native sequence length or token IDs")
    for name in FIELDS[:-1]:
        if tensors[name]["shape"] != [1, len(seq)] or len(arrays[name][0]) != len(seq):
            raise ValueError("Native TIR per-token fields are not aligned")
    if arrays["attention_mask"][0] != [True] * len(seq):
        raise ValueError("Unpadded native episode has an unexpected attention mask")
    if tensors["is_truncated"]["values"] != [False]:
        raise ValueError("Truncated native TIR episodes are rejected before training")
    aggregates = [event for event in events if event["kind"] == "model_aggregate"]
    if not aggregates:
        raise ValueError("Native TIR episode has no actual model response")
    significant = [event["kind"] for event in events if event["kind"] in ("model_aggregate", "tool_projection")]
    if significant[-1] == "tool_projection":
        raise ValueError("Native TIR exhausted its turn budget before consuming the final tool result")
    expected_seq = list(aggregates[0]["response"]["input_tokens"])
    expected_mask = [0] * len(expected_seq)
    expected_lp = [0.0] * len(expected_seq)
    expected_versions = [-1] * len(expected_seq)
    generated, tool_tokens = 0, 0
    for event in events:
        if event["kind"] == "model_aggregate":
            response = event["response"]
            if response["input_tokens"] != expected_seq:
                raise ValueError("Native model context does not continue the captured sequence")
            output = response["output_tokens"]
            if not output or len(output) != len(response["output_logprobs"]) or len(output) != len(response["output_versions"]):
                raise ValueError("Native model output/token/logprob/version lengths differ")
            if any(value != expected_version for value in response["output_versions"]):
                raise ValueError("One Run contains a changed or unexpected native policy version")
            if any(not math.isfinite(value) or value > 0 for value in response["output_logprobs"]):
                raise ValueError("Native model log probabilities are invalid")
            expected_seq.extend(output)
            expected_mask.extend([1] * len(output))
            expected_lp.extend(response["output_logprobs"])
            expected_versions.extend(response["output_versions"])
            generated += len(output)
        elif event["kind"] == "tool_projection":
            output = event["token_ids"]
            expected_seq.extend(output)
            expected_mask.extend([0] * len(output))
            expected_lp.extend([0.0] * len(output))
            expected_versions.extend([-1] * len(output))
            tool_tokens += len(output)
    if len(expected_seq) > max_length or expected_seq != seq:
        raise ValueError("Native sequence was truncated or differs from captured model/tool tokens")
    if aggregates[-1]["response"]["stop_reason"] in ("length", "abort"):
        raise ValueError("Length/abort terminal responses are rejected rather than receiving a full-answer reward")
    if arrays["loss_mask"][0] != expected_mask or arrays["versions"][0] != expected_versions:
        raise ValueError("Native prompt/tool/model token masks or versions changed")
    rounder = _f32 if tensors["logprobs"]["dtype"] == "float32" else float
    if arrays["logprobs"][0] != [rounder(x) for x in expected_lp]:
        raise ValueError("Native training log probabilities differ from the captured generation values")
    if tensors["rewards"]["shape"] != [1] or arrays["rewards"] != [_f32(reward)]:
        raise ValueError("Native training reward differs from the trusted full-episode reward")
    if not generated or not any(expected_mask):
        raise ValueError("Native episode has no trainable model tokens")
    return {"native_tensor_sha256": sha(tensors), "same_native_tensors": True, "truncation": "rejected",
            "generated_trainable_tokens": generated, "tool_masked_tokens": tool_tokens,
            "prompt_masked_tokens": len(aggregates[0]["response"]["input_tokens"]),
            "native_version": expected_version, "logprob_conversion": "native_torch_tensor_" + tensors["logprobs"]["dtype"]}
