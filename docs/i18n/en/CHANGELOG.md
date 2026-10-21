# Changelog

This file records code and public-contract changes. Working-tree versions, Git tags, and package-index publication are distinct; the entries below do not prove a GitHub Release or PyPI upload exists. Dates are used only for events with explicit records.

## 0.6.0 — Unreleased

Current source version, public interface specification 1.4.0. Complete the organization contracts for storing data, connecting data, organizing experiments, and recording experiments. See [ADR 0002](docs/adr/0002-experiment-organization.md) for the concrete requirements, adapter boundary, and compatibility rationale.

- Add four protocols for immutable experiment groups, frozen stage requests, execution attempts, and append-only organization events. Stages delegate to existing Run, AutoBench, capture, and publication services; domain executors remain external.
- Fix data references and artifact dependencies, with explicit retries, stale-dependent reruns, sealed-Run adoption, and interrupted-stage recovery.
- Associate Run creation with the stage in the same SQLite transaction. Add experiment/data/Run queries; rescoring existing Runs adds associations without changing ownership.
- Add `publish_build` to persist built shards and portable provenance in the data catalog, preserving the external reader, exact shard bytes, and usage permissions.
- Add `experiments`, `runs`, and `datasets publish-build` CLI commands, bilingual guides, and a complete data-to-Run/capture/score/rescore example. All 23 existing F1 schemas retain their exact definitions and historical freeze identities remain unchanged.

## 0.5.1 — F1 source baseline

Historical F1 source version, public interface specification 1.3.0. General four-kind data organization/storage explicitly belongs to EnvironmentTS core; project implementations remain external. See [ADR 0001](docs/adr/0001-core-data-source-catalog.md) for rationale and compatibility.

- Add DataSourceDefinition `gymts.data-source/1` and `gymts.source-dataset/2` for static, synthetic, simulated and live source definitions, actual snapshots and parent-resource lineage.
- Add source register/load/list, snapshot registration, source binding and sealed-Run capture. Public datasets can read portable attachments and capture metadata.
- Add `run_data` / `run-data`, `sources` and `datasets capture`, reusing real ExperimentSpecs, existing execution and AutoBenchTS without another execution/scoring engine.
- All 19 original core schemas have the same canonical digests as F0; four data protocols are additive, without rewriting v1 datasets, benchmarks, Runs or reports. All 168 core regressions and installation-outside-source distribution checks passed; frozen-F1 real four-source, portable-read and independent-rescoring technical acceptance passed; existing sixteen-package F1 compatibility also passed, with 407 discovered, 346 executed passes and 61 optional-dependency skips, including the current AReaL V13 CPU draft; coexistence, removal and core-run checks passed without changing native held-out evaluation status.
- F0 five-project and pending AReaL evidence retain their original versions rather than being rewritten for this data-layer change. This is not a release announcement.

## 0.5.0 — F0 Source Baseline

Recorded baseline, implementing public interface specification 1.2.0; no Git tag or PyPI release is inferred. Major changes relative to the recorded 0.3.1 initial commit follow.

### Framework and delivery

- Retain the two main responsibilities: EnvironmentTS execution/evidence and AutoBenchTS evaluation.
- Split project implementations into independent distributions discovered through entry points and enabled explicitly; the core has no project-name branches.
- Add pure `plan` / `validate`, declarative component descriptions, and compatibility checks; defer resource verification until a Run exists.
- Add execution seed / RNG context, fixed model/checkpoint identities, scoped artifact access, and capture correlation.
- Add DatasetCatalog, public DatasetHandle, private evaluation references, immutable resource aliases, and BenchmarkDefinition resolvers.
- Provide public DatasetBuilder provider interfaces; domain exports and external training backends remain in independent packages.

### Independent adapters and environments

- ChatTS, TimeSigma, RL, LibraryTS, the neutral timeseries domain, and benchmark TSQA install independently.
- Add five packages for HF static snapshots, the external interaction domain, Gymnasium, OpenEnv, and Prometheus.
- Add another five independent packages for TimeCopilot, ITFormer, Chronos-2, Data-Juicer, and AReaL. Adapters connect native Agents, strict native QA inference, quantile prediction/fit, data processing, and multi-turn RL backends without moving them into the core.
- Simulations preserve native terminal flags, final state, and reward; experiment-scope completion is represented separately.
- OpenEnv uses official stateful WebSockets, preserves unknown rewards / termination causes, and does not resend uncertain operations.
- Prometheus preserves source sample time and actual receipt time; history reads only previously delivered fixed intervals.

### Documentation and validation

- Complete Chinese and English project entry points, user guides, interface references, adapter development, contribution, security, conduct, and maintenance documentation.
- Add Issue/PR templates, citation, MIT licensing notes, third-party sources, and local documentation builds.
- Adopt the MIT License, add the standard license text, and synchronize core, adapter, teaching-package, and citation metadata; third-party projects, models, datasets, and user attachments retain their original terms.
- See [project status](docs/project-status.md) for core, independent distribution, and native validation scope; corresponding acceptance reports identify the actual versions and artifact hashes for each round.
- [Five-project integration and acceptance](docs/five-project-integration-acceptance-2026-10-21.md) freezes all 39 F0 core files, with zero core changes for the new integrations. TimeCopilot, ITFormer, Chronos-2, and Data-Juicer completed their stated native engineering workflows and independent rescoring; AReaL has a verified real parameter update and checkpoint publication, with held-out evaluation/rescoring pending. This does not claim complete paper reproduction or passage of quality Gates that were not configured.
- The sixteen-package offline total combines fifteen V2 packages with the V11 AReaL supplement: 404 discovered tests, 343 executed passes and 61 conditional skips (not one full check against all final source). Six cross-project CPU Runs, three fresh-process rescoring checks, and rejection of two incompatible combinations were also completed. Distribution checks and real model acceptance are reported separately; see the same acceptance document for scope, failure history, and resource boundaries.
- Preserve four real AReaL HF5 held-out failures caused by an incompatible generation argument. V12 only corrects CLI completion checks for reports without Gates. The HF4/tokenizer compatibility route awaits the user's choice; the optional V13 publisher has CPU draft evidence only, without publication or GPU execution, and is not successful held-out evaluation.

### Migration notes

- The core no longer forwards old `gymts.integrations.chatts/timesigma/rl` Python paths. Install the independent packages and use `gymts_chatts` / `gymts_timesigma` / `gymts_rl`.
- Old plugins without pure description providers require explicit migration; planning no longer falls back to constructing runtime instances.
- The core CLI uses `--integration NAME` for explicit project activation; project-specific commands belong to their own distributions.
- New source does not rewrite sealed component, Schema, or builder identities; rescoring still requires the original task/scoring contract implementations.
- New resource views, task semantics, or scoring rules require new identities and independent references, not impersonation of an original benchmark definition.

See the [framework guide](docs/framework.md), [adapter guide](adapters/README.md), and [formal interface specification](docs/feishu/GymTS接口规范/GymTS接口规范.md).

## 0.3.1 — Existing initial commit

Repository history includes commit `cffa38f` with message `Initial release of GymTS 0.3.1`. This is code history, not verified evidence of a matching Git tag, package-index release, or long-term support branch. Preserve original Git history; do not invent publication dates or releases for unverified intermediate working-tree versions.
