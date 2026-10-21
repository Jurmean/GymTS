# Adapter development guide

This guide is for developers integrating projects, sources, tasks, algorithms, models, or Agents with GymTS. It targets current `gymts==0.6.0` and formal specification `1.4.0`. The [interface specification](feishu/GymTS接口规范/GymTS接口规范.md) and [public Python protocols](../gymts/contracts/protocols.py) define complete message fields; lifecycle tables below use current implementation signatures.

Deliver an independent package that depends one way on GymTS public interfaces. Core need not import your project or add project-name branches. Callers choose compatible sources, tasks, methods, and scorers. The repository's `adapters/` directory is only the source location of independent packages, not a declaration that projects are built into the framework.

## 1. Decide which role to implement

The four core workflows are storing data, connecting data, organizing experiments, and recording experiments. EnvironmentTS owns data organization and storage for four source kinds, execution, and evidence; AutoBenchTS owns benchmarks and independent evaluation. Specific formats, generators and service connections, native backend calls, and domain scoring stay in adapters. Use the public interfaces in the [experiment organization guide](experiment-organization.md) for multistage definitions, fixed inputs/outputs, dependencies, and attempts. External executors call existing execution/evaluation APIs rather than adding another scheduler. Current [F2.1 acceptance](reports/experiment-organization-2026-10-21.json) preserves the content hashes of all 23 existing schemas and verifies independent integration, record queries, and rescoring after adapter removal.

| Need | Implementation | Boundary to reuse |
| --- | --- | --- |
| Read static/generated data, advance simulations, connect live sources | Environment | Source, scope, clock, observation, and action protocols |
| Define windows, questions, targets, turns, action meaning, and completion | Task / TaskSession | Public TaskInput, CandidateOutput, TaskResult, and TaskRequest |
| Invoke an algorithm, model, pipeline, or Agent | Candidate | Current TaskInput and restricted resources; native SDKs may compose internally |
| Derive domain metrics from independent references or sealed events | Scorer | AutoBenchTS fixed results, references, and event snapshots |
| Decode resource assets into records | DatasetReader | Precisely authorized asset references |
| Resolve reusable benchmark definitions into executable evaluations | BenchmarkResolver | Native EvaluationSpec, without a separate evaluation loop |
| Export training datasets from fixed experiment trajectories | DatasetBuilder | RecordSnapshot, DatasetBuildSpec, DatasetManifest |
| Supply tools to an Agent | External tool / Agent SDK adaptation | Agent decisions, actual execution evidence, and environment permissions |

One package may implement one or several roles. Adding a model does not require copying readers, Tasks, and Scorers. Domain contracts may also ship independently, as with `gymts-timeseries` and `gymts-interaction`: the contract package does not depend on a specific model or service; implementations depend on it.

An ordinary algorithm Candidate runs its algorithm directly. An Agent Candidate lets the Agent choose tools, arguments, and how to consume results. LibraryTS, MCP, and similar toolsets are replaceable external capabilities, not fixed core components. See [external toolsets and Agents](agent-toolsets.md) for full responsibilities.

## 2. Your first independent package: add one Candidate

[minimal_demo](../examples/adapters/minimal_demo/README.md) is a runnable teaching package implementing time-scale-aware drift forecasting. It reuses the existing replay Environment, `window_forecast`, and `forecast-mae`, without framework additions, private labels, network access, or a model.

```text
examples/adapters/minimal_demo/
├── pyproject.toml                       # 独立发行包与 entry point
├── README.md
├── rescore_without_adapter.py           # 卸载后只依赖 GymTS 的评分检查
└── src/gymts_minimal_demo/
    ├── __init__.py                      # register(registries, schemas)
    ├── candidate.py                     # Candidate 生命周期
    └── __main__.py                      # 原生运行、独立参考、同 Run 重评
```

Install from a full checkout with Python 3.9+:

```sh
python -m venv /tmp/gymts-adapter-tutorial-env
/tmp/gymts-adapter-tutorial-env/bin/python -m pip install . ./examples/adapters/minimal_demo
cd /tmp
/tmp/gymts-adapter-tutorial-env/bin/python -I -m gymts_minimal_demo \
  --root /tmp/gymts-adapter-tutorial-runs
```

Use a new run directory. The teaching package is excluded from core wheel/sdist; run the installation command from the repository root. A production integration can use its own repository, build wheels, and publish to its own index. Do not assume all adapters are on PyPI.

