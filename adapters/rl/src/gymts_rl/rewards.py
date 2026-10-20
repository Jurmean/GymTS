"""Dependency-free outcome verifiers shared by GymTS scoring and TRL.

Gold is supplied explicitly by the trusted reward caller; it never enters a
Candidate's prompt. Format validity is reported separately from correctness.
"""

import json
import math
import re
from decimal import Decimal, InvalidOperation

NUMBER = r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
FINAL = re.compile(r"####[ \t]+(" + NUMBER + r")[ \t]*")
MAX_OUTPUT_BYTES = 1_048_576


def extract_gsm8k_answer(raw_text):
    """Require one final answer marker on the final nonempty line."""
    if not isinstance(raw_text, str) or len(raw_text.encode("utf-8")) > MAX_OUTPUT_BYTES:
        return None, "invalid_text"
    lines = raw_text.rstrip().splitlines()
    if not lines or raw_text.count("####") != 1:
        return None, "expected_single_final_answer"
    match = FINAL.fullmatch(lines[-1].strip())
    if match is None:
        return None, "invalid_final_answer_format"
    try:
        value = Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None, "invalid_numeric_answer"
    if not value.is_finite():
        return None, "non_finite_answer"
    return str(value), None


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("non_finite_answer")


def parse_completion(raw_text, task_id):
    """Parse public answer format without inspecting a reference answer."""
    if task_id == "gsm8k.numeric":
        number, reason = extract_gsm8k_answer(raw_text)
        return ({"answer": number}, None) if reason is None else (None, reason)
    if task_id != "chatts.numeric_summary":
        raise ValueError("Unsupported verifiable task: " + str(task_id))
    if not isinstance(raw_text, str) or len(raw_text.encode("utf-8")) > MAX_OUTPUT_BYTES:
        return None, "invalid_text"
    try:
        value = json.loads(raw_text, object_pairs_hook=_pairs, parse_constant=_reject_constant)
    except (ValueError, RecursionError, OverflowError) as error:
        return None, str(error) if str(error) in ("duplicate_key", "non_finite_answer") else "invalid_json"
    if not isinstance(value, dict) or set(value) != {"mean", "min", "max", "last"}:
        return None, "summary_keys_mismatch"
    if any(type(item) not in (int, float) or not math.isfinite(item) for item in value.values()):
        return None, "non_finite_or_nonnumeric_answer"
    return value, None


def validate_reward_spec(reward_spec):
    """Validate an explicit reference independently of the candidate's format."""
    if isinstance(reward_spec, str):
        reward_spec = json.loads(reward_spec, object_pairs_hook=_pairs, parse_constant=_reject_constant)
    if not isinstance(reward_spec, dict):
        raise ValueError("Reward spec must be an object")
    if reward_spec.get("kind") == "gsm8k_numeric":
        try:
            target = Decimal(str(reward_spec["ground_truth"]))
        except (InvalidOperation, KeyError) as error:
            raise ValueError("Ground truth must be a finite number") from error
        if not target.is_finite():
            raise ValueError("Ground truth must be finite")
    elif reward_spec.get("kind") == "numeric_summary":
        target = reward_spec.get("ground_truth")
        if (not isinstance(target, dict) or set(target) != {"mean", "min", "max", "last"}
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in target.values())):
            raise ValueError("Summary ground truth requires four finite numeric fields")
        atol, rtol, scale = (float(reward_spec.get(key, default)) for key, default in (("atol", .001), ("rtol", .001), ("scale", 1.0)))
        if not all(math.isfinite(x) for x in (atol, rtol, scale)) or atol < 0 or rtol < 0 or scale <= 0:
            raise ValueError("Invalid numeric verifier tolerances or scale")
    else:
        raise ValueError("Unsupported reward kind")
    return reward_spec


def score_completion(raw_text, reward_spec):
    reward_spec = validate_reward_spec(reward_spec)
    if isinstance(reward_spec, str):
        reward_spec = json.loads(reward_spec, object_pairs_hook=_pairs, parse_constant=_reject_constant)
    if not isinstance(reward_spec, dict):
        raise ValueError("Reward spec must be an object or encoded JSON object")
    kind = reward_spec.get("kind")
    if kind not in ("gsm8k_numeric", "numeric_summary"):
        raise ValueError("Unsupported reward kind: " + str(kind))
    task_id = "gsm8k.numeric" if kind == "gsm8k_numeric" else "chatts.numeric_summary"
    parsed, reason = parse_completion(raw_text, task_id)
    result = {"reward": 0.0, "correct": False, "format_valid": reason is None,
              "reason": reason, "parsed": parsed, "error": None}
    if reason is not None:
        return result
    if kind == "gsm8k_numeric":
        target = Decimal(str(reward_spec["ground_truth"]))
        if not target.is_finite():
            raise ValueError("Ground truth must be finite")
        correct = Decimal(parsed["answer"]) == target
        result.update(reward=float(correct), correct=correct)
    else:
        target = reward_spec["ground_truth"]
        if set(target) != set(parsed) or any(type(value) not in (int, float) or not math.isfinite(value) for value in target.values()):
            raise ValueError("Summary ground truth requires four finite numeric fields")
        atol, rtol, scale = (float(reward_spec.get(key, default)) for key, default in (("atol", .001), ("rtol", .001), ("scale", 1.0)))
        if not all(math.isfinite(x) for x in (atol, rtol, scale)) or atol < 0 or rtol < 0 or scale <= 0:
            raise ValueError("Invalid numeric verifier tolerances or scale")
        errors = [abs(float(parsed[key]) - float(target[key])) for key in sorted(target)]
        if not all(math.isfinite(error) for error in errors):
            result.update(reason="numeric_error_overflow")
            return result
        mean_error = math.fsum(error / len(errors) for error in errors)
        correct = all(abs(float(parsed[key]) - float(target[key])) <= atol + rtol * abs(float(target[key])) for key in target)
        result.update(reward=1.0 if correct else 1.0 / (1.0 + mean_error / scale), correct=correct, error=mean_error)
    if not result["correct"]:
        result["reason"] = "incorrect_answer"
    return result


def _completion_text(completion):
    if isinstance(completion, str):
        return completion
    if isinstance(completion, list) and len(completion) == 1 and isinstance(completion[0], dict):
        return completion[0].get("content", "")
    raise ValueError("Expected a plain or single assistant-message completion")


def trl_reward(completions, reward_spec, **kwargs):
    """TRL extra-column reward callable for homogeneous or mixed task batches.

    Mixed Arrow datasets should encode each reward-spec object as a JSON string
    so scalar math targets and structured time-series targets share one dtype.
    """
    if len(completions) != len(reward_spec):
        raise ValueError("Completion and reward-spec counts differ")
    return [score_completion(_completion_text(text), spec)["reward"] for text, spec in zip(completions, reward_spec)]


__all__ = ["extract_gsm8k_answer", "parse_completion", "score_completion", "trl_reward", "validate_reward_spec"]
