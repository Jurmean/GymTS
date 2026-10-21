# GymTS TSQA benchmark adapter

An independent evaluation-only resource/adapter distribution. Core GymTS never
imports this project. Enable it explicitly with `integrations=('bench-tsqa',)`.

Install the GymTS core and `pip install './adapters/bench_tsqa[runtime]'`.
PyArrow is imported only when explicitly importing/reading Parquet resources.
Neither installation nor registration downloads sources or runs a model.

```python
from gymts import GymTS
from gymts_bench_tsqa.importer import import_attachments
from gymts_bench_tsqa.benchmark import first_choice_candidate

with GymTS('/tmp/tsqa-runs', data_home='/path/to/persistent/resources',
           cache_home='/tmp/tsqa-cache', integrations=('bench-tsqa',)) as gym:
    # Explicit one-time import of the five original, hash-checked JSONL files.
    imported = import_attachments(gym, '/path/to/attachments')
    print(gym.environment_ts.datasets.list_datasets())
    ds = gym.environment_ts.datasets.load_dataset(
        'local/tsexam-mcq', revision='2.0.0', split='test')
    print(len(ds), ds[0]['question_original'])
    # Public ds includes no answers, attributes, raw-file/target references.
    spec = gym.autobench.resolve_benchmark('local/tsexam-mcq', revision='2.0.0',
        candidates=[first_choice_candidate()], purpose='regression')
    report = gym.autobench.evaluate(spec)
```

`gymts-bench-tsqa import --attachments ... --data-home ... --root /tmp/...`
publishes immutable raw bytes, public/private Parquet, quality reports, cards,
dataset manifests and benchmark definitions. A readable release alias resolves
to a content revision before evaluation. Re-importing unchanged data is idempotent.
No attachment file or 19,354-row data shard is bundled in the wheel/sdist.

`gymts-bench-tsqa evaluate --benchmark local/tsexam-mcq --data-home ...`
runs the complete 746-source-row benchmark with a transparent first-public-choice
baseline. This is an integration/coverage check, not a claim of model quality.
Its expected accuracy is 332/746 with known source references and no row removal.
Gates require complete scoring coverage and zero failed Runs, not a quality floor.
Each source row is a planned evaluation case; native AutoBenchTS produces the plan,
Runs, independent scores, coverage and EvaluationReport. The resolver adds no
benchmark execution engine or alternative report hierarchy. Definition params must
contain exactly `scope`, `metrics`, `parser_ref`, `coverage_policy`, and
`question_policy`. This resolver supports full source rows, both accuracy and
format validity (or structured `task_score` plus format validity), `all_source_rows_eligible` coverage, and
`complete-original-lossless-projection/1` questions. Unsupported values, missing
fields or extra selection/scorer/prompt fields are rejected before resource
reading; they never silently change or get ignored by this definition.

Public questions retain their complete source text, choices, instructions and
conditions, including the original text in `question_original`. A reversible
projection replaces only each literal `<ts><ts/>` by a neutral ordered series
reference. Exact original offsets and full ordered named numeric arrays are
retained. The Task does not canonicalize/rewrite the original problem. Model codecs
own formatting: `tsqa-http` supports explicit `text-json-series` (full JSON numbers)
and `chatts-native` (original question plus native arrays). Both preserve all values
without rounding/truncation, and receive no references. HTTP configuration fixes a
claimed deployment model revision; the service's actual weights are not verified.
Requests/responses are CAS artifacts, not advertised as native token/logprob traces.
The first-choice baseline performs no LLM/tool call and invents no call records.

References, original answer/attributes and unreviewed metadata are private assets.
All five datasets are `test / user_declared_evaluation`, `training_allowed=false`;
training/prepare/dataset-build access is denied by the resource service. The name
`dataset_a_rlvr` never authorizes training or grants a verifier.

