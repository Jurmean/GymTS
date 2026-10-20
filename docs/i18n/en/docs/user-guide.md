# GymTS user guide

This guide is for users installing, running, and comparing methods with **GymTS 0.5.0 / interface specification 1.2.0**. Run commands from the repository root unless stated otherwise. The minimal workflow uses only Python's standard library and local deterministic data, without GPUs, model accounts, or external services.

The [formal specification](feishu/GymTS接口规范/GymTS接口规范.md) is authoritative for interface fields. See the [reference](reference.md) for CLI options and Python methods, the [developer guide](adapter-development.md) for new project adapters, and the [adapter directory](../adapters/README.md) for native dependencies and package-specific commands.

## 1. What GymTS does

GymTS separates an experiment into independently replaceable data environments, tasks, and tested methods, and stores execution facts separately from evaluation references.

| Object | Role | Examples |
| --- | --- | --- |
| Environment | Supply scoped observations, execute authorized actions, report clocks and end causes | Static sequences, simulation steps, external WS sessions, read-only metrics |
| Task | Define public inputs, output meaning, environment requests, and result alignment | Window forecasting, QA, interactive control |
| Candidate | Produce outputs as an algorithm, model, pipeline, or Agent | last-value, local models, external inference services |
| Scorer | Compute metrics from sealed outputs and independent references | MAE, answer accuracy, episode return |
| Dataset | Reusable fixed data resource | Public questions, private references, usage policies |
| Benchmark | Recipe fixing data, tasks, and evaluation rules | Candidate comparison on a fixed test set |

**EnvironmentTS owns execution and evidence; AutoBenchTS owns evaluation and rescoring.** Core does not embed LibraryTS, ChatTS, TimeSigma, or their models, formats, and domain scoring. Independent adapters provide these capabilities. The tested Agent chooses tools; its SDK/adapter executes calls while the framework records associations and evidence. See [Agent and tool responsibilities](agent-toolsets.md).

`run` creates a new experiment, `evaluate` creates and evaluates a fixed set of new experiments, and `score` evaluates specified old outputs only. Rerunning a model and rescoring its original results are different operations.

## 2. Installation and checks

### 2.1 Install from source

This documentation uses source installation and does not assume a PyPI release.

```bash
git clone https://github.com/Jurmean/GymTS.git
cd GymTS
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -c 'import gymts; print(gymts.__version__)'
gymts --help
```

If you already have the source directory, enter it and start with virtual-environment creation. Python **3.9+** is required; the local records backend needs Linux/macOS POSIX filesystem operations. Core JSON workflows have no third-party runtime dependencies. pip/setuptools handle builds and installation; build tools must come from the local environment or an available index. Prepare tools and wheels in advance for fully offline deployment.

Install optional format support as needed:

```bash
python -m pip install -e '.[yaml]'
python -m pip install -e '.[datasets]'
```

`yaml` adds PyYAML. `datasets` adds PyArrow for local Parquet reading and is **not** an alias for Hugging Face `datasets`. For `DatasetHandle.to_hf()`, install `datasets` separately or use the HF adapter's runtime dependencies.

### 2.2 Install and enable adapters

Installation provides entry-point metadata; explicit enablement registers capabilities. For example:

```bash
python -m pip install . ./adapters/timeseries ./adapters/chatts
gymts --integration chatts plugins
```

```python
from gymts import GymTS

print(GymTS.available_integrations())
with GymTS(root="/tmp/gymts-chatts-runs", integrations=("chatts",)) as gym:
    print(gym.enabled_integrations)
```

`integrations` is a sequence of names: even one item must be `("chatts",)`, not a string. An adapter may depend on other independent domain packages; use the installation combination in its README. Prepare scientific interpreters, weights, and native services as directed. Installing a lightweight package does not provide a complete native runtime.

## 3. Your first complete run

```bash
python examples/quickstart.py --root /tmp/gymts-first-run
```

The script verifies the complete workflow:

