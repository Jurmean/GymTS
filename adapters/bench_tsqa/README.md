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
        'local/tsexam-mcq', revision='1.0.0', split='test')
    print(len(ds), ds[0]['question_original'])
    # Public ds includes no answers, attributes, raw-file/target references.
    spec = gym.autobench.resolve_benchmark('local/tsexam-mcq', revision='1.0.0',
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
format validity, `all_source_rows_eligible` coverage, and
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

Reference rules are versioned in `tsqa.single-answer/1`: uppercase public choice
labels, exact `True`/`False`, or a unique public text choice. For `mcq2`, leading
`1.` is a question number, never a choice index; outer whitespace and terminal
full stops are ignored for exact text matching. No fuzzy match, synonyms or
numerical tolerance is invented. Responses must be one public token/text or a
single standalone `\answer{...}`. Multiple tags or extra reasoning around a tag
are invalid; invalid predictions are not silently scored as correct.

All 19,354 source rows and duplicates remain eligible. The reviewed import finds:

| Dataset | Rows | Known references | Unknown references |
|---|---:|---:|---:|
| local/tsexam-mcq | 746 | 746 | 0 |
| local/bedtime | 394 | 394 | 0 |
| local/mcq2 | 100 | 100 | 0 |
| local/timemqa-full | 17,703 | 16,983 | 720 |
| local/dataset-a-rlvr | 411 | 0 | 411 |

Unknown references yield `eligible=1,missing=1` for accuracy, including when the
output is invalid, and prevent full-coverage readiness. The coverage Gate can fail
while accuracy is `insufficient_evidence`; this reports reference coverage, not a
model-quality failure. `format_valid` is a
separate reference-free metric. Neither unknown nor invalid rows are excluded or
turned into zero accuracy. Timemqa's 720 consists of 683 unresolved public choice
formats and 37 source answers outside parsed public choices. These are parser
review flags, not human-confirmed label errors. Structured RLVR scoring awaits an
original verifier or separately approved task-specific rules. Raw annotations
remain available only through explicit evaluation provenance for future review.

Dataset/card identities use `local/` because official origin/license were not
provided. Publishing or redistributing the uploaded data is outside this package's
import operation. Source content revisions and preserved raw bytes support review;
this package does not assert official benchmark equivalence beyond preserving
question/observation content and explicitly declaring its own response rules.

## License

GymTS-owned code in this package is licensed under the [MIT License](LICENSE).
Third-party libraries, upstream projects, datasets, model weights and services
retain their own licenses and terms; this package does not relicense them.
