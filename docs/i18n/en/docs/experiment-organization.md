# Experiment Organization and Dataset Publication

This page describes the GymTS **0.6.0** working tree and public interface specification **1.4.0**, not a released version. GymTS focuses on four responsibilities: store data, connect data, organize experiments and record experiments. This guide connects fixed data references, execution stages and the persistent catalog into one inspectable chain. See [ADR 0002](adr/0002-experiment-organization.md) for the reasons for core changes and compatibility rules.

## Three Distinct Identities

| Identity | Represents | Changes when |
| --- | --- | --- |
| Fixed dataset / source revision | Registered data contents or a source definition | Data, a recipe or fixed source configuration changes |
| Fixed experiment-group revision | Stages, dependencies, input bindings, configuration and output selection | The experiment definition changes |
| Stage attempt | One actual stage invocation | Every invocation, including a retry, adds an attempt |

A stage can create one Run, multiple evaluation Runs or only publish data. An attempt records what that stage did; Runs continue to retain environment-execution events. Neither replaces the other.

EnvironmentTS owns data, execution and evidence; AutoBenchTS owns evaluation and rescoring. `gym.experiments` and `gym.environment_ts.experiments` refer to the same organization service connecting existing entry points. Adapters retain domain formats, model calls, conversions and scoring.

## Storage Locations

```text
<data_home>/
  objects/sha256/                 Persistent data and manifest-referenced bytes
  sources/...                    Source definitions
  datasets/...                   Fixed dataset revisions
  autobench/benchmarks/...        Benchmark definitions

<run_root>/
  records.sqlite3                Runs, events and experiment organization indexes
  artifacts/blobs/...            Immutable configurations, outputs and reports
  artifacts/refs/...             Artifact references
```

`cache_home` contains only rebuildable caches. Registering data or an experiment does not download models, start services or call paid models. Keep active SQLite and artifacts on local storage with normal filesystem transaction semantics; these examples use `/tmp`.

## Define an Experiment

An experiment definition uses `gymts.experiment-group/1`. Each stage declares:

| Field | Meaning |
| --- | --- |
| `stage_id` | Unique name within the experiment |
| `executor_ref` | Fixed ComponentRef for the execution entry point |
| `depends_on` | Stages that must succeed first; a `stage_output` input adds its dependency automatically |
| `purpose` | Data use for this stage; built-in evaluate/score default to evaluation, publish-build to dataset_build, and others to runtime |
| `spec` | The configuration already required by that entry point |
| `inputs` | Fixed data, sources, artifacts or upstream stage outputs |
| `bindings` | JSON Pointers writing named inputs into `spec` |
| `outputs` | JSON Pointers selecting named outputs from the return object |

Binding pointers start at `spec` itself, such as `/candidate/artifact`, without a `/spec` prefix; parent containers must exist. Output pointers start at the executor's return object, such as `/run_id`; an empty string `""` selects the whole returned object. JSON Pointers select or bind values. They do not convert HF rows into time-series windows or transform a checkpoint for another backend. An external executor or adapter performs such conversions and saves fixed artifacts.

Registration fixes dataset and source revisions. Before execution, the service resolves inputs and saves this attempt's configuration, then calls the existing execution service. Named return values become inputs of later stages without manual artifact-reference copying.

## A Local Example

Install core and run from the repository root:

```bash
python -m pip install .
python examples/experiment_organization.py --work /tmp/gymts-organization-demo
```

The [complete example](../examples/experiment_organization.py) registers 12 public ramp observations, then executes five stages: forecast → capture / outcomes → score → rescore. One real Run supplies two independent scoring passes; the repeated execution adds no attempts and the original RunResult stays unchanged. Source-dataset queries find the group. Two short external executors handle the public-row projection and construction of independent outcome references. No external model or online service is required. This local example does not establish a new frozen-core acceptance baseline.

The following minimal Run registration and query example is directly executable from the repository root. An existing complete ExperimentSpec does not need conversion into another execution protocol.

```python
import json
from pathlib import Path
from gymts import GymTS

spec = json.loads(Path("examples/forecast_experiment.json").read_text())
with GymTS("/tmp/gymts-group-runs", data_home="/tmp/gymts-group-data") as gym:
    definition = gym.experiments.register({
        "group_id": "demo/forecast",
        "name": "Local forecast experiment",
        "stages": [{
            "stage_id": "forecast",
            "executor_ref": {
                "name": "gymts.run", "version": "1.0.0", "origin_ref": None},
            "spec": spec,
            "outputs": {"run_id": "/run_id", "result": ""},
        }],
    })
    revision = definition["revision"]
    state = gym.experiments.execute("demo/forecast", revision=revision)
    print(state["status"], state["stages"][0]["outputs"]["run_id"])
    print(gym.experiments.query(group_id="demo/forecast"))
```

