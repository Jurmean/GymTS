# Project status and support scope

Current working tree: GymTS **0.6.0**, public interface specification **1.4.0**; F2.1 organization verification passed and this version is unreleased. This page describes implementation and existing evidence; it does not claim a PyPI release, Git tags, a hosted platform, or a support SLA. See the [CHANGELOG](../CHANGELOG.md) for release changes.

This round adds `gymts.experiment-group/1`, `gymts.stage-request/1`, `gymts.stage-attempt/1` and `gymts.experiment-event/1`: fixed definitions, stage input/output bindings, independent attempts, explicit retry/recovery, Run association queries and `publish_build` publication to the persistent catalog. Declared input usage and provenance propagate to nested Runs and evaluation plans; rescoring historical Runs adds associations only. A local five-stage example has executed: 12 public observations registered, one real Run, two independent scoring passes over the same outputs, no new attempts on repeated execution and an unchanged original RunResult. F2.1 passed 196 installed core regressions, sixteen-package compatibility (417 discovered, 356 passed, 61 optional-dependency skips), and real execution, post-uninstall reads and rescoring through an independent ETTh1 adapter. See the [current evidence](reports/experiment-organization-2026-10-21.json); historical F1 retains its identity. See the [experiment organization guide](experiment-organization.md) and [ADR 0002](adr/0002-experiment-organization.md).

Historical F1 (0.5.1 / 1.3.0) adds four-kind source definitions, dataset `/2`, snapshot registration, source binding, sealed-Run capture and `run_data`. All 168 core regressions and installation-outside-source distribution checks passed, and F1 is frozen; independent real four-source, portable-read and model-free-rescoring technical acceptance passed, with existing sixteen-package F1 compatibility also passing: 407 discovered, 346 executed passes and 61 optional-dependency skips, plus coexistence, removal and core-run checks. This round includes the current AReaL V13 CPU draft and does not replace its native training or held-out evidence. All 19 original core-schema digests match F0, with only four data protocols added. Existing 0.5.0/five-project reports retain their original baseline; AReaL user choice and successful held-out evaluation remain pending. See [ADR 0001](adr/0001-core-data-source-catalog.md).

## Available capabilities

| Area | Current implementation | Evidence or limitation |
| --- | --- | --- |
| Experiment organization | Fixed group revisions, stage requests/attempts/events, dependencies and named outputs, explicit retry/rerun/recover, dataset and Run queries | Local five-stage example executed; recovery at stage boundaries, without taking over native process state; F2.1 independent-package verification passed |
| Core execution | Synchronous local SDK / CLI, pure assembly, validation, execution, scope checks, cleanup | Python 3.9+; default JSON workflows have no third-party runtime dependencies |
| Records and storage | SQLite, immutable content artifacts, events, results, late Outcomes, Snapshots | Active Run stores require local POSIX storage; trusted-plugin API boundaries are not process sandboxes |
| Independent evaluation | Fixed expected units, independent Scorers, comparison/Gates, rescoring old Runs | Missing, failed, and insufficient evidence remain explicit; Scorers define domain counts |
| Replaceable delivery | 16 independent adapter packages, entry-point discovery, explicit activation | Sharing a repository does not bundle projects with the core; install scientific dependencies separately |
| Datasets and benchmarks | Local persistent resource catalog, public reading, private references, immutable aliases, benchmark resolvers | Not a remote HF Hub service or a general streaming platform |
| Environment sources | Synthetic data, HF static data, Gymnasium, OpenEnv, Prometheus | HF supports finite numeric views; external service acceptance used real localhost services |
| Training extensions | Public DatasetBuilder, external native rollout export, TRL GRPO; native Chronos-2 fit and checkpoint-reload evaluation; AReaL TIR / PPOTrainer interfaces | Chronos-2 completed 60 updates and 16 held-out windows; AReaL has a verified real parameter update and checkpoint publication, with held-out evaluation/rescoring pending; not a general RL trainer or completed verl adapter |
| Model and tool trajectories | Explicit ModelCall / ToolCall capture, correlation, and failure policies | Requires provider cooperation; does not intercept every SDK automatically or promise automatic redaction |
| Native Agent loop | Native TimeCopilot tool selection, continuation from tool returns, and independent evaluation/rescoring | Six actual HTTP model requests and four native tool types; not a general Agent Runtime across projects or passage of model-quality requirements |
| Native models and data processing | Strict ITFormer model inference; native Data-Juicer filtering/deduplication/QA, lineage evaluation, and derived-data registration | An eight-QA view and a fixed synthetic train-only view; generated labels remain unverified, not a complete benchmark or paper reproduction |

