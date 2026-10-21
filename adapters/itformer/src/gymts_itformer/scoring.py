"""Model-free independent scoring; lexical overlap is not semantic correctness."""
import re
from collections import Counter
from gymts.contracts import canonical_json
from gymts.plugin_support import fail, unpack
from .contracts import PARSER_REF

# Strict A-F interpretation follows the MIT-licensed upstream utils/metrics.py
# at b80142fc8b6ab2be8f148f3bb7a7534bb32f318b. Keep it in this lightweight
# domain package so rescoring never imports torch, transformers or native code.
def parse_options(value):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    def bare(item):
        tokens = re.sub(r"[,;/&+]", " ", item).lower().split()
        return sorted(set(tokens)) if tokens and all(len(t) == 1 and t in "abcdef" for t in tokens) else None
    parsed = bare(text)
    if parsed is not None:
        return parsed
    marker = re.compile(r"(?<![A-Za-z0-9])([a-f])\s*[\).]", re.I)
    if re.fullmatch(r"\s*[a-f]\s*[\).](?:\s*(?:(?:[,;/&+]|\band\b)\s*)?[a-f]\s*[\).])*\s*", text, re.I):
        return sorted({m.group(1).lower() for m in marker.finditer(text)})
    leading = re.fullmatch(r"\s*([a-f])\s*[\).](?:\s+(.*))?\s*", text, re.I | re.S)
    if leading is None:
        return None
    answer = leading.group(1).lower()
    if {m.group(1).lower() for m in marker.finditer(text)} != {answer}:
        return None
    tail = bare(leading.group(2) or "")
    return None if tail and tail != [answer] else [answer]


def lexical_f1(prediction, reference):
    left, right = Counter(prediction.lower().split()), Counter(reference.lower().split())
    shared = sum((left & right).values())
    return 2.0 * shared / (sum(left.values()) + sum(right.values())) if left or right else 1.0


def _records(value):
    if isinstance(value, list):
        return value
    for key in ("records", "results", "outcomes", "items"):
        if isinstance(value.get(key), list):
            return value[key]
    fail("schema_mismatch", "Scoring view must contain records")


class ReferenceScorer:
    def __init__(self, spec):
        self.expected = spec['params']['expected_alignments']
        keys = [canonical_json(row) for row in self.expected]
        if not keys or len(set(keys)) != len(keys):
            fail('invalid_config', 'Scorer requires a nonempty unique fixed planned QA membership')

    def validate_scoring(self, scoring):
        alignment = scoring['alignment']
        if alignment['keys'] != ['dataset_revision', 'sample_id'] or alignment['matching'] != 'exact' or alignment['duplicate_policy'] != 'error':
            fail('unsupported_capability', 'ITFormer requires exact unique dataset_revision/sample_id alignment')

    def score(self, results, outcomes, context):
        services, scoring = context['services'], context['scoring']
        self.validate_scoring(scoring)
        expected = {canonical_json(key) for key in self.expected}
        predicted, gold = {}, {}
        for row in _records(services.read_json(results['records_ref'])):
            key = canonical_json(row['alignment_key'])
            if key in predicted or key not in expected:
                fail('conflict', 'Duplicate or unplanned ITFormer result')
            predicted[key] = row
        for outcome in _records(services.read_json(outcomes['records_ref'])):
            if 'evaluation' not in outcome.get('allowed_uses', []):
                fail('permission_denied', 'Private answers are evaluation-only')
            key = canonical_json(outcome['alignment_key'])
            if key in gold or key not in expected:
                fail('conflict', 'Duplicate or unplanned ITFormer reference')
            gold[key] = outcome
        metrics, diagnostics = {}, []
        for metric in scoring['metrics']:
            counts = {'eligible': len(expected), 'scored': 0, 'missing': 0, 'invalid': 0, 'excluded': 0}
            values = []
            for alignment in self.expected:
                key = canonical_json(alignment)
                row, outcome = predicted.get(key), gold.get(key)
                result = unpack(row['payload'], services) if row else None
                truth = unpack(outcome['payload'], services) if outcome else None
                if result and result['parser_ref'] != PARSER_REF:
                    fail('schema_mismatch', 'Unrecognized fixed answer parser')
                if truth and result and truth['stage'] != result['stage']:
                    fail('conflict', 'Answer and reference stages differ')
                value, reason = None, None
                if row is None:
                    counts['missing'] += 1; reason = 'missing_result'
                elif metric != 'format_valid' and truth is None:
                    counts['missing'] += 1; reason = 'missing_reference'
                else:
                    counts['scored'] += 1
                    if metric == 'format_valid':
                        value = float(row['status'] == 'valid')
                    elif metric == 'answer_exact_match':
                        if truth['stage'] in (2, 3):
                            wanted = parse_options(truth['answer'])
                            if wanted is None:
                                fail('schema_mismatch', 'Native closed reference cannot be parsed')
                            value = float(result['parsed_options'] is not None and result['parsed_options'] == wanted)
                        else:
                            value = float(result['raw_text'].strip() == truth['answer'].strip())
                    elif metric == 'lexical_token_f1':
                        value = lexical_f1(result['raw_text'], truth['answer'])
                    else:
                        fail('unsupported_capability', 'Unknown ITFormer metric')
                    reason = result['reason']
                    values.append(value)
                diagnostics.append({'metric_id': metric, 'alignment_key': alignment,
                    'result_id': row['result_id'] if row else None,
                    'outcome_id': outcome['outcome_id'] if outcome else None,
                    'value': value, 'reason': reason})
            metrics[metric] = {'value': sum(values) / len(values) if values else None,
                'status': 'ready' if values else 'insufficient_evidence', 'counts': counts,
                'reason': None if values else 'no_scored_results'}
        return {'metrics': metrics, 'item_scores_ref': services.save_json({'records': diagnostics}, 'gymts.json/1'),
            'diagnostics_ref': None}
