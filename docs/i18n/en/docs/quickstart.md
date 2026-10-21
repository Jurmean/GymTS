# Quickstart

GymTS focuses on **storing data, connecting data sources, organizing experiments, and recording experiments**.
Run a small built-in experiment first, then install adapters as needed. This workflow needs no GPU,
external dataset, model service, or API key. Python 3.9+ is required; the local storage backend targets Linux / macOS.

## 1. Install from source

```bash
git clone https://github.com/Jurmean/GymTS.git
cd GymTS
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

The current implementation is **0.6.0**, with public contract **1.4.0**. These commands install the
repository source; they do not assume this version has been published to PyPI.

Current F2.1 technical acceptance is complete. See the [experiment organization guide](experiment-organization.md) for fixed data references, stages, failure recovery, and data publication, and the [current acceptance report](reports/experiment-organization-2026-10-21.json) for verified scope and limitations.

## 2. Run your first experiment and rescore it

```bash
python examples/quickstart.py --root /tmp/gymts-quickstart
```

The program runs forecasting and control examples, evaluates two candidates, appends independent
labels, and rescores the same Runs. Its summary includes these fields (Run IDs are generated):

```json
{
  "counter_operations": 3,
  "initial_verdict": "insufficient_evidence",
  "rescored_verdict": "pass",
  "mae": {"last-value": 1.0, "window-mean": 2.0},
  "same_run_ids": true,
  "original_results_unchanged": true
}
```

When labels are initially missing, `insufficient_evidence` is the correct result. Execution
completion, sufficient evidence, and passing evaluation are separate judgments. Rescoring adds
an evaluation report while preserving the original Runs, events, and method outputs.

## 3. Inspect a trace

```bash
gymts --store /tmp/gymts-cli run examples/forecast_experiment.json
gymts --store /tmp/gymts-cli inspect RUN_ID --events
```

Replace `RUN_ID` with the `run_id` returned by the preceding command. A Run links configuration,
component versions, inputs, outputs, and events. Artifacts are stored by content in CAS;
evaluation reports have separate identities.

## 4. Add adapters as needed

```bash
python -m pip install . ./adapters/timeseries ./adapters/chatts
```

```python
from gymts import GymTS

with GymTS("/tmp/gymts-adapter-demo") as gym:
    print(gym.available_integrations())
    gym.enable_integration("timeseries")
    gym.enable_integration("chatts")
```

Discovery does not automatically enable an adapter. Each package explicitly registers its
environments, tasks, methods, and Scorers. Prepare datasets, native models, simulation dependencies,
and credentials separately according to the adapter instructions.

## 5. Continue from here

- [User guide](user-guide.md): data storage and ingestion, planning, execution, late labels, and records.
- [Experiment organization](experiment-organization.md): stage dependencies, attempt records, queries, and data publication.
- [API and CLI](reference.md): method signatures, exit codes, and protocol fields.
- [Environment adapters](environment-adapters.md): synthetic, static, simulation, and live sources.
- [Independent adapters](../adapters/README.md): package installation and validation matrices.
- [Minimal teaching adapter](../examples/adapters/minimal_demo/README.md): independent installation, execution, removal, and rescoring.

Keep active SQLite / CAS stores on a local POSIX filesystem, rather than an object-storage mount
such as S3FS. `/tmp` is useful for a trial, but is not a backup; use your own persistent local
directory for long-running experiments.
