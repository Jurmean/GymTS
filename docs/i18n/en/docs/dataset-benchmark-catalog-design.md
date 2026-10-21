# EnvironmentTS Data Resources and AutoBenchTS Benchmark Management

Status: Current GymTS **0.6.0 / interface 1.4.0**, with F2.1 technical acceptance complete. The main responsibilities are **storing data, connecting data sources, organizing experiments, and recording experiments**. See the [experiment organization guide](experiment-organization.md) and [current acceptance report](reports/experiment-organization-2026-10-21.json). The 0.5.1 / 1.3.0 four-source F1 acceptance and 0.5.0 / 1.2.0 catalog/attachment records below retain their historical identities. See [ADR 0001](adr/0001-core-data-source-catalog.md) for the data-layer decision, the [Interface Specification](feishu/GymTS接口规范/GymTS接口规范.md) for current fields, the [delivery record](framework-delivery-2026-10-20.md) for 0.5.0 acceptance, and the [historical snapshot](archive/2026-10-20-before-api-v1.2/dataset-benchmark-catalog-design.md) for the earlier proposal.

GymTS retains **two main modules: EnvironmentTS and AutoBenchTS**. The dataset catalog serves EnvironmentTS; registering, maintaining and resolving benchmark definitions serves AutoBenchTS. Resolution produces the existing EvaluationSpec, execution still uses `evaluate`, rescoring sealed outputs still uses `score`, and the result is a native EvaluationReport. There is no separate benchmark executor or alternative reporting system.