1. Window forecasting on a linear synthetic series.
2. 3 actual actions in the counter environment.
3. Formal evaluation of two Candidates, returning `insufficient_evidence` before truth is available.
4. Attaching independent truth and rescoring original Runs, with MAE 1 and 2.
5. Checking unchanged Run IDs and original RunResult before and after scoring.

Successful output includes `counter_operations: 3`, `rescored_verdict: "pass"`, `same_run_ids: true`, and `original_results_unchanged: true`. Executions generate different Run IDs; use the actual IDs from your run. `/tmp` is convenient for trials but may be cleared by the system. Use durable local disk for long-term retention.

## 4. Validation, planning, and a single experiment

### 4.1 Plan before execution

```bash
gymts --store /tmp/gymts-guide-runs plan examples/forecast_experiment.json \
  --output /tmp/gymts-guide-plan.json
gymts --store /tmp/gymts-guide-runs validate examples/forecast_experiment.json
gymts --store /tmp/gymts-guide-runs run examples/forecast_experiment.json \
  --output /tmp/gymts-guide-run.json
```

`plan` resolves defaults, fixes component versions, checks declarations and composition constraints, and returns variable/action bindings and `read_scope`. It does not instantiate project Environment/Task/Candidate objects, open data/models/network connections, or submit a plan to CAS. Constructing `GymTS` itself still initializes local storage directories. `validate` returns `valid`, `issues`, and inline `resolved_spec`, with null `resolved_spec_ref`. Save plans using CLI `--output` or persist the returned value yourself.

A valid plan does not prove that files exist, models load, or services connect. Resources open after the Run is established; opening failures enter the failed Run's trace. `run` returns RunResult. Check `status` first, then `completion`, `errors`, and `summary`; receiving a `run_id` alone does not establish success.

### 4.2 Equivalent Python calls

```python
import json
from pathlib import Path
from gymts import GymTS

spec = json.loads(Path("examples/forecast_experiment.json").read_text())
with GymTS(root="/tmp/gymts-guide-sdk") as gym:
    check = gym.validate(spec)
    if not check["valid"]:
        raise ValueError(check["issues"])
    plan = gym.plan(spec)
    result = gym.run(plan["resolved_spec"])
    print(result["run_id"], result["status"], result["completion"])
    if result["status"] != "succeeded":
        raise RuntimeError(result["errors"])
```

One `GymTS` instance may execute multiple Runs. Use `with` to close the records store when finished. Do not pass one SQLite connection across processes.

### 4.3 Understanding ExperimentSpec

[forecast_experiment.json](../examples/forecast_experiment.json) is a complete executable configuration. Its top-level structure is:

| Field | Controls | When changing it |
| --- | --- | --- |
| `protocol_version` | Message contract, currently `gymts.experiment/1` | Distinct from distribution version 0.5.0 |
| `name`, `purpose` | Name and intended use | Purpose affects prepare/training authorization |
| `scene.environment` | Source, field mapping, clocks, and operation capabilities | `source.kind` is a source category; the adapter defines its semantics |
| `scene.task` | Task plugin and parameters | Task defines windows, inputs, and result meaning |
| `scene.binding` | Task variable/action bindings to the Environment | Units, types, and operation schemas must be compatible |
| `candidate` | Exact version, model artifact, parameters, and inherited state | Replace models here rather than changing Task or Runner |
| `execution` | batch/stream/interactive, start mode, scope, seed, learning, and limits | Reject reset/seed requests unsupported by the Environment |
| `recording` | Input/output and internal-call evidence policies | Core execution evidence cannot be disabled |
| `extensions` | Explicit extension fields | Do not bypass contracts or secretly pass private labels |

Time windows use `[start, end)`; `end: null` needs effective limits that guarantee termination. Temporal scopes use timezone-aware strings, while simulation steps use nonnegative integers; do not mix clock domains. UTC examples look like `2026-01-01T00:00:00Z`. Durations require units such as `1min` or `500ms`; a step is not implicitly one second.