Checks cover pure planning without Candidate construction, actual `evaluate`, explicit `insufficient_evidence` without references, `score` after references from an independent linear function, repeated scoring with inference forbidden, and unchanged Run IDs, original RunResult, and event digests. Expected fixture MAE is `0.0` for drift and `1.0` for last-value. This verifies integration, not forecasting quality.

### 2.1 The three names are independent

| Name | Tutorial value | Purpose |
| --- | --- | --- |
| Python distribution | `gymts-minimal-demo==0.1.0` | Installation, upgrade, removal |
| integration entry point | `minimal-demo` | Explicitly enable a set of registrations |
| Component reference | `example-drift@1.0.0` | Fix the selected implementation and compatible protocol for an experiment |
| Parameter schema | `example.minimal/drift-params/1` | Validate the component's JSON parameters |

Fixed versions cannot use `latest`, `main`, or `master`. Distribution versions, protocol versions, and semantic component versions are different identities.

### 2.2 Discovery and activation

`pyproject.toml` declares:

```toml
[project.entry-points."gymts.integrations"]
minimal-demo = "gymts_minimal_demo:register"
```

Registration only registers schemas, manifests, and factories:

```python
def register(registries, schemas):
    schemas.register(PARAMS, parameter_schema)
    registries.candidates.register(manifest, CandidateClass)
```

Callers discover, then select explicitly:

```python
from gymts import GymTS

print(GymTS.available_integrations())
with GymTS(root="/tmp/my-runs", integrations=("minimal-demo",)) as gym:
    candidate_spec = {
        "adapter": "example-drift", "version": "1.0.0",
        "artifact": None, "params": {"damping": 1.0}, "inherited_state": [],
    }
```

Installation does not activate the integration. Metadata discovery does not import plugin code; explicit enablement executes registration. Duplicate entry-point names conflict rather than selecting by installation order. Re-enabling a name does not register it twice. The framework rolls back registration state on failure, but cannot undo the plugin's own filesystem/network side effects; registration must therefore be side-effect-free.

### 2.3 Manifests must declare actual capabilities

Candidate manifests contain fixed `component_ref`, `implementation_ref`, `component_refs`, supported protocols and input/output schemas, parameter schema, and `supports_fit`, `fit_requires_targets`, `supports_update`, `model_revision_mode`, and `capture_profiles`. The teaching package declares no training, updates, model artifacts, or internal model-call capture.

Do not claim unsupported capabilities to pass composition checks. Supporting one input shape does not support every similarly named time-series task. Sending a seed does not prove backend enforcement. IO does not imply native tokens, logprobs, or training-weight identity.

See the [tutorial registration](../examples/adapters/minimal_demo/src/gymts_minimal_demo/__init__.py) for a complete example, and [public Registry](../gymts/registries/__init__.py) for Environment, Task, and Scorer manifest fields.

### 2.4 Candidate lifecycle

```python
prepare(context, training) -> PreparationResult
infer(task_input) -> CandidateOutput
update(feedback) -> UpdateResult
finish() -> list[ArtifactRef]
```

The factory receives CandidateSpec at runtime. `prepare` receives this Run's restricted `resources`, `learning`, independent randomness context, and optional `traces`. Pure algorithms reject training/updates under `load_only/frozen`. Load models at runtime, not during import, registration, or pure planning callbacks.

`infer` handles authorized TaskInput only. Use public `gymts.plugin_support.unpack(payload, resources)` for inline/authorized artifact payloads, and `payload(schema_ref, value)` to form outputs. Outputs must link the original `input_id` and `task_protocol_ref` and record actual `produced_at` and `model_revision`. Do not create Run IDs yourself or give methods the full GymTS, records, private dataset directory, or Environment instance.

`finish` releases resources this Candidate created and returns retained artifact references. Preserve acquired evidence after partial failure. Each Run uses an independent session. Cross-Run inheritance requires explicit fixed references, not hidden updates in globals or shared model caches.

## 3. Data and Environment adapters

### 3.1 Declare before opening

Current API:

```python
describe_spec(environment_spec) -> EnvironmentDescription  # 纯声明回调
check_compatibility_spec(context) -> None                   # 可选，纯校验

describe() -> EnvironmentDescription
start(environment_start) -> SessionInfo
observe(observation_request) -> ObservationBatch
act(environment_command) -> ActionReceipt
finish() -> EnvironmentSummary
```