## Reading existing validation

For the frozen 0.5.0 core identity and 160 recorded core regressions, see the [freeze identity](reports/core-frozen-identity-2026-10-20.json) and [core distribution check](reports/core-package-check-2026-10-20.json). Earlier report filenames retain their generation dates. Assess applicability using the versions, SHAs, and scope inside reports rather than inferring version order from filenames.

The earlier [environment integration acceptance](reports/environment-acceptance-2026-10-19.json) records:

- Independent builds, source rebuilds, installation, discovery, simultaneous activation, removal, and rescoring of existing core Runs across eleven packages.
- 319 tests in minimal dependency environments: 265 passed and 54 skipped according to dependency conditions.
- Another 58 tests for new adapter packages with complete runtime dependencies, with zero skips.
- Fixed official HF sources, real Gymnasium, official OpenEnv servers/SDK, and real Prometheus calls.
- Sealed failures, final states/rewards, no resend of unknown outcomes, and same-Run rescoring without new model/environment calls.

These numbers are recorded results for the corresponding source and dependency snapshots, not live status for every future CI run. The three-row HF view is not the complete Monash benchmark. Technical acceptance of fixed actions, last-value baselines, and tiny RL training is not evidence of model quality or Agent intelligence.

This round’s [five-project integration and acceptance](five-project-integration-acceptance-2026-10-21.md) freezes all 39 F0 core files, with no core changes for the new integrations. TimeCopilot, ITFormer, Chronos-2, and Data-Juicer completed their stated native execution, independent evaluation, and zero-inference rescoring. AReaL has 32 verified real Runs, nonzero advantages, one Adam update and checkpoint publication; fresh-process held-out evaluation/rescoring are pending, with the first four attempts preserved. Evaluations without quality Gates retain `insufficient_evidence`; engineering completion, model correctness, generalization, and complete paper reproduction are separate claims.

The first AReaL HF5 held-out evaluation records four expected, zero succeeded and four failed Runs: HF5 removed a generation argument used by the shared HF4 Candidate. Its original report and budget remain preserved. HF4 tiny CPU checks and lossless production-tokenizer metadata projection checks establish equality across 151,665 vocabulary mappings, IDs and templates. The compatibility route awaits the user's choice; the optional V13 publisher is an unpublished draft with no GPU run. Training, CPU compatibility and successful held-out evaluation remain distinct.

The V2 sixteen-package frozen distribution snapshot originally discovered 398 tests: 339 passed and 59 skipped. Replacing old AReaL 13/13/0 with V11 AReaL 19/17/2 gives 404 discovered, 343 executed passes and 61 conditional skips. This combines two frozen V2 + V11 reports, rather than one full check against all final source. V11 full-scientific CPU 19/19 with zero skips is separate and not counted twice; V2 installation, joint activation, removal and core compatibility evidence remains intact. Six cross-project CPU Runs also replaced LibraryTS Candidates, an equivalent CSV Source, and an independent trend Task on the same public snapshot. Three evaluations were rescored in fresh processes with model/source calls forbidden; two incompatible combinations were rejected before native calls. See the same acceptance document for identities and scope. Conditional skips, fixed Candidates, and single-task metrics do not establish a new Agent experiment.

## Full capabilities not yet delivered

Multi-tenant authentication/quotas, general remote workers, operating-system process/network isolation, automatic recovery of arbitrary backend internal execution state, production testbed identity and write permissions, a general Agent Runtime, arbitrary HF modalities/streaming, arbitrary training profiles, and verl backends each require integration and acceptance. The accepted native TimeCopilot loop and adapter-owned Linux process-group cleanup do not establish those general capabilities. Exposed extension points do not imply corresponding production implementations exist.

The [next-version protocol draft](pluggability-contract-v2.md) and [enterprise platform review](enterprise-platform-roadmap.md) are design materials, not substitutes for this version’s runtime contract.

## Platforms and compatibility

The core local storage currently supports Linux/macOS; Windows has not passed acceptance as a supported platform. CI configuration includes Python 3.9, 3.12, and 3.13, but configuration alone does not mean current remote checks are green. Gymnasium 1.2.1 and the official OpenEnv runtime used in this round require Python 3.10+; see package READMEs for GPUs, model weights, and other scientific dependencies.

Both the adapter’s declared core version range and task protocol must match. Successful installation only establishes dependency resolution. `plan` / `validate` do not verify real model files, credentials, or remote availability; these are opened and recorded after a Run exists.