`execution.learning.prepare="load_only"` does not fit persistent weights, and `online="frozen"` does not invoke weight updates. Training requires explicit `fit`, fixed training views, and permitted feedback, supported by both Candidate capabilities and data usage. An Agent retaining conversational context within a Run does not itself update model weights.

Set at least one reachable stopping boundary: finite `scope.end`, `max_inputs`, `max_operations`, or `max_wall_time_s`. An action-count bound alone cannot constrain live waiting. Synchronous wall limits are checked at call boundaries; backends also need I/O timeouts of their own.

## 5. Evaluation, late labels, and original-output rescoring

### 5.1 Evaluate new experiments

```bash
gymts --store /tmp/gymts-guide-evaluation evaluate examples/forecast_evaluation.json \
  --output /tmp/gymts-guide-evaluation.json
```

This configuration has 1 case, 2 Candidates, and 1 repetition, fixing 2 expected units. The plan is saved before the first Run. Failed and unstarted units remain in its manifest; removing them must not inflate coverage. The current example has no labels, so the workflow can complete with `verdict` equal to `insufficient_evidence`.

`EvaluationReport.status` describes workflow completion; `verdict` reports the conclusion from metrics, evidence requirements, and Gates. CLI exit 0 does not guarantee a passing Gate. CI integrations must read report fields, for example:

```bash
python - <<'PY'
import json
from pathlib import Path
report = json.loads(Path("/tmp/gymts-guide-evaluation.json").read_text())
print(report["status"], report["verdict"])
# acceptance CI 可采用：
# raise SystemExit(0 if report["status"] == "completed" and report["verdict"] == "pass" else 1)
PY
```

Inspect each metric's own eligible/scored/missing/invalid counts and coverage. Missing labels are not zero error; undefined rewards are not zero reward. Even with an average value, check whether evidence covers the samples required by the plan.

### 5.2 An executable late-label example

This script derives independent truth from the example synthetic source definition, without reading Candidate predictions to construct labels. It preserves real planned unit identities, attaches labels, and builds ScoreSpec. Run the complete block from the repository root:

```bash
python - <<'PY'
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from gymts import GymTS
from gymts.contracts import digest, inline, utc_now

evaluation = json.loads(Path("examples/forecast_evaluation.json").read_text())
with GymTS(root="/tmp/gymts-guide-late-labels") as gym:
    first = gym.autobench.evaluate(evaluation)
    plan = gym.artifacts.read_json(first["plan_ref"])
    manifest = gym.artifacts.read_json(first["run_manifest_ref"])
    units = {unit["unit_id"]: unit for unit in plan["expected_units"]}
    run_ids = [entry["run_id"] for entry in manifest["entries"]]
    before = {run_id: digest(gym.records.get_run(run_id)["result"]) for run_id in run_ids}

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    def stamp(index):
        return (start + timedelta(minutes=index)).isoformat().replace("+00:00", "Z")
    truth = [{"timestamp": stamp(index), "value": index} for index in range(12)]
    source_ref = gym.artifacts.save_json(truth, "gymts.json/1")
    outcomes = []
    for index in range(11):
        alignment = {"entity": "demo", "variable": "value",
                     "issued_at": stamp(index), "target_time": stamp(index + 1)}
        outcomes.append({
            "outcome_id": "guide-label-" + digest(alignment), "revision": "1",
            "alignment_key": alignment,
            "payload": inline({"value": index + 1}, "gymts.builtin/forecast-outcome/1"),
            "event_time": stamp(index + 1), "available_at": "2026-01-01T01:00:00Z",
            "recorded_at": None, "source_ref": source_ref,
            "supersedes_ref": None, "allowed_uses": ["evaluation"]})
    for run_id in run_ids:
        gym.records.attach_outcomes(run_id, outcomes)

    cutoff = utc_now()
    frozen = gym.records.read_outcomes({"run_ids": run_ids,
        "outcomes_as_of": cutoff, "purpose": "evaluation"})
    labels_ref = gym.artifacts.save_json(frozen, "gymts.outcome-records/1")
    scoring = copy.deepcopy(evaluation["scoring"])
    scoring["outcomes"] = {"sources": [{
        "view_id": "guide-fixed-labels", "revision": labels_ref["revision"],
        "source_refs": [labels_ref],
        "selection": inline({"kind": "all", "source_index": 0}, "gymts.selection/1"),
        "as_of": None, "purpose": "evaluation"}], "as_of": cutoff}
    selected = []
    for entry in manifest["entries"]:
        unit = units[entry["unit_id"]]
        selected.append({"unit_id": unit["unit_id"],
            "evaluation_case_id": unit["evaluation_case_id"],
            "candidate_id": unit["candidate_id"], "repetition": unit["repetition"],
            "run_id": entry["run_id"], "unavailable_reason": None,
            "unit_spec_ref": unit["resolved_spec_ref"]})
    spec = {"protocol_version": "gymts.score/1", "name": "guide-rescore",
        "purpose": "regression", "runs": selected,
        "baseline_id": evaluation["baseline_id"], "scoring": scoring,
        "comparison": evaluation["comparison"], "failure_policy": evaluation["failure_policy"],
        "previous_evaluation_id": first["evaluation_id"]}
    Path("/tmp/gymts-guide-score.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2))
    report = gym.autobench.score(spec)
    assert report["verdict"] == "pass"
    assert all(digest(gym.records.get_run(run_id)["result"]) == before[run_id] for run_id in run_ids)
    print({"initial": first["verdict"], "rescored": report["verdict"], "run_ids": run_ids})
PY
```

