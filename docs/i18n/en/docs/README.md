# GymTS documentation

Current source is the unreleased **0.6.0** working tree with public contract **1.4.0**; F2.1 organization technical acceptance has passed. Documentation follows two stable responsibilities: EnvironmentTS data organization/execution/evidence and AutoBenchTS evaluation. Design proposals and historical experiment records are listed separately from current usage documentation.

## Getting started

| What you want to do | Documentation |
| --- | --- |
| Understand project goals, roles, experiment boundaries, and system placement | [Complete project overview](overview.md) |
| Install, run your first experiment, evaluate, and rescore original Runs | [User guide](user-guide.md) |
| Fix data references, connect stages, recover failures and publish data | [Experiment organization guide](experiment-organization.md) |
| Look up commands, arguments, APIs, and configuration structures | [API / CLI reference](reference.md) |
| Find executable scripts and configurations | [Examples](../examples/README.md) |
| Troubleshoot common errors | [FAQ](faq.md) |
| Check capabilities available in this version | [Project status](project-status.md) |
| Read the English project entry point | [English README](../README.en.md) |

## Core concepts and usage topics

- [Framework implementation guide](framework.md): public SDK, component lifecycles, assembly, access boundaries, records, independent evaluation, and training extensions.
- [Environment integration](environment-adapters.md): synthetic data, HF static data, Gymnasium, OpenEnv, and Prometheus; invocation, clocks, ownership, and actual acceptance scope.
- [Dataset and benchmark catalog](dataset-benchmark-catalog-design.md): EnvironmentTS data access, public/private resources, AutoBenchTS benchmark resolution, and long-term storage.
- [Experiment organization and dataset publication](experiment-organization.md): fixed data references, stage dependencies, attempts, explicit retry/recovery and linked queries.
- [ADR 0002: experiment organization](adr/0002-experiment-organization.md): reasons for this round's core changes, adapter boundaries and historical compatibility.
- [ADR 0001: four-kind core data organization](adr/0001-core-data-source-catalog.md): real gaps, corrected core responsibilities, existing-protocol compatibility and F1 freeze validation.
- [Agents and external toolsets](agent-toolsets.md): Agent decisions, tool execution, environment I/O, private scoring boundaries, and the general tool loop that has not yet passed acceptance.
- [Formal interface specification 1.4.0](feishu/GymTS接口规范/GymTS接口规范.md): fields, states, sequencing, errors, trajectories and integration contracts; §21 defines this round's organization contract and §20 retains the historical F1 data-layer acceptance scope.

## Project and domain adapters

Start with the [independent adapter overview](../adapters/README.md). Each package has its own metadata, dependencies, activation name, and tests. Prepare data, weights, servers, and API keys according to its instructions; installing the framework does not download or publish them.

| Integration | Documentation |
| --- | --- |
| Neutral time-series domain and LibraryTS | [timeseries](../adapters/timeseries/README.md), [the specified LibraryTS toolset](../adapters/libraryts/README.md) |
| ChatTS | [Package documentation](../adapters/chatts/README.md), [complete integration guide](chatts-integration.md) |
| TimeSigma | [Package documentation](../adapters/timesigma/README.md), [integration guide](timesigma-integration.md) |
| RL rollout and training | [Package documentation](../adapters/rl/README.md), [GSM8K / ChatTS / TRL guide](rl-integration.md) |
| Question-answering benchmarks | [TSQA package](../adapters/bench_tsqa/README.md); all five attachments remain evaluation-only |
| HF static sources | [HF Datasets package](../adapters/hf_datasets/README.md) |
| Control domain and simulation | [interaction](../adapters/interaction/README.md), [Gymnasium](../adapters/gymnasium/README.md) |
| External services and live testbeds | [OpenEnv](../adapters/openenv/README.md), [Prometheus](../adapters/prometheus/README.md) |

## Development, collaboration, and releases

