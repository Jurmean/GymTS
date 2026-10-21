"""Versioned gold-free answer syntax projection; numeric scoring is unchanged."""
import copy
import hashlib
from decimal import Decimal, InvalidOperation
import json
import re

from gymts_rl.rewards import NUMBER, parse_completion

CALCULATOR_INSTRUCTION = (
    "Before answering, use the available calculator to verify numeric arithmetic relevant to this question. "
    "The calculator accepts basic arithmetic expressions containing numbers, decimal points, +, -, *, /, "
    "parentheses and whitespace. Write only the arithmetic expression inside <calculator>...</calculator>: no assignments, variable names, function calls (including sum, min, max or len), lists or Python code. Valid syntax example unrelated to this question: <calculator>(2 + 3) / 2</calculator>. Choose the expression and calculations yourself. "
    "Use the calculator result in your reasoning, then put the final answer in the requested boxed format."
)


def native_messages(sample):
    """Render all authorized TS values; change format instructions, never answers."""
    messages = copy.deepcopy(sample["messages"])
    series = sample.get("timeseries", [])
    if sum(message["content"].count("<ts><ts/>") for message in messages) != len(series):
        raise ValueError("Public series placeholder count differs from the authorized arrays")
    arrays = iter(series)
    for message in messages:
        text = message["content"]
        parts = text.split("<ts><ts/>")
        text = parts[0]
        for tail in parts[1:]:
            text += json.dumps(next(arrays), allow_nan=False, separators=(",", ":")) + tail
        # TIR's original system instruction requests boxed answers. Keep user intent consistent.
        if sample["task_id"] == "gsm8k.numeric":
            text = re.sub(r"\nSolve the problem\. Finish with exactly one final line: #### <number>\. Do not write anything after that line\.$", "", text)
        elif sample["task_id"] == "chatts.numeric_summary":
            text = text.replace("Return only a JSON object", "Put a JSON object in the final boxed answer")
        else:
            raise ValueError("Unsupported native TIR task")
        message["content"] = text
    user_messages = [message for message in messages if message["role"] == "user"]
    if not user_messages:
        raise ValueError("Native calculator verification requires a public user instruction")
    user_messages[-1]["content"] += "\n" + CALCULATOR_INSTRUCTION
    return messages


def last_boxed(text):
    start = text.rfind("\\boxed{")
    if start < 0:
        return None
    first, depth = start + len("\\boxed{"), 1
    for index in range(first, len(text)):
        if text[index] == "{" and (index == 0 or text[index-1] != "\\"):
            depth += 1
        elif text[index] == "}" and (index == 0 or text[index-1] != "\\"):
            depth -= 1
            if not depth:
                if re.fullmatch(r"\s*(?:\\\)|\\\]|\$\$|\$)?\s*[.!?]?\s*", text[index+1:]) is None:
                    return None
                return text[first:index]
    return None


def project_completion(text, task_id, terminal_tokens=()):
    original, removed = text, []
    for _ in range(8):
        match = next((token for token in terminal_tokens if token and text.rstrip().endswith(token)), None)
        if match is None:
            break
        text = text.rstrip()[:-len(match)]
        removed.append(match)
    answer = last_boxed(text)
    source_format = "terminal_boxed"
    if answer is None:
        # A malformed/unsupported last box never falls back to an earlier answer.
        if "\\boxed{" in text or task_id != "chatts.numeric_summary":
            return original, {"converted": False, "reason": "missing_or_nonterminal_complete_boxed_answer"}
        blocks = list(re.finditer(r"```json[ \t]*\r?\n(.*?)```", text, flags=re.IGNORECASE | re.DOTALL))
        if len(blocks) != 1:
            return original, {"converted": False, "reason": "missing_or_ambiguous_explicit_json_answer_block"}
        answer, source_format = blocks[0].group(1).strip(), "unique_explicit_json_answer_block"
    if task_id == "gsm8k.numeric":
        if re.fullmatch(NUMBER, answer.strip()) is None:
            return original, {"converted": False, "reason": "boxed_answer_is_not_a_plain_number"}
        try:
            value = Decimal(answer.strip().replace(",", ""))
        except InvalidOperation:
            return original, {"converted": False, "reason": "boxed_answer_is_not_a_plain_number"}
        if not value.is_finite():
            return original, {"converted": False, "reason": "nonfinite_boxed_answer"}
        projected = "#### " + format(value, "f")
    elif task_id == "chatts.numeric_summary":
        projected = answer.strip()
    else:
        raise ValueError("Unsupported native TIR answer task")
    _, reason = parse_completion(projected, task_id)
    if reason is not None:
        return original, {"converted": False, "reason": reason}
    return projected, {"converted": True, "reason": None, "source_format": source_format,
        "rule": "last_terminal_box_modulo_closing_LaTeX_and_punctuation_or_one_explicit_json_fence",
        "removed_native_stop_tokens": removed,
        "native_text_sha256": hashlib.sha256(original.encode()).hexdigest(),
        "projected_text_sha256": hashlib.sha256(projected.encode()).hexdigest(),
        "format_metric_scope": "canonical_projected_answer; raw_native_text_is_preserved"}