Then use the CLI to score the same sealed outputs again:

```bash
gymts --store /tmp/gymts-guide-late-labels score /tmp/gymts-guide-score.json \
  --output /tmp/gymts-guide-rescore.json
```

`score` creates a new report and `evaluation_id` without advancing Environment, invoking Candidate again, or overwriting earlier reports. `previous_evaluation_id` links reports. The `REPLACE_WITH_ACTUAL_RUN_ID` in [forecast_score_template.json](../examples/forecast_score_template.json) is not directly executable. Production workflows should retain real identities from original plans/manifests, as above.

### 5.3 Label revision rules

OutcomeRecord preserves `alignment_key`, truth payload, independent `source_ref`, event time, availability time, and permitted uses. The records service assigns `recorded_at`; callers pass null or omit it. Repeated identical `(outcome_id, revision)` submissions are idempotent; different content yields `conflict`. To correct a label, create a new revision and use `supersedes_ref` to identify its previously committed revision.

Historical cutoffs constrain both `available_at` and `recorded_at`, preventing later backfills of old events from entering past evaluations. `attach_outcomes` alone does not send new labels to a Scorer: select a fixed Outcome set, create a view with `purpose="evaluation"`, then call `score` again. Private evaluation labels do not automatically become training data or Candidate online feedback.

## 6. Data resources and Benchmarks

### 6.1 Where data lives

Configure execution evidence, long-term data, and rebuildable cache separately:

```python
from gymts import GymTS

with GymTS(root="/tmp/gymts-work/runs",
           data_home="/tmp/gymts-work/data",
           cache_home="/tmp/gymts-work/cache") as gym:
    print(gym.environment_ts.datasets.list_datasets())
    print(gym.autobench.list_benchmarks())
```

Examples use `/tmp` for convenience. Deployments should place `data_home` and Run roots on durable local disk. The data default is `$XDG_DATA_HOME/gymts` or `~/.local/share/gymts`; cache defaults to `$XDG_CACHE_HOME/gymts` or `~/.cache/gymts`. Explicit arguments override `GYMTS_DATA_HOME` / `GYMTS_CACHE_HOME`.