Pure Environment/Task `describe_spec` callbacks support planning. Independent `describe=` and `compatibility=` callbacks can also be supplied during Registry registration. Candidates may offer pure compatibility checks; current planning does not require Candidate `describe_spec`.

Pure callbacks inspect JSON configuration and declared capabilities only: no runtime construction, source files, credentials, connections, model loading, or CAS writes. Successful `validate`/`plan` means configuration and declaration compatibility. File existence, service availability, and model loading are checked at runtime after establishing the Run; failures enter the actual failed trace.

EnvironmentSpec `source.kind` supports `dataset`, `generator`, `simulator`, and `live`. Only declared capabilities may be used. Static datasets must not masquerade as controllable simulators, and attached services must not claim reset or seeded reconstruction of the world.

### 3.2 Separate source facts from task meaning

Source descriptions own raw variables, types, shapes, units, available scopes, operations, clock domains, and advancement modes. `mapping` parses source fields. `binding` maps source variables/operations to Task public variables/operations, with explicit transforms. Windows, horizons, questions, label meaning, reward interpretation, and scoring standards belong to Task or Scorer.

Public observations preserve timestamps, valid masks, cursors, progress/waiting/end state, context, and source identity. Static QA uses sample cursors rather than fabricated business event time. Large arrays and native formats may use ArtifactRef; the framework does not require everything to become text.

Environments can receive exact input grants through `source.connection.artifact_refs`. The framework does not recursively grant every nested reference, nor automatically pass them to Candidates. Current-input permission does not grant access to source files, future data, or private answers.

### 3.3 Clocks, cursors, and final state

| Concept | Development requirement |
| --- | --- |
| `clock.domain` / `clock.now` | Express actual event_time, wall_time, or step semantics without moving backward |
| `visible_until` | Delivered-information frontier, not expanded by waiting or arbitrary history queries |
| `event_time` / `available_at` | Separate occurrence from actual knowledge; state when original ingestion time is unknown |
| `cursor` | Actual progress position; waiting does not advance secretly |
| Half-open scope | GymTS uses `[start, end)`; adapters translate differing backend endpoint semantics |
| Empty windows and ending | Distinguish progressing empty windows, immature waiting, normal end, and failure |
| Final transition | Preserve final observation, actual reward, and cause even on termination or a scope boundary |

EnvironmentSummary must include `session_id`, `actual_scope`, `last_cursor`, `final_clock`, `end`, `counts`, `pending_operations`, `artifact_refs`, and `backend_disposition`. `counts` contains batches, points, operations, late_points, and dropped_points; unstarted fields may be null. `backend_disposition` is only `closed`, `detached`, or `not_started`. Do not substitute a project-specific string for a formal enum; keep detailed cleanup results in a separate evidence artifact.

### 3.4 Execute actions exactly once

For control backends, `act` should invoke one native step, cache the actual transition, and return the operation-linked receipt. Subsequent `observe` consumes the cache without another step. If cancellation occurs between act and observe, preserve the occurred but unconsumed transition; do not call it unexecuted or a complete episode.

Timeouts or disconnection do not prove the action failed to take effect. Record unknown/uncertain states without automatic resend. Retry only when the backend explicitly supplies verified idempotency keys and guarantees. TaskRequest, environment_request_id, operation_id, and receipts must associate actual execution.

Separate natural termination, backend truncation, and experiment scope truncation. If OpenEnv supplies only `done`, preserve it with unknown classification rather than guessing Gymnasium `terminated`. When the backend provides no reward, retain `null` and let Scorer report missing evidence; do not insert zero.

See the reusable external [gymts-interaction](../adapters/interaction/README.md) implementation. It remains outside core; Gymnasium/OpenEnv adapters may reuse its cache and neutral control contracts.

### 3.5 Ownership and live reproducibility

Distinguish sessions this Run creates from hosts it attaches to. Owned simulation instances can be closed; connecting to someone else's service does not authorize killing it in finish. Closing your WebSocket does not imply owning the remote service. Local services created by a test script are cleaned up by that script after verification, not by an overprivileged generic adapter.

A caller-declared deployment version is not a verified deployment identity. Dynamic source revisions do not make future values immutable. Record which facts are verified or declared, actual requests/responses, and receipt times. Freeze a static snapshot before comparing Candidates fairly on the same field data. Sequential live Runs do not replay the same world time.

