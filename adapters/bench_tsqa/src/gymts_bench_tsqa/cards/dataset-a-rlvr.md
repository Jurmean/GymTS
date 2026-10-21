# local/dataset-a-rlvr

User-uploaded RLVR conversion. Content has been matched to the official ChatTS
Dataset A subquestions. The conversion distributor/license has not been verified;
`local/` is an identity, not a claim of official publication.

All 411 physical source rows are retained, including duplicates. Split:
`test`; split origin: `user_declared_evaluation`. Uses: evaluation only; training,
RL, SFT, prepare/fit and dataset-build export are not authorized.

Public questions retain complete original text, conditions and choices. Literal
time-series placeholders are reversibly projected to ordered neutral references;
all named ragged observations are stored in Float64 without truncation. Original
JSONL bytes, answers, attributes and unreviewed source metadata are private.

The corrected import reads all 411 structured references and supports all 10
abilities with the pinned deterministic ChatTS RLVR task rules. The metric is
`task_score`, not choice accuracy. See the distribution's UPSTREAM.md for exact
source revisions, license and the official Dataset A content match. Prose answers
are not the scoring authority; private structured attributes are.

Evaluation definitions use full source rows, one planned case per source row,
independent reference scoring and native AutoBenchTS plan/report contracts. The
first-public-choice baseline checks integration/coverage only, not scientific
model quality. MCQ/text/Boolean parsing policies are detailed in the package README.
