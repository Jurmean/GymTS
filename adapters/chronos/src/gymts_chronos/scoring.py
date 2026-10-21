"""Pure stdlib independent scoring: no Chronos, torch or model service."""
import math

from gymts.contracts import canonical_json
from gymts.plugin_support import fail, unpack
from .contracts import PARSER, validate_prediction


def metrics(prediction, target, context):
    validate_prediction(prediction, context)
    if set(target) != set(context["targets"]):
        raise ValueError("Reference targets differ from task targets")
    errors, losses, coverage, widths = [], [], [], []
    for name, item in prediction["targets"].items():
        ys = target[name]
        if (len(ys) != context["horizon"] or
                any(type(y) not in (int, float) or not math.isfinite(y) for y in ys)):
            raise ValueError("Invalid reference forecast horizon")
        errors.extend(a-b for a, b in zip(item["mean"], ys))
        for q in context["quantiles"]:
            losses.extend(max(q*(y-p), (q-1)*(y-p)) for y, p in zip(ys, item["quantiles"][str(float(q))]))
        lo, hi = item["quantiles"]["0.1"], item["quantiles"]["0.9"]
        coverage.extend(float(a <= y <= b) for a, b, y in zip(lo, hi, ys))
        widths.extend(b-a for a, b in zip(lo, hi))
    return {"mae": math.fsum(abs(e) for e in errors)/len(errors),
            "rmse": math.sqrt(math.fsum(e*e for e in errors)/len(errors)),
            "pinball": math.fsum(losses)/len(losses), "coverage_80": math.fsum(coverage)/len(coverage),
            "width_80": math.fsum(widths)/len(widths)}


class DistributionScorer:
    def __init__(self, spec):
        if spec["params"]:
            fail("invalid_config", "Distribution scorer parameters must be empty")

    def validate_scoring(self, scoring):
        a = scoring["alignment"]
        if a["matching"] != "exact" or set(a["keys"]) != {"dataset_revision", "sample_token"} or a["duplicate_policy"] != "error":
            fail("unsupported_capability", "Distribution scoring requires unique exact source/sample alignment")

    def score(self, results, outcomes, context):
        services, scoring = context["services"], context["scoring"]
        self.validate_scoring(scoring)
        def records(reference):
            value = services.read_json(reference)
            if isinstance(value, list):
                return value
            if isinstance(value, dict) and isinstance(value.get('records'), list):
                return value['records']
            fail('schema_mismatch', 'Distribution snapshot requires a records list')
        rows = records(results["records_ref"])
        golds = records(outcomes["records_ref"])
        if len(rows) > 1:
            fail("unsupported_capability", "Each distribution evaluation unit must contain one sample")
        matched = {}
        for gold in golds:
            if "evaluation" not in gold["allowed_uses"]:
                fail("permission_denied", "Reference is not authorized for evaluation")
            key = canonical_json(gold["alignment_key"])
            if key in matched:
                fail("conflict", "Duplicate distribution reference")
            matched[key] = gold
        row, reason, values = (rows[0] if rows else None), None, {}
        if row is None:
            reason, category = "missing_result", "missing"
        elif row["status"] != "valid":
            reason, category = "invalid_result", "invalid"
        else:
            result = unpack(row["payload"], services)
            if result["parser_ref"] != PARSER:
                fail("schema_mismatch", "Unexpected distribution parser")
            gold = matched.get(canonical_json(row["alignment_key"]))
            if gold is None:
                reason, category = "missing_outcome", "missing"
            else:
                try:
                    values = metrics(result["parsed"], unpack(gold["payload"], services)["targets"], result["context"])
                    category = "scored"
                except (ValueError, KeyError, TypeError, OverflowError) as error:
                    reason, category = str(error), "invalid"
        scores = {}
        for metric in scoring["metrics"]:
            counts = dict(eligible=1, scored=0, missing=0, invalid=0, excluded=0)
            counts[category] = 1
            scores[metric] = {"value": values.get(metric), "status": "ready" if category == "scored" else "insufficient_evidence",
                              "counts": counts, "reason": reason}
        return {"metrics": scores, "item_scores_ref": services.save_json({"records": [{
            "result_id": row["result_id"] if row else None, "reason": reason, "values": values}]}, "gymts.json/1"),
                "diagnostics_ref": None}
