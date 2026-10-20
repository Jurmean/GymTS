# GymTS project adapter packages

The final deliverable is the GymTS framework. Real project integrations test public contracts, expose gaps, and guide framework corrections; project adapters and resources ship independently. The current core is `gymts==0.5.0`, implementing formal interface specification 1.2.0. The five original adapters are 0.2.0; TSQA and the five new source/domain packages are 0.1.0. All depend on `gymts>=0.5,<0.6`, for eleven independent adapters in total. The public SDK ships with the core, while shared domain contracts remain separate packages. Pure assembly, a minimal resource catalog, and new RL checkpoint evaluation are implemented; the complete v2 Runtime remains a proposal.

## Roles and dependencies

```text
实验配置 ──选择──> Source / Task / Candidate / Scorer / DatasetBuilder
                       │             │
                       ├──单向依赖──> GymTS 公开 SDK
                       └──按需依赖──> 独立领域合同

GymTS
  EnvironmentTS：源数据目录、执行、访问边界、Run、轨迹、制品与快照
  AutoBenchTS：benchmark 登记/解析、评价计划、独立评分、比较、Gate 与报告
  公共注册、版本、错误、训练构建与资源存储服务
```

| Deliverable | Directory and module | Contents |
| --- | --- | --- |
| `gymts` | Repository root / `gymts` | Two main modules, public SDK, trajectories, storage, training builds, and resource catalog services |
| `gymts-timeseries` | [timeseries](timeseries/README.md) / `gymts_timeseries` | Neutral numeric JSON/CSV Sources, seven Tasks, parsing, independent Scorers; no specific model dependency |
| `gymts-libraryts` | [libraryts](libraryts/README.md) / `gymts_libraryts` | Ten real tools from the specified NetmanAIOps/sktime source, native loading, Naive/Polynomial Candidates, forecasting Scorers |
| `gymts-chatts` | [chatts](chatts/README.md) / `gymts_chatts` | ChatTS data reading/generation, internal model codecs, time-series/text HTTP, legacy QA contract compatibility |
| `gymts-timesigma` | [timesigma](timesigma/README.md) / `gymts_timesigma` | Native data/Schemas, detectors, preprocessing, scoring, tools, and Research parent trajectories |
| `gymts-rl` | [rl](rl/README.md) / `gymts_rl` | GSM8K/ChatTS data, HF policies, rewards, native exporters, TRL, immutable checkpoints, independent Scorers |
| `gymts-bench-tsqa` | [bench_tsqa](bench_tsqa/README.md) / `gymts_bench_tsqa` | Five evaluation-only QA resource imports, Parquet, original-question-preserving Task/codec/Scorer, BenchmarkDefinition resolver |
| `gymts-hf-datasets` | [hf_datasets](hf_datasets/README.md) / `gymts_hf_datasets` | Fixed HF Hub sources, save_to_disk, local-file freezing; public numeric forecasting views, private references, benchmark resolver |
| `gymts-interaction` | [interaction](interaction/README.md) / `gymts_interaction` | Independent neutral JSON control contracts, Tasks, example policies, sealed-event Scorer; no native-project dependency |
| `gymts-gymnasium` | [gymnasium](gymnasium/README.md) / `gymts_gymnasium` | Owned Gymnasium instance reset/step/close, reusing the external interaction contract |
| `gymts-openenv` | [openenv](openenv/README.md) / `gymts_openenv` | Official SDK persistent WS sessions, raw request/response evidence, reusing the interaction contract |
| `gymts-prometheus` | [prometheus](prometheus/README.md) / `gymts_prometheus` | Read-only attached live metrics, PromQL, receipt times, historical caches; owns no Task, model, or Scorer |
| Resources and experiment configurations | External resource packages or deployment directories | Versioned cards/benchmark definitions, data and weight references, budgets, recipes |

The core neither imports project packages nor contains project-name branches; adapters do not depend on private core implementations. Multiple projects may share a domain package, but sharing is not a reason to move it into the core. RL calls upstream ChatTS numeric generation functions without depending on `gymts-chatts`.

A data Source supplies only numeric values and explicitly public source facts. The Task determines the question, output meaning, parsing, and visibility boundaries; the Candidate’s model codec constructs native requests. ChatTS uses this neutral path by default, with old `/1` IDs, schemas, and behavior retained through `--legacy`. Default canonical questions form a separate derived-prompt experiment; manifests/reports explicitly distinguish them from original benchmark prompts, while original materials remain source evidence. Existing benchmark task constraints must not change casually: changing the task requires a new view and independent references.

