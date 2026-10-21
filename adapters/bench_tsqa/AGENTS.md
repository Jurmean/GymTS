# Benchmark integration requirements

Before implementing or changing a dataset parser/scorer, inspect the upstream
dataset schema, official evaluation code and any existing local reward adapter.
Record exact revisions and transformation differences in UPSTREAM.md. Reuse
applicable upstream rules; do not silently replace structured scoring with an
MCQ-only parser. Do not claim that no official parser exists without checking.

Before reporting coverage or updating slides/docs, audit every source row and
separately report reference availability, parser/scorer support, input quality
issues and actual model execution. Keep row-level reasons and source hashes.
Missing parser support is an implementation gap, never evidence of missing gold
labels. Preserve planned denominators and immutable historical runs/reports.
Use regression tests and deterministic upstream parity checks for scoring changes.