| Content | Location | Can it be removed and rebuilt? |
| --- | --- | --- |
| Runs, execution events, Outcome indexes | `<root>/records.sqlite3` | No; these are experiment records |
| Inputs/outputs, calls, plans, and report artifacts | `<root>/artifacts/` | No; referring records need these bytes |
| Fixed source files, public inputs, private references, and manifests | `<data_home>/` | No, unless fully backed up elsewhere |
| Verified data object cache | `<cache_home>/` | Yes, from complete source resources |
| Native environment/model files | Explicit adapter configuration | Depends on fixed assets and deployment |

Active SQLite WAL, atomic CAS publication, and resource locks require local POSIX semantics. Do not place active Run roots on S3FS, object-storage mounts, or shared filesystems lacking those guarantees. This project has no automatic remote synchronization or cross-host resource transactions. Close writers before backing up the complete records store and artifacts. Do not separately remove referenced CAS. `GymTS.close()` closes the local records service only; external service lifecycles depend on adapter session ownership.

### 6.2 Register and read local data from scratch

This complete example publishes public questions and separate private answers, binding the release label `1.0.0` once. It demonstrates resource registration/reading only, without automatically turning data into a forecasting or QA Task.

```bash
python - <<'PY'
import json
from gymts import GymTS
from gymts.environment_ts.datasets import JSONL_READER

public = [{"sample_id": "case-0", "question": "数列的下一个值是什么？", "values": [1, 2, 3]}]
private = [{"sample_id": "case-0", "answer": 4}]
with GymTS(root="/tmp/gymts-guide-catalog/runs",
           data_home="/tmp/gymts-guide-catalog/data",
           cache_home="/tmp/gymts-guide-catalog/cache") as gym:
    catalog = gym.environment_ts.datasets
    def publish(rows):
        content = ("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n").encode()
        return catalog.publish_asset(content, media_type="application/jsonl")
    manifest = {
        "protocol_version": "gymts.source-dataset/1", "dataset_id": "local/guide-series",
        "config": "default", "revision": None, "schema_ref": "gymts.json/1",
        "reader_ref": JSONL_READER, "features": {"values": "list[float64]"},
        "splits": {"test": {"row_count": 1, "split_origin": "user_declared_evaluation",
                            "input_indices": [0], "target_indices": [0]}},
        "usage_policy": {"allowed_uses": ["evaluation"], "training_allowed": False},
        "source_files": [],
        "importer_ref": {"name": "guide.explicit-jsonl", "version": "1.0.0", "origin_ref": None},
        "inputs": [publish(public)], "series": [], "targets": [publish(private)],
        "quality_report_ref": None, "card_ref": None}
    fixed = catalog.register_dataset(manifest, aliases=("1.0.0",))
    dataset = catalog.load_dataset("local/guide-series", revision="1.0.0", split="test")
    print(fixed["revision"], dataset.info, dataset[0])
    assert "answer" not in dataset[0]
    assert not hasattr(dataset, "read_targets")
PY
```

`schema_ref="gymts.json/1"` is a permissive JSON contract for this tutorial. Actual releases should register explicit row schemas, readers, and importers through independent adapters. Manifest `features` are descriptive, not a replacement for per-row schema validation.

Resource revisions derive from canonical manifests; source bytes use SHA-256 storage. Bound aliases cannot change content. Changes to data, splits, uses, or representations produce new revisions and release labels. Do not use `latest`, `main`, or `master` as fixed versions.

### 6.3 HF-style public reading

After the preceding step:

```python
from gymts import GymTS

with GymTS(root="/tmp/gymts-guide-catalog/other-runs",
           data_home="/tmp/gymts-guide-catalog/data",
           cache_home="/tmp/gymts-guide-catalog/cache") as gym:
    ds = gym.environment_ts.datasets.load_dataset("local/guide-series", revision="1.0.0")
    print(ds.info, ds.features, len(ds), ds[0])
    subset = ds.select([0]).filter(lambda row: len(row["values"]) > 0)
    print(subset.sample_ids())
    for batch in subset.iter_batches(batch_size=16):
        print(batch)
    # 安装 Hugging Face datasets 后可执行：hf_dataset = subset.to_hf()
```

