import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from gymts.contracts import GymTSError
from gymts_chronos.contracts import validate_input, validate_prediction
from gymts_chronos.scoring import DistributionScorer, metrics
from gymts.plugin_support import payload
from gymts_chronos.contracts import OUTCOME, RESULT, PARSER
from gymts_chronos.candidate import checkpoint_bytes, unpack_checkpoint, training_data
from gymts_chronos.cli import stable_outcome


def example():
    return {'series':[{'name':'y','values':[1.,2.]},{'name':'calendar_hour','values':[0,1]}],
            'context':{'horizon':1,'targets':['y'],'quantiles':[.1,.5,.9],
                'timestamps':['2020-01-01T00:00:00','2020-01-01T01:00:00'],
                'future_timestamps':['2020-01-01T02:00:00'],'future_covariates':{'calendar_hour':[2]}}}


class Contracts(unittest.TestCase):
    def test_training_unpacks_real_view_and_rejects_evaluation_members(self):
        from gymts.storage.artifacts import ArtifactStore
        from gymts.contracts import inline
        with tempfile.TemporaryDirectory() as root:
            artifacts = ArtifactStore(root)
            data = {'usage':'training','split':'train','inputs':[{'target':[[1.,2.,3.]]}]}
            ref = artifacts.save_json(data, 'gymts.json/1')
            view = {'view_id':'train','revision':ref['revision'],'source_refs':[ref], 'as_of':None,
                    'purpose':'prepare','selection':inline({'kind':'all','source_index':0},'gymts.selection/1')}
            self.assertEqual(training_data(artifacts,view),data)
            with self.assertRaises(GymTSError):training_data(artifacts,dict(view,purpose='evaluation'))
            data['split']='test'
            view['source_refs']=[artifacts.save_json(data,'gymts.json/1')]
            with self.assertRaises(GymTSError):training_data(artifacts,view)

    def test_repeated_runs_reuse_immutable_outcome_availability(self):
        from gymts.storage.artifacts import ArtifactStore
        from gymts.storage.records import LocalExperimentRecords
        from gymts.contracts import inline
        with tempfile.TemporaryDirectory() as root:
            artifacts=ArtifactStore(Path(root)/'artifacts')
            records=LocalExperimentRecords(Path(root)/'records',artifacts)
            try:
                config=artifacts.save_json({},'gymts.experiment/1')
                for run_id in ('first','second'):
                    records.begin_run({'run_id':run_id,'resolved_spec_ref':config,'created_at':'2026-01-01T00:00:00Z'})
                draft={'outcome_id':'ett-y','revision':'1','alignment_key':{'sample_token':'y'},
                    'payload':inline({'targets':{'y':[3.]}},OUTCOME),'event_time':0,
                    'available_at':'2026-01-01T00:00:00Z','recorded_at':None,
                    'source_ref':artifacts.save_json({'targets':{'y':[3.]}},OUTCOME),
                    'supersedes_ref':None,'allowed_uses':['evaluation']}
                records.attach_outcomes('first',[draft])
                existing={(r['outcome_id'],r['revision']):r for r in records.read_outcomes()}
                repeated=stable_outcome(dict(draft,available_at='2026-01-02T00:00:00Z'),existing)
                records.attach_outcomes('second',[repeated])
                self.assertEqual(records.read_outcomes({'run_ids':['first']}), records.read_outcomes({'run_ids':['second']}))
                changed=copy.deepcopy(draft);changed['payload']['value']['targets']['y']=[4.]
                with self.assertRaises(ValueError):stable_outcome(changed,existing)
            finally:records.close()

    def test_independent_registration_never_imports_science(self):
        import sys
        from gymts import GymTS
        with tempfile.TemporaryDirectory() as root:
            with GymTS(root,integrations=('chronos',)):
                self.assertNotIn('torch',sys.modules)
                self.assertNotIn('chronos',sys.modules)

    def test_future_target_cannot_become_covariate(self):
        value = example();value['context']['future_covariates']['y']=[99.]
        with self.assertRaises(GymTSError): validate_input(value)

    def test_unobserved_calendar_assertion_is_rejected(self):
        value=example();value['context']['future_covariates']['calendar_hour']=[17]
        with self.assertRaises(GymTSError): validate_input(value)

    def test_irregular_time_is_rejected(self):
        value=example();value['context']['future_timestamps']=['2020-01-01T04:00:00']
        with self.assertRaises(GymTSError): validate_input(value)

    def test_multitarget_missing_horizon_is_invalid(self):
        context=example()['context']
        p={'targets':{'y':{'mean':[], 'quantiles':{'0.1':[0.],'0.5':[1.],'0.9':[3.]}}}}
        with self.assertRaises(ValueError):validate_prediction(p,context)

    def test_score_known_interval_and_pinball(self):
        p={'targets':{'y':{'mean':[2.], 'quantiles':{'0.1':[0.],'0.5':[2.],'0.9':[4.]}}}}
        values=metrics(p,{'y':[3.]},example()['context'])
        self.assertEqual(values['mae'],1.)
        self.assertEqual(values['coverage_80'],1.)
        self.assertEqual(values['width_80'],4.)
        self.assertAlmostEqual(values['pinball'],(.3+.5+.1)/3)

    def test_quantile_crossing_not_repaired(self):
        p={'targets':{'y':{'mean':[2.], 'quantiles':{'0.1':[5.],'0.5':[2.],'0.9':[4.]}}}}
        with self.assertRaises(ValueError):metrics(p,{'y':[3.]},example()['context'])

    def test_archive_rejects_traversal(self):
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w') as z:z.writestr('../escape','x')
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(GymTSError):unpack_checkpoint(b.getvalue(),d)

    def test_checkpoint_rejects_changed_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'model.safetensors').write_bytes(b'weights');(p/'config.json').write_text('{}')
            raw=checkpoint_bytes(p,{'steps':1})
            source=zipfile.ZipFile(io.BytesIO(raw));b=io.BytesIO()
            with zipfile.ZipFile(b,'w') as target:
                for name in source.namelist():target.writestr(name,b'altered' if name=='model/model.safetensors' else source.read(name))
            with tempfile.TemporaryDirectory() as out:
                with self.assertRaises(GymTSError):unpack_checkpoint(b.getvalue(),out)

    def test_scorer_consumes_framework_record_lists_and_keeps_denominator(self):
        prediction={'targets':{'y':{'mean':[2.], 'quantiles':{'0.1':[0.],'0.5':[2.],'0.9':[4.]}}}}
        key={'dataset_revision':'r1','sample_token':'a'*64}
        rows=[{'result_id':'result1','status':'valid','alignment_key':key,
               'payload':payload(RESULT,{'parsed':prediction,'parser_ref':PARSER,'context':example()['context']})}]
        gold=[{'alignment_key':key,'allowed_uses':['evaluation'],'payload':payload(OUTCOME,{'targets':{'y':[3.]}})}]
        class Services:
            def read_json(self, ref):return {'r':rows,'g':gold}[ref]
            def save_json(self,value,schema):return {'saved':True}
        scoring={'alignment':{'matching':'exact','keys':['dataset_revision','sample_token'],'duplicate_policy':'error'},'metrics':['mae']}
        scorer=DistributionScorer({'params':{}})
        result=scorer.score({'records_ref':'r'},{'records_ref':'g'},{'services':Services(),'scoring':scoring})
        self.assertEqual(result['metrics']['mae']['value'],1.)
        self.assertEqual(result['metrics']['mae']['counts']['eligible'],1)
        rows.clear()
        result=scorer.score({'records_ref':'r'},{'records_ref':'g'},{'services':Services(),'scoring':scoring})
        self.assertEqual(result['metrics']['mae']['counts']['missing'],1)
        self.assertEqual(result['metrics']['mae']['counts']['eligible'],1)


if __name__=='__main__':unittest.main()
