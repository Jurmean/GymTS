"""SDK integration and privacy/denominator regressions, independent of checkout data."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS, GymTSError
from gymts.contracts import canonical_json, digest, inline
from gymts_bench_tsqa.benchmark import first_choice_candidate
from gymts_bench_tsqa.contracts import OUTCOME, PUBLIC, RESULT
from gymts_bench_tsqa.importer import POLICY, _parquet, audit_rows
from gymts_bench_tsqa.parsing import PARSER_REF, decode_public, decode_target, parse_response
from gymts_bench_tsqa.registration import IMPORTER_REF, RESOLVER_REF
from gymts_bench_tsqa.scoring import TSQAReferenceScorer


def raw_row(answer='B'):
    return {'question':'Given observations <ts><ts/>, use ONLY the final two points.\nWhich change?\nA) rising\nB) falling\nYour answer must be in \\answer{A}.',
        'timeseries':[[8.25,3.5,-2.0]],'cols':['temperature'],'answer':answer,'attributes':[answer],
        'ability_types':['PRIVATE-ANNOTATION']}


def register_fixture(gym,rows,dataset_id='fixture/tsqa'):
    public,targets,quality=audit_rows(dataset_id,b'\n'.join(canonical_json(row) for row in rows))
    datasets=gym.environment_ts.datasets
    publish=lambda body:datasets.publish_asset(body,media_type='application/x-ndjson')
    inputs=publish(b'\n'.join(canonical_json(row) for row in public))
    target=publish(b'\n'.join(canonical_json(row) for row in targets))
    manifest=datasets.register_dataset({'protocol_version':'gymts.source-dataset/1','dataset_id':dataset_id,
        'config':'default','revision':None,'schema_ref':PUBLIC,
        'reader_ref':{'name':'gymts.jsonl-reader','version':'1.0.0','origin_ref':None},'features':{},
        'splits':{'test':{'row_count':len(rows),'split_origin':'user_declared_evaluation','input_indices':[0],'target_indices':[0]}},
        'usage_policy':POLICY,'source_files':[],'importer_ref':IMPORTER_REF,'inputs':[inputs],'series':[],
        'targets':[target],'quality_report_ref':None,'card_ref':None},aliases=('1.0.0',))
    definition=gym.autobench.register_benchmark({'protocol_version':'gymts.autobench.benchmark/1','benchmark_id':dataset_id,
        'revision':None,'resolver_ref':RESOLVER_REF,'datasets':[{'dataset_id':dataset_id,'config':'default',
            'revision':manifest['revision'],'split':'test'}],
        'params':{'scope':'full','metrics':['task_score' if dataset_id=='local/dataset-a-rlvr' else 'accuracy','format_valid'],'parser_ref':PARSER_REF,
            'coverage_policy':'all_source_rows_eligible','question_policy':'complete-original-lossless-projection/1'},'card_ref':None},aliases=('1.0.0',))
    return public,targets,manifest,definition


class TSQATests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        root=Path(self.tmp.name)
        self.gym=GymTS(root/'records',data_home=root/'data',cache_home=root/'cache',integrations=('bench-tsqa',))

    def tearDown(self):
        self.gym.close(); self.tmp.cleanup()

    def test_original_conditions_series_projection_and_gold_isolation(self):
        row=raw_row(); public=decode_public(row,'fixture/tsqa',0); target=decode_target(row,public)
        restored=public['question']
        for projection in public['attachment_projection']:
            restored=restored.replace(projection['reference'],'<ts><ts/>')
        self.assertEqual(row['question'],public['question_original']); self.assertEqual(restored,row['question'])
        self.assertIn('ONLY the final two points',public['question'])
        self.assertEqual(public['series'][0],{'name':'temperature','values':row['timeseries'][0]})
        self.assertEqual(target['reference_answer'],'B')
        self.assertFalse({'answer','attributes','ability_types','raw_answer_json'} & set(public))
        self.assertNotIn('PRIVATE-ANNOTATION',json.dumps(public))
        self.assertEqual(parse_response('\\answer{B}',public),({'answer':'B'},None))
        self.assertIsNone(parse_response('Reasoning \\answer{B}',public)[0])
        self.assertIsNone(parse_response('\\answer{B} \\answer{A}',public)[0])

    def test_unknown_reference_is_missing_even_when_answer_invalid(self):
        public=decode_public(raw_row('Z'),'fixture/tsqa',0)
        target=decode_target(raw_row('Z'),public)
        self.assertEqual(target['reference_status'],'unknown')
        row={'result_id':'r','status':'invalid','alignment_key':{'dataset_revision':'fixed','sample_id':public['sample_id']},
            'payload':inline({'raw_text':'ambiguous','parsed':None,'reason':'invalid_choice','parser_ref':'tsqa.single-answer/1'},RESULT)}
        gold={key:target[key] for key in ('reference_status','reference_answer','reference_kind','reason')}
        outcome={'outcome_id':'o','revision':'1','alignment_key':row['alignment_key'],'allowed_uses':['evaluation'],
            'payload':inline(gold,OUTCOME)}
        refs=[self.gym.artifacts.save_json(value,'gymts.json/1') for value in ([row],[outcome])]
        scoring={'metrics':['accuracy','format_valid'],'alignment':{'matching':'exact','keys':['dataset_revision','sample_id'],
            'duplicate_policy':'error'}}
        score=TSQAReferenceScorer({'params':{}}).score({'records_ref':refs[0]},{'records_ref':refs[1]},
            {'services':self.gym.artifacts,'scoring':scoring})
        self.assertEqual(score['metrics']['accuracy']['counts'],{'eligible':1,'scored':0,'missing':1,'invalid':0,'excluded':0})
        self.assertEqual(score['metrics']['format_valid']['value'],0)
        empty=self.gym.artifacts.save_json([],'gymts.json/1')
        missing=TSQAReferenceScorer({'params':{}}).score({'records_ref':empty},{'records_ref':refs[1]},
            {'services':self.gym.artifacts,'scoring':scoring})
        self.assertEqual(missing['metrics']['accuracy']['reason'],'missing_result')
        self.assertEqual(missing['metrics']['accuracy']['counts']['eligible'],1)
        with self.assertRaises(GymTSError):
            self.gym.schemas.validate(OUTCOME,{'reference_status':'known','reference_answer':None,
                'reference_kind':'mcq_label','reason':None})

    def test_public_catalog_eval_only_and_full_native_evaluation(self):
        public,targets,manifest,definition=register_fixture(self.gym,[raw_row('A'),raw_row('B')])
        dataset=self.gym.environment_ts.datasets.load_dataset('fixture/tsqa',revision='1.0.0')
        self.assertEqual(len(dataset),2); self.assertEqual(dataset.sample_ids(),[row['sample_id'] for row in public])
        self.assertEqual(dataset[0]['question_original'],raw_row()['question'])
        self.assertFalse({'targets','source_files'} & set(dataset.info))
        with self.assertRaises(GymTSError) as denied:
            self.gym.environment_ts.datasets.load_dataset('fixture/tsqa',revision='1.0.0',purpose='training')
        self.assertEqual(denied.exception.code,'permission_denied')
        spec=self.gym.autobench.resolve_benchmark('fixture/tsqa',revision='1.0.0',candidates=[first_choice_candidate()])
        self.assertEqual(len(spec['cases']),2)
        self.assertEqual(spec['cases'][0]['scene']['environment']['options']['row_count'],1)
        # Pure planning cannot construct an environment or dereference CAS data.
        from gymts_bench_tsqa.environment import TSQASnapshotEnvironment
        experiment={'protocol_version':'gymts.experiment/1','name':'pure fixture',
            'scene':spec['cases'][0]['scene'],'candidate':spec['candidates'][0]['spec'],
            'execution':spec['cases'][0]['execution'],'recording':spec['cases'][0]['recording']}
        with patch.object(TSQASnapshotEnvironment,'__init__',side_effect=AssertionError('constructed during planning')):
            self.gym.plan(experiment)
        report=self.gym.autobench.evaluate(spec)
        self.assertEqual(report['status'],'completed'); self.assertEqual(report['verdict'],'pass')
        self.assertEqual(report['coverage']['expected_units'],2)
        run_manifest=self.gym.artifacts.read_json(report['run_manifest_ref'])
        run_ids=[row['run_id'] for row in run_manifest['entries']]
        self.assertEqual(len(run_ids),2)
        for run_id in run_ids:
            record=self.gym.records.get_run(run_id)
            self.assertEqual(record['result']['status'],'succeeded')
            self.assertFalse([event for event in record['events'] if event['kind'] in ('model_call','tool_call')])
            for event in record['events']:
                if event['kind']=='input':
                    value=event['payload']['value']; model_input=value['payload']['value']
                    self.assertFalse({'reference_answer','raw_answer_json','answer','attributes'} & set(model_input))

    def test_parquet_preserves_ragged_public_and_private_separation(self):
        try:
            import pyarrow.parquet as pq
        except ImportError:
            self.skipTest('optional PyArrow not installed')
        import io
        public,targets,_=audit_rows('fixture/tsqa',canonical_json(raw_row()))
        restored=pq.read_table(io.BytesIO(_parquet(public))).to_pylist()
        self.assertEqual(restored,public)
        private=pq.read_table(io.BytesIO(_parquet(targets,True))).to_pylist()
        self.assertEqual(private,targets)
        self.assertNotIn('raw_answer_json',pq.read_table(io.BytesIO(_parquet(public))).schema.names)

    def test_definition_rejects_unsupported_policies_before_reading_resources(self):
        from gymts_bench_tsqa.benchmark import TSQABenchmarkResolver
        params={'scope':'full','metrics':['accuracy','format_valid'],'parser_ref':PARSER_REF,
            'coverage_policy':'all_source_rows_eligible','question_policy':'complete-original-lossless-projection/1'}
        variations=[{'coverage_policy':'exclude_unknown_reference'},
            {'question_policy':'rewrite_canonical_question'}, {'selection':{'indices':[0]}},
            {'scorer':{'adapter':'other-scorer'}}, {'metrics':['format_valid']}, {'metrics':[{},'accuracy']}]
        for change in variations:
            with self.subTest(change=change):
                definition={'params':dict(params,**change),'datasets':[{}]}
                # None has no resource methods: a policy error must be rejected
                # before the resolver can load data, gold or CAS artifacts.
                with self.assertRaises(GymTSError) as error:
                    TSQABenchmarkResolver().resolve(definition,None,[first_choice_candidate()],'regression',None)
                self.assertEqual(error.exception.code,'unsupported_capability')
        incomplete=copy.deepcopy(params); incomplete.pop('question_policy')
        with self.assertRaises(GymTSError) as error:
            TSQABenchmarkResolver().resolve({'params':incomplete,'datasets':[{}]},None,[],'regression',None)
        self.assertEqual(error.exception.code,'unsupported_capability')

    def test_model_codecs_keep_complete_public_question_and_full_values(self):
        from gymts_bench_tsqa.candidate import TSQAHTTPCandidate
        public=decode_public(raw_row(),'fixture/tsqa',0)
        for dialect in TSQAHTTPCandidate.DIALECTS:
            model=TSQAHTTPCandidate({'params':{'base_url':'http://127.0.0.1:12345',
                'model':'explicit-local-model','model_revision':'fixed-weights-digest','dialect':dialect}})
            wire=model._wire(public)
            self.assertIn('ONLY the final two points',wire['messages'][0]['content'])
            self.assertNotIn('PRIVATE-ANNOTATION',json.dumps(wire))
            if dialect=='chatts-native':
                self.assertEqual(wire['messages'][0]['content'],public['question_original'])
                self.assertEqual(wire['timeseries'],raw_row()['timeseries'])
            else:
                text=wire['messages'][0]['content']
                self.assertTrue(text.startswith(public['question']))
                attachment=json.loads(text.split('Referenced time-series observations (JSON):\n')[1])
                self.assertEqual(attachment[0]['values'],raw_row()['timeseries'][0])
                self.assertEqual(attachment[0]['name'],'temperature')

    def test_mcq2_question_number_is_not_choice_index(self):
        row={'question':'Time series <ts><ts/>\nPlease choose from: rising.; falling.; stable.; unknown.\nPlease directly output your choice.',
            'timeseries':[[1,2,3]],'cols':['signal'],'answer':'1. falling..','attributes':['1. falling..']}
        public=decode_public(row,'fixture/mcq2',0)
        self.assertEqual(public['task_kind'],'text_choice')
        self.assertEqual(decode_target(row,public)['reference_answer'],'choice_2')
        self.assertEqual(parse_response('falling.',public),({'answer':'choice_2'},None))
        self.assertIsNone(parse_response('1',public)[0])


if __name__=='__main__':
    unittest.main()