Supported operations include indexing, slicing, `select`, `filter`, batches, sample IDs, and HF conversion. Current readers materialize local data; they do not provide HF Hub hosting, huge-dataset streaming, or distributed indexes. `select` cannot implicitly duplicate a source row. `read_series()` reads independent public series assets declared by the manifest; resources with only inline numbers may have none.

A public `DatasetHandle` does not expose private target/source raw assets. Benchmark resolvers needing private references receive a separate evaluation service through AutoBenchTS. Candidates receive only public Task inputs. Evaluation-only sources may supply public questions at runtime, but forbid training, prepare, and training exports from trajectories.

### 6.4 Register and invoke Benchmarks

BenchmarkDefinition fixes data revision, resolver version, and rule parameters. It is not another executor: `resolve_benchmark` returns formal EvaluationSpec for `evaluate`; old outputs still use `score`.

Use the explicit importer in the [TSQA adapter](../adapters/bench_tsqa/README.md) for existing QA files, or the [HF adapter](../adapters/hf_datasets/README.md) to freeze numeric series from HF or local Arrow/Parquet. Importers own actual formats, schemas, usage policies, and matching resolvers. Core CLI does not guess task/scoring meaning for arbitrary JSONL.

The following is a template **after installing bench-tsqa and importing into the specified data_home**. Replace the resource path with your own:

```python
from gymts import GymTS
from gymts_bench_tsqa.benchmark import first_choice_candidate

with GymTS(root="/tmp/gymts-benchmark-runs", data_home="/path/to/imported/resources",
           cache_home="/tmp/gymts-benchmark-cache", integrations=("bench-tsqa",)) as gym:
    spec = gym.autobench.resolve_benchmark("local/tsexam-mcq", revision="1.0.0",
        candidates=[first_choice_candidate()], purpose="regression",
        repetitions={"count": 1, "seeds": [0]})
    report = gym.autobench.evaluate(spec)
    print(report["status"], report["verdict"])
```

The five user QA datasets are evaluation-only, are not distributed with core, and do not authorize training. The `local/` namespace does not imply an official dataset release. One existing resource catalog can serve several independent Run stores, provided each process installs and enables the required reader/resolver.

## 7. Traces, artifacts, and reproducible evidence

### 7.1 Inspect Runs and events

This CLI block reads the actual Run ID produced in section 4:

```bash
RUN_ID=$(python -c 'import json; print(json.load(open("/tmp/gymts-guide-run.json"))["run_id"])')
gymts --store /tmp/gymts-guide-runs inspect "$RUN_ID"
gymts --store /tmp/gymts-guide-runs inspect "$RUN_ID" --events \
  > /tmp/gymts-guide-inspection.json
```

Python supports pagination, event-kind selection, and fixed snapshots:

```python
import json
from pathlib import Path
from gymts import GymTS

run_id = json.loads(Path("/tmp/gymts-guide-run.json").read_text())["run_id"]
with GymTS(root="/tmp/gymts-guide-runs") as gym:
    record = gym.records.get_run(run_id)
    results = gym.artifacts.read_json(record["result"]["result_ref"])
    snapshot = gym.records.snapshot([run_id])
    cursor = 0
    while True:
        page = gym.records.read_events(run_id, {"after_seq": cursor, "limit": 100,
            "kinds": ["input", "candidate_output", "task_result"],
            "snapshot_ref": snapshot["snapshot_ref"]})
        for event in page["events"]:
            print(event["seq"], event["kind"], event["links"])
        cursor = page["next_after_seq"]
        if cursor is None:
            break
    print(len(results), snapshot["snapshot_ref"])
```

