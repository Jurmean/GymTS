<div class="eyebrow">GYMTS DOCUMENTATION · v0.5.0</div>

# Time-series experiments.<br> Evidence you can inspect.

<p class="lead">Connect data, environments, and methods. Keep the evidence from every run, evaluate it independently, and revisit results as new references arrive.</p>

<div class="hero-actions"><a class="button-primary" href="../../../docs/quickstart.md">Get started <span aria-hidden="true">→</span></a><a class="button-secondary" href="../../../docs/reference.md">Explore the API</a></div>

<p class="hero-note">Python 3.9+ · Zero third-party core runtime dependencies · MIT · Install from source</p>

<div class="workflow" aria-label="Experiment workflow"><div class="workflow-step"><span class="workflow-number">01</span><strong>Compose an experiment</strong><small>Register and replace data sources, tasks, and methods.</small></div><div class="workflow-step"><span class="workflow-number">02</span><strong>Run and record</strong><small>EnvironmentTS manages execution, access, and evidence.</small></div><div class="workflow-step"><span class="workflow-number">03</span><strong>Evaluate and rescore</strong><small>AutoBenchTS creates new reports from fixed outputs.</small></div></div>

## Start with a reproducible experiment

```bash
git clone https://github.com/Jurmean/GymTS.git
cd GymTS
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
python examples/quickstart.py --root /tmp/gymts-quickstart
```

This example needs no GPU, external dataset, or API key. It runs forecasting, performs control
actions, compares candidates, appends labels, and rescores the same Runs. You can inspect each
operation, input, output, and scoring reference when it finishes.

<p class="note-line">Implementation 0.5.0 · Public contract 1.2.0. Install the repository source; this version is not assumed to be on PyPI. Keep active SQLite / CAS stores on a local POSIX filesystem. <code>/tmp</code> is only for a quick trial.</p>

## Two stable responsibilities. An open integration boundary.

**EnvironmentTS** owns execution, access boundaries, and evidence. **AutoBenchTS** owns evaluation
plans, independent scoring, comparison, and rescoring. Independent adapters own data formats,
model calls, domain tasks, and scoring rules.

LibraryTS, TimeSigma, ChatTS, and other toolsets connect through public interfaces.
Agents choose which tools to call; adapters translate calls and preserve evidence. The delivered
tool wrappers and Research parent traces do not establish a generic autonomous tool loop.
See the [architecture](../../../docs/framework.md), [agents and toolsets](../../../docs/agent-toolsets.md),
and [current acceptance boundaries](../../../docs/project-status.md).

## Find your starting point

<div class="resource-list"><div><strong><a href="../../../docs/user-guide.md">User guide →</a></strong><p>Install, run an experiment, inspect traces, and rescore with late labels.</p></div><div><strong><a href="../../../docs/reference.md">API and CLI →</a></strong><p>GymTS, EnvironmentTS, AutoBenchTS, and the public contracts.</p></div><div><strong><a href="../../../docs/environment-adapters.md">Data and environments →</a></strong><p>Synthetic data, HF datasets, Gymnasium, OpenEnv, and Prometheus.</p></div><div><strong><a href="../../../docs/adapter-development.md">Integrate a project →</a></strong><p>Independent packages, discovery, activation, and rescoring after removal.</p></div></div>

## An adapter ecosystem. Install what you need.

| Need | Independent adapters |
| --- | --- |
| Time-series contracts and tools | [timeseries](../../../adapters/timeseries/README.md), [LibraryTS](../../../adapters/libraryts/README.md) |
| Synthetic time series and model Q&A | [ChatTS](../../../adapters/chatts/README.md), [TimeSigma](../../../adapters/timesigma/README.md) |
| Static datasets and evaluation resources | [HF Datasets](../../../adapters/hf_datasets/README.md), [TSQA benchmarks](../../../adapters/bench_tsqa/README.md) |
| Simulation, interaction, and live testbeds | [interaction](../../../adapters/interaction/README.md), [Gymnasium](../../../adapters/gymnasium/README.md), [OpenEnv](../../../adapters/openenv/README.md), [Prometheus](../../../adapters/prometheus/README.md) |
| Rollouts and external training backends | [RL / TRL](../../../adapters/rl/README.md) |

Install and explicitly enable each adapter separately. Integrating a project does not make it a
core dependency. The [installation matrix](../../../adapters/README.md) lists dependencies,
runnable examples, and validation scope.

## Contribute to GymTS

Connect your method with the [minimal teaching adapter](../../../examples/adapters/minimal_demo/README.md),
or read the [contributing guide](../../../CONTRIBUTING.md) and [roadmap](../../../docs/roadmap.md).
The framework and these docs use the [MIT license](../../../LICENSE). External projects,
datasets, and weights retain their own licenses.
