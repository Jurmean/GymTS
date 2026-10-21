"""Regressions for structured rules, evidence gaps and versioned old outputs."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from gymts import GymTS
from gymts.contracts import canonical_json, inline
from gymts_bench_tsqa.contracts import OUTCOME, RESULT
from gymts_bench_tsqa.importer import audit_rows
from gymts_bench_tsqa.parsing import PARSER_REF, decode_public, decode_target, parse_response
from gymts_bench_tsqa.scoring import TSQAReferenceScorer
from gymts_bench_tsqa.structured import RULE_REF, evaluate_structured
from test_bench_tsqa import raw_row, register_fixture


def structured_row():
    return {'question': 'Series <ts><ts/>: describe its noise characteristics.',
            'timeseries': [[1, 2, 1]], 'cols': ['signal'],
            'answer': 'noisy, the overall noise standard deviation is around 2.0.',
            'attributes': [{'type': 'noisy', 'std': 2.0}], 'ability_types': ['noise']}


class StructuredTests(unittest.TestCase):
    def test_structured_labels_do_not_require_a_prose_answer(self):
        row=structured_row(); row['answer']=None
        public=decode_public(row,'local/dataset-a-rlvr',0)
        target=decode_target(row,public)
        self.assertEqual(target['reference_status'],'known')
        self.assertEqual(json.loads(target['reference_answer'])['attribute'],row['attributes'][0])

    def test_structured_reference_and_soft_score_are_private_and_not_exact_text(self):
        row=structured_row(); public=decode_public(row,'local/dataset-a-rlvr',0)
        target=decode_target(row,public)
        self.assertEqual(public['task_kind'],'structured')
        self.assertEqual(target['reference_status'],'known')
        self.assertNotIn('std',canonical_json(public).decode())
        reference=json.loads(target['reference_answer'])
        score,groups=evaluate_structured('noisy, standard deviation is around 1.0.',reference)
        self.assertEqual(score,.75)  # category 1; numeric 0.5; mean 0.75
        self.assertEqual(groups['numeric'],[.5])
        self.assertEqual(evaluate_structured('almost no noise',reference)[0],0)
        parsed,_=parse_response('<think>analysis</think><answer>\\answer{noisy, std 2.0}</answer>',public)
        self.assertEqual(parsed['answer'],'noisy, std 2.0')

    def test_local_rule_does_not_mutate_private_labels(self):
        ref={'rule_ref':RULE_REF,'ability_type':'local','cols':['signal'],
             'attribute':[{'type':'spike','position':10,'amplitude':2}]}
        original=copy.deepcopy(ref)
        self.assertEqual(evaluate_structured('spike, position 10, amplitude 2',ref)[0],1)
        self.assertEqual(ref,original)

    def test_unsupported_reasoning_judge_is_not_claimed_supported(self):
        row=structured_row(); row['ability_types']=['deductive']; row['attributes']=['Explain the mechanism.']
        public=decode_public(row,'local/dataset-a-rlvr',0)
        target=decode_target(row,public)
        self.assertEqual(target['reference_status'],'unknown')
        self.assertIn('separate judge',target['reason'])

    def test_reference_present_but_missing_options_remains_input_review(self):
        row=raw_row('C')
        row['question']='Series <ts><ts/>: which section?\nYour answer should be only a choice with upper letter: A/B/C/D.'
        public,target,quality=audit_rows('local/timemqa-full',canonical_json(row))
        self.assertEqual(target[0]['reference_status'],'known')
        self.assertEqual(target[0]['reference_answer'],'C')
        self.assertEqual(target[0]['input_issue'],'public_choice_text_unresolved')
        self.assertEqual(public[0]['choices'],[])  # no fabricated option text
        self.assertEqual(quality['input_review_rows'],1)
        self.assertEqual(quality['evaluable_reference_rows'],0)
        self.assertEqual(parse_response('C',public[0]),({'answer':'C'},None))

    def test_label_outside_visible_options_is_not_repaired(self):
        row=raw_row('C'); row['question']+='\nYour answer should be only a choice with upper letter: A/B/C/D.'
        public=decode_public(row,'local/timemqa-full',0); target=decode_target(row,public)
        self.assertEqual(target['reference_answer'],'C')
        self.assertEqual(target['input_issue'],'reference_outside_visible_choices')


class StructuredSDKTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        root=Path(self.tmp.name)
        self.gym=GymTS(root/'records',data_home=root/'data',cache_home=root/'cache',integrations=('bench-tsqa',))

    def tearDown(self):
        self.gym.close(); self.tmp.cleanup()

    def test_native_structured_metric_and_original_run_rescore(self):
        _,targets,_,_=register_fixture(self.gym,[structured_row()],'local/dataset-a-rlvr')
        from gymts_bench_tsqa.benchmark import first_choice_candidate
        spec=self.gym.autobench.resolve_benchmark('local/dataset-a-rlvr',revision='1.0.0',candidates=[first_choice_candidate()])
        self.assertEqual(spec['scoring']['metrics'],['task_score','format_valid'])
        native=self.gym.autobench.evaluate(spec)
        self.assertEqual(native['status'],'completed')
        self.assertEqual(native['coverage']['expected_units'],1)
        # Score a saved result directly with the same native scorer/view API.
        target=targets[0]
        row={'result_id':'r','status':'valid','alignment_key':{'dataset_revision':'fixed','sample_id':target['sample_id']},
             'payload':inline({'raw_text':'noisy, std 1.0','parsed':{'answer':'noisy, std 1.0'},
                 'reason':None,'parser_ref':PARSER_REF},RESULT)}
        gold={k:target[k] for k in ('reference_status','reference_answer','reference_kind','reason','input_issue')}
        outcome={'outcome_id':'o','revision':'1','alignment_key':row['alignment_key'],'allowed_uses':['evaluation'],
                 'payload':inline(gold,OUTCOME)}
        refs=[self.gym.artifacts.save_json(v,'gymts.json/1') for v in ([row],[outcome])]
        scoring={'metrics':['task_score','format_valid'],'alignment':{'matching':'exact',
                 'keys':['dataset_revision','sample_id'],'duplicate_policy':'error'}}
        scorer=TSQAReferenceScorer({'params':{}})
        for _ in range(2):
            result=scorer.score({'records_ref':refs[0]},{'records_ref':refs[1]},
                                {'services':self.gym.artifacts,'scoring':scoring})
            self.assertEqual(result['metrics']['task_score']['value'],.75)
            self.assertEqual(result['metrics']['task_score']['counts']['scored'],1)
        self.assertEqual(self.gym.artifacts.read_json(refs[0]),[row])

    def test_input_issue_keeps_planned_denominator_and_missing_evidence(self):
        row=raw_row('C'); row['question']+='\nYour answer should be only a choice with upper letter: A/B/C/D.'
        register_fixture(self.gym,[row])
        from gymts_bench_tsqa.benchmark import first_choice_candidate
        spec=self.gym.autobench.resolve_benchmark('fixture/tsqa',revision='1.0.0',candidates=[first_choice_candidate()])
        report=self.gym.autobench.evaluate(spec)
        self.assertEqual(report['coverage']['expected_units'],1)
        aggregate=next(m for m in report['metrics'] if m['level']=='aggregate' and m['metric_id']=='accuracy')
        self.assertEqual(aggregate['result']['counts']['eligible'],1)
        self.assertEqual(aggregate['result']['counts']['missing'],1)
        self.assertIsNone(aggregate['result']['value'])


if __name__=='__main__':
    unittest.main()
