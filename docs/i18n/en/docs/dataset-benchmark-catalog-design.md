# EnvironmentTS Data Resources and AutoBenchTS Benchmark Management

Status: GymTS 0.5.0 implements the local resource catalog, 2026-10-20. See [Interface Specification 1.2.0 §19](feishu/GymTS接口规范/GymTS接口规范.md) for the formal contract, and [this delivery record](framework-delivery-2026-10-20.md) for acceptance evidence and remaining gaps. The proposal before these changes is preserved in a [historical snapshot](archive/2026-10-20-before-api-v1.2/dataset-benchmark-catalog-design.md).

GymTS retains **two main modules: EnvironmentTS and AutoBenchTS**. The dataset catalog serves EnvironmentTS; registering, maintaining and resolving benchmark definitions serves AutoBenchTS. Resolution produces the existing EvaluationSpec, execution still uses `evaluate`, rescoring sealed outputs still uses `score`, and the result is a native EvaluationReport. There is no separate benchmark executor or alternative reporting system.

This division follows the [overall design](feishu/GymTS总体设计/GymTS总体设计.md), [execution model](feishu/GymTS%20运行机制/GymTS%20运行机制.md) and [project website](https://netman.aiops.org/contacts/projects/). The website assigns benchmark construction and maintenance, reproduction, acceptance, regression and safety evaluation to AutoBenchTS. Specific safety scenarios and system connectors still require adapters; an entry point does not mean every use has passed acceptance.

## 1. What Is Stored and Who Manages It

| Object | Responsibility | Immutable identity |
| --- | --- | --- |
| DatasetAssetRef | Original bytes, public Parquet, private references, quality reports and cards | SHA-256, byte count, media type |
| SourceDatasetRevision | EnvironmentTS data resource: schema, reader, splits, usage policy, inputs/references and import lineage | dataset_id + config + content revision |
| BenchmarkDefinition | AutoBenchTS reusable evaluation recipe: fixed data, resolver and rule parameters | benchmark_id + content revision |
| EvaluationSpec / Plan | Candidates, cases, repetition seeds, comparison and Gates for this evaluation; all expected units fixed before execution | Existing evaluation_id / unit_id / plan_ref |
| Run / RecordSnapshot | Actual execution, capture and sealed evidence | Existing Run and snapshot identities |
| EvaluationReport | Independent scoring, coverage, comparison and Gates | Existing native report references |

The source-data protocol is `gymts.source-dataset/1`. The existing `gymts.dataset/1` continues to represent training exports from trajectories; they are not interchangeable. Changing source content, splits, usage policy, reader or imported representation creates a new source revision; changing declared scoring, prompting or filtering rules creates a new benchmark revision. A fixed-version resolver owns the domain Task/Binding/Scorer recipe. Unknown rules must be rejected, not ignored.

## 2. Storage Locations

| Content | Current location or configuration | Distribution boundary |
| --- | --- | --- |
| General resource contracts, store and reader services | `gymts/contracts/resources.py`, `storage/resources.py`, `environment_ts/datasets.py` | Core package; no question bank |
| General benchmark resource resolution | `gymts/autobench_ts/catalog.py` | Core package; no branches by project name |
| Importer, cards, Task, Candidate, Scorer and resolver for this group of question banks | `adapters/bench_tsqa/`, distribution `gymts-bench-tsqa` | Independently installed and explicitly enabled |
| Original and normalized assets, dataset and benchmark manifests | `GymTS(data_home=...)` or `GYMTS_DATA_HOME`; default XDG data/gymts | Long-lived resources independent of any Run |
| Verified local copies of assets | `GymTS(cache_home=...)` or `GYMTS_CACHE_HOME`; default XDG cache/gymts | Cache that can be deleted and rebuilt |
| Active SQLite, Run CAS and reports | Explicit `GymTS(root=...)` | Local POSIX filesystem |
| Sealed evidence archives | Persistent archive directory selected by the deployer | Stored in the repository-ignored `output/` for this delivery; excluded from the core wheel |

The five actual resources for this delivery are at `/zzr/zmx/GymTS/Jurmean-GymTS/output/resources-20261020`. This is deployment configuration, not a hard-coded core path; source wheels/sdists do not contain the uploaded question banks. Routine reads after import do not depend on Codex attachments paths. `/zzr` uses S3FS, so active SQLite, caches, builds and tests run under `/tmp` and are archived afterward.

```text
<data_home>/
  objects/sha256/<first-two>/<full-hash>
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

SourceDatasetRevision fields are `{protocol_version,dataset_id,config,revision,schema_ref,reader_ref,features,splits,usage_policy,source_files,importer_ref,inputs,series,targets,quality_report_ref,card_ref}`. A split declares `{row_count,split_origin,input_indices,target_indices}`; source_files retains original filenames and asset references. reader/importer use fixed ComponentRefs.

This importer preserves the original JSONL, public Parquet, private-reference Parquet, JSON quality report and Markdown card. Public rows retain sample_id, dataset_id, source_row, task_kind, the complete question_original, reversible attachment_projection, public choices and ordered ragged Float64 series. Only the literal `<ts><ts/>` is replaced with a neutral series reference; questions are not abbreviated or rewritten, and numbers are not rounded or truncated. Original bytes and actual Parquet codec round-trip checks are retained. In this import, series are inline in public rows and the general manifest's separate series-asset list is empty; cross-dataset series-table deduplication is not claimed.

`answer`, `attributes`, unreviewed original metadata and complete original files remain private assets. Public DatasetHandle info, indexing, batch reads and HF conversion do not expose private-asset references; the reader receives services for only the selected public shards. The AutoBenchTS resolver separately receives EvaluationDatasets services for the data in its definition and the private references. This is a service boundary for trusted plugins, not an operating-system sandbox against malicious Python code.

The usage policy is fixed to `allowed_uses=['evaluation']`, `training_allowed=false`. A public runtime projection does not change that policy. Data reads, training_collection Runs and the general training-build entry point all reject using these sources for training, prepare or dataset_build; switching exporters does not grant permission.

## 4. Five Registered Resources

All source rows are `test / user_declared_evaluation`; duplicates, source order and source-row identities are retained, totaling **19,354** rows. Source provenance and licenses were not provided, so these use the `local/` namespace and are not presented as official releases.

| dataset / benchmark ID | Rows | References determined by current rules | Unresolved references |
| --- | ---: | ---: | ---: |
| local/bedtime | 394 | 394 | 0 |
| local/dataset-a-rlvr | 411 | 0 | 411 |
| local/mcq2 | 100 | 100 | 0 |
| local/timemqa-full | 17,703 | 16,983 | 720 |
| local/tsexam-mcq | 746 | 746 | 0 |

In `mcq2` references, `1.` is a question number, not an option number. timemqa's 720 unresolved items include 683 samples with unresolved public-option/format parsing and 37 whose references are outside the parsed options. These are parser-review flags, not confirmed annotation errors. RLVR structured references await the original verifier or explicitly approved task rules; the filename neither authorizes training nor automatically provides rewards.

The private Scorer uses the explicit local `tsqa.single-answer/1` rule and does not claim to reproduce an unavailable official scoring script. It accepts a unique public answer token/text or a single independent answer tag; multiple answers or reasoning outside the tag are not silently tolerated. Every source row remains eligible; unresolved references count as missing, invalid outputs as invalid, and format validity is reported separately. Questions are not dropped, denominators are not reduced and zero answers are not fabricated.

This delivery first completed native evaluation and same-Run rescoring for all 746 rows of `tsexam-mcq`. The other four resources are registered and readable; full formal model evaluation of all resources is not claimed. The first-public-option baseline's accuracy of 332/746 checks wiring and coverage; it does not indicate improvement from training.

## 5. Calling the Services

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

The corresponding CLI commands are `gymts --store ... --data-home ... datasets list/info/register` and `autobench list/register/resolve`. `autobench resolve --candidate` accepts JSON files containing candidate_id/spec; it outputs a native EvaluationSpec for `gymts evaluate`. Existing `gymts score` rescores sealed Runs against fixed references. See the [adapter guide](../adapters/bench_tsqa/README.md) for full configuration, HTTP model boundaries and repeated imports.

## 6. Lineage, Extensions and Remaining Design

Resolution commits the fixed source manifest, usage policy and BenchmarkDefinition into the current CAS. Provenance propagates into EvaluationSpec, each Run's configuration/metadata and report evidence without granting private references to the Candidate. Candidate weight/algorithm configuration identity remains fixed; seeds pass through execution context, rather than changing Candidate identity to express repetitions.

Registry's pure describe/compatibility callbacks support offline `plan/validate`. They do not read resources, create environments or load models; actual open/prepare happens after the Run is established, and corrupted resources or native-interface failures retain a failed Run. New readers, Tasks, Candidates, Scorers and resolvers are independent adapter packages, requiring no question-bank-name branches in core.

RL checkpoint → Candidate in a new process → native AutoBenchTS.evaluate with repeated seeds → independent score has also been exercised. See the [RL guide](rl-integration.md) and [actual report](reports/rl-checkpoint-loop-2026-10-20.json) for the precise scope. Training still reuses TRL; these five evaluation attachments were not used for training.

Future projects still need to validate or extend structured RLVR verifiers, formal scoring/model acceptance for more benchmarks, human review and asset publication workflows, heterogeneous-suite report navigation, remote resource synchronization, true streaming, multi-process Runtime/forced timeouts, and live safety/control tests. These must not add alternative execution, aggregation or Gate logic through convenient catalog APIs. The complete v2 Runtime contract remains a draft.
