# Four real sources, one GymTS data API

This independently installed example composes existing adapters against a frozen
GymTS core. **Core owns source registration, persistent datasets, provenance and
portable capture.** This package supplies only the source-specific recipe,
numerical projection and example configuration. It introduces no second catalog,
executor or evaluator and does not bundle an upstream project's algorithms.

| Kind | Genuine implementation | Task / Candidate / independent score |
| --- | --- | --- |
| `static` | AirPassengers, loaded by the fixed LibraryTS fork | Neutral forecast Task, real native NaiveForecaster drift fit, private-holdout MAE/RMSE |
| `synthetic` | ChatTS's actual numerical generator, seed 27 | Same replaceable forecast components; 32 public observations and eight private future values |
| `simulation` | Gymnasium FrozenLake, deterministic map and reset seed 19 | Existing interaction components, six native actions, independently scored native terminal return |
| `live_testbed` | Genuine Prometheus scraping a local exporter | Existing forecast components, independent declared exporter reference; service stops before scoring |

The five uploaded benchmark files are not used. These four small engineering
examples have evaluation-only references and do not authorize model training.
Simple baselines establish execution, storage and scoring behavior; they do not
establish model quality or autonomous Agent tool selection. The Prometheus example
also makes no claim of causal online forecasting.

## Install independently

Use a complete GymTS checkout to build the core and the needed independent
packages. Keep the chosen core wheel unchanged throughout acceptance.

```bash
python -m build --wheel --outdir /tmp/four-data-wheels .
python -m build --wheel --outdir /tmp/four-data-wheels adapters/timeseries
python -m build --wheel --outdir /tmp/four-data-wheels adapters/libraryts
python -m build --wheel --outdir /tmp/four-data-wheels adapters/interaction
python -m build --wheel --outdir /tmp/four-data-wheels adapters/gymnasium
python -m build --wheel --outdir /tmp/four-data-wheels adapters/prometheus
python -m build --wheel --outdir /tmp/four-data-wheels examples/data_organization
python3.11 -m venv /tmp/four-data-runtime
/tmp/four-data-runtime/bin/python -m pip install \
  numpy scipy pandas scikit-base scikit-learn joblib packaging \
  gymnasium==1.2.1 pyyaml tqdm
/tmp/four-data-runtime/bin/python -m pip install --no-deps /tmp/four-data-wheels/*.whl
```

