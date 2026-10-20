"""Independent episode metrics reconstructed from sealed execution evidence."""
from gymts.contracts import canonical_json
from gymts.plugin_support import fail, unpack
from .contracts import NATIVE, RECEIPT

METRICS=('episode_return','episode_length','terminated','truncated','scope_limited')

class EpisodeScorer:
    def __init__(self,spec): pass

    def validate_scoring(self,scoring):
        if (scoring['alignment']['matching']!='exact' or
                scoring['alignment']['keys']!=['episode_id','step'] or
                scoring['alignment']['duplicate_policy']!='error'):
            fail('unsupported_capability','Interaction scoring requires unique exact episode/step alignment')

    def score(self,results,outcomes,context):
        services=context['services']; self.validate_scoring(context['scoring'])
        rows=services.read_json(results['records_ref'])
        events=services.read_json(results['event_snapshot_ref'])
        states=[]; operations=[]; receipts=[]; final_end=None
        for event in events:
            value=unpack(event['payload'],services)
            if event['kind']=='observation' and value.get('data'):
                native=value['data']['native']
                if native and native['schema_ref']==NATIVE:
                    states.append(unpack(native,services))
                    if value['status']=='end': final_end=value['end']
            elif event['kind']=='environment_operation': operations.append(value)
            elif event['kind']=='environment_receipt': receipts.append(value)
        reason=None
        if not states or states[0]['step']!=0 or states[0]['reward'] is not None:
            reason='missing_initial_state'
        elif len({state['episode_id'] for state in states})!=1:
            reason='episode_reset_or_identity_changed'
        elif [s['step'] for s in states]!=list(range(len(states))):
            reason='missing_or_duplicate_transition'
        elif len(operations)!=len(receipts) or len(states)!=len(receipts)+1 or len(rows)!=len(operations):
            reason='incomplete_action_transition_evidence'
        elif final_end is None:
            reason='episode_or_scope_not_closed'
        if reason is None:
            for i,(row,operation,receipt) in enumerate(zip(rows,operations,receipts)):
                body=unpack(row['payload'],services)
                receipt_body=unpack(receipt['payload'],services) if receipt.get('payload') else None
                if (row['status']!='valid' or row['alignment_key']!={'episode_id':states[i]['episode_id'],'step':i}
                        or canonical_json(body['state'])!=canonical_json(states[i])
                        or operation['name']!='act' or operation['output_id']!=row['output_id']
                        or canonical_json(unpack(operation['arguments'],services))!=canonical_json(body['action'])
                        or receipt['operation_id']!=operation['operation_id']
                        or receipt['request_id']!=operation['request_id'] or receipt['status']!='completed'
                        or receipt['payload']['schema_ref']!=RECEIPT
                        or receipt_body!={'step':i+1,'transition_available':True}):
                    reason='action_result_transition_mismatch'; break
                if states[i]['terminated'] or states[i]['truncated'] or states[i].get('backend_done',False):
                    reason='action_after_terminal'; break
        values={}
        reward_available=bool(states) and all(state['reward'] is not None for state in states[1:])
        cause_available=bool(states) and states[-1].get('end_cause')!='unclassified'
        if reason is None:
            values={'episode_return':sum(state['reward'] for state in states[1:]) if reward_available else None,
                'episode_length':len(receipts),'terminated':float(states[-1]['terminated']),
                'truncated':float(states[-1]['truncated']),
                'scope_limited':float(final_end['reason']=='read_scope_end')}
        metrics={}
        for metric in context['scoring']['metrics']:
            metric_reason=reason or ('reward_unavailable' if metric=='episode_return' and not reward_available else None)
            if metric_reason is None and metric in ('terminated','truncated') and not cause_available:
                metric_reason='termination_cause_unavailable'
            counts={'eligible':1,'scored':int(metric_reason is None),'missing':int(metric_reason is not None),'invalid':0,'excluded':0}
            metrics[metric]={'value':values.get(metric) if metric_reason is None else None,'status':'ready' if metric_reason is None else 'insufficient_evidence',
                'counts':counts,'reason':metric_reason}
        diagnostics={'episode_id':states[0]['episode_id'] if states else None,'reason':reason,
            'transition_rewards':[s['reward'] for s in states[1:]],'final_state':states[-1] if states else None,
            'operation_count':len(operations),'receipt_count':len(receipts),
            'reward_available':reward_available,
            'termination_cause_available':cause_available,
            'result_count':len(rows),'state_count':len(states),'event_snapshot_ref':results['event_snapshot_ref']}
        return {'metrics':metrics,'item_scores_ref':services.save_json(diagnostics,'gymts.json/1'),
            'diagnostics_ref':None}
