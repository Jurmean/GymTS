# GymTS CLI and public API reference

Applies to the unreleased GymTS **0.6.0** working tree, formal contract **1.4.0**. This reference lists public entry points in the current implementation, without presenting design drafts as callable APIs. See the [user guide](user-guide.md) for complete workflows and the [formal specification](feishu/GymTS接口规范/GymTS接口规范.md) for fields and plugin lifecycles.

## 1. CLI

After installation, use `gymts` or the equivalent `python -m gymts`. JSON is the default. `.yaml` / `.yml` require the source extra `.[yaml]`.

### 1.1 Global arguments and commands

```text
gymts [--store PATH] [--data-home PATH] [--cache-home PATH]
      [--integration NAME ...] COMMAND ...
```

Global arguments must precede the subcommand. Repeat `--integration` as needed, for example `--integration timeseries --integration libraryts`.

| Argument | Default | Meaning |
| --- | --- | --- |
| `--store PATH` | `.gymts` | Active Run SQLite/CAS root, requiring local POSIX semantics |
| `--data-home PATH` | Environment variable or XDG data directory | Four-kind source definitions, fixed data resources and benchmark manifests |
| `--cache-home PATH` | Environment variable or XDG cache directory | Rebuildable verified resource cache |
| `--integration NAME` | None | Explicitly enable an installed trusted integration; repeatable |
| `--help` | — | Show help; subcommands also support `--help` |

| Command | Arguments | Result and behavior |
| --- | --- | --- |
| `plan SPEC` | `[--output FILE]` | Pure declarative AssemblyPlan; no project runtime resources opened |
| `validate SPEC` | `[--output FILE]` | ValidationResult; no experiment execution |
| `run SPEC` | `[--output FILE]` | Execute one ExperimentSpec and return RunResult |
| `evaluate SPEC` | `[--output FILE]` | Fix an EvaluationSpec plan, execute new Runs, and independently evaluate |
| `score SPEC` | `[--output FILE]` | Evaluate old outputs selected by ScoreSpec without invoking Candidates |
| `attach-outcomes SPEC` | `--run-id ID [--output FILE]` | SPEC is an **array** of OutcomeRecord; append it and return fixed OutcomeSnapshotRef |
| `inspect RUN_ID` | `[--events]` | Read persisted RunRecord; omit events/event_refs by default |
| `plugins` | None | Exact Environment/Task/Candidate/Scorer Manifests currently enabled |
| `run-data SPEC` | `--source ID --source-revision REV --dataset-id ID [--source-config default] [--config default] [--split recorded] [--output FILE]` | Bind source, execute original ExperimentSpec and capture a dataset; returns run/dataset |
| `sources list` | None | List source definitions in data_home |
| `sources register SPEC` | `[--alias LABEL ...] [--output FILE]` | Register DataSourceDefinition without starting a backend |
| `sources info SOURCE_ID` | `--revision REV [--config default] [--output FILE]` | Read a fixed source definition |
| `datasets capture RUN_ID` | `--source ID --source-revision REV --dataset-id ID [--source-config default] [--config default] [--split recorded] [--output FILE]` | Register actual environment data from a sealed Run as dataset v2 |
| `datasets list` | None | Fixed dataset manifests in the current data_home |
| `datasets info DATASET_ID` | `--revision REV [--config default] [--split test] [--output FILE]` | Public DatasetHandle.info, without private references |
| `datasets register SPEC` | `[--alias LABEL ...] [--output FILE]` | Register SourceDatasetRevision; referenced resource bytes must already exist |
| `experiments register SPEC` | `[--output FILE]` | Register an immutable group definition; return defaults and fixed revision |
| `experiments run GROUP_ID` | `--revision REV [--retry-failed] [--rerun STAGE_ID ...] [--output FILE]` | Execute ready stages; retry and rerun require explicit selection |
| `experiments info GROUP_ID` | `--revision REV [--output FILE]` | Derived stage states, all attempts and associated Runs |
| `experiments list` | `[--group-id ID] [--dataset-id ID] [--dataset-revision REV] [--status STATUS] [--output FILE]` | Query group revisions by experiment or dataset |
| `experiments events GROUP_ID` | `--revision REV [--after-seq N] [--output FILE]` | Ordered organization events |
| `experiments recover ATTEMPT_ID` | `--reason TEXT [--adopt-run] [--output FILE]` | Explicitly recover an open attempt after confirming previous work stopped |
| `runs` | `[--group-id ID] [--revision REV] [--attempt-id ID] [--dataset-id ID] [--dataset-revision REV] [--status STATUS] [--output FILE]` | Run summaries retaining original organization and all associations |
| `datasets publish-build SPEC` | `[--output FILE]` | SPEC includes manifest, reader_ref and options; publish fixed build data to the persistent catalog |
| `autobench list` | None | Benchmark definitions in the current data_home |
| `autobench register SPEC` | `[--alias LABEL ...] [--output FILE]` | Register BenchmarkDefinition, resolving and fixing data revisions |
| `autobench resolve BENCHMARK_ID` | `--revision REV --candidate FILE ... [--purpose regression] [--output FILE]` | Invoke an installed resolver and return native EvaluationSpec |