Reference rules are versioned in `tsqa.single-answer/2`. Choice/Boolean/text
questions retain exact matching and standalone answer-tag rules. For `mcq2`,
leading `1.` is a question number, never a choice index; outer whitespace and
terminal full stops are ignored. No fuzzy option matching is introduced.

Dataset A RLVR uses the existing deterministic task evaluators derived from
ChatTS and the pinned local RLVR implementation. Its 10 abilities cover noise,
trend, seasonality, local features, correlations, clusters and reasoning.
Structured `attributes`, not the prose `answer`, are the scoring authority.
The native metric is `task_score`: the upstream mean of category/numeric/reason
means, including numeric partial credit and cluster F1. It is not MCQ accuracy.
Answer wrappers follow the existing RLVR extraction behavior. No judge, RAGAS,
API or model is loaded. Source revisions, license and transformation differences
are recorded in [UPSTREAM.md](UPSTREAM.md).

The corrected all-row audit distinguishes available references from input issues:

| Dataset | Rows | References read | Evaluable references | Input review |
|---|---:|---:|---:|---:|
| local/tsexam-mcq | 746 | 746 | 746 | 0 |
| local/bedtime | 394 | 394 | 394 | 0 |
| local/mcq2 | 100 | 100 | 100 | 0 |
| local/timemqa-full | 17,703 | 17,703 | 16,983 | 720 |
| local/dataset-a-rlvr | 411 | 411 | 411 | 0 |

All 19,354 rows have readable references. TimeMQA's declared A/B/C/D response
alphabet is parsed independently of visible option text. Of its 720 input review
rows, 683 have no complete uniquely parsed option block and 37 have answer labels
outside the visible options. The original text, arrays and answer labels remain
unchanged; no option is fabricated and no label is repaired. These rows stay
eligible, yield missing/insufficient accuracy evidence, and prevent the complete
coverage Gate from passing. This is not a missing-answer or model-error claim.
`format_valid` remains reference-free. Unknown/unsupported future references are
also kept eligible/missing; rows are never silently dropped.

New imports use alias `2.0.0`; old `1.0.0` datasets, definitions, Run outputs and
frozen reports are preserved. The scorer accepts saved v1 result payloads for
re-evaluation. New definitions fix parser v2; an old definition is not silently
upgraded. The unchanged TSExam first-choice baseline remains 332/746, a wiring
check with zero model calls, not a model-quality result.

The uploaded Dataset A content has been matched exactly to the official 411
ChatTS Dataset A subquestions by arrays, columns, attributes and normalized
ability names. This does not establish the distributor/license of the converted
upload. Other uploaded transformations retain `local/` identities; no official
benchmark equivalence is asserted. Evaluation-only use remains enforced.

Reproduce the all-row audit without model calls:

```bash
PYTHONPATH=.:adapters/bench_tsqa/src python adapters/bench_tsqa/scripts/audit_references.py \
  --source-data-home output/resources-20261020 \
  --output docs/reports/bench-tsqa-reference-repair-2026-10-21.json
```

This command creates a local detailed report with per-row question/reference
excerpts; that exact output path is ignored by Git. The
[public aggregate summary](../../docs/reports/bench-tsqa-reference-repair-summary-2026-10-21.json)
omits questions, answers and row diagnostics, retaining counts, source/rule
identities and the unchanged original report SHA-256.

Optional `--parity-source /path/to/open_r1/reward_qa.py` checks the reviewed source
hash and 1,233 deterministic parity vectors. Optional `--official-dataset-a`
checks the official file MD5 and all 411 subquestion identities. The report keeps
source row numbers/reasons, reference-text self-checks and the explicit statement
that these checks are not model results. Some stored prose answers are rounded
or only say Yes, while structured labels require additional details; they need
not score 1 against the original evaluator.

## License

GymTS-owned code in this package is licensed under the [MIT License](LICENSE).
Third-party libraries, upstream projects, datasets, model weights and services
retain their own licenses and terms; this package does not relicense them.
