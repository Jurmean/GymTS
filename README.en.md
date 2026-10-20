# GymTS

[中文文档](https://gymts-docs.zrr9392.chatgpt.site/zh/) · [English docs](https://gymts-docs.zrr9392.chatgpt.site/en/)

**A framework for time-series experiments, environment execution, and independent evaluation.**

[中文](README.md) · English · [User guide (Chinese)](docs/user-guide.md) · [API / CLI](docs/reference.md)

GymTS connects the data an experiment saw, the method it ran, the operations it performed, and the
references used to evaluate it. Replace sources, tasks, models, algorithms, or Agents through
independent adapters. Preserve execution evidence and rescore the same outputs when labels or
scoring rules change.

The current implementation is **0.5.0**, using public contract **1.2.0**. The core requires
**Python 3.9+**, has no mandatory third-party runtime dependencies for JSON workflows, and uses a
local storage backend supported on Linux/macOS. Individual adapters have additional requirements.
The commands below install from a source checkout containing this version; no PyPI release is assumed.

## Quick start

```bash
git clone https://github.com/Jurmean/GymTS.git
cd GymTS
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
python examples/quickstart.py --root /tmp/gymts-quickstart
```

No GPU, downloaded dataset, API key, or model service is required. The example executes forecasting
and control experiments, evaluates two methods before labels arrive, adds independent references,
and rescores the original Runs. Expected fields include:

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

Keep active SQLite/CAS stores on a local POSIX filesystem. `/tmp` is convenient for demonstrations
and is not a backup; use durable local storage and a closed-store backup for long-term retention.

## Architecture and boundaries

- **EnvironmentTS** owns experiment execution, source lifecycle, access boundaries, and evidence.
- **AutoBenchTS** owns fixed evaluation plans, independent scoring, comparisons, gates, and rescoring.
- **Independent adapters** implement source formats, native environment APIs, task semantics, model
  calls, codecs, and domain scoring. Shared domain contracts are also optional external packages.

A Candidate can be an algorithm, a pipeline, a model, or an Agent. An Agent chooses tools through its
SDK and adapters. Additional experiment data access and environment operations must pass through
Task/Runner authorization. Existing fixed-method and tool-wrapper checks do not establish a general
autonomous Agent tool-selection loop.

GymTS currently provides a synchronous local SDK and CLI. A multi-tenant service, remote workers,
process isolation, recovery, and a general Agent tool loop require separate implementation and
acceptance. See the [project overview](docs/overview.md), [project status](docs/project-status.md), and [roadmap](docs/roadmap.md).

## CLI and Python

Run these commands from the repository root; global options precede subcommands:

```bash
gymts --store /tmp/gymts-cli plan examples/forecast_experiment.json
gymts --store /tmp/gymts-cli validate examples/forecast_experiment.json
gymts --store /tmp/gymts-cli run examples/forecast_experiment.json --output /tmp/gymts-run.json
gymts --store /tmp/gymts-cli evaluate examples/forecast_evaluation.json
gymts --store /tmp/gymts-cli plugins
```

`evaluate` runs a fixed set of evaluation units. `score` evaluates existing Runs without rerunning
Candidates. `inspect RUN_ID --events` reads their recorded execution. Missing evidence is explicit:
a completed evaluation can still have `verdict="insufficient_evidence"`.

```python
import json
from pathlib import Path
from gymts import GymTS

spec = json.loads(Path("examples/forecast_experiment.json").read_text())
with GymTS("/tmp/gymts-python") as gym:
    validation = gym.validate(spec)
    if not validation["valid"]:
        raise ValueError(validation["issues"])
    result = gym.run(spec)
    print(result["status"], result["run_id"])
```

Optional source-install extras: `python -m pip install '.[yaml]'` for YAML configuration and
`python -m pip install '.[datasets]'` for Parquet readers. The latter is separate from the HF adapter.

## Datasets, benchmarks, and evidence

EnvironmentTS manages versioned dataset resources. AutoBenchTS registers and resolves reusable
BenchmarkDefinitions into native evaluation specifications. Public dataset handles support indexing,
selection, filtering, and batches; evaluation references remain separate from Candidate inputs.
`data_home` stores durable resources, `cache_home` holds rebuildable cache entries, and the Run root
contains SQLite records and immutable content-addressed artifacts.

A Run retains resolved configuration, observations, inputs, outputs, operations, receipts, errors,
and cleanup evidence. ModelCall/ToolCall details require explicit adapter instrumentation and the
configured capture profile. Adding labels or rescoring creates new evidence and reports without
rewriting the original execution. Credentials, private outcomes, and model assets require separate
access and publication decisions; trusted Python plugins are not a process sandbox.

## Optional integrations

Adapters are independently packaged inside this repository. Install only what you use, then enable
its integration explicitly. Discovery reads installed entry-point metadata without importing providers.

```bash
python -m pip install ./adapters/timeseries ./adapters/chatts
```

```python
from gymts import GymTS

print(GymTS.available_integrations())
with GymTS("/tmp/gymts-optional", integrations=("chatts",)) as gym:
    print(gym.enabled_integrations)
```

| Package / integration | Purpose |
| --- | --- |
| `gymts-timeseries` / `timeseries` | Neutral numeric sources, time-series tasks, and scorers |
| `gymts-libraryts` / `libraryts` | The specified NetmanAIOps/sktime toolset, loaders, and methods |
| `gymts-chatts` / `chatts` | ChatTS data, generation, model codecs, and HTTP Candidates |
| `gymts-timesigma` / `timesigma` | Native data, schemas, CPU models, tools, and parent research traces |
| `gymts-rl` / `rl` | GSM8K/ChatTS rollouts, TRL GRPO, checkpoints, and independent evaluation |
| `gymts-bench-tsqa` / `bench-tsqa` | Evaluation-only QA resources and private references |
| `gymts-hf-datasets` / `hf-datasets` | Fixed HF commits, saved datasets, and explicit local-file snapshots |
| `gymts-interaction` / `interaction` | External neutral control tasks, policies, and episode scoring |
| `gymts-gymnasium` / `gymnasium` | Native Gymnasium simulator lifecycle |
| `gymts-openenv` / `openenv` | Official OpenEnv SDK over persistent WebSocket sessions |
| `gymts-prometheus` / `prometheus` | Read-only live numeric telemetry and immutable delivered history |

See [adapter documentation](adapters/README.md) for exact installation/runtime requirements.
Gymnasium/OpenEnv examples also enable `interaction`. HF currently supports materialized numeric
forecasting views. Live acceptance uses real localhost services, not an unverified production testbed.
Existing synthetic sources and the external ChatTS integration remain available.

## Development and documentation

```bash
python -m pip install -e .
python -m pip install 'setuptools>=58' wheel
python -B -m unittest discover -s tests -v
python -B scripts/check_release.py --output /tmp/gymts-core-check.json
python -B scripts/check_adapters.py --output /tmp/gymts-adapter-check.json
```

After build dependencies are prepared, distribution checks run offline. Minimal environments may
skip tests requiring scientific runtimes; those skips are separate from actual native acceptance.
[Recorded environment acceptance](docs/reports/environment-acceptance-2026-10-19.json) distinguishes
package checks, native calls, preserved failures, and same-Run rescoring from model-quality claims.

- [Documentation index](docs/README.md), [user guide](docs/user-guide.md), [API/CLI reference](docs/reference.md).
- [Adapter development](docs/adapter-development.md), [environment adapters](docs/environment-adapters.md).
- [Contributing](CONTRIBUTING.md), [maintainer guide](docs/maintainer-guide.md), [support](SUPPORT.md).
- [Security](SECURITY.md), [code of conduct](CODE_OF_CONDUCT.md), [changelog](CHANGELOG.md).
- [Citation](docs/citing.md), [third-party sources](THIRD_PARTY.md), [MIT licensing](docs/licensing.md).
- [Build the documentation locally](docs/documentation.md).

New integrations should validate the public contract through adapters first. Any core change needs
a concrete unmet requirement, an explanation of why an adapter cannot express it, and compatibility
evidence from existing projects. See the developer guide for the frozen-core acceptance procedure.

## License

GymTS uses the **MIT License**; see [LICENSE](LICENSE) for the full text. The framework,
independent adapters, teaching examples, and documentation in this repository use this license,
except where third-party content is separately identified. External projects, model weights,
datasets, and user attachments retain their own licenses and usage conditions. Integrating them
with GymTS does not relicense them under MIT; see [third-party sources](THIRD_PARTY.md).
