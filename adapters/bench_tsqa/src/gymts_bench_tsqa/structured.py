"""Pinned deterministic ChatTS RLVR scoring; references remain evaluation-only."""
import copy
import json
import math
from statistics import mean

from . import chatts_rlvr_rules as rules

RULE_REF = 'chatts.dataset-a-rlvr/dc2dcb0-deterministic-1'
EVALUATORS = {name: getattr(rules, 'evaluate_' + name) for name in (
    'trend', 'season', 'noise', 'local', 'shape_correlation', 'local_correlation',
    'shape_cluster', 'local_cluster', 'deductive', 'causal')}


def evaluate_structured(answer, reference):
    """Return the upstream mean of nonempty category/numeric/reason means.

    This is a soft task score, not multiple-choice accuracy. The original RLVR
    outer reward also scores malformed response bodies as zero. No judge/API is
    loaded, and a fresh attribute copy prevents upstream local-rule mutation.
    """
    if reference['rule_ref'] != RULE_REF:
        raise ValueError('Unsupported structured scoring revision')
    evaluator = EVALUATORS[reference['ability_type'].replace('-', '_')]
    try:
        category, numeric, reasoning, _ = evaluator(
            answer, copy.deepcopy(reference['attribute']), reference['cols'])
    except (IndexError, KeyError, TypeError, ValueError, ZeroDivisionError) as error:
        return 0.0, {'response_error': type(error).__name__}
    groups = {'category': category, 'numeric': numeric, 'reasoning': reasoning}
    values = [mean(items) for items in groups.values() if items]
    value = float(mean(values)) if values else 0.0
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('Structured scorer produced a nonfinite or out-of-range score')
    return value, groups


def structured_reference(row):
    """Validate structured annotations, without exposing them in public inputs."""
    abilities, attributes, cols = row.get('ability_types'), row.get('attributes'), row.get('cols')
    if (not isinstance(abilities, list) or len(abilities) != 1 or not isinstance(abilities[0], str)
            or abilities[0].replace('-', '_') not in EVALUATORS):
        raise ValueError('Unsupported structured ability')
    if not isinstance(attributes, list) or len(attributes) != 1:
        raise ValueError('Expected one structured annotation per RLVR question')
    ability, attribute = abilities[0].replace('-', '_'), attributes[0]
    if ability in ('deductive', 'causal'):
        if not isinstance(attribute, str) or not attribute.strip():
            raise ValueError('Missing reasoning reference')
        if ability == 'deductive' and rules.split_sentences(attribute)[0].lower() not in ('yes', 'no'):
            raise ValueError('Non-Yes/No deductive references require a separate judge')
    elif ability == 'local':
        if not isinstance(attribute, list) or any(not isinstance(item, dict) for item in attribute):
            raise ValueError('Expected local feature annotations')
        for item in attribute:
            for field in ('type', 'position', 'amplitude'):
                if field not in item:
                    raise ValueError('Incomplete local annotation')
    else:
        fields = {'trend': ('type', 'start', 'amplitude'), 'season': ('type',),
                  'noise': ('type',), 'shape_correlation': ('label',),
                  'local_correlation': ('label', 'pair'), 'shape_cluster': ('cols',),
                  'local_cluster': ('cols', 'col_idx')}[ability]
        if not isinstance(attribute, dict) or any(key not in attribute for key in fields):
            raise ValueError('Incomplete structured annotation')
        if ability == 'season' and attribute['type'] != 'no periodic fluctuation':
            if not {'period', 'amplitude'} <= set(attribute):
                raise ValueError('Incomplete seasonal annotation')
        if ability == 'noise' and 'noisy' in attribute['type'] and 'std' not in attribute:
            raise ValueError('Missing noise standard deviation')
    reference = {'rule_ref': RULE_REF, 'ability_type': abilities[0],
                 'attribute': copy.deepcopy(attribute), 'cols': list(cols)}
    # JSON validity includes rejecting NaN/Infinity in private annotations.
    return json.dumps(reference, ensure_ascii=False, allow_nan=False, sort_keys=True)
