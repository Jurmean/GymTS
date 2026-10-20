# Changelog

This file records code and public-contract changes. Working-tree versions, Git tags, and package-index publication are distinct; the entries below do not prove a GitHub Release or PyPI upload exists. Dates are used only for events with explicit records.

## 0.5.0 — Unreleased

Current source version, implementing public interface specification 1.2.0. Major changes relative to the recorded 0.3.1 initial commit follow.

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
- Simulations preserve native terminal flags, final state, and reward; experiment-scope completion is represented separately.
- OpenEnv uses official stateful WebSockets, preserves unknown rewards / termination causes, and does not resend uncertain operations.
- Prometheus preserves source sample time and actual receipt time; history reads only previously delivered fixed intervals.

### Documentation and validation

- Complete Chinese and English project entry points, user guides, interface references, adapter development, contribution, security, conduct, and maintenance documentation.
- Add Issue/PR templates, citation, MIT licensing notes, third-party sources, and local documentation builds.
- Adopt the MIT License, add the standard license text, and synchronize core, adapter, teaching-package, and citation metadata; third-party projects, models, datasets, and user attachments retain their original terms.
- See [project status](docs/project-status.md) for core, independent distribution, and native validation scope; corresponding acceptance reports identify the actual versions and artifact hashes for each round.

### Migration notes

- The core no longer forwards old `gymts.integrations.chatts/timesigma/rl` Python paths. Install the independent packages and use `gymts_chatts` / `gymts_timesigma` / `gymts_rl`.
- Old plugins without pure description providers require explicit migration; planning no longer falls back to constructing runtime instances.
- The core CLI uses `--integration NAME` for explicit project activation; project-specific commands belong to their own distributions.
- New source does not rewrite sealed component, Schema, or builder identities; rescoring still requires the original task/scoring contract implementations.
- New resource views, task semantics, or scoring rules require new identities and independent references, not impersonation of an original benchmark definition.

See the [framework guide](docs/framework.md), [adapter guide](adapters/README.md), and [formal interface specification](docs/feishu/GymTS接口规范/GymTS接口规范.md).

## 0.3.1 — Existing initial commit

Repository history includes commit `cffa38f` with message `Initial release of GymTS 0.3.1`. This is code history, not verified evidence of a matching Git tag, package-index release, or long-term support branch. Preserve original Git history; do not invent publication dates or releases for unverified intermediate working-tree versions.