- [Adapter development tutorial](adapter-development.md): an independently installable minimal Candidate, plus Source, Task, Scorer, resource, and training extension entry points.
- [Contributing](../CONTRIBUTING.md): development environments, testing, Issues / PRs, reasons for core changes, and frozen-core compatibility checks.
- [Maintainer guide](maintainer-guide.md): versions, release preparation, distribution checks, data/credentials, and compatibility; no automatic publication.
- [Bilingual documentation build and publication](documentation.md): source files remain the single text source; check links and build a navigable documentation site.
- [Support](../SUPPORT.md), [security](../SECURITY.md), [code of conduct](../CODE_OF_CONDUCT.md).
- [Changelog](../CHANGELOG.md), [roadmap](roadmap.md), [citation](citing.md), [MIT licensing](licensing.md), [license text](../LICENSE), [third-party sources](../THIRD_PARTY.md).

## Current acceptance and engineering evidence

- [0.6.0 / contract 1.4.0 experiment organization acceptance](reports/experiment-organization-2026-10-21.json): F2.1 frozen identity; 196 core tests passed; sixteen-package compatibility records 356 passes and 61 optional-dependency skips; an independent 32-row ETTh1 view completed execution, independent evaluation and rescoring after adapter removal.
- [Historical 0.5.1 four-kind core data acceptance](reports/core-data-organization-2026-10-21.json): real sources on frozen F1, catalog/portable attachments, independent evaluation and model-free rescoring.

Reports document specific source, runtime dependency, and data snapshots. They are not live CI status, full benchmark rankings, or proof of production readiness. Some historical filenames retain dates from earlier environments; assess applicability by the versions, commits, hashes, and acceptance scope inside them.

- [Four-source environment acceptance](reports/environment-acceptance-2026-10-19.json) and [eleven-package independent distribution checks](reports/environment-adapter-package-check-2026-10-19.json).
- [HF static sources](reports/hf-environment-2026-10-19.json), [Gymnasium](reports/gymnasium-environment-2026-10-19.md), [OpenEnv](reports/openenv-environment-2026-10-19.md), [Prometheus](reports/prometheus-environment-2026-10-19.json).
- [0.5.0 milestone delivery](framework-delivery-2026-10-20.md), [frozen core identity](reports/core-frozen-identity-2026-10-20.json), [core distribution check](reports/core-package-check-2026-10-20.json).
- [Data/task/model replacement](component-replacement-validation-2026-10-19.md), [LibraryTS native acceptance](reports/libraryts-native-final-2026-10-20.json), [TimeSigma native acceptance](reports/timesigma-frozen-core-final-2026-10-20.json).
- [746-question acceptance](reports/bench-tsqa-full746-final-2026-10-20.json), [RL checkpoint chain](reports/rl-checkpoint-loop-2026-10-20.json), [RL validation notes](rl-validation-2026-10-19.md).
- [Earlier release preparation](release-readiness-2026-10-18.md) and [pre-integration TimeSigma review](timesigma-repository-review.md) remain historical references.

Complete CAS / SQLite / weight or dataset archives may reside in ignored local `output/` directories. Public reports do not automatically publish these materials through Git or packages. For reproduction, prepare the sources, hashes, configurations, and permissions recorded in the reports separately.

## Original designs and future proposals

- [Overall design](feishu/GymTS总体设计/GymTS总体设计.md), [execution mechanism](feishu/GymTS%20运行机制/GymTS%20运行机制.md), [scenario integration](feishu/场景接入/场景接入.md), [project interpretation](项目理解.md).
- [Framework evolution principles and pluggability design](pluggability-design.md): current alignment principles and next-version proposals; proposals are not implemented contracts.
- [Draft v2 messages and invocation protocol](pluggability-contract-v2.md): field definitions and message walkthroughs, not the current SDK.
- [Enterprise multi-team platform review](enterprise-platform-roadmap.md): research proposals for remote execution, identity, isolation, and collaboration.
- [Historical pre-edit snapshots](archive/2026-10-12-before-api-v1/) and `archive/2026-10-20-before-api-v1.2/` preserve earlier text.
- The [project group website](https://netman.aiops.org/contacts/projects/) provides external context for project responsibilities; higher-level business systems do not automatically become GymTS core components.

Original PDFs, PPTs, and images may use older names. Preserve these source materials rather than rewriting them as the new specification. Where they conflict, the current formal contract determines message semantics; project status and registered components determine the actual runnable support scope.
