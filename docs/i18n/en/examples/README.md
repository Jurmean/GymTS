# Runnable examples

`quickstart.py` and the forecasting/counter examples below use local deterministic data, without model files, LLM APIs, GPUs, or private data. Model connection configurations near the end require their corresponding inference services. All components are registered at the exact version `1.0.0`.

New sources still run through independent adapters. See the [environment integration guide](../docs/environment-adapters.md) for installation and scope. Each native example uses a fresh `/tmp` output directory; active CAS/SQLite is kept off shared storage.

| Source | Independent-package example |
| --- | --- |
| HF static data | [hf_static.py](../adapters/hf_datasets/examples/hf_static.py): fixed official data, three freezing sources, native evaluation, and offline rescoring |
| Gymnasium simulation | [native_cpu.py](../adapters/gymnasium/examples/native_cpu.py): real FrozenLake/CartPole, final reward, and native termination separated from scope_limited |
| OpenEnv external sessions | [echo_roundtrip.py](../adapters/openenv/examples/echo_roundtrip.py): official Echo/Connect4 services, stateful WS, independent evaluation, and same-Run rescoring |
| Prometheus live source | [native_server_demo.py](../adapters/prometheus/examples/native_server_demo.py): actual scraping, fixed-reference scoring, and disconnected rescoring |

These examples verify execution and evidence contracts for specific sources, not a complete HF platform, a user's production testbed, an autonomous Agent tool loop, or model quality. The existing synthetic quickstart and independent ChatTS contracts remain available; the ChatTS generator was not rerun in this round. See the evidence index in the [environment guide](../docs/environment-adapters.md) for native results and the [eleven-package check](../docs/reports/environment-adapter-package-check-2026-10-19.json) for distribution isolation.

Run from the project root:

```bash
python3 examples/quickstart.py --root .gymts-demo
```

The script executes forecasting and interactive Runs, compares two Candidates, reports insufficient evidence before labels, attaches independent truth, and rescores original Runs. It verifies unchanged Run IDs and original RunResult digests, then prints MAE=1/2 and Gate results. Records and artifacts remain in the chosen local directory.

| File | Purpose |
| --- | --- |
| `forecast_experiment.json` | Generate a minute-level linear series, accumulate a 3-point window, and predict 1 minute ahead |
| `forecast_evaluation.json` | Compare `last-value` and `window-mean`; initial missing labels should produce insufficient evidence |
| `forecast_score_template.json` | Old-Run rescoring template; insert a real `run_id` and an authorized label view |
| `counter_experiment.json` | Interactive counter: consume initial state → request increment → consume transition; terminate naturally after 3 operations |

The forecasting source's `source.connection` must provide exactly one of `generator` or `points`. An explicit point has this structure:

```json
{
  "timestamp": "2026-01-01T00:00:00Z",
  "available_at": "2026-01-01T00:02:00Z",
  "entity": "demo",
  "values": {"value": 8}
}
```

`mapping.variables` maps fields in the original `values` object to public environment variables. `options.availability=explicit` requires actual `available_at` on every point. `event_time` permits omission and explicitly assumes event-time availability. The main stream delivers by availability time while retaining original event time. Queries may read only the opened temporal frontier; loading everything into memory does not authorize future reads.

`window_forecast` accumulates a window for the same entity/variable, retaining nulls and masks for invalid points, and does not call the Candidate before enough points exist. This reference version skips previously processed late points and those earlier than the current window, without revising issued forecasts. The framework still fully records original late observations. `last-value` uses the last valid window value; `window-mean` averages valid values. With no valid values, each returns an explicit invalid result.

The scoring count unit is the original TaskResult; missing labels do not shrink the eligible denominator. With complete linear-series truth, MAE is 1 and 2 respectively. Without labels, both have `insufficient_evidence`. `forecast-mae` supports only exact matching and unit `value`; other rules or units require an independently versioned plugin.

Save labels as immutable artifacts and pass them to `scoring.outcomes.sources` through a DataViewRef with `purpose=evaluation`. OutcomeRecord requires a real `source_ref`, availability/commit times, and `allowed_uses=["evaluation"]`. Rescoring old outputs invokes only the Scorer, not the Candidate or environment advancement.
## ChatTS synthetic experiments

