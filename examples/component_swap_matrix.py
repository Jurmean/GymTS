#!/usr/bin/env python3
"""Run a real 2-source x 2-task x 2-LibraryTS-method replacement matrix.

Install GymTS, gymts-timeseries and gymts-libraryts first. The worker interpreter
must also have the adapter and the fixed NetmanAIOps/sktime source installed.
Only configurations change between combinations. No hosted model is called.
"""
import argparse
import copy
import csv
import json
from pathlib import Path
import sys
from uuid import uuid4


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def value(gym, payload):
    return payload['value'] if payload['storage'] == 'inline' else gym.artifacts.read_json(payload['artifact_ref'])


def evidence(gym, run_id):
    from gymts.contracts import digest
    record = gym.records.get_run(run_id)
    inputs = [value(gym, event['payload']) for event in record['events'] if event['kind'] == 'input']
    require(len(inputs) == 1, 'Each matrix unit must have one public TaskInput')
    public = value(gym, inputs[0]['payload'])
    require(not {'model_input', 'messages', 'tokenizer', 'ground_truth', 'expected_output'} & set(public),
            'The shared task payload must not contain model messages or evaluation truth')
    calls = [event for event in record['events'] if event['kind'] in ('model_call', 'tool_call')]
    return {'run_result_hash': digest(record['result']), 'execution_event_count': len(record['events']),
            'native_call_events': len(calls), 'task_input_hash': digest(public),
            'task_input': public, 'run_result': record['result']}


def evaluate_and_rescore(gym, spec, expected, truth_ref):
    """Use the existing AutoBenchTS plan, Run and immutable rescoring contracts."""
    from gymts.contracts import digest, inline, utc_now
    from gymts_timeseries.contracts import OUTCOME
    initial = gym.autobench.evaluate(spec)
    require(initial['status'] == 'completed', 'Initial AutoBenchTS evaluation did not complete')
    require(initial['verdict'] == 'insufficient_evidence', 'Unlabelled evaluation must report missing evidence')
    plan = gym.artifacts.read_json(initial['plan_ref'])
    manifest = gym.artifacts.read_json(initial['run_manifest_ref'])
    executions = {entry['unit_id']: entry for entry in manifest['entries']}
    before, selected, run_ids = {}, [], []
    case = spec['cases'][0]
    source = case['scene']['environment']['source']
    token = case['scene']['environment']['options']['sample_tokens'][0]
    task = case['scene']['task']['params']
    alignment = {'dataset_revision': source['revision'], 'sample_token': token}
    outcome = {'outcome_id': 'matrix-gold-' + digest({'alignment': alignment, 'task': task}),
        'revision': '1', 'alignment_key': alignment, 'payload': inline({**task, 'expected_output': expected}, OUTCOME),
        'event_time': 0, 'available_at': utc_now(), 'recorded_at': None, 'source_ref': truth_ref,
        'supersedes_ref': None, 'allowed_uses': ['evaluation']}
    for unit in plan['expected_units']:
        run_id = executions[unit['unit_id']]['run_id']
        require(bool(run_id), 'An expected unit has no Run; inspect the initial EvaluationReport')
        before[run_id] = evidence(gym, run_id)
        require(before[run_id]['run_result']['status'] == 'succeeded', 'A native method failed; original trace is retained')
        require(before[run_id]['native_call_events'] >= 2, 'Expected actual native model and tool-call evidence')
        gym.records.attach_outcomes(run_id, [outcome])
        run_ids.append(run_id)
        selected.append({'unit_id': unit['unit_id'], 'evaluation_case_id': unit['evaluation_case_id'],
            'candidate_id': unit['candidate_id'], 'repetition': unit['repetition'], 'run_id': run_id,
            'unavailable_reason': None, 'unit_spec_ref': unit['resolved_spec_ref'], 'tags': copy.deepcopy(unit['tags'])})
    cutoff = utc_now()
    outcomes = gym.records.read_outcomes({'run_ids': run_ids, 'outcomes_as_of': cutoff, 'purpose': 'evaluation'})
    outcome_ref = gym.artifacts.save_json(outcomes, 'gymts.outcome-records/1')
    view = {'view_id': 'matrix-outcomes-' + outcome_ref['revision'], 'revision': outcome_ref['revision'],
        'source_refs': [outcome_ref], 'selection': inline({'kind': 'all', 'source_index': 0}, 'gymts.selection/1'),
        'as_of': None, 'purpose': 'evaluation'}
    scoring = copy.deepcopy(spec['scoring'])
    scoring['outcomes'] = {'sources': [view], 'as_of': cutoff}
    score_spec = {'protocol_version': 'gymts.score/1', 'name': spec['name'] + ' fixed outputs',
        'purpose': spec['purpose'], 'runs': selected, 'baseline_id': spec['baseline_id'], 'scoring': scoring,
        'comparison': copy.deepcopy(spec['comparison']), 'failure_policy': copy.deepcopy(spec['failure_policy']),
        'previous_evaluation_id': initial['evaluation_id']}
    final = gym.autobench.score(score_spec)
    require(final['verdict'] == 'pass', 'The independently specified matrix gold/Gates did not pass')
    units = gym.artifacts.read_json(final['run_manifest_ref'])['entries']
    require([row['run_id'] for row in units] == run_ids, 'Rescoring changed the selected Runs')
    for run_id in run_ids:
        after = evidence(gym, run_id)
        for key in ('run_result_hash', 'execution_event_count', 'native_call_events', 'task_input_hash'):
            require(after[key] == before[run_id][key], 'Rescoring changed execution evidence: ' + key)
    return {'initial_report': initial, 'report': final, 'score_spec': score_spec, 'run_ids': run_ids,
            'evidence': before, 'rescoring_preserved_execution': True}


