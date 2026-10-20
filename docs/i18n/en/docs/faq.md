# Frequently asked questions

This page separates current capabilities, usage constraints, and future designs. Start at the [documentation index](README.md); see [support](../SUPPORT.md) for the minimum information needed to reproduce an error.

## Project and boundaries

### What are GymTS, EnvironmentTS, and AutoBenchTS?

GymTS is the unified SDK and project entry point. EnvironmentTS owns execution, access scope, lifecycle, and evidence for an experiment. AutoBenchTS owns fixed evaluation plans, independent scoring, comparisons, and rescoring of original Runs. Public interfaces connect data, tasks, models, toolsets, and domain scoring. A new project does not require copying an executor or evaluation system.

### Are LibraryTS, TimeSigma, ChatTS, HF, and similar projects built into core?

No. Projects are installed as independent adapter packages and explicitly enabled; the core distribution does not contain them. Shared domain packages `gymts-timeseries` and `gymts-interaction` are also independently distributed. Core contains only small deterministic reference plugins for checks and examples. See the [adapter guide](../adapters/README.md) for the directory layout.

### Where do toolsets fit? Does GymTS choose tools for the Agent?

Toolsets are external providers. The Agent selects tools and arguments; the Agent SDK/tool adapter or external backend executes them, while GymTS preserves the associated permissions and evidence. Native calls in current environment examples and fixed-action Candidates do not constitute acceptance of a general autonomous Agent tool-selection loop. See [Agents and toolsets](agent-toolsets.md).

### Is this already a multi-user cloud platform or an untrusted-code sandbox?

The current implementation is a synchronous local Python framework. General remote workers, forced process interruption, recovery, tenant permission services, and cloud resource scheduling have not been accepted. Plugins must be trusted; isolation must come from an external runtime. See the [platform roadmap](enterprise-platform-roadmap.md) and [security policy](../SECURITY.md).

## Installation and getting started

### Do I need a GPU, a large model, a database service, or a key to start?

The basic quickstart needs none of these. Run from the source root:

```bash
python3 -B examples/quickstart.py --root /tmp/gymts-first-run
```

It uses local synthetic sequences and reference components to verify execution, evaluation, late labels, and rescoring. Core requires Python 3.9+; optional native runtimes such as Gymnasium 1.2.1 and the official OpenEnv SDK used in this round have higher requirements of their own.

### Why does storage creation fail on Windows or a mounted drive?

The local artifact backend requires POSIX directory-relative access, no-follow semantics, and durable operations, targeting Linux/macOS. Do not assume a network/object-storage mount supports active SQLite and the required filesystem semantics. Put the Run root, cache, and temporary builds on local disk, then archive to shared storage after closing writers. Windows users can use a Linux environment with these semantics; native Windows has not been verified.

### I installed an adapter. Why are its components missing from `plugins`?

Installation enables discovery; explicit activation registers components. Use `GymTS.available_integrations()` to inspect metadata, pass `integrations=("集成名",)` in Python, or put `--integration 集成名` before the generic CLI subcommand. For example: `gymts --integration chatts plugins`. Integration and pip distribution names can differ; use the adapter's README. Discovery should not import model runtimes, and enabling a plugin should not load models during planning.

### Why can I not read YAML configuration?

JSON has no additional runtime dependency. YAML needs the optional `gymts[yaml]` dependency; from the source directory use `python -m pip install -e '.[yaml]'`. Model, HF, and simulation dependencies are installed separately.

### Why does the CLI reject `--store`?

Global arguments must precede the subcommand, for example:

```bash
gymts --store /tmp/gymts-first-run inspect RUN_ID --events
```

Replace `RUN_ID` with your actual ID, and use the store that created that Run. Consult `gymts --help` and each subcommand's `--help` for full syntax.

## Data, benchmarks, and models

### Can I store and read data as with HF Datasets?

There are local immutable SourceDatasetRevision, DatasetHandle, and BenchmarkDefinition resources. Read by ID/revision/config/split, select rows, browse batches, convert to optional HF views, and resolve benchmarks into native EvaluationSpec. This is not a complete HF Hub: general remote synchronization, arbitrary modalities, streaming services, and distributed queries are absent. [Resource design](dataset-benchmark-catalog-design.md) covers storage and interfaces. The [HF adapter](../adapters/hf_datasets/README.md) supports limited numeric time-series views from fixed Hub commits, save_to_disk, and explicit local files.

### Why are datasets and benchmarks separate?

A dataset preserves source bytes, public inputs, private references, features, and usage policies. A benchmark fixes questions/splits, tasks, scoring, and comparison rules, then resolves into EvaluationSpec rather than implementing a separate execution/reporting system. Changing scoring rules generally creates a new benchmark/evaluation revision instead of modifying sealed Runs.

### Can I use a registered benchmark directly for RL training?

