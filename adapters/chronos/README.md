# gymts-chronos

Independent Chronos-2 adapter for GymTS 0.5 / public contract 1.2. The core has no Chronos imports or defaults. The lightweight package exposes a model independent distribution task, a native Candidate, and a stdlib Scorer; neutral numerical sources remain in `gymts-timeseries`.

This profile supports aligned finite multivariate histories, multiple forecast targets, past covariates, and future **calendar** hour/weekday covariates derived from the declared regular timestamp grid. Other future covariates are rejected until their availability contract is implemented. Outputs include native point predictions and quantiles. The fixed upstream calls its second return value `mean`, but computes the median (q=0.5); this adapter preserves that field name and records `point_statistic=median`. `mae`, `rmse`, mean pinball loss, 80% interval coverage and interval width are independently scored, with one eligible unit per planned window; errors average over target/horizon points. Coverage and width must be read together, not as a stand-alone quality gate. Higher coverage alone does not measure calibration error against the 80% target.

## Install

Application environment (no model dependencies):

```bash
python -m venv /tmp/chronos-app
/tmp/chronos-app/bin/pip install /path/to/frozen/gymts-0.5.0-py3-none-any.whl ./adapters/timeseries ./adapters/chronos
```

Native worker environment (Python 3.10+, CPU or a compatible CUDA stack):

```bash
python -m venv /tmp/chronos-native
/tmp/chronos-native/bin/pip install 'torch>=2.2,<3' 'transformers==4.57.6' 'accelerate>=1.1,<2'
/tmp/chronos-native/bin/pip install 'chronos-forecasting @ git+https://github.com/amazon-science/chronos-forecasting.git@1224fafa91e1ecd6674f5204066b159e40b5e4a1'
/tmp/chronos-native/bin/pip install /path/to/frozen/gymts-0.5.0-py3-none-any.whl ./adapters/timeseries ./adapters/chronos
```

Pin the resolved dependencies for your platform. The adapter verifies the native pipeline file hash; a different upstream implementation fails rather than being labelled with this revision. Installation/discovery never downloads weights. Download the official `amazon/chronos-2` model separately, at an explicit HF revision, with its `config.json` and complete safetensors. All native loads are local-only. Original model/data licensing remains applicable; this package does not redistribute them.

## Prepare a real dataset

This profile uses the fixed official [ETDataset](https://github.com/zhouhaoyi/ETDataset) commit below and verifies the cached CSV bytes. Preserve the original CSV and recorded hash.

```bash
/tmp/chronos-app/bin/gymts-chronos prepare \
  --output /tmp/chronos-data --windows 16 \
  --source-revision 1d16c8f4f943005d613b5bc962e9eeb06058cf07 \
  --source-url https://raw.githubusercontent.com/zhouhaoyi/ETDataset/1d16c8f4f943005d613b5bc962e9eeb06058cf07/ETT-small/ETTh1.csv
```

The delivered profile uses two targets (OT/HULL), seven numerical channels and two calendar covariates, context 128 and horizon 24. Train `[0,8640)`, validation `[8640,11520)` and test `[11520,14400)` are fixed chronological ranges; selected test windows do not overlap. The first test history may include already observed validation history. Future measured sensors/targets never enter public inputs. This named engineering profile is not a claim to reproduce every published ETT benchmark protocol.

`public.json` contains only historical observations and calendar facts; `private-evaluation.json` remains outside Candidate access. `train.json` holds the explicit training range. Do not publish raw data, private references or active stores in the source repository.

## Run, train, reload, rescore

```bash
/tmp/chronos-app/bin/gymts-chronos run --store /tmp/chronos-runs \
  --data /tmp/chronos-data --python /tmp/chronos-native/bin/python \
  --model /path/to/chronos-2 --device cpu --output /tmp/chronos-base.json

# Actual upstream fit in Candidate.prepare on an authorized train view.
/tmp/chronos-app/bin/gymts-chronos run --store /tmp/chronos-runs \
  --data /tmp/chronos-data --python /tmp/chronos-native/bin/python \
  --model /path/to/chronos-2 --device cuda:0 --train-steps 60 --output /tmp/chronos-train.json

# Extract checkpoint_refs[0] from the training result into checkpoint-ref.json.
/tmp/chronos-app/bin/gymts-chronos run --store /tmp/chronos-runs \
  --data /tmp/chronos-data --python /tmp/chronos-native/bin/python \
  --model /path/to/chronos-2 --checkpoint /tmp/checkpoint-ref.json \
  --device cpu --output /tmp/chronos-trained-evaluation.json

# No native worker, model loading or inference is used by rescore.
/tmp/chronos-app/bin/gymts-chronos rescore --store /tmp/chronos-runs \
  --result /tmp/chronos-trained-evaluation.json --output /tmp/chronos-rescore.json
```

Choose an unoccupied GPU explicitly using your deployment scheduler; this package is not a GPU scheduler. Each Run owns its bounded RPC worker and closes only that worker. Keep active SQLite/CAS, checkpoints and work directories on a local POSIX filesystem. Model/worker failures become failed sealed Runs, not replacement predictions.

Native training uses Chronos `fit` and its Transformers trainer, with weight decay zero, actual gradient norms and optimizer-step counts, plus hashes before/after. The immutable archive contains config, complete weights and training provenance. Subsequent Runs unpack, verify and load it in fresh native processes. The training Run's heldout output is diagnostic; the separately reloaded evaluation is the formal post-training evaluation. Engineering success does not establish a quality improvement.

## Validate

```bash
/tmp/chronos-app/bin/python -B -m unittest discover -s adapters/chronos/tests -v
```

These contract tests check availability/shape boundaries, independent score calculations and checkpoint tamper rejection. Real model acceptance must additionally use the commands above and retain Run IDs, artifact identities, evaluation reports, zero-inference rescore evidence and the actual installed frozen-core hashes.

The [2026-10-21 native validation index](examples/native-validation-2026-10-21.json) records the fixed sources, 60 real native optimizer updates, 16 checkpoint-reloaded windows, and independent rescore with model execution forbidden. All five metrics score 16/16 windows. This profile has no quality gates, so its formal verdict remains `insufficient_evidence`; engineering completion is not a paper-reproduction or quality-pass claim. Full CAS stores and model checkpoints remain local and are excluded from source distributions.