def run(root, repository, python):
    from gymts import GymTS
    from gymts.contracts import digest
    from gymts_timeseries.experiments import scene, scoring
    from gymts_timeseries.sources import import_csv, publish_snapshot
    root = Path(root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=False)
    values = [float(number) for number in range(12)]
    token = digest({'case': 'linear-window', 'values': values}).removeprefix('sha256:')
    sample = {'sample_token': token, 'series': [{'name': 'signal', 'values': values}],
              'context': {'horizon': 2}, 'annotations': {}}
    path = root / 'same-observations.csv'
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['sample_token', 'series_name', 'index', 'value'])
        writer.writeheader()
        writer.writerows({'sample_token': token, 'series_name': 'signal', 'index': i, 'value': v}
                         for i, v in enumerate(values))
    implementation = {'repository': str(Path(repository).expanduser().resolve()),
        'revision': '080f4c3c3695f239e328548bac7d7a3ef7aa9127', 'python': python}
    methods = [('naive-drift', 'naive', {'strategy': 'drift'}), ('polynomial', 'polynomial', {'degree': 1})]
    summary = {'status': 'running', 'scope': 'Independent component substitution on a known synthetic ramp; not a scientific model-quality benchmark',
               'store': str(root / 'records'), 'implementation': implementation, 'groups': []}
    summary_file = root / 'summary.json'
    try:
        with GymTS(root / 'records', integrations=('timeseries', 'libraryts')) as gym:
            numeric = publish_snapshot(gym, [sample])
            csv_source = import_csv(gym, path, context=sample['context'])
            sources = [('json', numeric['snapshot_ref'], numeric['dataset_revision'], 'numeric-snapshot', {}),
                       ('csv', csv_source['source_ref'], csv_source['dataset_revision'], 'csv-numeric-snapshot',
                        {'context': csv_source['context']})]
            truth_ref = gym.artifacts.save_json({'generator': 'linear-ramp', 'observed': values,
                'held_out': [12.0, 13.0], 'trend_direction': 'increasing', 'uses': ['evaluation']}, 'gymts.json/1')
            for source_id, reference, revision, source_adapter, options in sources:
                for task_id in ('forecast.numeric', 'pattern.trend_direction'):
                    expected = {'forecast': [12.0, 13.0]} if task_id == 'forecast.numeric' else {'trend_direction': 'increasing'}
                    metric, operator, threshold = ('mae', 'le', 1e-8) if task_id == 'forecast.numeric' else ('accuracy', 'ge', 1)
                    spec = {'protocol_version': 'gymts.evaluation/1', 'name': source_id + '/' + task_id,
                        'purpose': 'regression', 'cases': [{'evaluation_case_id': 'same-linear-window',
                            'scene': scene(reference, revision, token, task_id, '0.1.0',
                                           source_adapter=source_adapter, source_options=options),
                            'execution': {'mode': 'stream', 'start': {'mode': 'reinitialize'},
                                'scope': {'start': 0, 'end': 1}, 'feedback_until': None, 'seed': 7,
                                'learning': {'prepare': 'load_only', 'online': 'frozen', 'training_view': None,
                                    'training_targets': None, 'alignment_schema_ref': None, 'allowed_feedback_sources': []},
                                'limits': {'max_inputs': 1, 'max_operations': None, 'max_turns_per_case': 1, 'max_wall_time_s': 180}},
                            'recording': {'store_ref': 'local://records/default', 'inputs': 'full', 'outputs': 'full',
                                'artifacts': 'reference', 'model_calls': 'io', 'on_capture_failure': 'fail_run',
                                'redaction_policy_ref': None, 'extra_event_kinds': []},
                            'tags': {'source': source_id, 'task': task_id}}],
                        'candidates': [{'candidate_id': name, 'spec': {'adapter': 'libraryts-qa', 'version': '1.0.0',
                            'artifact': None, 'params': {'implementation': implementation, 'estimator': estimator,
                                'estimator_params': params}, 'inherited_state': []}} for name, estimator, params in methods],
                        'baseline_id': None, 'repetitions': {'count': 1, 'seeds': [7]},
                        'scoring': scoring(task_id, '0.1.0'),
                        'comparison': {'group_by': ['evaluation_case_id', 'tags.source', 'tags.task'],
                            'repetition_aggregation': 'mean', 'aggregation': 'macro_mean', 'baseline_method': 'difference',
                            'gates': [{'metric': metric, 'target': 'absolute', 'candidate_ids': None, 'for_metric': None,
                                       'operator': operator, 'threshold': threshold, 'scope': 'aggregate'}]},
                        'failure_policy': {'partial_results': 'include', 'invalid_result_policy': 'report'}}
                    group = evaluate_and_rescore(gym, spec, expected, truth_ref)
                    summary['groups'].append({'source': source_id, 'task': task_id, **group})
                    summary_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
            for task_id in ('forecast.numeric', 'pattern.trend_direction'):
                inputs = [row['task_input_hash'] for group in summary['groups'] if group['task'] == task_id
                          for row in group['evidence'].values()]
                require(len(inputs) == 4 and len(set(inputs)) == 1,
                        'Source/model replacement changed the shared task input for ' + task_id)
            summary.update(status='passed', combinations=8, source_replacement_inputs_equal=True,
                           task_replacement_reuses_same_observations=True,
                           model_replacement_preserves_public_inputs=True)
            summary['record_snapshot_ref'] = gym.records.snapshot(
                [run_id for group in summary['groups'] for run_id in group['run_ids']], {})['snapshot_ref']
            summary['summary_ref'] = gym.artifacts.save_json(summary, 'gymts.json/1')
    except BaseException as error:
        summary.update(status='failed', error={'type': type(error).__name__, 'message': str(error)})
        raise
    finally:
        summary_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    return {key: summary[key] for key in ('status', 'combinations', 'store', 'summary_ref', 'record_snapshot_ref')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='/tmp/gymts-component-swap-' + uuid4().hex)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--python', default=sys.executable, help='Installed LibraryTS scientific worker interpreter')
    args = parser.parse_args()
    print(json.dumps(run(args.root, args.repository, args.python), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