`register` fills defaults and resolves explicit resource aliases to content revisions. Save its returned `revision` and use it explicitly with `get/execute/inspect`.

## Inputs, Bindings and Executors

`inputs` is a named object. Its four reference shapes are below; the relevant services return the actual IDs, revisions and ArtifactRefs.

```python
inputs = {
    "data": {"kind": "dataset", "ref": {
        "dataset_id": "local/example", "config": "default",
        "revision": fixed_dataset_revision, "split": "test"}},
    "source": {"kind": "source", "ref": {
        "source_id": "local/example-source", "config": "default",
        "revision": fixed_source_revision}},
    "artifact": {"kind": "artifact", "ref": artifact_ref},
    "previous": {"kind": "stage_output", "stage_id": "previous-stage", "output": "result"},
}
```

Declared inputs fix identity and check usage. Their manifests and restrictive combined policy propagate through the attempt context to nested Runs and evaluation plans, including custom executors calling the supplied services. These provenance references do not grant private resources to a Candidate. `bindings` selects values to write into the execution configuration. For example, a capture stage receives an upstream Run ID with these fields:

```python
{
    "inputs": {
        "run": {"kind": "stage_output", "stage_id": "forecast", "output": "run_id"}
    },
    "bindings": {"run": "/run_id"},
    "outputs": {"dataset": ""},
}
```

The pointer addresses the capture stage's `spec`. Binding does not perform domain-format conversion.

| Fixed executor | `spec` and actual entry point |
| --- | --- |
| `gymts.run@1.0.0` | Original ExperimentSpec → `gym.run`; declared source inputs bind source and usage evidence |
| `gymts.evaluate@1.0.0` | Original EvaluationSpec → `gym.autobench.evaluate` |
| `gymts.score@1.0.0` | Original ScoreSpec → `gym.autobench.score` |
| `gymts.capture@1.0.0` | `run_id`, `source_ref`, `dataset_id` and capture options → `datasets.capture_run` |
| `gymts.publish-build@1.0.0` | `manifest`, `reader_ref` and publication options → `datasets.publish_build` |

Every ComponentRef includes `name`, `version` and `origin_ref`. For adapter-specific steps, call `gym.experiments.register_executor(reference, executor)` with an `executor(spec, gym) -> dict` callable. Register required executors again in a new process. Return a JSON-serializable object. Create Runs through the supplied `gym` services so the framework can associate them with the current attempt.

## Execution, Failure and Continuation

The organization service creates an attempt for every actual stage invocation. Success retains fixed returned values; failure retains the error and any Runs already created. Stages with unmet dependencies do not execute.

By default, another execution runs only ready stages that have not executed or have become stale. It skips successful, failed and interrupted attempts. Explicitly select retry or rerun:

```python
# Retry failed / cancelled stages without repeating successful ones.
gym.experiments.execute(group_id, revision=revision, retry_failed=True)

# Rerun one stage; downstream stages depending on its old attempt become stale.
gym.experiments.execute(group_id, revision=revision, rerun=["forecast"])
```

Old attempts, Runs and reports remain available. Changes to data, configuration or dependencies require a new definition revision. Continuation occurs at stage boundaries, not by restoring Python objects or an evaluation matrix's internal execution position.

A process interruption can leave an attempt marked running. Confirm that the old process and related backends have stopped, then explicitly recover:

```python
gym.experiments.recover(attempt_id, reason="Previous worker has stopped")
gym.experiments.execute(group_id, revision=revision, rerun=[stage_id])
```

Default recovery records the attempt as `interrupted`, after which a rerun must be explicit. If a `gymts.run` stage sealed exactly one Run but failed to write its stage completion record, use `recover(attempt_id, reason=..., adopt_run=True)` to adopt that Run and its outputs without executing it again. Other executors do not support this adoption path.

Recovery updates organization state. It does not establish that a remote operation stopped or take over an old Run's internal cursor.

## Publish Built Data to the Persistent Catalog

Keep the existing fixed-evidence build entry point:

```python
from gymts.training import build_dataset

built = build_dataset(build_spec, gym.records, gym.artifacts)
```

Its returned `gymts.dataset/1` describes this build: input RecordSnapshots, build configuration, output shards, rewards, tokenization and lineage reference Run CAS. The persistent catalog uses a different resource: `gymts.source-dataset/1` or `/2`. Explicit publication copies necessary bytes into `data_home` and registers a discoverable dataset revision.

A build without a real source definition uses `/1`. For a genuine registered source, existing snapshot or capture entry points can register `/2`. Adapters provide readers; choose one matching the shard format before publication.