Prepare the external projects and a real Prometheus binary separately. LibraryTS
uses the user-selected [NetmanAIOps/sktime](https://github.com/NetmanAIOps/sktime)
fork, not a replacement PyPI sktime. Install the pinned checkout into the declared
scientific interpreter:

```bash
git clone https://github.com/NetmanAIOps/sktime /tmp/four-data-libraryts
git -C /tmp/four-data-libraryts checkout 080f4c3c3695f239e328548bac7d7a3ef7aa9127
/tmp/four-data-runtime/bin/python -m pip install --no-deps -e /tmp/four-data-libraryts
```

Supply an actual [ChatTS](https://github.com/NetManAIOps/ChatTS) checkout containing
`chatts/ts_generator/generate.py` and `config/datagen_config.yaml`. The example
calls its original `generate_random_attributes` and `generate_time_series`, records
the Git revision and generator/config hashes, and does not reimplement them.
A separate ChatTS interpreter may be supplied if its dependencies require one.
The Prometheus integration has been exercised with the real 3.15.0 Linux binary;
provide an explicit local binary path rather than a production endpoint.

## Run outside the source checkout

Choose a new POSIX working directory. No GPU or paid API is used.

```bash
cd /tmp
/tmp/four-data-runtime/bin/python -I -B -m gymts_data_organization_demo.cli run \
  --work /tmp/four-data-result \
  --core-wheel /tmp/four-data-wheels/gymts-0.5.1-py3-none-any.whl \
  --libraryts-repository /tmp/four-data-libraryts \
  --libraryts-python /tmp/four-data-runtime/bin/python \
  --chatts-repository /path/to/ChatTS \
  --chatts-python /tmp/four-data-runtime/bin/python \
  --prometheus-binary /path/to/prometheus
```

The entry point checks installed core files against that exact wheel before and
after execution. Use the same frozen wheel in a separate LibraryTS worker
interpreter when one is supplied. Its original adapter also verifies the fixed
upstream source identity. New caches, Run SQLite/CAS, dataset resources and service
files stay under the chosen POSIX work directory.

All four cases follow the same public core flow:

```python
catalog = gym.environment_ts.datasets
source = catalog.register_source(source_definition)
result = gym.run_data(
    experiment_spec,
    source_id=source["source_id"], revision=source["revision"],
    dataset_id="my-project/recorded",
)
dataset = catalog.load_dataset(
    result["dataset"]["dataset_id"], revision=result["dataset"]["revision"],
    split="recorded",
)
```

For static and generated data, `register_snapshot` first stores the public
numerical rows and separate evaluation targets in ResourceStore. A later source
revision names that exact dataset as its parent. The domain adapter materializes
only public `DatasetHandle` rows into the current Run's neutral snapshot.
Source configuration contains logical recipes and selections, **no original
Run-local ArtifactRef**. The same content reference can be reconstructed in a
new Run CAS using persistent dataset bytes.

`run_data` executes the existing EnvironmentTS runner and calls core
`capture_run` after sealing. It returns the genuine Run result plus a versioned
DatasetV2 manifest. Captured observations, actions, receipts, session, clock,
seed, ownership and actual termination are available through the same dataset
reader. Nested evidence is copied into portable dataset attachments.

## Read after the service and original Run CAS are unavailable

The run command stops its own Prometheus/exporter, copies only `data/` into
`portable-data-copy/`, temporarily moves the original Run directory out of the
way, and reads all four recorded datasets through a fresh GymTS Run root.
It resolves every portable attachment and reconstructs the numerical public
snapshots without the original Run CAS. The original Run directory is restored
for historical scoring. The evidence is `portable-read-summary.json`.

A separate process can repeat the public read:

```bash
/tmp/four-data-runtime/bin/python -I -B -m gymts_data_organization_demo.cli inspect \
  --work /tmp/four-data-result \
  --data-home /tmp/four-data-result/portable-data-copy
```

## Independent evaluation and model-free re-scoring

AutoBenchTS scores each sealed Run with the existing independent domain Scorer.
Private numerical holdouts are read through `EvaluationDatasets`; they never
enter TaskInput. The live reference comes from the declared exporter fixture,
not from a prediction. Technical gates require completed execution and full
scoring coverage; no model-quality threshold is invented.

Install only the core, lightweight adapter and example wheels in another fresh
environment, without NumPy, Gymnasium, sktime or source checkouts:

```bash
python3.11 -m venv /tmp/four-data-rescore
/tmp/four-data-rescore/bin/python -m pip install --no-deps /tmp/four-data-wheels/*.whl
/tmp/four-data-rescore/bin/python -I -B -m gymts_data_organization_demo.cli rescore \
  --work /tmp/four-data-result \
  --core-wheel /tmp/four-data-wheels/gymts-0.5.1-py3-none-any.whl
```

Re-scoring forbids Environment/Candidate construction and experiment execution,
compares coverage and every metric with the first independent score, and checks
that sealed Run records remain identical. It uses the retained Run evidence;
portable dataset reading separately proves independence from the original Run
store. It does not claim that uninstalling all domain metadata enables scoring.

`run-summary.json`, `portable-read-summary.json`, `rescore-summary.json`, the
four fixed `*-score-spec.json` files, the retained Run root and ResourceStore form
the reviewable result. Keep original source identities and service logs with
that evidence. The CLI preserves failed Run artifacts if an actual backend fails.

Run the one lightweight projection regression after installing the package:

```bash
python -I -B -m unittest discover -s /path/to/examples/data_organization/tests -v
```

## License

This example is [MIT licensed](LICENSE). LibraryTS, ChatTS, Gymnasium, Prometheus,
source datasets and their dependencies retain their own licenses. This example
does not relicense or vendor their algorithms, services or data.
