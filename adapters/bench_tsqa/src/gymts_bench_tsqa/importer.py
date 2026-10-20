"""Explicit, content-addressed import of the user's five evaluation-only sources.

Registration/discovery never reads an attachment or imports PyArrow. This module
is invoked explicitly to preserve complete public questions and separate targets.
"""
import collections
import hashlib
import importlib.resources
import io
import json
from pathlib import Path

from gymts.contracts import canonical_json
from gymts.plugin_support import fail
from .contracts import PUBLIC
from .parsing import PARSER_REF, PROJECTION_REF, decode_public, decode_target
from .registration import IMPORTER_REF, RESOLVER_REF

SOURCES = {
    'local/bedtime': ('bedtime.jsonl',394,'33184d62aa56bb84320d1083743ff429733fd1f9200a739a695c04fbf86c3a99'),
    'local/dataset-a-rlvr': ('dataset_a_rlvr.jsonl',411,'76250827aa9c7e37337048d682eb0bd966700265c3b6ee9720823c2b824da0f3'),
    'local/mcq2': ('mcq2.jsonl',100,'b67358a0cf2947584b5e7514678fd715957a775257f77ac808d588fa7643c66d'),
    'local/timemqa-full': ('timemqa_full.jsonl',17703,'958fe1cba75b573a5723f38ea80d82bfeb2d2f1ede377c0f8bf81983aca405f2'),
    'local/tsexam-mcq': ('tsexam_mcq.jsonl',746,'4bf0e416b8e66771686a0f12b167da3a8af9e5e453f5fb95665b0004b1f8f5c7'),
}
POLICY={'allowed_uses':['evaluation'],'training_allowed':False}


def _arrow_schema(private=False):
    import pyarrow as pa
    if private:
        return pa.schema([pa.field('sample_id',pa.string(),False),pa.field('reference_status',pa.string(),False),
            pa.field('reference_answer',pa.string()),pa.field('reference_kind',pa.string(),False),
            pa.field('reason',pa.string()),pa.field('raw_answer_json',pa.string(),False),
            pa.field('raw_attributes_json',pa.string(),False),pa.field('raw_private_metadata_json',pa.string(),False),
            pa.field('allowed_uses',pa.list_(pa.string()),False)])
    series=pa.struct([pa.field('name',pa.string(),False),pa.field('values',pa.list_(pa.float64()),False)])
    choice=pa.struct([pa.field('id',pa.string(),False),pa.field('text',pa.string(),False)])
    projection=pa.struct([pa.field('series_index',pa.int64(),False),pa.field('original_start',pa.int64(),False),
        pa.field('original_end',pa.int64(),False),pa.field('reference',pa.string(),False)])
    return pa.schema([pa.field('sample_id',pa.string(),False),pa.field('dataset_id',pa.string(),False),
        pa.field('source_row',pa.int64(),False),pa.field('task_kind',pa.string(),False),
        pa.field('question_original',pa.string(),False),pa.field('question',pa.string(),False),
        pa.field('series',pa.list_(series),False),pa.field('choices',pa.list_(choice),False),
        pa.field('attachment_projection',pa.list_(projection),False),pa.field('projection_ref',pa.string(),False),
        pa.field('context',pa.struct([pa.field('question_policy',pa.string(),False)]),False)])


def _parquet(rows,private=False):
    import pyarrow as pa
    import pyarrow.parquet as pq
    table=pa.Table.from_pylist(rows,schema=_arrow_schema(private))
    target=io.BytesIO()
    pq.write_table(table,target,compression='zstd',version='2.6',write_statistics=True,row_group_size=1024)
    # Verify exact public fields, list order and numbers after the actual codec.
    decoded=pq.read_table(io.BytesIO(target.getvalue())).to_pylist()
    if decoded!=rows:
        fail('artifact_integrity','Parquet encoding changed source question, observations or references')
    return target.getvalue()


