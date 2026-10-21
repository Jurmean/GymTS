# Dataset A scoring provenance

The Dataset A RLVR task rules in `chatts_rlvr_rules.py` are adapted from
`src/open_r1/reward_qa.py` in the local open-r1-zzr checkout, remote
<https://gitee.com/wannabtl/open-r1-zzr.git>, revision
`dc2dcb091f5268fb4c87b89584f2ac120a095e5e`.
The original file SHA-256 is
`415e0e278a31769a9f6e522315b0c6fc92fe8c68a06b805e7d3ef17da03ee8ff`.
Its MIT copyright/license header is retained in the adapted file. The complete
ChatTS MIT notice is distributed as `LICENSE-ChatTS`.

The original ChatTS project provides its evaluator at
<https://github.com/NetManAIOps/ChatTS/blob/a16ca1a7bd2d0cbe1dd40af37cb5658e7008357e/evaluation/evaluate_qa.py>.
Its README explains that structured `attributes` are evaluation labels, while
`answer` is reference text. Official Dataset A is at
<https://zenodo.org/records/14349206> (`dataset_a.json`, MD5
`1978d2ae5f2760ef944477fdcab223b2`). Its 159 compound questions contain 411
subquestions. The uploaded 411 rows preserve the exact multiset of time-series
arrays, column names, attributes and abilities after removing `-inductive` from
ability names. This identifies the content source, not the distributor or license
of the transformed upload. Some transformed prompts omit the original request
for a physical explanation. The RLVR variant is therefore scored by its pinned
deterministic rules, not advertised as original ChatTS benchmark equivalence.

Changes from the local reward file:

- Retain only 3 text helpers and 10 Dataset A task evaluators. Remove unused
  third-party imports; registration and scoring need only Python's standard library.
- Replace dynamic `eval` dispatch with a fixed allowlist in `structured.py`.
- Reject non-Yes/No deductive references before scoring. The unsupported judge
  branch raises `ValueError`; no RAGAS, API key or model service is loaded.
- Deep-copy annotations before evaluation because the original local evaluator
  normalizes local feature types in place.
- Preserve the original outer reward aggregation: mean each nonempty category,
  numeric and reasoning list, then mean those means. Malformed response bodies
  score zero, as in the original outer reward's exception handling.

The result is `task_score`, a soft score in [0,1], not MCQ accuracy. Numeric
tolerances, local matching rules and cluster F1 retain the pinned RLVR behavior.
Any future change to those rules requires a new `RULE_REF` and parity evidence.

No corresponding official evaluator has been verified for the uploaded
`timemqa_full.jsonl` transformation. Its declared response alphabet can be parsed
independently of its option text. Unresolved or conflicting public options are
recorded as input review issues, not missing answers; affected rows remain in
the planned denominator and yield insufficient evidence for accuracy.
