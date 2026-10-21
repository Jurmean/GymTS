<div class="eyebrow">GYMTS DOCUMENTATION · v0.6.0</div>

# Time-series data.<br> Experiments you can trace.

<p class="lead">Store and connect data. Organize experiments and keep their records. Fix inputs and configurations, follow stage outputs, and revisit results through independent evaluation.</p>

<div class="hero-actions"><a class="button-primary" href="../../../docs/quickstart.md">Get started <span aria-hidden="true">→</span></a><a class="button-secondary" href="../../../docs/experiment-organization.md">Organize an experiment</a></div>

<p class="hero-note">Python 3.9+ · Zero third-party core runtime dependencies · MIT · Install from source</p>

<div class="workflow" aria-label="GymTS four main responsibilities"><div class="workflow-step"><span class="workflow-number">01</span><strong>Store data</strong><small>One catalog, fixed versions, usage and lineage.</small></div><div class="workflow-step"><span class="workflow-number">02</span><strong>Connect data</strong><small>Static, synthetic, simulation and live sources.</small></div><div class="workflow-step"><span class="workflow-number">03</span><strong>Organize experiments</strong><small>Declare stages and bind inputs and outputs.</small></div><div class="workflow-step"><span class="workflow-number">04</span><strong>Record experiments</strong><small>Keep each attempt, Run, result and evaluation.</small></div></div>

## From stored data to experiment records

```bash
git clone https://github.com/Jurmean/GymTS.git
cd GymTS
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
python examples/experiment_organization.py --work /tmp/gymts-organization-demo
```

This example needs no GPU, external dataset, or API key. It registers observations and organizes
forecasting, snapshot capture, reference registration, scoring and rescoring as stages.
Executing the same plan again retains successful stages; query records by data or experiment.
See the [organization guide](../../../docs/experiment-organization.md) for the complete workflow,
or the [quickstart](../../../docs/quickstart.md) for forecasting and control basics.

<p class="note-line">Implementation 0.6.0 · Public contract 1.4.0. F2.1 passed technical verification for experiment organization, dataset publication, linked queries and independent adapter integration. Install repository source; this version is not assumed to be on PyPI. Keep active SQLite / CAS stores on a local POSIX filesystem. <code>/tmp</code> is only for a quick trial.</p>

## Two stable responsibilities. An open integration boundary.

**EnvironmentTS** manages four-kind source catalogs, snapshots, lineage, execution and evidence in
core. **AutoBenchTS** owns benchmarks, evaluation plans, independent scoring, comparison and
rescoring. Independent adapters own project formats, model calls, domain tasks and scoring rules.
See [ADR 0001](../../../docs/adr/0001-core-data-source-catalog.md) for data ownership and [ADR 0002](../../../docs/adr/0002-experiment-organization.md) for experiment organization, publication and query contracts.

LibraryTS, TimeSigma, ChatTS, and other toolsets connect through public interfaces.
Agents choose which tools to call; adapters translate calls and preserve evidence. TimeCopilot
completed six real model requests, four native tool types, and independent rescoring; see
[five-project acceptance](../../../docs/five-project-integration-acceptance-2026-10-21.md).
This does not establish a general Agent Runtime across projects.
See the [architecture](../../../docs/framework.md), [agents and toolsets](../../../docs/agent-toolsets.md),
and [current acceptance boundaries](../../../docs/project-status.md).

## Find your starting point

<div class="resource-list"><div><strong><a href="../../../docs/dataset-benchmark-catalog-design.md">Data catalog and storage →</a></strong><p>Locations, versions and reads for sources, datasets and benchmarks.</p></div><div><strong><a href="../../../docs/experiment-organization.md">Experiments and data publication →</a></strong><p>Stages, input/output bindings, explicit retry and stage-level recovery.</p></div><div><strong><a href="../../../docs/reference.md">Records, queries and APIs →</a></strong><p>Find Runs, artifacts and evaluations by data, experiment or attempt.</p></div><div><strong><a href="../../../docs/adapter-development.md">Interfaces and independent adapters →</a></strong><p>Boundaries for formats, connectors, model calls and domain scoring.</p></div></div>

## Current verification scope

All 196 installed core tests passed. Sixteen-package compatibility checks recorded 356 passes
and 61 optional-dependency skips. An independent CSV adapter completed real Runs on the frozen
core; data reads, experiment queries and rescoring still worked after uninstalling it.
See the [acceptance report](../../../docs/reports/experiment-organization-2026-10-21.json) and
[project status](../../../docs/project-status.md) for scope and limits.

## An adapter ecosystem. Install what you need.

| Need | Independent adapters |
| --- | --- |
| Time-series contracts and tools | [timeseries](../../../adapters/timeseries/README.md), [LibraryTS](../../../adapters/libraryts/README.md) |
| Synthetic time series and model Q&A | [ChatTS](../../../adapters/chatts/README.md), [TimeSigma](../../../adapters/timesigma/README.md) |
| Static datasets and evaluation resources | [HF Datasets](../../../adapters/hf_datasets/README.md), [TSQA benchmarks](../../../adapters/bench_tsqa/README.md) |
| Simulation, interaction, and live testbeds | [interaction](../../../adapters/interaction/README.md), [Gymnasium](../../../adapters/gymnasium/README.md), [OpenEnv](../../../adapters/openenv/README.md), [Prometheus](../../../adapters/prometheus/README.md) |
| Native Agents and signal Q&A | [TimeCopilot](../../../adapters/timecopilot/README.md), [ITFormer](../../../adapters/itformer/README.md) |
| Quantile prediction and native fit | [Chronos-2](../../../adapters/chronos/README.md) |
| Processing, lineage, and derived data | [Data-Juicer](../../../adapters/datajuicer/README.md) |
| Rollouts and external training backends | [RL / TRL](../../../adapters/rl/README.md), [AReaL](../../../adapters/areal/README.md) (training/publication verified; held-out evaluation/rescoring pending) |

Install and explicitly enable each adapter separately. Integrating a project does not make it a
core dependency. The [installation matrix](../../../adapters/README.md) lists dependencies,
runnable examples, and validation scope.
All sixteen packages passed the stated offline distribution checks. TimeCopilot, ITFormer,
Chronos-2, and Data-Juicer completed this round’s native engineering workflows; AReaL training/publication are verified, with held-out
evaluation/rescoring awaiting final evidence. Engineering completion and model quality are separate claims.

## Contribute to GymTS

Connect your method with the [minimal teaching adapter](../../../examples/adapters/minimal_demo/README.md),
or read the [contributing guide](../../../CONTRIBUTING.md) and [roadmap](../../../docs/roadmap.md).
The framework and these docs use the [MIT license](../../../LICENSE). External projects,
datasets, and weights retain their own licenses.