def audit_rows(dataset_id,raw):
    public,targets=[],[]
    for index,line in enumerate(raw.decode('utf-8').splitlines()):
        if not line.strip():
            fail('invalid_dataset','Blank physical source lines would change row identities')
        row=json.loads(line)
        sample=decode_public(row,dataset_id,index)
        # IEEE754 columns must not silently change a source integer.
        if any(type(v) is int and int(float(v))!=v for item in sample['series'] for v in item['values']):
            fail('unsupported_capability','This importer cannot preserve an observation integer beyond float64 precision')
        public.append(sample); targets.append(decode_target(row,sample))
    groups=collections.defaultdict(list)
    for row,target in zip(public,targets):
        identity=hashlib.sha256(canonical_json({'question':row['question_original'],'series':row['series']})).hexdigest()
        groups[identity].append(target)
    duplicates=[items for items in groups.values() if len(items)>1]
    # Different raw reference representations are a review flag, not a proved
    # contradiction. They remain private and no rows are deduplicated.
    ambiguous=[items for items in duplicates if len({x['raw_answer_json'] for x in items})>1]
    quality={'dataset_id':dataset_id,'source_sha256':hashlib.sha256(raw).hexdigest(),'row_count':len(public),
        'task_kinds':dict(collections.Counter(row['task_kind'] for row in public)),
        'reference_status':dict(collections.Counter(row['reference_status'] for row in targets)),
        'unknown_reference_reasons':dict(collections.Counter(row['reason'] for row in targets if row['reference_status']=='unknown')),
        'duplicate_public_input_groups':len(duplicates),'additional_duplicate_rows':sum(len(g)-1 for g in duplicates),
        'different_raw_reference_groups':len(ambiguous),'rows_excluded':0,
        'unknown_reference_policy':'eligible_missing_no_answer_repair','split_origin':'user_declared_evaluation',
        'parser_ref':PARSER_REF,'projection_ref':PROJECTION_REF,
        'question_policy':'original question complete; only literal attachment markers projected reversibly',
        'license_status':'not_supplied','training_allowed':False}
    return public,targets,quality


def import_attachments(gym,attachment_dir,*,dataset_ids=None,alias='1.0.0'):
    """Publish all rows, private raw files/targets and fixed reusable definitions."""
    catalog=gym.environment_ts.datasets
    results=[]
    for dataset_id in dataset_ids or SOURCES:
        if dataset_id not in SOURCES:
            fail('invalid_config','Unknown attachment dataset ID')
        filename,count,expected=SOURCES[dataset_id]
        raw=(Path(attachment_dir)/filename).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=expected:
            fail('artifact_integrity','Attachment hash differs from the reviewed source: '+filename)
        public,targets,quality=audit_rows(dataset_id,raw)
        if len(public)!=count:
            fail('artifact_integrity','Attachment row count differs from the reviewed source')
        assets={}
        for key,body,media in (('raw',raw,'application/x-ndjson'),
                ('inputs',_parquet(public),'application/vnd.apache.parquet'),
                ('targets',_parquet(targets,True),'application/vnd.apache.parquet'),
                ('quality',canonical_json(quality),'application/json')):
            assets[key]=catalog.publish_asset(body,media_type=media)
        card=importlib.resources.files('gymts_bench_tsqa').joinpath('cards',dataset_id.split('/')[-1]+'.md').read_bytes()
        assets['card']=catalog.publish_asset(card,media_type='text/markdown')
        manifest={'protocol_version':'gymts.source-dataset/1','dataset_id':dataset_id,'config':'default','revision':None,
            'schema_ref':PUBLIC,'reader_ref':{'name':'gymts.parquet-reader','version':'1.0.0','origin_ref':None},
            'features':{'question':'complete source text','series':'ordered ragged float64 observations',
                'choices':'public choices only','projection':'reversible attachment offsets','private_fields':['answer','attributes','source_metadata']},
            'splits':{'test':{'row_count':count,'split_origin':'user_declared_evaluation','input_indices':[0],'target_indices':[0]}},
            'usage_policy':POLICY,'source_files':[{'name':filename,'asset_ref':assets['raw']}],
            'importer_ref':IMPORTER_REF,'inputs':[assets['inputs']],'series':[],'targets':[assets['targets']],
            'quality_report_ref':assets['quality'],'card_ref':assets['card']}
        manifest=catalog.register_dataset(manifest,aliases=(alias,))
        definition={'protocol_version':'gymts.autobench.benchmark/1','benchmark_id':dataset_id,'revision':None,
            'resolver_ref':RESOLVER_REF,'datasets':[{'dataset_id':dataset_id,'config':'default',
                'revision':manifest['revision'],'split':'test'}],
            'params':{'scope':'full','metrics':['accuracy','format_valid'],'parser_ref':PARSER_REF,
                'coverage_policy':'all_source_rows_eligible','question_policy':'complete-original-lossless-projection/1'},
            'card_ref':assets['card']}
        definition=gym.autobench.register_benchmark(definition,aliases=(alias,))
        results.append({'dataset_id':dataset_id,'dataset_revision':manifest['revision'],
            'benchmark_revision':definition['revision'],'row_count':count,'quality':quality,
            'assets':assets})
    return results