Direct publication is below. `built` can be the original Manifest, a build return object including `manifest_ref`, or that Manifest's ArtifactRef. The reader must match the original shard format.

```python
published = gym.environment_ts.datasets.publish_build(
    built,
    dataset_id="local/derived-data",
    reader_ref=reader_ref,
    aliases=("1.0.0",),
)
rows = gym.environment_ts.datasets.load_dataset(
    published["dataset_id"], config=published["config"],
    revision=published["revision"], split="train", purpose="training",
)
```

The signature is `publish_build(build, *, reader_ref, dataset_id=None, config="default", usage_policy=None, parents=(), aliases=())`. Publication preserves original shard bytes. Private `source_files` retain portable build evidence and an index from original artifacts to persistent assets; public reads do not expose that original evidence. Original references remain available for verification, while dataset reads no longer depend on the original Run root.

Publication defaults to training use and may narrow it further. It does not automatically add runtime or evaluation authorization. Evaluation-only data cannot become training data through publication, and generated labels do not become human gold. Private references retain their separate read boundary.

## Query an Experiment Chain

Query saved identities rather than paths embedded in log text:

- Inspect stages, all attempts, resolved configuration, errors and named outputs by group and revision.
- Find the Runs created by an attempt, then inspect their existing events and sealed results.
- Find experiments and Runs by fixed dataset; source definitions and actual capture relationships remain in stage inputs and dataset manifests.
- Follow output references to original evaluation reports and independently rescore through the existing ScoreSpec path.

Public query entry points are:

```python
state = gym.experiments.inspect(group_id, revision=revision)
groups = gym.experiments.query(
    dataset_id="local/derived-data", dataset_revision=fixed_dataset_revision)
runs = gym.records.list_runs(
    group_id=group_id, revision=revision, status="succeeded")
events = gym.experiments.events(group_id, revision=revision, after_seq=0)
```

`inspect` includes stages, all attempts and linked Runs. Each attempt's `request_ref` points to `gymts.stage-request/1`, fixing binding status, executor, purpose, inputs, configuration, datasets and provenance. A binding failure also leaves a request with `binding_status="failed"`. `result_ref` fixes the returned object; `outputs` retains named results. `query` filters by group_id, dataset_id/dataset_revision or group status. Dataset filters also match parent references explicitly recorded in output dataset manifests: source-dataset/2 lineage.parents and official source-dataset/1 build publications' features.parent_datasets. They do not recursively search arbitrary payloads. `list_runs` also filters by attempt_id, Run status and dataset. Ordered organization `events` do not replace the internal Run trace. Run summaries distinguish their original `organization` from `associations`: scoring an older Run adds an association without changing its original ownership, sealed result or events.

A successful stage means its entry point completed according to its contract. AutoBench coverage, missing/invalid counts, metrics and Gate verdicts remain evaluation facts; organization does not override them.

## Existing Entry Points Remain Available

`gym.run(spec)`, `gym.run_data(...)`, `gym.autobench.evaluate(...)`, `gym.autobench.score(...)` and data-catalog methods remain usable independently, without registering an experiment group.

Historical Runs without organization links remain readable, scoreable and rescoreable. New indexes neither change old events nor present historical Runs as products of a new attempt.

F1 is the historical GymTS 0.5.1 / interface 1.3.0 frozen baseline. These organization additions belong to the 0.6.0 / 1.4.0 working tree and require separate frozen identities and verification evidence. F1 four-source acceptance does not verify every new behavior on this page.


## F2.1 Verification Record

The [2026-10-21 machine-readable report](reports/experiment-organization-2026-10-21.json) fixes the F2.1 wheel/source identities, unchanged definitions of all 23 existing schemas, 196 installed core regressions and sixteen-package compatibility with 356 passes and 61 optional-dependency skips. Source distributions and rebuilt wheels also passed installation checks.

An [independent CSV adapter example](../examples/adapters/organization_demo/README.md) registered a 32-row ETTh1 view against the frozen core, completed four stages and two real Runs, independently reproduced numerical scores, and rescored in fresh processes and after adapter uninstall. Runtime core files, original Run results and events stayed unchanged. No quality gates were configured, so its verdict remains insufficient_evidence; this is neither the full ETT benchmark nor a model-quality acceptance claim.

Built data remained readable after deleting its original Run directory. Parent-dataset queries were verified with the exact F2.1 wheel. The initial F2 query omission, two adapter-configuration failures and subsequent successful evidence remain preserved. Closed evidence was archived locally and verified after extraction through file hashes, CAS/resource assets and another independent rescore; runtime environments and caches are excluded from source uploads.