LibraryTS uses the user-specified [NetmanAIOps/sktime](https://github.com/NetmanAIOps/sktime) commit `080f4c3c3695f239e328548bac7d7a3ef7aa9127`, not a substitute PyPI sktime. Methods, generators, data operators, and scoring implementations integrate into their corresponding roles; LibraryTS implementation versions and individual Run Candidate instances are recorded separately. Real native APIs are connected. The toolset’s unified asset registration/publication remains an external project responsibility; GymTS provides generic references and interfaces. The two current numeric methods fit and predict only on each authorized input window, reuse no cross-call state, and access no future labels; they are not claimed to be persistent pretrained weights.

Deployment configurations supply data, weights, upstream checkout, and scientific-interpreter paths. `/zzr/models` is a local resource, not a global protocol default. Active SQLite/CAS/training output uses local POSIX storage; sealed archives may reside on shared or object storage. Data and weights are not bundled in the core wheel.

## Installation and activation

Install only what you need. Installing shared contracts does not install project models:

```bash
python -m pip install .
python -m pip install ./adapters/timeseries
python -m pip install ./adapters/libraryts ./adapters/chatts
python -m pip install './adapters/timesigma[runtime]'
python -m pip install './adapters/rl[runtime]'
python -m pip install './adapters/bench_tsqa[runtime]'
python -m pip install './adapters/hf_datasets[runtime]'
python -m pip install ./adapters/interaction './adapters/gymnasium[runtime]'
python -m pip install ./adapters/openenv ./adapters/prometheus
```

Packages expose entry points through `gymts.integrations`. Discovery reads only metadata; explicit activation registers components. It does not automatically load models, train, or download data.

```python
from gymts import GymTS

print(GymTS.available_integrations())
with GymTS('/tmp/gymts-records', integrations=('timeseries', 'libraryts')) as gym:
    pass
```

A project entry point can register the domain components it declares as dependencies without a core project table. Duplicate plugin names raise errors; failed registrations roll back. Removing an adapter does not delete old trajectories. Executing that project or rescoring its old Runs requires the original contract implementation, while the core and other independent packages continue working. `[runtime]` belongs only to the corresponding adapter; prepare native source and scientific interpreters according to each README.

Gymnasium/OpenEnv calls explicitly enable `('interaction','gymnasium')` or `('interaction','openenv')`; HF and Prometheus use `hf-datasets` and `prometheus`. Gymnasium 1.2.1 and the official native OpenEnv environment used here require Python 3.10+. Installing an adapter does not start a server. See the [environment guide](../docs/environment-adapters.md) for invocation, storage, permissions, and evidence boundaries across four source types.

The 0.3.x paths `gymts.integrations.chatts/timesigma/rl` become independent modules `gymts_chatts/gymts_timesigma/gymts_rl`. The core does not forward them. Existing component/Schema/builder/mask and committed evidence IDs retain their identities. New neutral protocols use new identities rather than presenting new source as an old implementation.

## Declarative assembly and resource boundaries

Environment/Task providers supply pure `factory.describe_spec(spec)` or a registered `describe=`. Additional restrictions use `compatibility=` or `factory.check_compatibility_spec(context)`. `gym.plan/validate` constructs no components, reads no data/models/credentials, connects to no services, and commits no CAS objects. Old plugins without pure descriptions cannot fall back to instance construction. `run` opens resources and verifies declarations/content only after establishing a Run; failures retain available evidence. Static success proves neither resource availability nor a general worker Runtime.

Source dataset reading belongs to `gym.environment_ts.datasets`; benchmark registration/resolution belongs to `gym.autobench`. Independent resource packages publish fixed source manifests, Dataset Cards, quality reports, and BenchmarkDefinitions. Domain resolvers return native EvaluationSpecs rather than running candidates or inventing another report type. `data_home` holds persistent original/derived assets and manifests; `cache_home` holds rebuildable caches; the Run root still holds SQLite/CAS. Installation and activation do not import attachments automatically.

The five attachments were explicitly registered by `bench-tsqa` as 5 `test/user_declared_evaluation` datasets with 19,354 rows; training, prepare, and dataset_build are prohibited. Public DatasetHandle supports indexing, select/filter, and iter_batches without exposing raw/targets or answer references. Benchmark evaluation services read private references separately. Original questions, conditions, choices, numeric series, and duplicate rows remain intact; unresolved references remain missing and eligible. Complete 746-row Python/CLI reads, native evaluate, and original-Run rescoring passed validation. The first-public-choice baseline checks integration only, not real model quality or execution of all 19,354 rows. See [TSQA notes](bench_tsqa/README.md) and [acceptance](../docs/reports/bench-tsqa-full746-final-2026-10-20.json).

## Training extensions and formal evaluation

The core exposes `gymts.training.build_dataset(spec, records, artifacts)`, `DatasetBuilderProvider`, and `DatasetBuilderRegistry`. Providers are selected at exact versions through `gymts.dataset_builders`; the service validates fixed references, target formats, and consistency between BuildSpec/CAS and DatasetManifest. Independent providers validate concrete token/mask/reward/sample lineage; the framework does not define an RL row layout.

RL’s `NativeRolloutBuilder` implements existing native-trajectory export; the old two-argument helper remains compatible. TRL receives published shards through `rollout_provider` and artifact services, retaining upstream GRPO loss, backward, and optimizer implementations. Small CPU model tests verify real parameter updates instead of testing mirrored substitutes for upstream training. No new training framework was added; verl, multi-round, and distributed backends remain unadapted.

Formal evaluation always belongs to AutoBenchTS `evaluate/score`. Existing RL `rl-qa-scorer` and `gymts-rl score` support old evaluation Runs, independent references, explicit Gates, and revised references without reloading models; training heldout summaries do not become formal reports. RL now publishes one archive with fixed base identity, adapter/config, tokenizer/processor, and training lineage. A new-process Candidate loads it through `artifact`; execution seeds do not change candidate identity. Native evaluate supports repeated identical seeds and zero-inference rescoring without falsely merging historical identities. [Full engineering acceptance](../docs/reports/rl-checkpoint-loop-2026-10-20.json) includes two real TRL updates and 28 sealed Runs, with actual accuracy=0.0 and format_valid=0.5; technical Gates examine only execution and coverage. Effective tiny-model training uses only two official GSM8K train questions; ChatTS data was really prepared and independently evaluated, and the five attachments were not used for training. This is not fresh acceptance of large models or every processor.

The ChatTS workbench, shared ChatTS FM, and this package have separate responsibilities on the [project website](https://netman.aiops.org/contacts/projects/). This package does not implement the entire workbench or FM. AutoResearchTS on the website corresponds to the higher-level responsibilities of local LabTS/callers; this is not an asserted name migration. Package releases, asset publication, and business-Agent updates are separate; evaluation reports do not automatically update shared models.

## Validation and future integrations

```bash
python -B scripts/check_release.py --output /tmp/gymts-core-check.json
python -B scripts/check_adapters.py --output /tmp/gymts-adapter-check.json
```

Checks require local setuptools/wheel and build all wheels/sdists plus source rebuilds offline. Each package installs independently outside the checkout in a clean environment, resolving dependencies only from a local wheelhouse, and checks discovery, activation, CLI, regressions, removal, and rescoring old core Runs. The earlier six-package [distribution check](../docs/reports/adapter-package-check-2026-10-20.json) remains preserved. All eleven packages passed independent builds/installation/simultaneous activation/removal in the [new distribution check](../docs/reports/environment-adapter-package-check-2026-10-19.json); native zero-skip acceptance for new sources is described in the [environment guide](../docs/environment-adapters.md). Native-project and large-model tests require explicit opt-in and do not call paid services. Historical acceptance remains intact; see [this round’s validation](../docs/component-replacement-validation-2026-10-19.md) for current versions, eight real combinations, native calls, and training extensions.

For future projects, compare real semantics with the current specification first and use a minimal real experiment to locate gaps. Formats, task interpretation, and native APIs belong in external adapters; shared domain semantics belong in independent contract packages. Extend the core only for gaps in lifecycle, permissions, identity, trajectories, or evaluation organization, retaining existing-project regressions. Completed integration must verify compatible role replacement, invalid-combination rejection, independent delivery, removal, and historical rescoring. The minimal catalog, pure assembly, and RL checkpoint chain are delivered. Full v2 lifecycles, general isolated/remote Runtimes, real Agent loops over replaceable toolsets, and more training profiles/backends still require acceptance. External LibraryTS asset platforms and higher-level Research/Memory orchestration remain independent. After fixing concurrent immutable resource alias publication, the final same-version core, 746-row benchmark, RL checkpoint chain, TimeSigma 75 native tests, and LibraryTS 10 native tests were revalidated; see [this round’s delivery](../docs/framework-delivery-2026-10-20.md) for exact identities and scope.

## Agents invoke toolsets

LibraryTS and other toolsets are replaceable external providers. The tested Agent selects tools within Task/configuration permissions; a native SDK or platform executes through adapters and returns results to the Agent. GymTS provides public interfaces, experiment environment boundaries, call correlation, and evidence storage. It neither requires a particular toolset nor internalizes projects because an adapters directory shares its repository.

Existing tool wrappers, fixed-algorithm Candidates, and Research journals retain their separate acceptance results. They do not prove autonomous Agent tool selection and continued reasoning. Route input-local computation, additional environment I/O, orchestration outside Runs, and private scoring according to actual effects; see [tool responsibilities and status](../docs/agent-toolsets.md).
