# Project status and support scope

Current working tree: GymTS **0.5.0**, public interface specification **1.2.0**. This page describes implementation and existing evidence; it does not claim a PyPI release, Git tags, a hosted platform, or a support SLA. See the [CHANGELOG](../CHANGELOG.md) for release changes.

## Available capabilities

| Area | Current implementation | Evidence or limitation |
| --- | --- | --- |
| Core execution | Synchronous local SDK / CLI, pure assembly, validation, execution, scope checks, cleanup | Python 3.9+; default JSON workflows have no third-party runtime dependencies |
| Records and storage | SQLite, immutable content artifacts, events, results, late Outcomes, Snapshots | Active Run stores require local POSIX storage; trusted-plugin API boundaries are not process sandboxes |
| Independent evaluation | Fixed expected units, independent Scorers, comparison/Gates, rescoring old Runs | Missing, failed, and insufficient evidence remain explicit; Scorers define domain counts |
| Replaceable delivery | 11 independent adapter packages, entry-point discovery, explicit activation | Sharing a repository does not bundle projects with the core; install scientific dependencies separately |
| Datasets and benchmarks | Local persistent resource catalog, public reading, private references, immutable aliases, benchmark resolvers | Not a remote HF Hub service or a general streaming platform |
| Environment sources | Synthetic data, HF static data, Gymnasium, OpenEnv, Prometheus | HF supports finite numeric views; external service acceptance used real localhost services |
| Training extensions | Public DatasetBuilder, external native rollout export, TRL GRPO, checkpoint evaluation in a new process | Accepted profiles have explicit boundaries; not a general RL trainer or completed verl adapter |
| Model and tool trajectories | Explicit ModelCall / ToolCall capture, correlation, and failure policies | Requires provider cooperation; does not intercept every SDK automatically or promise automatic redaction |

## Reading existing validation

For the frozen 0.5.0 core identity and 160 recorded core regressions, see the [freeze identity](reports/core-frozen-identity-2026-10-20.json) and [core distribution check](reports/core-package-check-2026-10-20.json). Earlier report filenames retain their generation dates. Assess applicability using the versions, SHAs, and scope inside reports rather than inferring version order from filenames.

The [environment integration acceptance](reports/environment-acceptance-2026-10-19.json) records:

- Independent builds, source rebuilds, installation, discovery, simultaneous activation, removal, and rescoring of existing core Runs across eleven packages.
- 319 tests in minimal dependency environments: 265 passed and 54 skipped according to dependency conditions.
- Another 58 tests for new adapter packages with complete runtime dependencies, with zero skips.
- Fixed official HF sources, real Gymnasium, official OpenEnv servers/SDK, and real Prometheus calls.
- Sealed failures, final states/rewards, no resend of unknown outcomes, and same-Run rescoring without new model/environment calls.

These numbers are recorded results for the corresponding source and dependency snapshots, not live status for every future CI run. The three-row HF view is not the complete Monash benchmark. Technical acceptance of fixed actions, last-value baselines, and tiny RL training is not evidence of model quality or Agent intelligence.

## Full capabilities not yet delivered

Multi-tenant authentication/quotas, remote workers, process/network isolation, forced interruption/recovery, production testbed identity and write permissions, general autonomous Agent tool loops, arbitrary HF modalities/streaming, arbitrary training profiles, and verl backends each require integration and acceptance. Exposed extension points do not imply corresponding production implementations exist.

The [next-version protocol draft](pluggability-contract-v2.md) and [enterprise platform review](enterprise-platform-roadmap.md) are design materials, not substitutes for this version’s runtime contract.

## Platforms and compatibility

The core local storage currently supports Linux/macOS; Windows has not passed acceptance as a supported platform. CI configuration includes Python 3.9, 3.12, and 3.13, but configuration alone does not mean current remote checks are green. Gymnasium 1.2.1 and the official OpenEnv runtime used in this round require Python 3.10+; see package READMEs for GPUs, model weights, and other scientific dependencies.

Both the adapter’s declared core version range and task protocol must match. Successful installation only establishes dependency resolution. `plan` / `validate` do not verify real model files, credentials, or remote availability; these are opened and recorded after a Run exists.