Not by default. The five user-uploaded JSONL files were explicitly designated for evaluation and registered as `evaluation-only`; training, prepare, and dataset_build are rejected. HF evaluation projections do not automatically authorize training either. Training requires separate data with appropriate provenance and usage permission. Changing exporters, renaming files, or removing labels cannot bypass source policy. The [RL guide](rl-integration.md) describes the separate training data and TRL integration.

### How do I replace data, tasks, models, or scorers?

Compose registered Environment/Task/Candidate/Scorer implementations using fixed schemas and component revisions. Reject incompatible capabilities at planning or validation. Formats, native model calls, and domain interpretation belong in adapters, without core branches by project name. See [component replacement verification](component-replacement-validation-2026-10-19.md) and the [framework guide](framework.md).

### Where are data and trajectories actually stored?

`GymTS(root=...)` or CLI `--store` selects the active Run/CAS/records root, defaulting to `.gymts`. Long-term data and benchmark resources live in `data_home` (or `GYMTS_DATA_HOME`, default `gymts` under XDG data). Rebuildable resource caches live in `cache_home` (or `GYMTS_CACHE_HOME`, default `gymts` under XDG cache). Override them with `--data-home` and `--cache-home`. Long-term AssetRef and experiment ArtifactRef are different; required content becomes execution evidence after entering this Run's CAS. Copying only SQLite or a final report does not copy the full experiment: close storage and retain every associated artifact.

## Execution, evaluation, and failures

### Why does a successful `run` not mean the benchmark passed?

Run status describes execution; AutoBenchTS verdict describes evaluation against the configured references and rules. A workflow can complete with missing labels or unmet quality conditions. CLI configuration/validation errors exit 2, failed or cancelled Runs exit 1, and completed evaluations with insufficient evidence can exit 0. Automation must inspect `status`, `verdict`, and coverage together.

### Is `insufficient_evidence` an execution failure?

It usually means the current references, outputs, available metrics, or coverage cannot support a conclusion. Do not insert zeros or drop difficult cases automatically. Inspect missing/invalid counts, matching, failed units, and Gate reasons. Missing labels can be attached later, followed by rescoring the original Runs.

### Does rescoring call the model again or restart the environment?

`AutoBenchTS.score`/`gymts score` creates a new evaluation from fixed old Runs and reference snapshots, without calling Candidates or live services again. Run IDs, original RunResult, and event evidence remain unchanged, and the new evaluation links to the old one. The scoring contracts that interpret old tasks/results must still be installed and enabled. Removing the model SDK is not the same as removing all domain scoring packages.

### Can live or simulation reruns reproduce the same world state?

A deployment name or seed field alone cannot guarantee that. Static sources can explicitly freeze bytes. Gymnasium reproducibility depends on its native environment, version, and seed implementation. OpenEnv currently rejects seeds whose support cannot be established. Prometheus is an attach-only, read-only live source; real time does not rewind. Compare Candidates using common frozen replay or explicitly assigned separate windows. Rescoring original Runs reads captured evidence.

### Why is unknown reward not zero, and OpenEnv done not terminated?

Missing values differ from a real 0, and native done may not distinguish natural termination from external truncation. Adapters retain null and unknown causes; only affected metrics have insufficient evidence, while other supported metrics can still be evaluated. Gymnasium terminated/truncated retain their native meanings. GymTS scope ending is expressed separately without inventing upstream end flags. See the [environment integration guide](environment-adapters.md).

### Why not retry service requests automatically after timeouts?

The server may already have performed the action. Retrying can duplicate side effects or advance a session twice. Record unknown/possible state, request/response evidence, and pending operations; explicit backend recovery rules must determine the next step. The current implementation cannot treat every timeout as proof that nothing happened.

### Can maintainers inspect my trace with only a Run ID?

No. An ID identifies a local record; it is not an upload or sharing link. Use the same `--store` with `inspect RUN_ID --events` and share a minimal redacted excerpt. Associated CAS may contain private references, prompts, service responses, and original attachments; review them separately before sharing a complete directory. There is no general automatic-redaction backend. See the [security policy](../SECURITY.md).

## Contributing, verification, and releases

### Do skipped tests in a minimal installation show that a backend works?

No. Independent-package checks deliberately use minimal environments and conditionally skip optional native dependencies. Complete backends need separate native tests and actual calls under fixed dependencies. The [acceptance report](reports/environment-acceptance-2026-10-19.json) distinguishes 319 minimal-environment tests (54 skipped) from 58 new-adapter native tests. It proves a particular snapshot and scope, not all future versions, production services, or model quality.

### How do I contribute, and which license applies?

Read [Contributing](../CONTRIBUTING.md) and prefer new independent adapters under the current interfaces. GymTS code and documentation use the [MIT License](../LICENSE); the license text contains the full terms. Third-party data, models, code, and user attachments retain their own provenance, licenses, and usage restrictions, and are not relicensed by GymTS adopting MIT. See the [maintainer guide](maintainer-guide.md) for release verification.
