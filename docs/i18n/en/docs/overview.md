# Project overview

GymTS is a framework for time-series experiments and independent evaluation. It lets callers run methods under fixed tasks, data visibility boundaries, and budgets, preserve actual evidence, and compare results against independent references. Algorithms, models, Agents, data sources, and toolsets connect through public interfaces. Integrating projects tests the framework's generality; the final deliverable remains the framework itself.

## The problem it addresses

Time-series experiments often combine data loading, window construction, method calls, environment operations, and scoring. When these steps are mixed into one model script, changing the source or model can inadvertently change the task itself. Failures also make it difficult to establish which data the model actually saw. Retraining or rerunning inference after labels arrive or references change alters the object being compared.

GymTS fixes experiment conditions and execution facts, with evaluation as a separate step. For example, two methods predict the next point from the same public window. Until future values arrive, the report explicitly records insufficient evidence. Once those values are registered, the original predictions are rescored into a new report. Comparison conditions, missing results, and scoring versions remain inspectable, and the original execution is never rewritten.

This applies to numeric forecasting, time-series QA, detection, controlled interaction, and Agent tasks. Each task must declare its inputs, outputs, permitted operations, and evaluation references; the framework does not force every problem into forecasting MAE.

## Who uses it

| User | Main work | Documentation |
| --- | --- | --- |
| Experiment users | Select fixed configurations, run methods, inspect failures, and compare results | [User guide](user-guide.md) |
| Model/Agent developers | Map existing methods to Candidates while preserving native internal workflows | [Adapter development](adapter-development.md) |
| Dataset/benchmark maintainers | Register immutable sources, public views, private references, and scoring policies | [Resource management](dataset-benchmark-catalog-design.md) |
| Environment/tool providers | Adapt native reads, operations, ownership, and call evidence | [Environment integration](environment-adapters.md), [tool responsibilities](agent-toolsets.md) |
| Framework maintainers | Refine public contracts, freeze the core, and verify compatibility with new projects | [Contributing](../CONTRIBUTING.md), [maintainer guide](maintainer-guide.md) |

## Two main modules

**EnvironmentTS owns data organization and storage, execution, and evidence.** It registers static, synthetic, simulation, and external live-testbed sources through one catalog, fixes source versions, dataset snapshots, and lineage, and provides public reads. It organizes a Run, fixes the resolved configuration and component identities, invokes Environment, Task, and Candidate, and preserves observations, inputs, outputs, receipts, errors, and cleanup facts. Actual captured data can then become reusable dataset revisions. Independent adapters still handle specific formats, generators, and service connections.

**AutoBenchTS owns evaluation.** It registers and resolves benchmarks, fixes every expected evaluation unit, organizes the necessary new Runs, passes fixed results and independent references to Scorers, and aggregates metrics, comparisons, and Gates. `score` reads old Runs to create a new report without rerunning Candidates. Failed, missing, and not-yet-started units remain in the plan.

Registration, Schema, storage, artifacts, and DatasetBuilder are shared public SDK capabilities, not a third business-facing main module. See the [framework guide](framework.md) and [API reference](reference.md) for implementation and API details.

## Replaceable roles

| Role | Responsibility | Coupling to avoid |
| --- | --- | --- |
| Source / Environment | Source identity, public data, clocks, reading/advancing/acting, and resource release | Model-specific prompts or private scoring answers |
| Task / TaskSession | Task meaning, windows/turns, public TaskInput, output interpretation, and permitted requests | Silently changing questions or scoring based on model/tool names |
| Candidate | Execution of algorithms, models, pipelines, or Agents, and declared learning capabilities | Unauthorized data, independent evaluation references, or bypassing environment boundaries |
| Scorer | Domain metrics and missing counts under a fixed task contract and independent references | Calling the tested method to regenerate answers, or giving gold to the Candidate |
| Reader / BenchmarkResolver | Reading sources and converting benchmarks into native EvaluationSpec | Creating a separate executor or report system |
| DatasetBuilder provider | Fixed snapshots to training artifacts, with usage and domain token/reward/mask checks | Automatically converting evaluation samples into training data |

