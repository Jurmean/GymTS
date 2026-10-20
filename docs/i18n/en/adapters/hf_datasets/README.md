# gymts-hf-datasets

This independently installed adapter prepares static Hugging Face datasets for
EnvironmentTS execution and native AutoBenchTS evaluation. GymTS core does not
import HF, download a dataset, understand its columns, or score a forecast.

There are three explicit preparation sources:

| Mode | Identity | Loading |
| --- | --- | --- |
| `hub` | Dataset repository, complete 40-character commit and exact files | `hf_hub_download` then the HF csv/json/parquet builder |
| `save_to_disk` | Local saved Dataset/DatasetDict, every original file hash | `datasets.load_from_disk` |
| `local_files` | Exact ordered local csv/json/parquet files, every file hash | `datasets.load_dataset` |

HF [documents the loading interfaces](https://huggingface.co/docs/datasets/loading)
and [save/load methods](https://huggingface.co/docs/datasets/package_reference/main_classes#datasets.Dataset.save_to_disk).
The adapter supports materialized one-dimensional numeric forecasting views;
it does not claim arbitrary HF modality support or an HF Hub implementation.
Remote code, wildcard files, floating revisions and implicit split slicing are
not accepted. Hub credentials are not accepted or recorded in this public-data
adapter. HF runtime dependencies are optional and loaded only in preparation.

Install core and this adapter separately:

```bash
python -m pip install ./gymts-0.5.0-py3-none-any.whl
python -m pip install './adapters/hf_datasets[runtime]'
```

The bundled real-data example uses the official
[Monash tourism_monthly test Parquet](https://huggingface.co/datasets/Monash-University/monash_tsf/tree/7bf79ee8270e340b6c5848b7b56d8e1c35305fb6/tourism_monthly/test)
at commit `7bf79ee8270e340b6c5848b7b56d8e1c35305fb6`. It explicitly selects source
rows 0, 1 and 2, takes their last 24 observations as evaluation references and
uses the preceding 48 as public context. This is a declared local evaluation
projection of that official split, not a claim to reproduce the complete
Monash evaluation protocol or achieve a model-quality threshold.

```bash
python adapters/hf_datasets/examples/hf_static.py \
  --work /tmp/gymts-hf-example --report /tmp/gymts-hf-example/report.json
```

The example executes a direct `EnvironmentTS.run`, then native
`AutoBenchTS.evaluate` over three source rows and two seeds. It independently
computes reference MAE, rescoring the same sealed Runs and checking that their
results and event traces remain unchanged. No model server or paid LLM is used.
The supplied last-value Candidate is only a transparent execution baseline;
other Candidates can register this adapter's public task/input/output protocol.
An Agent may call resource-preparation or experiment tools; this Environment
does not itself choose tools or make Agent decisions.

CLI preparation and calling use the same public SDK:

```bash
gymts-hf-datasets --store /tmp/hf-runs --data-home /tmp/hf-data freeze local/tourism-monthly \
  --source adapters/hf_datasets/examples/monash_source.json --series-column target \
  --horizon 24 --context-length 48 --indices 0 1 2 --alias 1.0.0 \
  --receipt /tmp/hf-freeze-receipt.json
gymts-hf-datasets --store /tmp/hf-runs --data-home /tmp/hf-data evaluate local/tourism-monthly \
  --revision 1.0.0 --direct-run --rescore
```

Python callers use `freeze_dataset`, `register_benchmark`, the ordinary
`gym.environment_ts.datasets.load_dataset`, and `gym.autobench.resolve_benchmark`.
The frozen output split is explicitly `test`, with `split_origin` retaining the
source split and the immutable recipe retaining every selected source row.
For an unsplit local saved `Dataset`, use `split: "data"`; a saved `DatasetDict`
must name an existing split. Local source JSON examples:

```json
{"mode":"save_to_disk","path":"/absolute/path/to/saved-dataset","split":"test"}
```

```json
{"mode":"local_files","format":"parquet","files":["/absolute/path/to/test.parquet"],"split":"test"}
```

All original bytes, hashes, HF version/features, selection, context length,
horizon and projection version are preserved in resource provenance. Original
rows can contain answers or other metadata; they are stored as source assets,
not exposed to the Candidate. Public rows include only the selected context,
declared horizon and sample identity. Held-out future values remain in separate
evaluation-only target assets. All resources created by this version prohibit
training/prepare/dataset_build. The private evaluator role resolves references;
runtime reader services cannot read them. This is a trusted-plugin API boundary,
not a Python process security sandbox.

Preparation is explicit resource management, before an experimental Run exists.
`freeze --receipt` writes a success/failure receipt. Once execution starts,
missing/corrupt snapshot failures are sealed by EnvironmentTS with Run evidence.
Planning does not import HF, open source files, read artifacts or create a Run.
After freezing, execution and rescoring require neither the original source
directory nor HF network access. Large streaming datasets, arbitrary structured
series columns and per-sample missing-value imputation need further explicit
adapters; this version rejects incompatible selected rows rather than dropping
or repairing them silently.

## License

GymTS-owned code in this package is licensed under the [MIT License](LICENSE).
Third-party libraries, upstream projects, datasets, model weights and services
retain their own licenses and terms; this package does not relicense them.
