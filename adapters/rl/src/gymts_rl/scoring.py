"""Independent AutoBenchTS scoring of sealed verifiable-QA results.

Accuracy uses an authorized reference; format_valid can be measured without
one. Neither metric treats a training RewardRecord as evaluation evidence.
"""
from gymts.contracts import GymTSError, canonical_json
from gymts.plugin_support import unpack
from .contracts import PARSER_REF
from .rewards import parse_completion, score_completion, validate_reward_spec


class RLQAScorer:
    def __init__(self, spec):
        if spec.get("params", {}):
            raise GymTSError("invalid_config", "RL QA scorer has no configurable parsing policy")

    def validate_scoring(self, scoring):
        alignment = scoring["alignment"]
        if (alignment["matching"] != "exact" or set(alignment["keys"]) != {"dataset_revision", "sample_id", "group_id"}
                or len(alignment["keys"]) != 3 or alignment["duplicate_policy"] != "error"):
            raise GymTSError("unsupported_capability", "RL QA requires exact dataset/sample/group alignment and unambiguous outcomes")

    def score(self, results, outcomes, context):
        services, scoring = context["services"], context["scoring"]
        self.validate_scoring(scoring)
        rows = services.read_json(results["records_ref"])
        references = services.read_json(outcomes["records_ref"])
        if len(rows) > 1:
            raise GymTSError("unsupported_capability", "One RL QA unit contains at most one captured result")
        key = lambda record: canonical_json({name: record["alignment_key"][name] for name in scoring["alignment"]["keys"]})
        matched = {}
        for reference in references:
            if "evaluation" not in reference["allowed_uses"]:
                raise GymTSError("permission_denied", "Training-only outcomes cannot support independent evaluation")
            identity = key(reference)
            if identity in matched:
                raise GymTSError("conflict", "More than one evaluation reference for the RL QA sample")
            matched[identity] = reference
        row = rows[0] if rows else None
        answer = unpack(row["payload"], services) if row is not None else None
        if answer is not None and answer["parser_ref"] != PARSER_REF:
            raise GymTSError("unsupported_capability", "Unsupported RL QA parser revision")
        metrics, items = {}, []
        for metric in scoring["metrics"]:
            counts = {"eligible": 1, "scored": 0, "missing": 0, "invalid": 0, "excluded": 0}
            value, reason, reference = None, None, None
            if answer is None:
                counts["missing"], reason = 1, "missing_result"
            elif metric == "format_valid":
                _, parse_reason = parse_completion(answer["raw_text"], answer["task_id"])
                value, counts["scored"] = float(parse_reason is None), 1
            elif metric == "accuracy":
                reference = matched.get(key(row))
                if reference is None:
                    counts["missing"], reason = 1, "missing_outcome"
                else:
                    gold = unpack(reference["payload"], services)
                    if gold["sample_id"] != answer["sample_id"] or gold["task_id"] != answer["task_id"]:
                        raise GymTSError("schema_mismatch", "Evaluation reference belongs to another sample/task")
                    try:
                        definition = validate_reward_spec(gold["reward_spec"])
                        expected = {"gsm8k.numeric": "gsm8k_numeric", "chatts.numeric_summary": "numeric_summary"}[answer["task_id"]]
                        if definition["kind"] != expected:
                            raise ValueError("reference kind differs from task")
                        result = score_completion(answer["raw_text"], definition)
                    except (ValueError, TypeError, KeyError, ArithmeticError):
                        counts["invalid"], reason = 1, "invalid_outcome"
                    else:
                        # A malformed answer with a valid reference is a measured
                        # wrong answer, rather than missing ground truth.
                        value, counts["scored"] = float(result["correct"]), 1
            else:
                raise GymTSError("unsupported_capability", "Unsupported RL QA evaluation metric")
            metrics[metric] = {"value": value, "status": "ready" if value is not None else "insufficient_evidence",
                               "counts": counts, "reason": reason}
            items.append({"metric_id": metric, "result_id": row["result_id"] if row else None,
                          "outcome_id": reference["outcome_id"] if reference else None,
                          "outcome_revision": reference["revision"] if reference else None,
                          "value": value, "reason": reason})
        return {"metrics": metrics, "item_scores_ref": services.save_json({"records": items}, "gymts.json/1"),
                "diagnostics_ref": None}