ChatTS ships as the independent `gymts-chatts` adapter. From the repository root, install `python3 -m pip install . ./adapters/chatts`. Python uses `GymTS(integrations=("chatts",))`; the generic CLI uses `--integration chatts`. The dedicated entry point is `python3 -B -m gymts_chatts.pipeline --help`, also available as `gymts-chatts`. Defaults generate actual native/classical profiles, export bundle-isolated SFT source data, evaluate numeric baselines for seven QA Tasks, attach gold, rescore original Runs, and export trajectories.

Configuration templates are in the [adapter examples](../adapters/chatts/examples/README.md). The service for `chatts_http_candidate.json` must support the chosen native time-series dialect. Its address and checkpoint come from the existing ChatTS-Bench configuration; replace them with an actual fixed deployment before running. Add `--candidate-config adapters/chatts/examples/chatts_http_candidate.json` for model comparison. See the [integration and execution guide](../docs/chatts-integration.md).

`deepseek_candidate.json` uses the separately registered `chatts-text-http` Candidate for ordinary text LLM APIs. It serializes public sequences in full, by name and original order, into `named_numeric_json/v1` text, without normalization, rounding, or the native ChatTS wire format. Native numeric arrays remain in TaskInput; gold, source sample IDs, and generation metadata are excluded from the request.

Set `DEEPSEEK_API_KEY` in the current process through local secret management, then reuse existing profiles for a small seven-task connection check:

```bash
python3 -B -m gymts_chatts.pipeline \
  --profile-dir /path/to/profiles/native \
  --profile-dir /path/to/profiles/classical \
  --candidate-config adapters/chatts/examples/deepseek_candidate.json \
  --no-baseline --max-per-task 1 \
  --output .gymts/deepseek-text-example-001
```

Configuration stores only the environment-variable name, never the key. The example selects the `deepseek-flash` API alias, disables thinking, and requests JSON object output. `model_revision=deepseek-flash-api-alias` identifies configuration, not a checkpoint digest; evidence records `weights_pinned=false`. Remove `--max-per-task 1` to use the full held-out set; remove `--no-baseline` to include numeric baselines. The output directory must be fresh. These commands do not claim an actual API result in advance.

## Replacing data, tasks, and models

[component_swap_matrix.py](component_swap_matrix.py) uses the installed core, `gymts-timeseries`, and `gymts-libraryts`. Prepare fixed LibraryTS source and a scientific Python runtime, then run:

```bash
python -I -B examples/component_swap_matrix.py \
  --root /tmp/gymts-component-swaps \
  --repository /path/to/fixed-sktime \
  --python /path/to/native-env/bin/python
```

It executes eight actual Runs: JSON/CSV × numeric forecasting/trend × Naive/Polynomial. Initial evaluations lack labels, then independent references are attached for rescoring. Checks cover identical inputs, actual model/tool traces, and no original-Run changes or new native calls during scoring. Outputs include `summary.json` and the complete local records store. See [LibraryTS](../adapters/libraryts/README.md) for native setup. The example uses explicit linear synthetic observations to verify interface composition, not real benchmark quality.

## 0.5 resource catalog and formal post-training evaluation

See the [resource catalog](../docs/dataset-benchmark-catalog-design.md) and [TSQA adapter](../adapters/bench_tsqa/README.md) for executable public QA reading and native resolve/evaluate calls. The five QA datasets are evaluation-only and must not be used for prepare/training in examples.

[checkpoint_loop.py](../adapters/rl/examples/checkpoint_loop.py) performs actual TRL updates on an explicitly tiny CPU model, publishes an immutable checkpoint, moves the original work directory away, loads it in a new process, evaluates two held-out tasks × three execution seeds, and independently rescores. This is engineering-path acceptance: effective training uses only two GSM8K train samples, and accuracy is not evidence of improved capability. See the [RL guide](../docs/rl-integration.md) for its runtime.

[frozen_core_cpu.py](../adapters/timesigma/examples/frozen_core_cpu.py) uses fixed upstream TimeSigma native AR to verify fit, independent-process replay, and eight AutoBenchTS metrics. See the [TimeSigma guide](../docs/timesigma-integration.md) for source/model Python dependencies. Neither example calls a paid LLM.

## Extend the examples for your own project

The [independent Candidate tutorial](adapters/minimal_demo/README.md) shows registration of a new method without changing core, reuse of built-in forecasting and independent MAE scoring, evaluation, same-Run rescoring, and metadata migration. It lives in a full Git checkout, builds and installs independently, and is excluded from core wheel/sdist. See the [adapter development guide](../docs/adapter-development.md) for Environment, Task, Scorer, dataset reader, benchmark resolver, and training builder contracts, and the [API reference](../docs/reference.md) for commands and public methods.
