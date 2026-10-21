#!/usr/bin/env python3
"""Audit exact uploaded bytes and deterministic reward parity; never call a model.

Run with GymTS and bench-tsqa installed, or PYTHONPATH=.:adapters/bench_tsqa/src.
The optional reference source is accepted only at its reviewed SHA-256. Its AST
is restricted to the 13 deterministic function definitions (no imports/main).
"""
import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from statistics import mean
from typing import List

from gymts.contracts import canonical_json
from gymts_bench_tsqa import chatts_rlvr_rules
from gymts_bench_tsqa.importer import SOURCES, audit_rows
from gymts_bench_tsqa.parsing import PARSER_REF, parse_response
from gymts_bench_tsqa.structured import EVALUATORS, RULE_REF, evaluate_structured

UPSTREAM_SHA='415e0e278a31769a9f6e522315b0c6fc92fe8c68a06b805e7d3ef17da03ee8ff'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parity_namespace(path):
    assert sha(path)==UPSTREAM_SHA, 'Unreviewed upstream reward source'
    names={'split_sentences','split_period_sentences','match_metric_name'} | {
        'evaluate_'+name for name in EVALUATORS}
    tree=ast.parse(path.read_text())
    tree.body=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in names]
    assert len(tree.body)==13
    namespace={'re':re,'List':List}
    exec(compile(tree,str(path),'exec'),namespace)
    return namespace


def identity(row,ability,attribute):
    return hashlib.sha256(canonical_json({'timeseries':row['timeseries'],'cols':row['cols'],
        'ability':ability.replace('-inductive',''),'attribute':attribute})).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-data-home',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--parity-source',type=Path)
    parser.add_argument('--official-dataset-a',type=Path)
    args=parser.parse_args()
    report={'parser_ref':PARSER_REF,'structured_rule_ref':RULE_REF,
        'model_calls':0,'training_calls':0,'source_store_read_only':True,
        'script_sha256':sha(__file__),'vendor_sha256':sha(chatts_rlvr_rules.__file__),
        'datasets':[],'input_review':[],'structured':{}}
    upstream=parity_namespace(args.parity_source) if args.parity_source else None
    if upstream:
        report['upstream_reward']={'path':str(args.parity_source),'sha256':UPSTREAM_SHA,
            'revision':'dc2dcb091f5268fb4c87b89584f2ac120a095e5e'}
    actual_identity=Counter(); abilities=Counter(); nonperfect=[]; checked=0
    negative_zero=0; reference_scores=[]
    for dataset_id,(filename,count,expected) in SOURCES.items():
        path=args.source_data_home/'objects/sha256'/expected[:2]/expected
        raw=path.read_bytes()
        assert sha(path)==expected
        public,targets,quality=audit_rows(dataset_id,raw)
        assert quality['row_count']==count
        report['datasets'].append(quality)
        for sample,target,line in zip(public,targets,raw.decode().splitlines()):
            row=json.loads(line)
            assert sample['question_original']==row['question']
            assert [s['values'] for s in sample['series']]==row['timeseries']
            assert not {'answer','attributes','ability_types','reference_answer'} & set(sample)
            if target['input_issue']:
                report['input_review'].append({'dataset_id':dataset_id,'source_row':sample['source_row'],
                    'reason':target['input_issue'],'reference_status':target['reference_status'],
                    'reference_answer':row['answer'],'visible_choice_ids':[v['id'] for v in sample['choices']],
                    'question_original':row['question']})
            if dataset_id!='local/dataset-a-rlvr':
                continue
            assert target['reference_status']=='known', target
            ref=json.loads(target['reference_answer']); ability=ref['ability_type']; abilities[ability]+=1
            actual_identity[identity(row,ability,ref['attribute'])]+=1
            score,detail=evaluate_structured(row['answer'],ref)
            reference_scores.append(score)
            if score!=1:
                nonperfect.append({'source_row':sample['source_row'],'ability':ability,'score':score,'detail':detail})
            # Compare pinned upstream behavior on gold, nonsense, and empty text.
            # The outer upstream reward maps response parser exceptions to zero.
            for answer in (row['answer'],'UNRESOLVED',''):
                ours,_=evaluate_structured(answer,ref)
                if answer=='UNRESOLVED' and ours==0:
                    negative_zero+=1
                if upstream:
                    import copy
                    try:
                        groups=upstream['evaluate_'+ability.replace('-','_')](answer,copy.deepcopy(ref['attribute']),ref['cols'])[:3]
                        means=[mean(g) for g in groups if g]
                        expected_score=float(mean(means)) if means else 0.0
                    except (IndexError,KeyError,TypeError,ValueError,ZeroDivisionError):
                        expected_score=0.0
                    assert abs(ours-expected_score)<1e-12, (sample['source_row'],ability,ours,expected_score)
                    checked+=1
            # Verify public response extraction separately from private grading.
            parsed,reason=parse_response('\\answer{'+row['answer']+'}',sample)
            assert reason is None and parsed is not None
    report['structured']={'rows':sum(abilities.values()),'abilities':dict(abilities),
        'parity_comparisons':checked,'parity_mismatches':0 if upstream else None,
        'negative_control_zero_rows':negative_zero,
        'reference_text_self_score_mean':mean(reference_scores),
        'reference_text_nonperfect':nonperfect,
        'self_score_mean_is_model_result':False}
    if args.official_dataset_a:
        official_raw=args.official_dataset_a.read_bytes()
        assert hashlib.md5(official_raw).hexdigest()=='1978d2ae5f2760ef944477fdcab223b2'
        original=json.loads(official_raw); official_identity=Counter()
        for row in original:
            for ability,attribute in zip(row['ability_types'],row['attributes']):
                official_identity[identity(row,ability,attribute)]+=1
        assert actual_identity==official_identity
        report['official_dataset_a']={'url':'https://zenodo.org/records/14349206',
            'md5':hashlib.md5(official_raw).hexdigest(),'sha256':hashlib.sha256(official_raw).hexdigest(),
            'compound_rows':len(original),'subquestions':sum(official_identity.values()),
            'exact_content_multiset_match':True,
            'matched_fields':['timeseries','cols','attributes','ability (without -inductive suffix)']}
    report['totals']={'source_rows':sum(q['row_count'] for q in report['datasets']),
        'references_read':sum(q['reference_status'].get('known',0) for q in report['datasets']),
        'input_review_rows':len(report['input_review']),
        'evaluable_reference_rows':sum(q['evaluable_reference_rows'] for q in report['datasets']),
        'rows_excluded':0}
    report['passed']=True
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'passed':True,'totals':report['totals'],'structured':report['structured']},ensure_ascii=False))


if __name__=='__main__':
    main()