The [environment guide](environment-adapters.md) records current implementations and actual calls: HF numeric snapshots, Gymnasium, persistent OpenEnv sessions, and read-only Prometheus scraping. Each package README describes supported and rejected capabilities.

## 4. Task adapters: preserve public task contracts

```python
describe_spec(task_spec) -> TaskDescription
describe() -> TaskDescription
bind(task_spec, binding, environment_description, execution) -> TaskSession

# TaskSession
next_observation() -> ObservationRequest
consume(batch) -> TaskUpdate
on_action(receipt) -> TaskUpdate
interpret(task_input, candidate_output, output_id) -> TaskEffect
finish(reason) -> TaskSummary
```

TaskDescription declares task protocols, input/output/result/reference/alignment schemas, required variables and operations, warmup, and capabilities. Tasks use public Environment descriptions and Bindings, without inspecting source Python class names, model names, or project names.

TaskSession converts public observations to TaskInput and interprets CandidateOutput into domain results or TaskRequest. Requests for new data or actions must follow TaskRequest → Runner checks → Environment, returning actual observations/receipts to the same session. Tasks do not correct model outputs using answers or directly compute final benchmark conclusions.

Public contracts need more than JSON shapes: units, time indexes, valid masks, targets, end conditions, and multi-turn semantics are required. Similar fields do not imply interchangeable tasks. Add versions or explicit adaptation when semantics change, instead of reinterpreting old inputs as a new task.

## 5. Scorers: independent evaluation and rescoring

```python
score(results_view, outcomes_view, context) -> ScoreResult
```

AutoBenchTS fixes Scorer inputs. Use `context["services"]` to read authorized result/reference artifacts, align under the declared rules, and compute metrics. To verify actual control-episode return, read fixed `event_snapshot_ref` and validate the action/receipt/transition chain; do not trust Candidate-reported return.

Each metric declares direction, unit, reference requirements, and eligibility contract. Fix the eligible denominator before reporting scored, missing, invalid, and excluded counts. Missing labels, unknown end causes, and uncaptured rewards must remain insufficient evidence; dropping difficult samples must not improve coverage. Scorers output measurements and evidence only; AutoBenchTS applies configured grouping/aggregation, coverage thresholds, comparisons, and gates.

`evaluate(EvaluationSpec)` creates new Runs and evaluates them. `score(ScoreSpec)` selects existing sealed Runs and creates a new report. Rescoring may use newly arrived but explicitly fixed references or a new Scorer version. Record previous_evaluation_id, reference cutoff, component versions, and all selections. Never alter old predictions, RunResult, or reports, nor rerun inference, training, steps, or live requests for scoring.

Rescoring after uninstalling the tutorial method:

```sh
GYMTS_CHECKOUT=/absolute/path/to/Jurmean-GymTS
/tmp/gymts-adapter-tutorial-env/bin/python -m pip uninstall -y gymts-minimal-demo
/tmp/gymts-adapter-tutorial-env/bin/python -I \
  "$GYMTS_CHECKOUT/examples/adapters/minimal_demo/rescore_without_adapter.py" \
  --root /tmp/gymts-adapter-tutorial-runs --require-absent
```

This script restores only the archived Candidate manifest and parameter schema, registering a factory that raises if execution is attempted; it does not restore the algorithm. Current AutoBenchTS still needs declarations for compatibility checks even without method invocation. The example's Task contract and Scorer remain available. In general, if these contracts and the Scorer are also removed, restore decoding/scoring support from an independent contract package or the original version archive. No original model does not mean no declarations or original contracts.

## 6. Dataset catalog and benchmark extensions

The resource catalog is neither a new execution engine nor a complete Hugging Face Hub. Current local services provide versioned assets, dataset definitions, public reads, and benchmark resolution, without a remote portal, accounts, hosted uploads, or search service. See [catalog design](dataset-benchmark-catalog-design.md).

### 6.1 DatasetReaderProvider

```python
read(resources, assets) -> list[dict]
registries.datasets.register(fixed_reader_ref, reader_instance)
```

This is a format-decoding hook, not a full importer. `resources.read_asset(ref)` / `local_asset(ref)` permit only selected assets. JSONL and Parquet readers already exist; new formats can register fixed readers in independent packages. Return actual row order and schema without silently dropping, deduplicating, or altering rows.