This division follows the [overall design](feishu/GymTS总体设计/GymTS总体设计.md), [execution model](feishu/GymTS%20运行机制/GymTS%20运行机制.md) and [project website](https://netman.aiops.org/contacts/projects/). The website assigns benchmark construction and maintenance, reproduction, acceptance, regression and safety evaluation to AutoBenchTS. Specific safety scenarios and system connectors still require adapters; an entry point does not mean every use has passed acceptance.

## F1 Correction: Four-Kind Data Organization Belongs in Core

Executing four source kinds does not establish unified data organization. The historical 0.5.0 baseline supplied a general static-resource catalog and four-kind Environment interfaces. Among that round’s five new projects, only Data-Juicer derived data entered the catalog; the other four mainly use preparation manifests and Run CAS, and none registered a reusable BenchmarkDefinition. This is a data-layer delivery gap, not something additional project adapters alone establish as complete.

F1 explicitly placed source catalogs, data organization, storage, versions and source→data→Run→feedback relationships in core. Concrete providers, formats and domain semantics remain external:

| Core source kind | Common core management | External provider responsibility |
| --- | --- | --- |
| `static` | Fixed sources, dataset revisions, splits, assets, uses and parents | File/HF reads, column interpretation and domain public/private projection |
| `synthetic` | Generation recipes, seeds/reproduction modes, actual generated snapshots and source links | Original generators and project parameters |
| `simulation` | Simulator definitions, episodes/capture scope, actual observations and action evidence | Native reset/step/close and state codecs |
| `live_testbed` | Connection definitions, actual collection windows and source/data-snapshot identities | External SDKs, query protocols and metric interpretation |

New `gymts.data-source/1` describes reusable sources; new `gymts.source-dataset/2` describes actual data revisions. They are distinct: one source may produce several datasets, and connection names or recipe versions are not future data-content versions. The common workflow is **register source → bind configuration → capture/import → dataset → Run → new dataset**. Static/already-generated snapshots can register directly. `run_data` preserves the complete ExperimentSpec's real Task/Candidate and composes binding, the original Run and capture, without inventing a Candidate or a separate Candidate-free capture engine.

V2 preserves v1 resource fields and adds `kind`, `origin`, `lineage` and `attachments`. Source definitions, parent manifests and actual capture records become traceable resources. Mutable native backends and fixed data remain separately represented. Derived data still requires explicit registration; feedback does not automatically change generated-label status or authorized use. SourceDatasetRevision remains distinct from training-export `gymts.dataset/1`.

Version 0.6.0 adds experiment groups/stage attempts and explicit build publication. `gym.environment_ts.datasets.publish_build(...)` registers a fixed training export in the persistent data catalog while retaining its reader/schema, original bytes, lineage, and usage policy. It does not merge source-dataset and training-export protocols. Stage bindings and executable examples are in the [experiment organization guide](experiment-organization.md).

Existing `/1` datasets, benchmarks, Runs and reports remain unchanged; new protocols are additive. F0 identities and five-project acceptance are not rewritten. Historical F1 froze core before independently packaged adapters connected four real source kinds and checked execution, lineage, independent evaluation and rescoring. See the [user guide](user-guide.md#65-四类来源实际快照与回流) and [API reference](reference.md#54-四类来源与-dataset-v2) for exact entry points and an executed standard-library data chain. All 168 core regressions and installation-outside-source distribution checks passed; frozen-F1 real four-source integration/rescoring passed, with existing sixteen-package compatibility recorded separately. This does not claim a complete remote Hub, distributed catalog or arbitrary streaming.

## 1. What Is Stored and Who Manages It

| Object | Responsibility | Immutable identity |
| --- | --- | --- |
| DatasetAssetRef | Original bytes, public Parquet, private references, quality reports and cards | SHA-256, byte count, media type |
| DataSourceDefinition | Core four-kind sources, provider binding, recipes and reproduction modes | source_id + config + content revision |
| SourceDatasetRevision | EnvironmentTS fixed data; v1 shards, with source/parent manifests/capture/attachments added in v2 | dataset_id + config + content revision |
| BenchmarkDefinition | AutoBenchTS reusable evaluation recipe: fixed data, resolver and rule parameters | benchmark_id + content revision |
| EvaluationSpec / Plan | Candidates, cases, repetition seeds, comparison and Gates for this evaluation; all expected units fixed before execution | Existing evaluation_id / unit_id / plan_ref |
| Run / RecordSnapshot | Actual execution, capture and sealed evidence | Existing Run and snapshot identities |
| EvaluationReport | Independent scoring, coverage, comparison and Gates | Existing native report references |

Source data supports both `gymts.source-dataset/1` and `gymts.source-dataset/2`; source definitions use `gymts.data-source/1`. Existing `gymts.dataset/1` continues to represent trajectory training exports and is not interchangeable with persistent source-data manifests. Changing source content, splits, usage policy, reader or imported representation creates a new source revision; changing declared scoring, prompting or filtering rules creates a new benchmark revision. A fixed-version resolver owns the domain Task/Binding/Scorer recipe. Unknown rules must be rejected, not ignored.

## 2. Storage Locations

| Content | Current location or configuration | Distribution boundary |
| --- | --- | --- |
| General resource contracts, store and reader services | `gymts/contracts/resources.py`, `storage/resources.py`, `environment_ts/datasets.py` | Core package; no question bank |
| General benchmark resource resolution | `gymts/autobench_ts/catalog.py` | Core package; no branches by project name |
| Importer, cards, Task, Candidate, Scorer and resolver for this group of question banks | `adapters/bench_tsqa/`, distribution `gymts-bench-tsqa` | Independently installed and explicitly enabled |
| Source definitions, original/derived assets, dataset and benchmark manifests | `GymTS(data_home=...)` or `GYMTS_DATA_HOME`; default XDG data/gymts | Long-lived resources independent of any Run |
| Verified local copies of assets | `GymTS(cache_home=...)` or `GYMTS_CACHE_HOME`; default XDG cache/gymts | Cache that can be deleted and rebuilt |
| Active SQLite, Run CAS and reports | Explicit `GymTS(root=...)` | Local POSIX filesystem |
| Sealed evidence archives | Persistent archive directory selected by the deployer | Stored in the repository-ignored `output/` for this delivery; excluded from the core wheel |

The following five attachments are historical 0.5.0 / v1 import examples. Their resources are at `/zzr/zmx/GymTS/Jurmean-GymTS/output/resources-20261020`. This is deployment configuration, not a hard-coded core path; source wheels/sdists do not contain the uploaded question banks. Routine reads after import do not depend on Codex attachments paths. `/zzr` uses S3FS, so active SQLite, caches, builds and tests run under `/tmp` and are archived afterward.

```text
<data_home>/
  objects/sha256/<first-two>/<full-hash>
  sources/<namespace>/<name>/<config>/
    revisions/<hash>/manifest.json
    aliases/1.0.0.json
  datasets/<namespace>/<name>/<config>/
    revisions/<hash>/manifest.json
    aliases/1.0.0.json
  autobench/benchmarks/<namespace>/<name>/
    revisions/<hash>/manifest.json
    aliases/1.0.0.json

<cache_home>/objects/sha256/...
<run_root>/records.sqlite3
<run_root>/artifacts/...
```

Resource bytes are deduplicated by hash; reads verify digest and size. A manifest revision is the SHA-256 of its canonical JSON with the revision field excluded. An explicit release alias can be bound only once; latest/main/master are unsupported. Current concurrent resource publication guarantees apply only on the same host and on a filesystem providing POSIX locks; there are no cross-host object-store transactions, remote downloads or multi-tenant authorization services.

## 3. Data Format and Public/Private Boundaries

A general AssetRef contains exactly `{uri,sha256,size_bytes,media_type}`. The built-in URI is `gymts-data://sha256/<hash>`, separate from ArtifactRef in the Run CAS. An object becomes an execution-evidence reference only after entering the current experiment's CAS.

SourceDatasetRevision v1 fields are `{protocol_version,dataset_id,config,revision,schema_ref,reader_ref,features,splits,usage_policy,source_files,importer_ref,inputs,series,targets,quality_report_ref,card_ref}`; v2 adds `kind/origin/lineage/attachments`, formally specified in §20. A split declares `{row_count,split_origin,input_indices,target_indices}`; source_files retains original filenames and asset references. reader/importer use fixed ComponentRefs.

This importer preserves the original JSONL, public Parquet, private-reference Parquet, JSON quality report and Markdown card. Public rows retain sample_id, dataset_id, source_row, task_kind, the complete question_original, reversible attachment_projection, public choices and ordered ragged Float64 series. Only the literal `<ts><ts/>` is replaced with a neutral series reference; questions are not abbreviated or rewritten, and numbers are not rounded or truncated. Original bytes and actual Parquet codec round-trip checks are retained. In this import, series are inline in public rows and the general manifest's separate series-asset list is empty; cross-dataset series-table deduplication is not claimed.

`answer`, `attributes`, unreviewed original metadata and complete original files remain private assets. Public DatasetHandle info, indexing, batch reads and HF conversion do not expose private-asset references; the reader receives services for only the selected public shards. The AutoBenchTS resolver separately receives EvaluationDatasets services for the data in its definition and the private references. This is a service boundary for trusted plugins, not an operating-system sandbox against malicious Python code.

The usage policy is fixed to `allowed_uses=['evaluation']`, `training_allowed=false`. A public runtime projection does not change that policy. Data reads, training_collection Runs and the general training-build entry point all reject using these sources for training, prepare or dataset_build; switching exporters does not grant permission.

## 4. Five Registered Resources

All source rows are `test / user_declared_evaluation`; duplicates, source order and source-row identities are retained, totaling **19,354** rows. Source provenance and licenses were not provided, so these use the `local/` namespace and are not presented as official releases.

| dataset / benchmark ID | Rows | References read | Evaluable | Input review |
| --- | ---: | ---: | ---: | ---: |
| local/bedtime | 394 | 394 | 394 | 0 |
| local/dataset-a-rlvr | 411 | 411 | 411 | 0 |
| local/mcq2 | 100 | 100 | 100 | 0 |
| local/timemqa-full | 17,703 | 17,703 | 16,983 | 720 |
| local/tsexam-mcq | 746 | 746 | 746 | 0 |

Parser v2 separates available references from input review. Dataset A reuses the
pinned deterministic ChatTS RLVR rules, with structured attributes and native
`task_score` rather than MCQ accuracy. Its content matches the official 411
subquestions; conversion differences and scoring provenance are in
[UPSTREAM.md](../adapters/bench_tsqa/UPSTREAM.md).

All 19,354 reference records are read. TimeMQA has 683 unresolved public option
blocks and 37 labels outside visible options. The 720 input review rows remain
eligible/missing for accuracy; no option text or gold labels are repaired.
New resources/definitions use alias `2.0.0`; old datasets, Runs and frozen reports
remain immutable. Saved v1 result payloads can still be scored. The complete audit
is in the [reference-repair report](reports/bench-tsqa-reference-repair-summary-2026-10-21.json); its 1,233 reward
parity comparisons contain no model calls or model-quality claims.

## 5. Calling the Services

For common four-kind APIs and a complete source→Run→dataset→derived example, see the [user guide](user-guide.md#65-四类来源实际快照与回流). The following import/read/benchmark examples retain the five v1 evaluation attachments. They remain compatible and do not replace the new source catalog.

Install from the main repository:

```bash
python -m pip install . './adapters/bench_tsqa[runtime]'
```

One-time import:

```bash
gymts-bench-tsqa import \
  --attachments /path/to/five-jsonl-files \
  --data-home /path/to/persistent/resources --root /tmp/gymts-import
```

Public reads and formal evaluation are both implemented:

```python
from gymts import GymTS
from gymts_bench_tsqa.benchmark import first_choice_candidate

with GymTS('/tmp/gymts-runs', data_home='/path/to/persistent/resources',
           cache_home='/tmp/gymts-cache', integrations=('bench-tsqa',)) as gym:
    ds = gym.environment_ts.datasets.load_dataset(
        'local/tsexam-mcq', revision='1.0.0', config='default', split='test')
    print(ds.info, len(ds), ds[0]['question_original'])
    view = ds.select([0, 1, 2])
    for batch in view.iter_batches(batch_size=2):
        print(len(batch))
    spec = gym.autobench.resolve_benchmark(
        'local/tsexam-mcq', revision='1.0.0',
        candidates=[first_choice_candidate()], purpose='regression',
        repetitions={'count': 1, 'seeds': [0]})
    report = gym.autobench.evaluate(spec)
```

DatasetHandle also supports `filter`, `sample_ids`, `read_series` and, with HF Datasets installed, `to_hf`. Current reads are local and materialized, not equivalent to the full HF Hub: there is no remote repository synchronization, streaming large-data access or distributed query index. The subset above is only for browsing; the formal full resolver does not replace the entire benchmark with it.

Common CLI commands include `sources list/register/info`, `run-data` and `datasets capture`; existing v1 resources still use `gymts --store ... --data-home ... datasets list/info/register` and `autobench list/register/resolve`. `autobench resolve --candidate` accepts JSON files containing candidate_id/spec; it outputs a native EvaluationSpec for `gymts evaluate`. Existing `gymts score` rescores sealed Runs against fixed references. See the [adapter guide](../adapters/bench_tsqa/README.md) for full configuration, HTTP model boundaries and repeated imports.

## 6. Lineage, Extensions and Remaining Design

Resolution commits the fixed source manifest, usage policy and BenchmarkDefinition into the current CAS. Provenance propagates into EvaluationSpec, each Run's configuration/metadata and report evidence without granting private references to the Candidate. Candidate weight/algorithm configuration identity remains fixed; seeds pass through execution context, rather than changing Candidate identity to express repetitions.

Registry's pure describe/compatibility callbacks support offline `plan/validate`. They do not read resources, create environments or load models; actual open/prepare happens after the Run is established, and corrupted resources or native-interface failures retain a failed Run. New readers, Tasks, Candidates, Scorers and resolvers are independent adapter packages, requiring no question-bank-name branches in core.

RL checkpoint → Candidate in a new process → native AutoBenchTS.evaluate with repeated seeds → independent score has also been exercised. See the [RL guide](rl-integration.md) and [actual report](reports/rl-checkpoint-loop-2026-10-20.json) for the precise scope. Training still reuses TRL; these five evaluation attachments were not used for training.

Future projects still need to validate or extend structured RLVR verifiers, formal scoring/model acceptance for more benchmarks, human review and asset publication workflows, heterogeneous-suite report navigation, remote resource synchronization, true streaming, multi-process Runtime/forced timeouts, and live safety/control tests. These must not add alternative execution, aggregation or Gate logic through convenient catalog APIs. The complete v2 Runtime contract remains a draft.