Within a Run, `seq` is durable commit order; do not reorder by source timestamps and treat that as execution order. Events associate inputs, outputs, operations, receipts, and calls. Sealed executions accept no new execution events. Attaching Outcomes and new evaluations does not rewrite original RunResult or execution snapshots.

`records.snapshot` fixes event boundaries and Outcome revisions that are available and committed at capture time. Reading it later does not query the latest labels again. Training and evaluation should retain fixed references rather than a query that changes over time.

### 7.2 ArtifactRef and data AssetRef

Run CAS ArtifactRef includes byte hash, media type, schema, size, and immutable identity; it is not an arbitrary local path or HTTP URL. Explicitly import with `gym.artifacts.save_json` or `save_artifact`, then verify through `read_json` or `resolve`. DatasetAssetRef in the resource catalog uses `gymts-data://...`, distinct from Run `gymts-artifact://...`. Resources become fixed CAS references when used as evidence for an execution.

A CAS hash establishes byte identity, not future external model weights, dataset licensing, or production service attestation. Reproduction also requires native versions, dependencies, weights, generation parameters, source bytes, and adapter declarations. Service aliases or URLs generally identify configuration, not fixed weights.

### 7.3 ModelCall and ToolCall capture

`recording.model_calls` has three settings:

| Value | Purpose | Still verify |
| --- | --- | --- |
| `none` | Do not require optional internal model-call capture | Core observations, inputs, raw outputs, TaskResult, and other evidence are still recorded |
| `io` | Require actual requests/responses from the adapter | Actual completeness, missing-field reasons, failure/unknown states |
| `native_rollout` | Require native tokens, inputs, policy, and other training evidence | Actually acquired tokens/masks/probability distributions and policy identity |

A requested profile does not prove capture, nor add support to a Candidate that has not declared it. Model/Agent adapters use the injected public `TraceCollector.record_model_call` / `record_tool_call` inside `Candidate.infer`, saving requests/results as artifacts first. Runner binds actual `run_id/input_id/output_id`; adapters report native call/attempt/parent-call identities. A tool call in a chat message alone does not prove tool execution.

