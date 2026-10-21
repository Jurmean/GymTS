"""Prepare, run, score and rescore a real native distribution forecast."""
import argparse
import copy
import json
from pathlib import Path
import sys

from gymts import GymTS
from gymts.contracts import digest, inline, utc_now
from gymts_timeseries.contracts import ALIGNMENT
from gymts_timeseries.experiments import scene
from gymts_timeseries.sources import publish_snapshot
from .contracts import METRICS, OUTCOME


def stable_outcome(draft, existing):
    """Reuse immutable availability; changed references require a new revision."""
    prior = existing.get((draft['outcome_id'], draft['revision']))
    value = copy.deepcopy(draft)
    value.pop('recorded_at', None)
    if prior is not None:
        previous = copy.deepcopy(prior)
        previous.pop('recorded_at', None)
        value['available_at'] = previous['available_at']
        if value != previous:
            raise ValueError('An existing reference revision has changed; publish a new explicit outcome revision')
    existing[(value['outcome_id'], value['revision'])] = copy.deepcopy(value)
    return value


def run(store, data_dir, python, model_dir, device='cpu', checkpoint=None, train_steps=0):
    root = Path(data_dir)
    source, references = json.loads((root/'public.json').read_text()), json.loads((root/'private-evaluation.json').read_text())
    with GymTS(store, integrations=('timeseries','chronos')) as gym:
        published = publish_snapshot(gym, source['samples'], source['dataset_revision'])
        params = {'python': python, 'model_dir': model_dir, 'device': device, 'timeout_seconds': 600}
        if checkpoint is None:
            from .worker import identity
            params['model_sha256'] = identity(model_dir)['sha256']
        train_view = None
        if train_steps:
            training = json.loads((root/'train.json').read_text())
            training_ref = gym.artifacts.save_json(training, 'gymts.json/1')
            train_view = {'view_id': 'chronos-ett-training', 'revision': training_ref['revision'], 'source_refs': [training_ref],
                          'selection': inline({'kind':'all','source_index':0}, 'gymts.selection/1'), 'as_of':None,'purpose':'prepare'}
            params['fit'] = {'steps':train_steps,'horizon':24,'context_length':128,'batch_size':16,'learning_rate':1e-5}
        candidate = {'adapter':'chronos2','version':'1.0.0','artifact':checkpoint,'params':params,'inherited_state':[]}
        cases = []
        # Training is exactly one Run. Subsequent evaluations explicitly reload
        # the resulting immutable checkpoint in fresh native worker processes.
        selected = published['sample_tokens'][:1] if train_steps else published['sample_tokens']
        for i, token in enumerate(selected):
            current_scene = scene(published['snapshot_ref'],published['dataset_revision'],token,'forecast.numeric','0.1.0')
            current_scene['task'] = {'plugin':'forecast-distribution','version':'1.0.0','params':{}}
            cases.append({'evaluation_case_id':f'ETTh1-window-{i:03d}', 'scene':current_scene,
                'execution':{'mode':'stream','start':{'mode':'reinitialize'},'scope':{'start':0,'end':1},
                    'feedback_until':None,'seed':7,'learning':{'prepare':'fit' if train_steps else 'load_only',
                    'online':'frozen','training_view':train_view,'training_targets':None,'alignment_schema_ref':None,
                    'allowed_feedback_sources':[]},'limits':{'max_inputs':1,'max_operations':1,'max_turns_per_case':1,'max_wall_time_s':1200}},
                'recording':{'store_ref':'local://records/default','inputs':'full','outputs':'full','artifacts':'reference',
                    'model_calls':'io','on_capture_failure':'fail_run','redaction_policy_ref':None,'extra_event_kinds':[]},
                'tags':{'dataset':'ETTh1','profile':'multivariate-calendar-h24','training_steps':train_steps}})
        scoring = {'scorer':{'adapter':'distribution-scorer','version':'1.0.0','params':{}},
            'outcomes':{'sources':[],'as_of':None},'alignment':{'schema_ref':ALIGNMENT,'keys':['dataset_revision','sample_token'],
                'matching':'exact','params':{},'duplicate_policy':'error'},'metrics':list(METRICS),
            'evidence_requirements':{'min_scored':1,'min_coverage':1,'overrides':{}},'missing_outcome_policy':'report_insufficient'}
        comparison = {'group_by':['evaluation_case_id'],'repetition_aggregation':'mean','aggregation':'macro_mean',
                      'baseline_method':'difference','gates':[]}
        spec = {'protocol_version':'gymts.evaluation/1','name':'Chronos-2 native distribution forecast','purpose':'development',
            'cases':cases,'candidates':[{'candidate_id':'chronos2','spec':candidate}],'baseline_id':None,
            'repetitions':{'count':1,'seeds':[7]},'scoring':scoring,'comparison':comparison,
            'failure_policy':{'partial_results':'include','invalid_result_policy':'report'}}
        initial = gym.autobench.evaluate(spec)
        plan = gym.artifacts.read_json(initial['plan_ref'])
        entries = gym.artifacts.read_json(initial['run_manifest_ref'])['entries']
        units = {u['unit_id']:u for u in plan['expected_units']}
        private = {r['sample_token']:r for r in references}
        existing_outcomes = {(r['outcome_id'], r['revision']):r for r in gym.records.read_outcomes()}
        selections, originals, checkpoints, failures = [], {}, [], []
        for entry in entries:
            run_id, unit = entry['run_id'], units[entry['unit_id']]
            if run_id is None:
                raise RuntimeError('Failed to allocate native Run')
            record = gym.records.get_run(run_id)
            if record['result']['status'] != 'succeeded':
                failures.append({'run_id':run_id,'errors':record['result']['errors']})
            originals[run_id] = digest(record['result'])
            for ref in record['result']['artifact_refs']:
                if ref['schema_ref'] == 'gymts.chronos/checkpoint-archive/1': checkpoints.append(ref)
            token = selected[int(unit['evaluation_case_id'].rsplit('-',1)[1])]
            gold = private[token]
            reference = gym.artifacts.save_json(gold, OUTCOME) if set(gold)=={'targets'} else gym.artifacts.save_json({'targets':gold['targets']},OUTCOME)
            draft = stable_outcome({'outcome_id':'chronos-ett-'+token,'revision':'1',
                'alignment_key':{'dataset_revision':published['dataset_revision'],'sample_token':token},
                'payload':inline({'targets':gold['targets']},OUTCOME),'event_time':0,'available_at':utc_now(),
                'recorded_at':None,'source_ref':reference,'supersedes_ref':None,'allowed_uses':['evaluation']}, existing_outcomes)
            gym.records.attach_outcomes(run_id,[draft])
            selections.append({'unit_id':unit['unit_id'],'evaluation_case_id':unit['evaluation_case_id'],
                'candidate_id':unit['candidate_id'],'repetition':unit['repetition'],'run_id':run_id,
                'unavailable_reason':None,'unit_spec_ref':unit['resolved_spec_ref'],'tags':copy.deepcopy(unit['tags'])})
        records = gym.records.read_outcomes({'run_ids':list(originals),'purpose':'evaluation'})
        ref = gym.artifacts.save_json(records,'gymts.outcome-records/1')
        view = {'view_id':'chronos-private-outcomes','revision':ref['revision'],'source_refs':[ref],
                'selection':inline({'kind':'all','source_index':0},'gymts.selection/1'),'as_of':None,'purpose':'evaluation'}
        score_spec = {'protocol_version':'gymts.score/1','name':'Chronos fixed-output independent score','purpose':'development',
            'runs':selections,'baseline_id':None,'scoring':copy.deepcopy(scoring),'comparison':comparison,
            'failure_policy':spec['failure_policy'],'previous_evaluation_id':initial['evaluation_id']}
        score_spec['scoring']['outcomes'] = {'sources':[view],'as_of':None}
        final = gym.autobench.score(score_spec)
        if any(digest(gym.records.get_run(r)['result'])!=v for r,v in originals.items()):
            raise RuntimeError('Scoring changed sealed execution evidence')
        return {'initial':initial,'report':final,'score_spec':score_spec,'run_ids':list(originals),
                'checkpoint_refs':checkpoints,'failures':failures}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command',required=True)
    p = commands.add_parser('prepare')
    p.add_argument('--output',required=True);p.add_argument('--source-url',required=True);p.add_argument('--source-revision',required=True)
    p.add_argument('--windows',type=int,default=16)
    p = commands.add_parser('run')
    p.add_argument('--store',required=True);p.add_argument('--data',required=True);p.add_argument('--python',required=True)
    p.add_argument('--model',required=True);p.add_argument('--device',choices=['cpu','cuda:0'],default='cpu')
    p.add_argument('--checkpoint');p.add_argument('--train-steps',type=int,default=0);p.add_argument('--output',required=True)
    p = commands.add_parser('rescore')
    p.add_argument('--store',required=True);p.add_argument('--result',required=True);p.add_argument('--output',required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        from .data import prepare_ett
        print(json.dumps(prepare_ett(args.output,source_url=args.source_url,source_revision=args.source_revision,windows=args.windows),indent=2))
    elif args.command == 'run':
        checkpoint = json.loads(Path(args.checkpoint).read_text()) if args.checkpoint else None
        result = run(args.store,args.data,args.python,args.model,args.device,checkpoint,args.train_steps)
        Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({'run_ids':result['run_ids'],'report_id':result['report']['evaluation_id'],'checkpoints':len(result['checkpoint_refs'])}))
        if result['failures'] or result['report']['status'] == 'failed':
            raise SystemExit(2)
    else:
        result = json.loads(Path(args.result).read_text())
        with GymTS(args.store,integrations=('timeseries','chronos')) as gym:
            report = gym.autobench.score(result['score_spec'])
        Path(args.output).write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'evaluation_id':report['evaluation_id'],'new_model_calls':0}))
        if report['status'] == 'failed':
            raise SystemExit(2)


if __name__ == '__main__':
    main()
