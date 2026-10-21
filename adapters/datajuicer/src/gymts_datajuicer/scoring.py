"""Independent quality checks: no Data-Juicer, torch, model or live data reads."""
import collections
import math
import re
from gymts.plugin_support import fail, unpack
from . import UPSTREAM_SHA
from .common import dumps, loads, row_identity, sha, validate_source
from .contracts import METRICS


def assess(value, gold):
    """Recompute quality from sealed rows and separately authorized references.

    A source that produces no usable answer counts as zero in source-level
    accuracy. Native filter statistics and model self-ratings are never used.
    """
    sources = validate_source(gold["rows"])
    by_id = {row["sample_id"]: row for row in sources}
    eligible, seen = [], set()
    for row in sources:
        if 32 <= len(row["text"]) <= 12000 and row["text"].strip() not in seen:
            eligible.append(row["sample_id"])
            seen.add(row["text"].strip())
    if not eligible:
        raise ValueError("No eligible training source in fixed reference")
    rows, stages = value["rows"], value["stages"]
    lineage_errors = []
    if value["identity"].get("upstream", {}).get("commit") != UPSTREAM_SHA:
        lineage_errors.append("upstream_identity_mismatch")
    if value["identity"].get("cpu_only") is not False or not value["identity"].get("native_execution"):
        lineage_errors.append("not_native_model_pipeline")
    operators = ["text_length_filter", "document_deduplicator", "gymts_audited_native_qa_mapper"]
    if [stage.get("operator") for stage in stages] != operators:
        lineage_errors.append("missing_or_reordered_stage")
    previous = sources
    for index, stage in enumerate(stages):
        if stage.get("index") != index or stage.get("status") != "succeeded" or stage.get("input") != previous:
            lineage_errors.append("stage_chain_mismatch:" + str(index))
        incoming, outgoing = stage.get("input", []), stage.get("output", [])
        if (stage.get("input_members") != [row_identity(row) for row in incoming]
            or stage.get("output_members") != [row_identity(row) for row in outgoing]):
            lineage_errors.append("member_digest_mismatch:" + str(index))
        out_ids = {row["sample_id"] for row in outgoing}
        if stage.get("dropped_ids") != [row["sample_id"] for row in incoming if row["sample_id"] not in out_ids]:
            lineage_errors.append("drop_accounting_mismatch:" + str(index))
        if stage.get("output_count_by_source") != dict(collections.Counter(row["sample_id"] for row in outgoing)):
            lineage_errors.append("expansion_accounting_mismatch:" + str(index))
        for row in outgoing:
            source = by_id.get(row["sample_id"])
            if source is None or any(row.get(key) != source[key] for key in source):
                lineage_errors.append("source_fields_changed:" + str(index))
        previous = outgoing
    if previous != rows:
        lineage_errors.append("final_members_mismatch")
    if sha(value["export_text"].encode()) != value["export_sha256"]:
        lineage_errors.append("export_hash_mismatch")
    try:
        exported = [loads(line) for line in value["export_text"].splitlines() if line.strip()]
        if exported != rows:
            lineage_errors.append("export_rows_mismatch")
    except ValueError:
        lineage_errors.append("export_parse_error")
    model_sources = [call.get("sample_id") for call in value["model_calls"]]
    if (set(model_sources) != set(eligible) or len(model_sources) != len(eligible)
        or any(call.get("status") != "succeeded" for call in value["model_calls"])):
        lineage_errors.append("model_attempt_coverage_mismatch")
    actual_pairs = collections.defaultdict(list)
    for call in value["model_calls"]:
        source = by_id.get(call.get("sample_id"))
        if source is None or call.get("messages") != [{"role": "user", "content": source["text"]}]:
            lineage_errors.append("model_request_source_mismatch")
        try:
            raw = call["response"][0]["generated_text"]
            actual_pairs[call["sample_id"]].extend((q.strip(), a.strip()) for q, a in
                re.findall(r"Human:(.*?)Assistant:(.*?)(?=Human|$)", raw, re.DOTALL)[:2])
        except (KeyError, TypeError, IndexError):
            lineage_errors.append("model_response_missing")
    for row in rows:
        if (row.get("query"), row.get("response")) not in actual_pairs[row.get("sample_id")]:
            lineage_errors.append("derived_pair_not_in_actual_model_response")
    grouped, diagnostics, structured, correct = collections.defaultdict(list), [], 0, 0
    forbidden = set(gold["holdout_families"])
    forbidden_series = set(gold["holdout_series_sha256"])
    all_members = rows + sources + [row for stage in stages for field in ("input", "output")
                                   for row in stage.get(field, [])]
    holdout_clean = not any(row.get("family_id") in forbidden or sha(row.get("series")) in forbidden_series
                            or row.get("split") != "train" for row in all_members)
    keys = []
    for row in rows:
        source = by_id.get(row.get("sample_id"))
        reason, valid, accurate = None, False, False
        try:
            question, answer = loads(row["query"]), loads(row["response"])
            if source is None or row["sample_id"] not in eligible:
                raise ValueError("unexpected_source")
            if (set(question) != {"operation", "family_id"} or question["operation"] != source["operation"]
                or question["family_id"] != source["family_id"] or set(answer) != {"value"}
                or type(answer["value"]) not in (int, float) or not math.isfinite(answer["value"])):
                raise ValueError("invalid_structure_or_alignment")
            valid = True
            series, op = source["series"], source["operation"]
            reference = min(series) if op == "min" else max(series) if op == "max" else math.fsum(series) / len(series)
            accurate = math.isclose(answer["value"], reference, rel_tol=1e-5, abs_tol=1e-4)
            reason = None if accurate else "incorrect_numeric_answer"
            keys.append(sha({"family_id": source["family_id"], "question": question, "answer": answer}))
        except (KeyError, TypeError, ValueError) as error:
            reason = str(error)
            keys.append(sha(row))
        grouped[row.get("sample_id")].append((valid, accurate))
        structured += int(valid)
        diagnostics.append({"sample_id": row.get("sample_id"), "row_sha256": sha(row),
                            "structured": valid, "correct": accurate, "reason": reason})
    for sample_id in eligible:
        answers = grouped[sample_id]
        correct += int(bool(answers) and all(valid and accurate for valid, accurate in answers))
        if not answers:
            diagnostics.append({"sample_id": sample_id, "structured": False, "correct": False,
                                "reason": "no_derived_output"})
    n = len(eligible)
    values = {"answer_accuracy": correct / n, "structure_rate": structured / max(n, len(rows)),
        "source_coverage": sum(bool(grouped[key]) for key in eligible) / n,
        "unique_rate": len(set(keys)) / len(keys) if keys else 0.0,
        "lineage_integrity": float(not lineage_errors), "holdout_clean": float(holdout_clean)}
    return {"values": values, "eligible_sources": n, "output_rows": len(rows), "diagnostics": diagnostics,
            "lineage_errors": lineage_errors, "empty_outputs": sum(not grouped[key] for key in eligible)}


