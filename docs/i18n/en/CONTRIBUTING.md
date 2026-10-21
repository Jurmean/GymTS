# Contributing to GymTS

Contributions through bug reports, usage feedback, documentation, and independent adapters are welcome. Read the [project overview](README.md), [code of conduct](CODE_OF_CONDUCT.md), and [support information](SUPPORT.md) first. Follow the [security policy](SECURITY.md) to report suspected vulnerabilities privately; do not include exploitation details or sensitive data in public Issues.

## Decide where the change belongs

GymTS centers on storing data, connecting data, organizing experiments, and recording experiments. EnvironmentTS owns general data, execution and evidence; core organization protocols link stages and attempts, and AutoBenchTS owns independent evaluation. Project-specific data formats, model backends, task semantics, training algorithms, and domain scoring belong in independent adapters. Sharing a repository does not allow project implementations into the `gymts` core distribution.

| Need | Preferred location |
| --- | --- |
| New data format, HF view, simulator, or testbed | Independent Environment, DatasetReader, or connector adapter |
| New task, model, scorer, or benchmark resolver | Independent domain adapter and its schemas |
| New toolset or Agent SDK | External tool/Agent adapter; the Agent chooses tool calls |
| TRL, LibraryTS, or other training capabilities | Independent training/tool adapter, reusing upstream implementations where possible |
| Execution, access boundaries, sealing, or evaluation mechanisms needed by all projects | Discuss a core contract after providing reproduction evidence |

See the [framework guide](docs/framework.md) and [interface specification 1.4.0](docs/feishu/GymTS接口规范/GymTS接口规范.md) for the current contract. The [next pluggability contract](docs/pluggability-contract-v2.md) is a draft, not an implemented contract. Follow the [adapter guide](adapters/README.md) and [environment integration guide](docs/environment-adapters.md) for new packages. See the [experiment organization guide](docs/experiment-organization.md) for fixed data/artifact inputs, stage dependencies, attempts, and continuation after failure.

Current 0.6.0 / specification 1.4.0 uses the F2.1 frozen verification baseline. [Current acceptance](docs/reports/experiment-organization-2026-10-21.json) verifies independent integration and post-uninstall rescoring, preserving all 23 existing schema hashes. Historical F0/F1 versions and evidence remain intact. A proposed core change should explain in its Issue or PR:

1. Which real project's requirement the existing interface cannot express, with minimal configuration and actual failure evidence.
2. Why independent adapters or existing extension points cannot solve it, beyond implementation convenience.
3. The proposed public contract, capability declarations, evidence structure, and failure semantics.
4. Compatibility for old configurations, adapters, and Run/CAS evidence; explicitly state migration and version boundaries where compatibility is impossible.
5. An external integration against a frozen core: execution, traces, independent evaluation, and original-Run rescoring.

## Local development

Run these commands from the repository root. Core requires Python 3.9+ and currently targets Linux/macOS for local storage. Use a separate virtual environment so dependencies from model-training environments do not become core requirements:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install "setuptools>=64" wheel packaging
python -m pip install --no-build-isolation -e .
python -B examples/quickstart.py --root /tmp/gymts-contribution-demo
```

This editable installation uses setuptools 64+ for editable-mode support; the declared minimum for distribution builds remains 58. Core JSON workflows have no third-party runtime dependencies. Install YAML, Arrow, and project-native dependencies as needed; they must not be prerequisites for discovering metadata or using unrelated projects. For offline development, prepare the declared build tools from your own wheelhouse before running checks. The two check scripts below do not access a package index themselves.

Keep active SQLite/CAS, virtual environments, and build work on disks with local locking and atomic filesystem operations. Object storage or similar mounts may hold closed immutable evidence archives, but should not be assumed suitable for active databases.

## Implementation conventions

- Use public SDKs, registries, Manifests, and schemas. Do not import core internals or add project-name branches to Runner.
- Keep planning and validation declarative: no data opening, service connections, model loading, sessions, or CAS writes. Actual I/O happens after a Run exists.
- Preserve evidence of actual calls and failures. Explicitly record unknown outcomes and possible side effects; do not automatically retry side-effecting operations.
- Use explicit component, protocol, data, and model revisions. Record source/upstream checksums, native parameters, and tool-call lineage.
- Do not turn nonexistent rewards, missing labels, or unknown end causes into zeros or success. Domain adapters interpret native semantics; the framework preserves declarations and evidence.
- Authorize public inputs, private references, and training data separately. Benchmarks are evaluation-only by default; training needs explicit usage permission and source policy.
- Discovery must not import heavy runtimes; separate installation from explicit enablement. Missing optional dependencies should yield actionable errors.
- Pass argument arrays to external processes instead of concatenated shell commands. Bound timeouts, work directories, and environments; clean up only processes/sessions you created. Never record credential values.
- Keep experiment outputs, logs, weights, downloaded data, and machine-specific paths out of distributions. Replace unshareable data with small public reproducible fixtures.

## Validate changes

Run checks appropriate to the change. Documentation and template edits need links, commands, formatting, and factual checks, without invented unit tests for prose. Logic fixes should add regressions that reproduce real defects, not assertions that repeat the implementation.

```bash
# 核心源码回归
python -B -m unittest discover -s tests -v

# 核心 sdist、wheel、sdist 重建、隔离安装和公共 API 外部插件
python -B scripts/check_release.py --output /tmp/gymts-release-check.json

# 全部独立适配包的构建、安装、发现/启用、回归、移除和共同启用
python -B scripts/check_adapters.py --output /tmp/gymts-adapter-check.json
```

Both packaging scripts need `setuptools>=58`, `wheel`, and the ability to create pip-enabled environments with `venv`; `check_adapters.py` additionally requires `packaging`. They build in temporary directories and install local artifacts using `--no-index`. Reports go to the requested paths; temporary distributions are removed at completion. The GitHub Actions [workflow](.github/workflows/ci.yml) configures Python 3.9, 3.12, and 3.13; configuration is not proof that remote CI passed for this branch.

The existing 0.5.0 [isolated core installation report](docs/reports/core-package-check-2026-10-20.json) records 160 passes. The [eleven-package report](docs/reports/environment-adapter-package-check-2026-10-19.json) records 319 tests, with 54 conditional skips. These are baselines for specific snapshots, not fixed counts for future changes. Skips caused by missing native dependencies cannot replace actual runtime verification: [native acceptance](docs/reports/environment-acceptance-2026-10-19.json) for HF, Gymnasium, OpenEnv, and Prometheus separately records sources, versions, and successful/failed traces. New native backends should include reproducible commands and dependency instructions.

## Submit a reviewable contribution

Create a focused topic branch from the current baseline. Documentation and ordinary fixes can go directly to a PR. For contract changes, new external side effects, scientific runtimes, or major refactors, first discuss interfaces and acceptance scope in an Issue. Contributors are not required to create an empty Issue as a formality.

A PR should explain the problem, resulting behavior, adapter/core boundary, actual verification commands and outcomes, conditional skips, and known limitations. Rescoring or compatibility changes should show preservation of old Run IDs/result hashes. Do not commit keys, user data, private reference answers, or complete production service endpoints. Use the [PR template](.github/PULL_REQUEST_TEMPLATE.md) to supply review material; this project currently declares no CLA or DCO process.

GymTS code and documentation use the [MIT License](LICENSE). Confirm that you have the right to contribute the relevant content under that license. When adding or citing third-party code, models, or data, record provenance and independent license requirements, and retain required notices. The project's MIT license cannot grant rights to those assets. See the [maintainer guide](docs/maintainer-guide.md) for release preparation.
