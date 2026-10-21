# local/timemqa-full

User-uploaded benchmark resource. Source and license have not been independently
verified; `local/` is an identity, not a claim of official publication.

All 17,703 physical source rows are retained, including duplicates. Split:
`test`; split origin: `user_declared_evaluation`. Uses: evaluation only; training,
RL, SFT, prepare/fit and dataset-build export are not authorized.

Public questions retain complete original text, conditions and choices. Literal
time-series placeholders are reversibly projected to ordered neutral references;
all named ragged observations are stored in Float64 without truncation. Original
JSONL bytes, answers, attributes and unreviewed source metadata are private.

Parser v2 reads all 17,703 answer labels. There are 720 separate input review
flags: 683 incomplete/unresolved public option blocks and 37 reference labels
outside visible options. None is classified as a missing reference. Their source
row numbers and reasons are retained in the quality audit. Input review rows
remain eligible/missing for accuracy; no options or answers are invented.

Evaluation definitions use full source rows, one planned case per source row,
independent reference scoring and native AutoBenchTS plan/report contracts. The
first-public-choice baseline checks integration/coverage only, not scientific
model quality. MCQ/text/Boolean parsing policies are detailed in the package README.