class QualityScorer:
    def __init__(self, spec):
        pass

    def validate_scoring(self, scoring):
        alignment = scoring["alignment"]
        if (alignment["matching"] != "exact" or alignment["keys"] != ["source_revision"]
            or alignment["duplicate_policy"] != "error" or any(metric not in METRICS for metric in scoring["metrics"])):
            fail("unsupported_capability", "Data quality requires exact source_revision alignment")

    def score(self, results, outcomes, context):
        services, scoring = context["services"], context["scoring"]
        self.validate_scoring(scoring)
        rows = services.read_json(results["records_ref"])
        gold = services.read_json(outcomes["records_ref"])
        if len(rows) > 1 or len(gold) > 1:
            fail("conflict", "One native pipeline requires one result and one independent reference")
        metrics, diagnostic = {}, None
        reason = None
        if not rows or not gold:
            reason = "missing_result_or_reference"
        elif rows[0]["status"] != "valid":
            reason = "invalid_result"
        elif rows[0]["alignment_key"] != gold[0]["alignment_key"]:
            reason = "alignment_mismatch"
        elif "evaluation" not in gold[0]["allowed_uses"]:
            fail("permission_denied", "Data-quality reference is evaluation-only")
        else:
            diagnostic = assess(unpack(rows[0]["payload"], services), unpack(gold[0]["payload"], services))
        for metric in scoring["metrics"]:
            metrics[metric] = {"value": diagnostic["values"][metric] if diagnostic else None,
                "status": "ready" if diagnostic else "insufficient_evidence", "reason": reason,
                "counts": {"eligible": 1, "scored": int(diagnostic is not None),
                    "missing": int(diagnostic is None and reason == "missing_result_or_reference"),
                    "invalid": int(diagnostic is None and reason != "missing_result_or_reference"), "excluded": 0}}
        return {"metrics": metrics, "item_scores_ref": services.save_json(diagnostic or {"reason": reason}, "gymts.json/1"),
                "diagnostics_ref": None}