Environment reads and actions must follow TaskRequest → Runner → Environment, retaining request/operation associations. New reads/writes cannot bypass boundaries by posing as input-only computation. Do not tokenize after the fact and claim native tokens, or invent unreturned logprobs, reasoning, or usage. See the [reference](reference.md#4-轨迹与制品-api), [formal specification §10.3](feishu/GymTS接口规范/GymTS接口规范.md#103-modelcallartifact-与-toolcallartifact), and [RL integration](rl-integration.md) for fields and implementation.

`on_capture_failure="fail_run"` is the default. `mark_incomplete` applies only to optional internal-call capture and cannot relax core recording failures. `redaction_policy_ref` fixes a policy reference; it does not automatically remove keys. Adapters must perform and version actual redaction transforms. Requests/responses may contain private inputs: follow project authorization before archiving or sharing.

## 8. Other sources and training extensions

Packages install independently and require explicit enablement. Their own READMEs maintain detailed environment setup:

| Need | Entry point and scope |
| --- | --- |
| Synthetic experiments | [Minimal examples](../examples/README.md), [ChatTS](../adapters/chatts/README.md) |
| Fixed HF/Arrow/local files | [hf_datasets](../adapters/hf_datasets/README.md): currently public numeric series contexts and private forecasting targets |
| Gymnasium | [gymnasium](../adapters/gymnasium/README.md) and independent [interaction](../adapters/interaction/README.md): real steps, final states/rewards, and end causes |
| External OpenEnv | [openenv](../adapters/openenv/README.md): official stateful WS, locally accepted on Echo/Connect4 |
| Prometheus | [prometheus](../adapters/prometheus/README.md): read-only live numeric metrics, cached delivered observations, and sealed rescoring |
| LibraryTS tools | [libraryts](../adapters/libraryts/README.md): specified sktime branch, native tools, and scientific interpreter |
| TimeSigma | [timesigma](../adapters/timesigma/README.md): independent training/inference and Research parent traces |
| RL rollout and training | [rl](../adapters/rl/README.md): local sampling, fixed trajectory datasets, TRL GRPO, and checkpoint reevaluation |
| Your own project | [Extension guide](adapter-development.md): independently registered packages without core project branches |

Offline data supports fixed-content replay. Live world state cannot be restored from configuration alone, and sequentially running Candidates does not inherently compare them on the same data. Explicitly freeze common observations, or use a scenario with recoverable sessions and controlled experimental design. Reject unsupported seed/reset requests; do not record an ineffective seed as applied.

Training dataset construction uses public `gymts.training.build_dataset(spec, records, artifacts)` with fixed RecordSnapshot input. Independent DatasetBuilder providers own formats, rewards, token/mask semantics, and backends. Core embeds neither TRL nor verl. The current RL package reuses TRL; verl, multi-turn RL, and distributed training are not adapted. `gymts.source-dataset/1` is a source resource manifest, while `gymts.dataset/1` is a training export result; they are not interchangeable.

## 9. Common issues and troubleshooting

| Symptom | Check and action |
| --- | --- |
| `gymts: command not found` | Activate the installation environment, or invoke `python -m gymts` with that interpreter |
| Integration or component missing | Inspect entry points with `GymTS.available_integrations()` and enabled Manifests with `gymts --integration NAME plugins`; check exact versions |
| Missing scientific dependencies after installation | Follow adapter `[runtime]`/native interpreter instructions and confirm which Python actually executes |
| Valid configuration but failed execution | Planning does not read resources; inspect failed Run `errors`, events, and actual file/service configuration |
| `schema_mismatch` / `unsupported_capability` | Check Task/Candidate protocols, variable units, clocks, seed/reset, action schemas, and scoring contracts |
| Predictions without scores | Check independent label views, matching keys, cutoffs, metric counts, invalid outputs, and minimum coverage |
| Labels attached but report unchanged | Old reports are immutable; select fixed labels and call `score` again |
| `conflict` | One immutable identity has different content; publish a new revision/alias instead of overwriting evidence |
| `artifact_integrity` / `persistence_failed` | Check bytes, disk space, permissions, and local POSIX semantics; preserve failure evidence without editing CAS |
| HTTP timeout with uncertain action state | Inspect `side_effect`, operation_id, and native receipts; do not automatically retry possibly executed actions |
| Capture failure or training export rejection | Inspect missing capture fields, native token/probability identities, and usage policies; unavailable facts cannot be fabricated |

Python callers can catch `GymTSError` and inspect `error.info`. Failures after a Run begins generally return `status="failed"`; not every failure raises a Python exception. See [CLI exit codes](reference.md#12-输出和退出码).

A reproducible issue should include version, platform, minimal configuration, redacted errors, Run/evaluation IDs, and relevant events. Where actual data/models are restricted, provide a public minimal example with the same structure. Do not paste keys, private labels, or unauthorized requests/responses into Issues.

## 10. Current implementation boundaries

0.5.0 is a synchronous local SDK/CLI, not a hosted HF Hub, enterprise multi-tenant platform, distributed scheduler, or general Agent engine. Plugins run as trusted in-process Python code. Restricted services form contractual access boundaries, **not an operating-system sandbox for malicious plugins**. Core has no ToolRegistry/ToolBroker for automatically injecting arbitrary toolsets. A complete autonomous Agent tool loop still needs independent integration and acceptance.

See the [environment integration guide](environment-adapters.md) for HF, Gymnasium, OpenEnv, and Prometheus acceptance scope and archived evidence. Working localhost services do not prove a user's production testbed is accepted. Tiny-model updates, fixed algorithms, and known-constant fixtures do not demonstrate improved model capability.

The current specification and guide take precedence. The [v2 contract](pluggability-contract-v2.md) and [enterprise platform roadmap](enterprise-platform-roadmap.md) are designs, not implemented APIs to call.