One adapter package can register several roles, and several projects can share independent domain contracts. Replaceability means compatible replacement under an explicit protocol. Incompatible tasks, outputs, or units must fail validation rather than silently turn into a different problem.

## An experiment and an evaluation

| Stage | Facts fixed or produced | Key distinction |
| --- | --- | --- |
| Prepare resources | Immutable sources, public views, uses, references, and resource versions | Downloading/freezing is explicit preparation, not a hidden planning side effect |
| Plan and validate | Component descriptions, versions, Schema, capabilities, and access scope | Pure assembly opens no data/models/credentials and does not guarantee runtime availability |
| Execute | Actual observations, inputs, model outputs, operations, and errors of one Run | Failures after opening resources still leave a Run and acquired evidence |
| Seal | RunResult, events, artifacts, and optional Snapshot | Preserve facts from that execution; do not overwrite them with later revisions |
| Evaluate | Fixed units, independent references, scoring policies, metrics, and reports | completed does not mean sufficient evidence or acceptable quality |
| Rescore | A new report under new references or policies | Use the same Run's original outputs without retraining or inference |
| Extend training | Authorized fixed snapshots and training artifacts | External training creates a new identity; the new model needs its own formal evaluation |

Each Run's experiment boundary is fixed by its Task and configuration. A research session can link multiple Runs through a parent trace, but the parent session and child experiments must not become one uninspectable result. Domain profiles further define the unit, such as one HF numeric forecasting sample or one simulation episode. Metrics from different tasks cannot simply be merged for comparison.

## Data, time, and independent references

Source sample time, actual availability time, and decision time are distinct facts. When historical data lacks actual transmission delay, the adapter should declare its assumptions. Live data must preserve receipt time. Final states and rewards are execution evidence: even when they occur at the exact end of the experiment scope, they must not be discarded or used as a reason to act again.

Public observations and private answers are stored separately. The Candidate may access only this experiment's public view. Evaluation-only resources do not automatically authorize training or prepare. Missing labels, unknown rewards, and indeterminate end causes remain explicit; do not insert zeros or shrink the original eligible denominator just to produce a number.

All plugins currently run as trusted in-process Python code. Restricted services form an API access boundary. They cannot prevent malicious Python from accessing the operating system directly; untrusted code needs external isolation. See the [security policy](../SECURITY.md).

## Where Agents and toolsets fit

Toolsets are external capability providers; the Agent decides which calls to make. For computation over already authorized inputs, the Agent SDK can execute tools and record ToolCall. New environment data access or side effects must become Task requests, pass Runner checks, invoke the Environment, and return results to the session.

LibraryTS is one replaceable toolset integration, not a built-in GymTS algorithm platform. ChatTS, TimeSigma, Gymnasium, OpenEnv, and other projects retain their native implementations and runtime dependencies. Acceptance of fixed-action policies, tool wrappers, or Research journals proves those interfaces and evidence, not a completed general autonomous Agent loop.

An upstream Research/workbench, model asset platform, business Agent, or training backend can work with GymTS without automatically becoming a core responsibility. See the [documentation index](README.md) for the original division of responsibilities and [project status](project-status.md) for implemented boundaries. Next-version contracts and enterprise platform designs remain separate proposals.

## How the framework evolves

Try the existing public contracts when integrating each new project. Differences in formats, native APIs, or domain scoring belong in independent adapters. If a shared lifecycle, permission, identity, or evidence concept is genuinely missing, record the real case, why an adapter cannot solve it, the proposed contract change, and regression results for existing projects before changing the core.

Periodically freeze a version and let another independent project complete execution, tracing, independent evaluation, and rescoring without core changes. Interface and project counts are intermediate outputs; preserving real semantics through independent integration is the evidence. The [acceptance index](reports/environment-acceptance-2026-10-19.json) for this round's four source kinds records that verification.
