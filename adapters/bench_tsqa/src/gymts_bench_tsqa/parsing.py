"""Versioned public-question decoding and explicit reference/response rules.

Questions are data, never instructions for the importer. No model or evaluator
receives source answer/attributes. Ambiguous references remain unknown.
"""
import copy
import hashlib
import json
import math
import re

from gymts.contracts import GymTSError, canonical_json

PARSER_REF = "tsqa.single-answer/1"
PROJECTION_REF = "tsqa.literal-series-reference/1"
CHOICE = re.compile(r"(?<![A-Za-z0-9])([A-Fa-f])\s*[):.]\s+")
FOOTER = re.compile(r"\n\s*(?:Your answer|Please output|Now, based|Please directly output)", re.I)
KINDS = ("mcq_label", "boolean", "text_choice", "unresolved")


def _fail(message):
    raise GymTSError("invalid_dataset", message, stage="tsqa.import")


def label_choices(question):
    matches = list(CHOICE.finditer(question))
    blocks, current = [], []
    for match in matches:
        label = match[1].upper()
        if label == "A":
            if len(current) >= 2:
                blocks.append(current)
            current = [match]
        elif current and ord(label) == ord(current[-1][1].upper()) + 1:
            current.append(match)
        elif current:
            if len(current) >= 2:
                blocks.append(current)
            current = []
    if len(current) >= 2:
        blocks.append(current)
    if len(blocks) != 1:
        return []
    block = blocks[0]
    choices = []
    for index, match in enumerate(block):
        end = block[index+1].start() if index+1 < len(block) else len(question)
        text = question[match.end():end]
        footer = FOOTER.search(text)
        if footer:
            text = text[:footer.start()]
        text = text.strip()
        if not text:
            return []
        choices.append({"id": match[1].upper(), "text": text})
    return choices


def text_choices(question):
    match = re.search(r"Please choose from:\s*(.*?)\s*Please directly output", question, re.I | re.S)
    if match is None:
        return []
    # The source generator appends one sentence-final dot after the final
    # semicolon-delimited option. Preserve question_original verbatim; normalize
    # that generator punctuation only when mapping a text choice reference.
    values = [part.strip() for part in match[1].split(";")]
    if len(values) != 4 or any(not part for part in values):
        return []
    return [{"id": "choice_" + str(index+1), "text": value} for index, value in enumerate(values)]


def decode_public(row, dataset_id, source_row):
    question, arrays, names = row.get("question"), row.get("timeseries"), row.get("cols")
    if not isinstance(question, str) or not question.strip():
        _fail("A source row requires its original nonempty question")
    if (not isinstance(arrays, list) or not arrays or not isinstance(names, list) or len(arrays) != len(names)
            or any(not isinstance(name, str) or not name for name in names)):
        _fail("Original columns must identify every ordered time series")
    series = []
    for name, values in zip(names, arrays):
        if not isinstance(values, list) or not values or any(type(v) not in (int,float) or not math.isfinite(v) for v in values):
            _fail("Original observations must be finite nonempty numeric lists")
        series.append({"name": name, "values": copy.deepcopy(values)})
    markers = list(re.finditer(re.escape("<ts><ts/>"), question))
    if len(markers) != len(series):
        _fail("Original time-series attachment markers differ from ordered arrays")
    projected, cursor, projection = [], 0, []
    for index, marker in enumerate(markers):
        reference = "[[GYMTS_SERIES_" + str(index) + "]]"
        if reference in question:
            _fail("Source question collides with the neutral attachment marker namespace")
        projected.extend((question[cursor:marker.start()], reference))
        projection.append({"series_index": index, "original_start": marker.start(), "original_end": marker.end(), "reference": reference})
        cursor = marker.end()
    projected.append(question[cursor:])
    choices = label_choices(question)
    if re.search(r"True\s*/\s*False|True\s+or\s+False", question, re.I):
        kind = "boolean"
        choices = [{"id":"True", "text":"True"},{"id":"False", "text":"False"}]
    elif choices:
        kind = "mcq_label"
    elif "Please choose from:" in question:
        choices = text_choices(question)
        kind = "text_choice" if choices else "unresolved"
    else:
        kind = "unresolved"
    identity = {"dataset_id":dataset_id,"source_row":source_row}
    sample_id = hashlib.sha256(canonical_json(identity)).hexdigest()
    return {"sample_id":sample_id,"dataset_id":dataset_id,"source_row":source_row,"task_kind":kind,
        "question_original":question,"question":"".join(projected),"series":series,"choices":choices,
        "attachment_projection":projection,"projection_ref":PROJECTION_REF,"context":{"question_policy":"complete-original-with-lossless-series-projection/1"}}


def _text_key(value):
    value = re.sub(r"^1\.\s*", "", value.strip())
    # A terminal full stop and source double full stop carry no option identity.
    return value.rstrip(".").strip()


def decode_target(row, public):
    answer = row.get("answer")
    status, canonical, reason = "unknown", None, "no_verified_reference_rule"
    if isinstance(answer, str):
        value = answer.strip()
        if public["task_kind"] in ("mcq_label", "boolean"):
            if value in {choice["id"] for choice in public["choices"]}:
                status, canonical, reason = "known", value, None
            else:
                reason = "reference_not_in_public_choices"
        elif public["task_kind"] == "text_choice":
            matches = [item["id"] for item in public["choices"] if _text_key(item["text"]) == _text_key(value)]
            if len(matches) == 1:
                status, canonical, reason = "known", matches[0], None
            else:
                reason = "reference_text_has_no_unique_public_choice"
    return {"sample_id":public["sample_id"],"reference_status":status,"reference_answer":canonical,
        "reference_kind":public["task_kind"],"reason":reason,"raw_answer_json":json.dumps(answer,ensure_ascii=False),
        "raw_attributes_json":json.dumps(row.get("attributes"),ensure_ascii=False),
        "raw_private_metadata_json":json.dumps({k:v for k,v in row.items() if k not in ("question","timeseries","cols","answer","attributes")},ensure_ascii=False),
        "allowed_uses":["evaluation"]}


def parse_response(raw, public):
    if not isinstance(raw, str) or not raw.strip():
        return None, "empty_answer"
    value = raw.strip()
    match = re.fullmatch(r"\\answer\{([^{}]*)\}", value, re.S)
    if match:
        value = match[1].strip()
    elif "\\answer" in value:
        return None, "not_one_standalone_answer_tag"
    kind = public["task_kind"]
    if kind in ("mcq_label", "boolean"):
        if value not in {item["id"] for item in public["choices"]}:
            return None, "answer_not_one_public_choice_id"
        return {"answer":value}, None
    if kind == "text_choice":
        matches = [item["id"] for item in public["choices"] if _text_key(item["text"]) == _text_key(value)]
        if len(matches) != 1:
            return None, "answer_text_has_no_unique_public_choice"
        return {"answer":matches[0]}, None
    return {"answer":value}, None
