"""Independent choice/structured scoring, with unresolved inputs in the denominator."""
import json
from gymts.contracts import canonical_json
from gymts.plugin_support import fail, unpack
from .parsing import SUPPORTED_PARSER_REFS
from .structured import evaluate_structured


def _records(value):
    if isinstance(value,list):
        return value
    for key in ('records','results','outcomes','items'):
        if isinstance(value.get(key),list):
            return value[key]
    fail('schema_mismatch','TSQA view must contain a records list')


class TSQAReferenceScorer:
    def __init__(self,spec):
        pass

    def validate_scoring(self,scoring):
        alignment=scoring['alignment']
        if (alignment['matching']!='exact' or alignment['keys']!=['dataset_revision','sample_id']
                or alignment['duplicate_policy']!='error'):
            fail('unsupported_capability','TSQA requires exact unique dataset_revision/sample_id alignment')
        if any(metric not in ('accuracy','task_score','format_valid') for metric in scoring['metrics']):
            fail('unsupported_capability','Unsupported TSQA metric')

    def score(self,results,outcomes,context):
        services,scoring=context['services'],context['scoring']; self.validate_scoring(scoring)
        rows=_records(services.read_json(results['records_ref']))
        if len(rows)>1:
            fail('schema_mismatch','One TSQA evaluation unit must contain at most one result')
        def key(row):
            alignment=row['alignment_key']
            if set(alignment)!={'dataset_revision','sample_id'}:
                fail('schema_mismatch','TSQA alignment has an unexpected shape')
            return canonical_json(alignment)
        matched={}
        for outcome in _records(services.read_json(outcomes['records_ref'])):
            if 'evaluation' not in outcome.get('allowed_uses',[]):
                fail('permission_denied','TSQA reference is not authorized for evaluation')
            k=key(outcome)
            if k in matched:
                fail('conflict','Duplicate TSQA reference')
            matched[k]=outcome
        row=rows[0] if rows else None
        outcome=matched.get(key(row)) if row else None
        answer=unpack(row['payload'],services) if row else None
        gold=unpack(outcome['payload'],services) if outcome else None
        if answer and answer['parser_ref'] not in SUPPORTED_PARSER_REFS:
            fail('schema_mismatch','Unsupported TSQA response parser revision')
        metrics,diagnostics={},[]
        for metric in scoring['metrics']:
            counts={'eligible':1,'scored':0,'missing':0,'invalid':0,'excluded':0}
            value=reason=details=None
            # Unknown reference takes priority, including when an answer is invalid.
            # No reference is repaired or silently removed from planned coverage.
            if row is None:
                counts['missing']=1; reason='missing_result'
            elif metric!='format_valid' and (gold is None or gold['reference_status']!='known'):
                counts['missing']=1; reason='missing_reference' if gold is None else gold['reason'] or 'unknown_reference'
            elif metric!='format_valid' and gold.get('input_issue'):
                counts['missing']=1; reason=gold['input_issue']
            elif metric=='format_valid':
                counts['scored']=1; value=float(row['status']=='valid' and answer['parsed'] is not None)
            elif row['status']!='valid' or answer['parsed'] is None:
                counts['invalid']=1; reason=answer['reason'] or 'invalid_result'
            else:
                if metric=='task_score' and gold['reference_kind']=='structured':
                    value, details=evaluate_structured(answer['parsed']['answer'],json.loads(gold['reference_answer']))
                elif metric=='accuracy' and gold['reference_kind']!='structured':
                    value=float(answer['parsed']['answer']==gold['reference_answer'])
                else:
                    fail('unsupported_capability','Metric does not match the reference task kind')
                counts['scored']=1
            metrics[metric]={'value':value,'status':'ready' if value is not None else 'insufficient_evidence',
                'counts':counts,'reason':reason}
            diagnostics.append({'metric_id':metric,'result_id':row['result_id'] if row else None,
                'outcome_id':outcome['outcome_id'] if outcome else None,
                'outcome_revision':outcome['revision'] if outcome else None,'value':value,'reason':reason,
                'task_details':details})
        return {'metrics':metrics,'item_scores_ref':services.save_json({'records':diagnostics},'gymts.json/1'),
            'diagnostics_ref':None}