Importers explicitly parse/validate outside Runs, separate public inputs/private targets, and publish assets through `gym.environment_ts.datasets.publish_asset(...)` and `register_dataset(manifest, aliases=...)`. Source-dataset manifests declare features, splits, source_files, inputs, series, targets, reader/importer references, and usage policy. Content revisions are fixed; release aliases are entry labels only.

Public `load_dataset(..., purpose="runtime")` does not return private answers. Training requires separate authorization. `EvaluationDataset.read_targets()` is available only through the benchmark-resolution evaluation service. Raw files may also leak answers; do not pass source_files paths to Candidates by default. Using data for evaluation does not authorize training, even when the filename contains `rlvr`.

### 6.2 BenchmarkResolverProvider

```python
resolve(definition, resources, candidates, purpose, repetitions) -> EvaluationSpec
registries.benchmarks.register(fixed_resolver_ref, resolver_instance)
```

Benchmark definitions fix dataset/config/revision/split, resolver_ref, and task parameters. Resolvers load only selected evaluation data, build Environment/Task/cases from public rows, and derive independent Outcome views from private references. Preserve caller-supplied candidates, purpose, and explicit repetitions. Do not create another model loop or second formal report system.

```python
spec = gym.autobench.resolve_benchmark(
    "my/benchmark", revision="fixed-release",
    candidates=selected_candidates, purpose="regression",
    repetitions={"count": 1, "seeds": [7]},
)
report = gym.autobench.evaluate(spec)
```

AutoBenchTS owns source-use intersections, resource provenance, and native plan checks; resolvers must not overwrite provenance. See the [HF resolver](../adapters/hf_datasets/src/gymts_hf_datasets/benchmark.py) and [bench-tsqa](../adapters/bench_tsqa/README.md).

## 7. Training exports and reuse of existing backends

The training export entry point is public `gymts.training.build_dataset(spec, records, artifacts)`; projects implement independent DatasetBuilders. This is not a third core business module alongside EnvironmentTS/AutoBenchTS, nor automatic model updating.

```python
class MyBuilder:
    builder_ref = {"name": "my.rollout-builder", "version": "1.0.0", "origin_ref": None}
    target_formats = ("my-fixed-format",)
    output_schema_refs = ("my.training-row/1",)

    def build(self, spec, records, artifacts):
        ...  # 读取固定快照，保存 shard、血缘、排除摘要，返回正式 Manifest。
```

Publish a provider through a separate entry-point group:

```toml
[project.entry-points."gymts.dataset_builders"]
"my.rollout-builder" = "my_package.builder:MyBuilder"
```

Alternatively, explicitly register instances with `DatasetBuilderRegistry(discover=False)` and pass `builders=` to build_dataset. This registration does not use `gymts.integrations`: builders are separately selected and loaded by the fixed builder_ref in DatasetBuildSpec.

Builders declare target formats/schemas, verify selected trajectories, training permission, reward origins, token/mask semantics, and lineage, then output DatasetManifest, shard references, build_spec_ref, lineage_ref, exclusion_summary_ref, and counts. The framework checks public envelopes, fixed identities, source uses, and artifact/Manifest consistency. Adapters validate domain masks/rewards. Missing capture cannot be fabricated as native tokens/logprobs.

RewardRecord must derive from an explicit environment, verifier, human, or specified rule; a trace is not itself a reward. Changing builders cannot turn evaluation-only data into training data. Reuse external TRL/verl implementations where possible. Native models, processors, optimizers, checkpoint publication, and training journals belong in training adapters. See [RL integration](rl-integration.md) and [gymts-rl](../adapters/rl/README.md) for current workflows.

## 8. Model and tool-call evidence

During infer, Candidates can use `context["traces"]` to submit actual `record_model_call(...)` / `record_tool_call(...)`, as enabled by recording configuration and supported capture profiles. The framework binds current Run/input and preallocated output identities. Formal schemas preserve original requests/responses, attempts, status/errors, versions, and actually available measurements.

Multiple tools associate native call IDs, parent_call_id, and attempt_id. A model's tool_call is intent only; actual tool success, failure, or unknown state must be recorded separately. Ordinary computation may omit environment operation_id; new environment reads/actions must associate TaskRequest and actual Runner requests/operations. Tool calls must not bypass future-data/private-reference boundaries.

