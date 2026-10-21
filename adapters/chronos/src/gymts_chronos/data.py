"""Explicit source preparation: original ETT bytes, chronological split, no labels in inputs."""
import csv
from datetime import datetime, timedelta
import hashlib
import io
import json
from pathlib import Path
import urllib.request

from gymts.contracts import digest
from .contracts import validate_input

ETT_REPOSITORY = 'https://github.com/zhouhaoyi/ETDataset'
ETT_REVISION = '1d16c8f4f943005d613b5bc962e9eeb06058cf07'
ETT_SHA256 = 'f18de3ad269cef59bb07b5438d79bb3042d3be49bdeecf01c1cd6d29695ee066'


def prepare_ett(output, *, source_url, source_revision, windows=16, horizon=24, lookback=128):
    if type(windows) is not int or not 1 <= windows <= 120 or horizon != 24 or lookback != 128:
        raise ValueError('Delivered ETTh1 profile uses 1..120 test windows, h24, context128')
    if source_revision != ETT_REVISION or source_url != (
            'https://raw.githubusercontent.com/zhouhaoyi/ETDataset/'+ETT_REVISION+'/ETT-small/ETTh1.csv'):
        raise ValueError('This delivered profile requires its fixed official ETTh1 source')
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    raw_path = root/'ETTh1.csv'
    if not raw_path.exists():
        with urllib.request.urlopen(source_url, timeout=60) as r:
            raw = r.read(10_000_001)
        if len(raw) > 10_000_000:
            raise ValueError('ETT source exceeds expected CSV size')
        raw_path.write_bytes(raw)
    raw = raw_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ETT_SHA256:
        raise ValueError('Cached ETTh1 bytes differ from the fixed official dataset')
    rows = list(csv.DictReader(io.StringIO(raw.decode())))
    if len(rows) < 14400 or set(rows[0]) != {'date', 'HUFL', 'HULL', 'MUFL', 'MULL', 'LUFL', 'LULL', 'OT'}:
        raise ValueError('Unexpected official ETTh1 columns or length')
    targets = ['OT', 'HULL']
    names = ['OT','HULL','HUFL','MUFL','MULL','LUFL','LULL','calendar_hour','calendar_weekday']
    timestamps = [datetime.fromisoformat(r['date']).isoformat() for r in rows]
    if any(datetime.fromisoformat(b)-datetime.fromisoformat(a) != timedelta(hours=1) for a,b in zip(timestamps,timestamps[1:])):
        raise ValueError('ETTh1 timestamps are not one hourly grid')
    def column(name, start, end):
        if name.startswith('calendar_'):
            dt = [datetime.fromisoformat(t) for t in timestamps[start:end]]
            return [t.hour if name == 'calendar_hour' else t.weekday() for t in dt]
        return [float(r[name]) for r in rows[start:end]]
    samples, references = [], []
    origin = {'repository': ETT_REPOSITORY, 'revision': source_revision, 'source_url': source_url,
              'source_sha256': hashlib.sha256(raw).hexdigest(), 'profile': 'ETTh1-gymts-h24-multivariate-v1',
              'split_ranges': {'train': [0,8640], 'validation': [8640,11520], 'test': [11520,14400]},
              'selected_test_windows': windows, 'row_count': len(rows), 'targets': targets,
              'calendar_semantics': 'derived from source naive timestamp grid; available at every origin'}
    for offset in range(windows):
        index = 11520+offset*horizon
        context = {'horizon': horizon, 'targets': targets, 'quantiles': [0.1,0.5,0.9],
                   'timestamps': timestamps[index-lookback:index], 'future_timestamps': timestamps[index:index+horizon],
                   'future_covariates': {n: column(n,index,index+horizon) for n in names if n.startswith('calendar_')}}
        value = validate_input({'series': [{'name': n, 'values': column(n,index-lookback,index)} for n in names], 'context': context})
        token = digest({'source': origin['source_sha256'], 'origin': index, 'input': value}).removeprefix('sha256:')
        samples.append(dict(value, sample_token=token, annotations={'source_row': index, 'split': 'test'}))
        references.append({'sample_token': token, 'targets': {n: column(n,index,index+horizon) for n in targets}})
    train = {'usage': 'training', 'split': 'train', 'provenance': origin,
             'inputs': [{'target': [column(n,0,8640) for n in targets],
                         'past_covariates': {n: column(n,0,8640) for n in names if n not in targets},
                         'future_covariates': {'calendar_hour': [], 'calendar_weekday': []}}]}
    # Training uses future-known column names, not test values. Chronos cuts its
    # supervised targets from this authorized historical train range itself.
    public = {'dataset_revision': digest(origin).removeprefix('sha256:'), 'samples': samples, 'provenance': origin}
    for name, value in [('public.json',public),('private-evaluation.json',references),('train.json',train)]:
        (root/name).write_text(json.dumps(value,allow_nan=False)+'\n')
    return origin