`--purpose` accepts `development` / `regression` / `acceptance`. Each `--candidate FILE` contains one `{"candidate_id": "...", "spec": CandidateSpec}` object; repeat it for multiple candidates. It is not a bare CandidateSpec file. There is currently no separate CLI repetitions option. Use Python `resolve_benchmark(..., repetitions=...)` to specify repetition seeds.

`plugins` lists enabled registries, not every installed integration entry point. Discover installed entry points with Python `GymTS.available_integrations()`. `datasets register` does not import arbitrary local paths, and `autobench register` does not infer domain Tasks/Scorers. Use the appropriate adapter importer, or publish bytes through resource APIs first.

Examples:

```bash
gymts --store /tmp/gymts-ref plan examples/forecast_experiment.json
gymts --store /tmp/gymts-ref validate examples/counter_experiment.json
gymts --store /tmp/gymts-ref run examples/counter_experiment.json --output /tmp/counter-result.json
gymts --store /tmp/gymts-ref plugins
gymts --data-home /tmp/gymts-guide-catalog/data datasets list
gymts --data-home /tmp/gymts-guide-catalog/data datasets info local/guide-series --revision 1.0.0
```

The last two commands require the registration step in the [user guide](user-guide.md#62-从零登记并读取本地数据). Project-specific CLIs such as `gymts-rl`, `gymts-timesigma`, and `gymts-hf-datasets` belong to their adapters; use their README and `--help` for parameters.

### 1.2 Output and exit codes

Configuration-driven commands write formatted JSON to stdout. `--output` additionally saves the same content, creating parent directories as needed. Structured top-level errors go to stderr. `inspect`, `plugins`, `datasets list`, and `autobench list` have no `--output`; use shell redirection.

| Exit code | Current meaning |
| --- | --- |
| `0` | Command handled successfully; neither passing business Gates nor sufficient evidence is guaranteed |
| `1` | Returned object's top-level `status` is `failed` or `cancelled` |
| `2` | Argument/configuration reading or structured service error; also `validate` with `valid=false` |

`argparse` errors also return 2, but help/argument errors are ordinary CLI text, not guaranteed JSON. `evaluate/score` may exit 0 with `status="completed"` and `verdict="fail"` or `"insufficient_evidence"`. Acceptance scripts must inspect both report `status` and `verdict`. `run.status="succeeded"` means execution succeeded; AutoBenchTS reports whether metrics meet requirements.

## 2. Top-level Python SDK

```python
from gymts import GymTS, EnvironmentTS, AutoBenchTS, GymTSError, __version__

with GymTS(root="/tmp/gymts-runs", integrations=(),
           data_home="/tmp/gymts-data", cache_home="/tmp/gymts-cache") as gym:
    ...
```

### 2.1 GymTS

```text
GymTS(root=".gymts", *, register_builtins=True, integrations=(),
      data_home=None, cache_home=None)
```

`root` accepts a path string or Path. Defaults register repeatable reference plugins, not independent project implementations. `integrations` must be a name sequence; registration failure rolls back registry changes. `register_builtins=False` supports fully custom assembly, requiring callers to register all necessary components.

| Method/property | Purpose |
| --- | --- |
| `GymTS.available_integrations()` | Static discovery of installed entry-point metadata without importing implementations |
| `gym.enable_integration(name)` | Explicit trusted integration registration; repeated enablement is idempotent |
| `gym.enabled_integrations` | Tuple of enabled names |
| `gym.plan(spec)` | Delegate to EnvironmentTS.plan |
| `gym.validate(spec)` | Delegate to EnvironmentTS.validate |
| `gym.run(spec)` | Delegate to EnvironmentTS.run |
| `gym.environment_ts` | EnvironmentTS service |
| `gym.autobench` / `gym.autobench_ts` | The same AutoBenchTS instance |
| `gym.records` | Local ExperimentRecords service |
| `gym.artifacts` | Local ArtifactStore |
| `gym.registries` / `gym.schemas` | Public registry/schema services for trusted integrations |
| `gym.close()` | Close records; context-manager support is available |

### 2.2 EnvironmentTS

| Method | Input | Result/failure semantics |
| --- | --- | --- |
| `plan(spec)` | Inline ExperimentSpec | AssemblyPlan; invalid declarations raise GymTSError |
| `validate(spec)` | Inline ExperimentSpec | `{valid, resolved_spec_ref, resolved_spec, issues}`; declaration errors collected in issues |
| `run(spec)` | ExperimentSpec | RunResult; planning errors may raise, runtime errors after establishment generally seal a failed Run |
| `datasets` | DatasetCatalog property | Long-term source data service; see section 5 |

AssemblyPlan fields include `protocol_version="gymts.assembly-plan/1"`, `resolved_spec`, `manifests`, `descriptions`, `variables`, `operations`, `read_scope`, and `resource_checks="deferred_to_open"`. `validate` writes no CAS, keeping null `resolved_spec_ref`. Historical `scene_ref` can be expanded for execution. Offline plan/validate requires inline scenes and cannot read artifacts as a planning side effect.

RunResult preserves `run_id`, `status`, `completion`, start/end times, `resolved_spec_ref`, TaskResult collection `result_ref`, immutable execution `trace_ref`, `summary`, `artifact_refs`, and `errors`. Read result contents using `gym.artifacts.read_json(result["result_ref"])`.

### 2.3 AutoBenchTS

```python
report = gym.autobench.evaluate(evaluation_spec)
new_report = gym.autobench.score(score_spec)
```

`evaluate` fixes every expected case × Candidate × repetition before creating Runs. `score` fixes old-Run selections and references without rerunning Candidates. Configuration validation may raise GymTSError directly. Scorer failures can produce `status="failed"` reports. Plan/report commit failures raise errors containing already committed references.

EvaluationReport contains `evaluation_id`, `status`, `verdict`, `plan_ref`, `run_manifest_ref`, `metrics`, comparisons/Gates, coverage summaries, `evidence_refs`, and `errors`. Retain the complete report and referenced CAS, not just one metric value. A report requires homogeneous task/result/Outcome contracts. Use separate reports for heterogeneous scenarios; a general heterogeneous-suite execution entry point is not implemented.

Benchmark resource methods:

```text
gym.autobench.register_benchmark(definition, *, aliases=())
gym.autobench.list_benchmarks()
gym.autobench.load_benchmark(benchmark_id, *, revision)
gym.autobench.resolve_benchmark(benchmark_id, *, revision, candidates,
                                purpose="regression", repetitions=None)
```

`resolve_benchmark` materializes fixed selected source manifests, usage policies, and BenchmarkDefinition into CAS evidence, then validates the derived EvaluationSpec. It is not the I/O-free `gym.plan`. Resolvers receive a separate evaluation resource service, not Runner/Candidate execution entry points.

### 2.4 Experiment organization

`gym.experiments` organizes the existing execution and data services:

```python
org.register(definition)  # Normalized group definition with fixed revision
org.get(group_id, revision=revision)
org.execute(group_id, revision=revision, retry_failed=False, rerun=())
org.inspect(group_id, revision=revision)
org.events(group_id, revision=revision, after_seq=0)
org.query(group_id=None, dataset_id=None, dataset_revision=None, status=None)
org.recover(attempt_id, reason=reason, adopt_run=False)
org.register_executor(component_ref, executor)  # executor(spec, gym) -> dict
```

Here `org = gym.experiments`. Protocols are `gymts.experiment-group/1`, `gymts.stage-request/1`, `gymts.stage-attempt/1` and `gymts.experiment-event/1`. By default, failed/cancelled/interrupted stages are not retried. retry_failed retries the first two; rerun explicitly repeats selected stages. Recovery occurs at stage boundaries; only gymts.run can adopt its single sealed Run. See the [experiment organization guide](experiment-organization.md) for inputs, JSON Pointers and a complete local example.

## 3. Configuration and message index

Public messages use serializable dict/list/scalar values, not NumPy objects, NaN, or Infinity posing as JSON. Versions must be exact registered versions; `latest/main/master` cannot replace fixed components. Schemas/formal specification define all required fields and defaults.

| Message | `protocol_version` / schema | Complete example/description |
| --- | --- | --- |
| Single experiment | `gymts.experiment/1` | [forecast_experiment.json](../examples/forecast_experiment.json), [counter_experiment.json](../examples/counter_experiment.json) |
| Environment configuration | `gymts.environment/1` | ExperimentSpec.scene.environment; adapter schemas define source/mapping/options |
| New-experiment evaluation | `gymts.evaluation/1` | [forecast_evaluation.json](../examples/forecast_evaluation.json) |
| Old-output scoring | `gymts.score/1` | [forecast_score_template.json](../examples/forecast_score_template.json); insert actual references |
| Reference view | `gymts.view/1` | Fixed source_refs, selection, purpose, and cutoff |
| Outcome | `gymts.outcome/1` | [Late-label workflow](user-guide.md#52-一个可直接执行的晚到标签示例) |
| Source resource manifest | `gymts.source-dataset/1` | Section 5; distinct from training DatasetManifest |
| Benchmark recipe | `gymts.autobench.benchmark/1` | Fixed datasets, resolver_ref, and params |
| Training build | `gymts.dataset-build/1` | Section 6 and the [RL guide](rl-integration.md) |
| Training export manifest | `gymts.dataset/1` | DatasetBuilder's fixed output, shards, and lineage |

Do not interchange identities: `run_id` identifies actual execution; `evaluation_id`, one evaluation; `unit_id`, a fixed evaluation unit; `evaluation_case_id`, a test condition; and Task `case_id`, a task-session case. `candidate_id` is the stable method identity in comparisons. Repetition seeds pass through execution context, not altered Candidate parameters masquerading as different methods.

### 3.1 RecordingSpec

| Field | Values/default | Rule |
| --- | --- | --- |
| `store_ref` | `local` or `local://records/default` | Recognized by current local EnvironmentTS; not a destination directory |
| `inputs`, `outputs` | `full` / `reference` | reference must resolve to a fixed snapshot |
| `artifacts` | `reference` | Fixed artifact references |
| `model_calls` | `none` / `io` / `native_rollout`; default none | Requested capture, not proof of completeness |
| `on_capture_failure` | `fail_run` / `mark_incomplete`; default fail_run | Optional internal-call capture only |
| `redaction_policy_ref` | ArtifactRef/null; default null | Adapter performs actual redaction and records transforms |
| `extra_event_kinds` | Registered kind list; default empty | Extensions do not replace core events |

There is no disable-all-tracing mode. Commit failures for observations, raw outputs, TaskResult, actions, receipts, or other core evidence stop further calls. `mark_incomplete` cannot continue a Run after core evidence loss.

## 4. Trace and artifact APIs

### 4.1 ExperimentRecords

| Method | Result/purpose |
| --- | --- |
| `get_run(run_id)` | RunRecord including metadata, session, preparation, result, resolved_spec_ref, result_ref, events, event_refs, and snapshot references |
| `read_events(run_id, query=None)` | `{events, next_after_seq}`, paginated by durable seq |
| `attach_outcomes(run_id, outcomes)` | Append independent OutcomeRecord list, returning OutcomeSnapshotRef |
| `read_outcomes(query=None)` | Committed OutcomeRecords under the selected fixed query |
| `snapshot(run_ids, query=None)` | RecordSnapshot envelope with snapshot_ref, captured_at, runs, and outcome_refs |
| `get_snapshot(ref)` | Validate/read formal RecordSnapshot |
| `list_outcome_refs(run_id)` | Currently available OutcomeRefs; use snapshot when freezing is required |
| `list_runs(*, group_id=None, revision=None, attempt_id=None, status=None, dataset_id=None, dataset_revision=None)` | Query Run summaries retaining original organization and all associations |

`read_events` query supports `after_seq` (default 0), `limit` (1..1000, default 100), `kinds` (null=all, []=none), and `snapshot_ref`. Pass `next_after_seq` to continue; null ends pagination.

`read_outcomes` query supports `run_ids`, `outcomes_as_of` (compatibility alias `as_of`; choose one), `outcome_refs`, `purpose`, and `snapshot_ref`. A cutoff and explicit revisions are mutually exclusive. With snapshot_ref, do not supply another dynamic cutoff or revision list. Unauthorized purposes raise rather than silently leaking data.

`snapshot` query supports only `through_seq` (run_id→seq), `outcomes_as_of`, and `outcome_refs`: **there is no purpose field**. Defaults capture current committed boundaries and available Outcomes. Prefix snapshots do not expose a final RunResult sealed later.

`gym.experiments.events(group_id, revision=revision, after_seq=0)` reads ordered organization events. Scoring an existing Run adds an association without changing original ownership or sealed evidence.

`begin_run`, `append`, and `end_run` are backend/Runner integration protocols. Ordinary users generate execution records through `run/evaluate/score`, rather than manually fabricating additional execution events for sealed Runs.

### 4.2 ArtifactStore

```python
reference = gym.artifacts.save_json({"example": 1}, "gymts.json/1")
value = gym.artifacts.read_json(reference)
path = gym.artifacts.resolve(reference)
binary_ref = gym.artifacts.save_artifact(b"example", {
    "media_type": "application/octet-stream", "schema_ref": None})
```

`save_json(value, schema_ref)` requires a nonempty schema_ref and publishes canonical JSON. `save_artifact(content, metadata)` accepts bytes only, with finite JSON metadata. These preserve identities and bytes; domain messages still require their schema/contract checks. `resolve` verifies references and actual contents before returning a local Path. It does not accept arbitrary file URLs or unimported external paths. Read schema-less raw bytes through resolve/read_bytes, not `read_json`.

`read_view(DataViewRef)` resolves supported fixed selections: `all`, `json_pointer`, and `rows`. It is not an arbitrary SQL/JSONPath service. The JSON view reader requires `as_of=null`. Apply temporal selection before saving a fixed source, or use another adapter explicitly supporting it. Source grants apply only to exact references, without recursively authorizing all nested artifacts or a disk directory.

### 4.3 TraceCollector (adapter side)

`gymts.contracts.protocols.TraceCollector` is a public structural interface. When `recording.model_calls` is not none and Candidate declares support, Runner injects the collector through `Candidate.prepare(context, training)` as `context["traces"]`, for use inside infer. none mode passes None. This is not a global top-level `GymTS` recorder. The local name `trace` below refers to that collector:

```text
trace.context                      -> 当前 run_id/input_id/output_id
trace.record_model_call(value)      -> 固定 ModelCallArtifact 引用
trace.record_tool_call(value)       -> 固定 ToolCallArtifact 引用
```

Candidate adapters call it within actual infer; do not fake active bindings in ordinary scripts. Model attempts preserve call_id/attempt_id/parent_call_id, component identities, times, status, requests/responses, effective parameters, and capture information. ToolCall preserves actual arguments/results/errors and necessary environment associations. `unknown` means unconfirmed, not failure or success. `native_rollout` also requires native tokens, native_inputs, tokenizer/template, and policy revision. Probabilities separately declare model/sampling distributions and captured/recomputed origins.

Complete implementations exist in [LibraryTS](../adapters/libraryts/README.md), [ChatTS](../adapters/chatts/README.md), and [RL](../adapters/rl/README.md). See [formal specification §10.3](feishu/GymTS接口规范/GymTS接口规范.md#103-modelcallartifact-与-toolcallartifact) for fields.

## 5. Dataset and Benchmark resource APIs

### 5.1 DatasetCatalog

```python
catalog = gym.environment_ts.datasets
asset_ref = catalog.publish_asset(content_bytes, media_type="application/jsonl")
fixed = catalog.register_dataset(manifest, aliases=("1.0.0",))
summaries = catalog.list_datasets()
dataset = catalog.load_dataset(dataset_id, revision="1.0.0",
                               config="default", split="test", purpose="runtime")
```

`publish_asset` returns DatasetAssetRef with exactly `{uri, sha256, size_bytes, media_type}`. `register_dataset` fixes a canonical content revision and verifies usage and all assets. Input manifest revision may be null for the registration service to calculate. Release labels cannot be redirected to another revision. `load_dataset` supports runtime/evaluation/training/prepare/dataset_build purposes and checks the fixed policy.

SourceDatasetRevision fields:

```text
protocol_version, dataset_id, config, revision, schema_ref, reader_ref,
features, splits, usage_policy, source_files, importer_ref,
inputs, series, targets, quality_report_ref, card_ref
```

`splits[name]` is `{row_count, split_origin, input_indices, target_indices}`, indexing corresponding public/private asset lists. Readers/importers use fixed ComponentRef; adapters define raw-format semantics. `usage_policy` is `{allowed_uses, training_allowed}`. Public-input reading or exporter replacement does not grant training permission to evaluation-only data.

### 5.2 DatasetHandle

| Method/property | Result |
| --- | --- |
| `.info` | Public ID/config/revision/split/row count/schema/features/purpose and selection |
| `.features` | Copy of feature descriptions |
| `len(ds)`, `ds[index]`, `ds[start:end]`, `iter(ds)` | Public rows/subviews; negative indexing supported, slices return handles |
| `.select(indices)` | Source-identity-preserving subview, rejecting duplicates/out-of-range indices |
| `.filter(predicate)` | Subview selected by a Python predicate |
| `.iter_batches(batch_size=100)` | List of public rows per batch |
| `.sample_ids()` | IDs for data with a sample_id contract |
| `.read_series()` | Public rows from independent series assets in the manifest |
| `.to_hf()` | `datasets.Dataset.from_list(...)`, requiring HF datasets separately |

Reads validate row counts, schemas, and sample IDs. The first read materializes selected-split shards; this is not a random-access server, lazy streaming query system, or automatic sharded trainer. Public handles have no `read_targets`.

AutoBenchTS exposes the separate evaluation view returned by `resources.datasets.load_dataset(..., purpose="evaluation")` and its `read_targets()` only to the selected benchmark resolver. BenchmarkDefinition fixes permitted datasets. This is authorization for trusted plugin services, not a sandbox for malicious Python.

### 5.3 BenchmarkDefinition

Fields are `{protocol_version, benchmark_id, revision, resolver_ref, datasets, params, card_ref}`. Each dataset reference is `{dataset_id, config, revision, split}`. Resolvers convert these into native EvaluationSpec instead of another executor. They cannot change requested candidates/purpose/repetitions or forge framework provenance.

Registration resolves dataset release labels into precise content revisions. Execution resolution fixes source manifests, policies, and definitions in CAS and propagates them into Run metadata/reports. Changes to data, prompts, selection, scoring rules, or resolver versions require a new definition revision.

### 5.4 Four source kinds and dataset v2

This is an entry-point reference template with caller-supplied variables. See the [user guide](user-guide.md#65-四类来源实际快照与回流) for an executable example. Core public interfaces are implemented and passed frozen-F1 real four-source, portable-read and model-free-rescoring acceptance.

```python
catalog = gym.environment_ts.datasets
source = catalog.register_source(definition, aliases=("1.0.0",))
source = catalog.load_source(source_id, revision=revision, config="default")
sources = catalog.list_sources()
manifest = catalog.load_manifest(dataset_id, revision=revision, config="default")
manifest = catalog.register_snapshot(
    rows, dataset_id=dataset_id, source_ref=source_ref, split="test", config="default",
    schema_ref="gymts.json/1", targets=None, parents=(), usage_policy=None,
    features=None, split_origin="explicit", attachments=(), capture=None, aliases=(), kind=None,
)
bound = catalog.bind_source(spec, source_id, revision=revision, config="default")
manifest = catalog.capture_run(
    run_id, source_id=source_id, revision=revision, dataset_id=dataset_id,
    config="default", source_config="default", split="recorded", event_kinds=None,
    usage_policy=None, aliases=(),
)
result = gym.run_data(spec, source_id=source_id, revision=revision, dataset_id=dataset_id,
                      source_config="default", config="default", split="recorded")
```

`definition` uses `gymts.data-source/1`; `source_ref` is `{source_id,config,revision}` and each `parents` entry is `{dataset_id,config,revision,split}`. Snapshot registration resolves labels to exact content digests. Source kinds are static/synthetic/simulation/live_testbed. Synthetic sources have a recipe and can be seeded (requiring a seed) or recorded. Declared and actual session seeds remain separate records.

`register_snapshot` returns `gymts.source-dataset/2`, retaining v1 public/private shard fields and adding kind/origin/lineage/attachments. `load_manifest` reads complete v1/v2 manifests. The public `load_dataset` handle additionally offers `read_capture()`, `read_asset(asset_ref)` and `resolve_payload(value)`. Capture metadata uses `gymts.data-capture/1`; environment-event rows use `gymts.data-capture-row/1`.

`bind_source` accepts a complete ExperimentSpec, checks its existing Environment provider/configuration and returns a copy with fixed source, parents and common usage policy in provenance. It does not modify the input spec. `run_data` returns `{"run": RunResult, "dataset": manifest}` and preserves the real Task/Candidate. `capture_run` accepts a sealed Run; by default it records environment session/request/observation/operation/receipt/feedback with failed/partial results, excluding model conversations and private Outcomes. Actual JSON/binary attachments enter data_home, so snapshot reads do not depend on the original Run CAS.

Data services add no alternate executor or scorer. Benchmark `/1` can fix v1/v2 datasets, with evaluation still handled by AutoBenchTS. See [ADR 0001](adr/0001-core-data-source-catalog.md) for rationale and existing-contract compatibility.

### 5.5 Explicit build-data publication

```python
catalog.publish_build(build, reader_ref=reader_ref, dataset_id=None,
                      config="default", usage_policy=None, parents=(), aliases=())
```

Publish an original `gymts.dataset/1` Manifest, a return object with manifest_ref, or its ArtifactRef as a persistent `gymts.source-dataset/1`. Preserve original shard bytes and private portable build evidence without inventing a source. Adapters provide readers. Default training usage may only narrow, without automatically adding runtime/evaluation. See the [publication workflow](experiment-organization.md).

## 6. Training dataset construction extensions

```python
from gymts.training import build_dataset, DatasetBuilderRegistry

# spec 必须是有效且已固定的 DatasetBuildSpec；由相应领域适配包提供。
# manifest = build_dataset(spec, gym.records, gym.artifacts)
```

The actual signature is `build_dataset(spec, records, artifacts, *, builders=None)`. Defaults lazily discover installed `gymts.dataset_builders` entry points by fixed builder_ref. Supply your own DatasetBuilderRegistry to register providers explicitly.

Providers declare `builder_ref`, `target_formats`, `output_schema_refs`, and `build(spec, records, artifacts)`. Inputs are fixed RecordSnapshots. Outputs are formal `gymts.dataset/1` Manifests with shards, counts, tokenization, rewards, and lineage references. The framework validates contracts and usage; domain providers own selection, pairing, row layouts, and masks. Adapters separately reuse trainers. No generic `gym.train()` API exists.

See the [RL README](../adapters/rl/README.md) for executable preparation, sampling, dataset building, and checkpoint evaluation commands for current rollout/TRL training. Do not give evaluation-only source Runs to another provider to evade training restrictions.

## 7. Structured errors and retries

```python
from gymts import GymTSError

try:
    # gym.plan(spec)、资源读取或其他服务调用
    pass
except GymTSError as error:
    print(error.code, error.stage, error.info)
```

`GymTSError.info` fields are `code, stage, method, message, run_id, links, retryable, side_effect`. `side_effect` is `none` / `possible` / `confirmed`. Network errors or `retryable` flags alone do not justify resending potentially executed device actions. Retain logical operation and actual attempt identities; decide recovery from receipts or backend deduplication guarantees.

Common codes include `invalid_config`, `schema_mismatch`, `unsupported_capability`, `permission_denied`, `conflict`, `recording_failure`, and `capture_incomplete`. Storage can additionally return `artifact_integrity`, `persistence_failed`, `invalid_query`, and others. Handle structured fields rather than matching English message strings. Failed Runner/AutoBenchTS results also require inspecting errors, not only catching exceptions.

## 8. Versions, trust, and interface stability

Distribution versions, message schema versions, project component versions, and data content revisions are different identities. Historical F1 core 0.5.1 corresponds to specification 1.3.0. This round's 0.6.0 / 1.4.0 working tree adds four organization protocols while retaining existing execution and data-resource identities. This does not mean the complete [v2 Runtime contract](pluggability-contract-v2.md) is implemented.

User entry points are this reference's SDK/CLI, `gymts.contracts`, public Protocols, Registry, schemas, and training extensions. Project-private helpers do not promise public compatibility. New adapters depend one way on public SDKs, without importing Runner private state. See the [developer guide](adapter-development.md) for extensions and migration.

Execution and storage are currently synchronous and local. Cross-tenant isolation, malicious-code sandboxes, remote Hubs, complete distributed Runtimes, forced interruption of blocking calls, and general autonomous Agent tool execution are not implemented capabilities. Arrange experiments from actual adapter capabilities rather than assuming support from a project name.