Preserve known failures and partial evidence; save raw returns before decoding. Do not replace failure with an empty success, or invent tokens, cost, effective backend seeds, or deployment digests. Obtain credentials only at runtime through explicit providers or environment-variable names; never put values in configuration, URLs, CAS, logs, or examples.

API restrictions form a responsibility contract for trusted in-process plugins, not an OS sandbox. Installing/enabling third-party Python means trusting its code. Use external processes, containers, or services for isolation when needed, and separately verify resource/network boundaries.

## 9. Compatible upgrades and independent distribution

Adapters import only public interfaces such as `gymts.contracts`, `gymts.contracts.schema`, `gymts.plugin_support`, and public catalog/training entry points. Do not depend on `_common`, Runner state, or project-private classes. Shared domain contracts should be independent declared dependencies, never reverse dependencies that make core import projects.

Production adapters generally retain their own pyproject/setup configuration, README, license information, tests, examples, runtime extras, and fixed compatibility ranges. Merely installing/discovering core must not load heavy scientific dependencies, native SDKs, models, or service binaries. Core must still import, run reference cases, and rescore old evidence without a model environment.

Upgrades create new semantic versions while retaining old references and evidence. Do not bulk-rename historical protocol IDs or rewrite sealed records. New implementations may support old contracts or explicitly reject incompatible combinations. Source/Task/Candidate/Scorer replaceability depends on contracts, units, shapes, permissions, seeds/clocks, and actual execution, not successful registration alone.

Before release, at minimum:

1. Build wheel and sdist, rebuild a wheel from sdist, and check for keys, models, experiment databases, or undeclared assets.
2. Install into a clean environment outside source directories. Verify discovery without runtime SDK imports, explicit activation, and pure-plan rejection of invalid configurations/role combinations.
3. Exercise a minimal actual backend and preserve success, failure, final-state, and cleanup evidence. Protocol fixtures cannot impersonate native backend acceptance.
4. Evaluate with independent references. Forbid further model/backend calls before rescoring the same Runs, comparing IDs, results, and event digests.
5. Replace compatible roles and test independent source/task/method composition. Other projects and core cases must keep working after uninstalling one project.
6. Verify declared minimum Python, missing optional dependency paths, compatibility ranges, and README commands.

The repository's [adapter check script](../scripts/check_adapters.py) performs isolated builds, activation, removal, and coexistence for formal packages under `adapters/*`. The teaching package lives under `examples/`, uses the independent native smoke commands above, and is not counted as a production adapter.

## 10. When core changes are justified

First demonstrate what the current contract cannot express with a minimal real project, then determine whether it is a cross-project responsibility. Data fields, model SDK differences, PromQL, Gymnasium space conversion, and backend done/reward semantics usually belong in project adapters or external domain contracts. Do not add named core branches for individual projects.

Every core change must record:

| Required item | Question to answer |
| --- | --- |
| Actual requirement and minimal reproduction | Which running project and valid operation cannot currently be expressed? |
| Why adapters are insufficient | Is authorization, association, scheduling, or immutable evidence controlled by the framework missing? Why is this not a domain-format issue? |
| Minimal public change | Which cross-project interface/field is added, and which roles will actually use it? |
| Compatibility | How are defaults, old callers, protocol references, Runs, and Scorers preserved? |
| Verification | Where is evidence of native execution, old-project regressions, failure cleanup, evaluation, and same-Run rescoring? |
| Frozen baseline | What are the core version, source digest, exact wheel SHA256, adapter version, and native backend version? |

Periodically freeze an exact core wheel and let another project install, run, trace, independently evaluate, and rescore through an independent package without changing core. Record both the no-core-change claim and actual digest checks. If there is a real gap, update decisions, versions, and compatibility tests before freezing again. Installation success is not domain compatibility; an algorithm experiment does not establish autonomous Agent tool-loop acceptance.

## 11. Current interfaces versus design drafts

This guide uses the current Environment/Task/Candidate/Scorer API. Parts of the [pluggability design](pluggability-design.md) and [v2 draft](pluggability-contract-v2.md), including `SourceProvider.open`, Method/Runtime separation, and ToolBroker, are proposed directions, not implemented functions to copy and call.

Core currently has no general ToolBroker or accepted general autonomous Agent tool loop. External Candidates can use native Agent SDKs and connect through current public request/evidence protocols. If a real requirement cannot be expressed, record and discuss a minimal extension as described above. Documentation must not turn unimplemented drafts into release commitments.
