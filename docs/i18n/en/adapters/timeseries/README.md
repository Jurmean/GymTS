# gymts-timeseries

An independent time-series domain contract and implementation package depending on `gymts>=0.5,<0.6`. It provides generic numeric sources, seven QA Tasks, and independent Scorers. **It contains no models and does not depend on ChatTS, LibraryTS, or RL adapters.** LibraryTS and model adapters may depend on these public contracts.

From the main repository root, install with `python -m pip install . ./adapters/timeseries`, then explicitly enable `GymTS(root, integrations=('timeseries',))`. Independent wheel/sdist installation also works without source paths or `PYTHONPATH`.

Public modules:

- `gymts_timeseries.contracts`: protocol `gymts.task/timeseries-qa/1`, source snapshot, TaskInput, CandidateOutput, TaskResult, Outcome and alignment schemas, plus numeric/shape validation.
- `gymts_timeseries.sources`: `publish_snapshot` publishes numeric JSON snapshots; `import_csv` fixes actual CSV bytes and public context.
- `gymts_timeseries.task`: `make_task_input`, seven-task schemas/versions/metrics, and strict parsing. Task parameters determine meaning and generate question and response_schema.
- `gymts_timeseries.experiments`: `scene` and `scoring` generate existing GymTS configurations; EnvironmentTS / AutoBenchTS still perform execution and formal evaluation.

Source samples are `{sample_token, series:[{name,values}], context, annotations}`. Generic sources allow `annotations={}` without preselecting a task; the same numeric sample can bind to `forecast.numeric` or `pattern.trend_direction`. Forecast length comes from explicitly public `context.horizon`. Sources may declare fixed benchmark tasks through `annotations.benchmark_task_id/benchmark_task_version`; changing such original tasks requires an explicit new view and independent references, not reuse of original gold.

TaskInput payload is `{task_id,task_version,question,series,context,response_schema}` without model messages, ChatTS placeholders, tokenizers, or model_input. Native requests are built only by the internal model codec.

Both source types share the same public numeric contract. `numeric-snapshot` reads JSON snapshots; `csv-numeric-snapshot` directly parses immutable long-form CSV with columns `sample_token,series_name,index,value`. Each series index increases continuously from 0, without interpolation, sorting repairs, or truncation. CSV context must be explicit in configuration and contributes to the dataset revision hash.

Example:

```python
from gymts import GymTS
from gymts_timeseries.sources import publish_snapshot
from gymts_timeseries.experiments import scene, scoring

with GymTS('/tmp/numeric-example', integrations=('timeseries',)) as gym:
    source = publish_snapshot(gym, [{
        'sample_token': 'a' * 64,
        'series': [{'name': 'Series 1', 'values': [1., 2., 3.]}],
        'context': {'horizon': 2}, 'annotations': {},
    }])
    task_scene = scene(source['snapshot_ref'], source['dataset_revision'],
                       'a' * 64, 'forecast.numeric', '0.2.0')
    scoring_spec = scoring('forecast.numeric', '0.2.0')
```

After choosing a model, put the scene into an ExperimentSpec or AutoBenchTS EvaluationSpec. Real Outcomes must be supplied separately as `{task_id,task_version,expected_output}` under `gymts.timeseries/qa-outcome/1`, aligned exactly through `dataset_revision/sample_token`. Missing references remain `insufficient_evidence`; scoring does not call models again. Forecast outputs are `{"forecast":[...]}`; trend outputs are `{"trend_direction":"increasing"}` (also allowing decreasing/stable).

This package extracts shared domain semantics from existing strict JSON, shape, and scoring implementations for seven QA tasks; historical ChatTS `/1` implementations remain in their original adapter. Tests use explicit numeric fixtures and test Candidates, not model-quality evidence. After installation, run `python -m unittest discover -s tests -v` at the sdist root.

`gym.plan(spec)` and `gym.validate(spec)` use only pure declarations and configuration compatibility checks: they load no JSON/CSV contents and construct no Source, Task, or model. Source bytes, sample count/series structure, public horizons, and benchmark constraints are checked during open/consume after Run start; such failures still retain sealed trajectories. Pure declarations are not a sandbox for external plugins; third-party providers must obey the no-I/O registration contract.

## License

GymTS-owned code in this package is licensed under the [MIT License](LICENSE).
Third-party libraries, upstream projects, datasets, model weights and services
retain their own licenses and terms; this package does not relicense them.
