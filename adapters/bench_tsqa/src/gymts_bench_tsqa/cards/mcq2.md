# local/mcq2

User-uploaded benchmark resource. Source and license have not been independently
verified; `local/` is an identity, not a claim of official publication.

All 100 physical source rows are retained, including duplicates. Split:
`test`; split origin: `user_declared_evaluation`. Uses: evaluation only; training,
RL, SFT, prepare/fit and dataset-build export are not authorized.

Public questions retain complete original text, conditions and choices. Literal
time-series placeholders are reversibly projected to ordered neutral references;
all named ragged observations are stored in Float64 without truncation. Original
JSONL bytes, answers, attributes and unreviewed source metadata are private.

The versioned `tsqa.single-answer/1` rules identify 100 known references and
0 unknown references on these exact reviewed bytes. Unknown cases stay
eligible and report missing/insufficient evidence; they are never auto-excluded.
The immutable quality report records actual task kinds, source hashes, duplicate
groups and unresolved-rule reasons. Parser review flags do not prove label errors.

Evaluation definitions use full source rows, one planned case per source row,
independent reference scoring and native AutoBenchTS plan/report contracts. The
first-public-choice baseline checks integration/coverage only, not scientific
model quality. MCQ/text/Boolean parsing policies are detailed in the package README.
