# Maintenance and release preparation

This guide describes the repository's currently runnable maintenance workflow. It does not imply a PyPI publication, a formal release/tag, or passing remote CI. See [Contributing](../CONTRIBUTING.md) for development rules and the [security policy](../SECURITY.md) for vulnerabilities. Core is version 0.5.0, with specification baseline 1.2.0. The project uses the [MIT License](../LICENSE); third-party code, models, and data retain their own provenance and license conditions.

## Maintenance boundaries

Core contains only general execution, resource/evidence interfaces, and evaluation. Projects belong in independent distributions. Neutral domain contracts can also be shared as independent packages; reuse by multiple projects does not automatically move them into core. Review domain semantics, access authorization, failure evidence, and the rescoring loop before considering a shared abstraction. The [environment guide](environment-adapters.md) records actual zero-core-change cases.

Core changes require a real unexpressible need, reasons adapters cannot solve it, public contract changes, and compatibility for existing projects. Periodically freeze `gymts/**/*.py` and `setup.cfg`, fix wheel and source-tree identities, and let an independent project run, seal evidence, evaluate, and rescore original Runs without modifying core. A freeze is an acceptance baseline for a round, not a permanent ban on corrections. If broken, establish a new baseline and preserve old evidence; do not overwrite Runs or represent a new implementation as an old revision.

## Sources for documentation and facts

| Content | Maintained source |
| --- | --- |
| Core version, Python range, extras, and package entry points | `setup.cfg`, `gymts/__init__.py` |
| Public execution/evaluation contracts | [Interface specification](feishu/GymTS接口规范/GymTS接口规范.md), [framework guide](framework.md) |
| Available integrations, dependencies, and commands | Each `adapters/*/setup.cfg` and README |
| Core distribution contents | `MANIFEST.in`, [core check script](../scripts/check_release.py) |
| Independent adapter contents and coexistence | Each adapter MANIFEST, [adapter check script](../scripts/check_adapters.py) |
| Performed verification and its limitations | [Acceptance report](reports/environment-acceptance-2026-10-19.json) and associated logs/hashes |
| CI configuration | [GitHub Actions workflow](../.github/workflows/ci.yml); actual outcomes are the runs for the relevant commit |

Some earlier environment reports use 2026-10-20, preserving the host timezone's naming when generated. Do not rewrite historical material merely to align current documentation dates. Assess applicability by version, source identity, and report contents. Adopting MIT does not rewrite the license status or hashes recorded historically. Distinguish design drafts, roadmaps, implemented interfaces, and native acceptance scope.

## Versioning and compatibility recommendations

There is currently no public long-term support or stable 1.x compatibility commitment. These are maintenance recommendations; confirm the adopted policy in formal release notes:

- During 0.x, bump the minor version for changes that break public configurations, protocols, imports, or persistent evidence reading, and provide migration notes.
- Use patch versions for compatible fixes and documentation clarification. Protocol messages and component revisions keep their own identities; a distribution-version change must not hide content changes.
- Version adapters independently and declare the actually verified `gymts` compatibility range, without forcing every project onto one release schedule.
- Fix ComponentRef, data revisions, model implementations, and reference snapshots. Published immutable content must not be overwritten.
- Preserve old Run/CAS evidence; rescoring creates a new evaluation. New Scorers or labels must not modify original results in place.
- If a new scoring contract is incompatible with old messages, retain the old scoring adapter or provide an explicit conversion. Do not silently replace a schema ID's meaning.

See the root [README](../README.md) for import/installation changes from 0.3.x to independent project packages. Environment integration acceptance for 0.5.0 uses the existing frozen tree and wheel; new adapters are accepted separately. Do not change core semantics simply for documentation release convenience.

The MIT synchronization updates only license texts, documentation, and packaging metadata. The `setup.cfg` hash and newly built wheel identity change, but core Python implementation and public contracts do not. Retain old frozen wheels, source identities, and experiment reports. New artifacts must record their own hashes instead of impersonating the wheel used in earlier acceptance.

## Checks for every PR

Read the actual diff and related requirements. Ensure it contains no local experiment environment, private benchmark, credential, or downloaded model. Verify repository adapters remain outside the core wheel, discovery does not import project runtimes, and explicit activation is safely repeatable. Domain missing/invalid/unknown semantics must be explicit; passing integration checks is not evidence of improved model quality.

Select verification by impact. For documentation, check links, commands, versions, fences, and claims; do not run training to increase a test count. After core or packaging changes, run the following checks. New backends additionally require bounded native acceptance according to their README.

```bash
# 环境预先具备 setuptools>=58、wheel、venv/pip；以下检查不访问包索引。
python -B -m unittest discover -s tests -v
python -B scripts/check_release.py --output /tmp/gymts-release-check.json
python -B scripts/check_adapters.py --output /tmp/gymts-adapter-check.json
```

`check_release.py` builds core sdist, direct wheel, and an sdist-rebuilt wheel; installs outside the source tree into clean environments; runs core regressions and a temporary external plugin; and checks archive paths, contents, and known key patterns. `check_adapters.py` discovers `adapters/*/pyproject.toml`, builds/rebuilds/installs each independently, checks discovery without imports, explicit activation, regressions, core behavior and old-output rescoring after removal, then coexistence of all packages. Shared domain dependencies resolve only from the local wheelhouse. The scripts remove temporary distributions when finished; `--output` retains only the JSON report.

Existing baselines are 160 core tests with no skips, and 319 tests for 11 independent packages: 265 passed and 54 skipped for missing optional dependencies. New environment adapters have a further 58 tests in complete native runtimes; see [acceptance](reports/environment-acceptance-2026-10-19.json). Record actual results, not skips as passes. Existing counts are not invariants that new tests must preserve. The workflow configures Python 3.9/3.12/3.13; local syntax parsing or one interpreter passing does not mean this matrix passed remotely.

## Evidence, credentials, and third-party material

Each native acceptance record fixes core/adapter identities, upstream versions, data/model sources, commands, budgets, successful/failed Runs, scoring references, same-Run rescoring, and limitations. For services, state session/host ownership, tested authentication scope, unknown side effects, and cleanup. Close only resources you created and own; ending an example does not authorize closing a user's existing testbed.

Keep active SQLite/CAS and build/training work on appropriate local filesystems. Close all writers before archiving the complete store. Read back the archive from its destination, verify hashes, and retain reference manifests and necessary schema/code identities. Evidence archives under `output/` may exist only on the verification host and are Git-ignored. A path in a public report is not an automatic download link for external users. Public reproduction still needs shareable fixtures, commands, and dependencies.

Manually review source, documentation, examples, archives, and Git changes before publication. Packaging checks are not a Git history review or comprehensive secret audit. Reference answers, raw responses, and logs may be sensitive. Do not edit sealed evidence directly to redact it. Instead create a separately reviewed projection, preserve the original authorization boundaries, and do not describe the edited view as an original record.

Record separate provenance, fixed versions, and license requirements for third-party code, data, models, and binaries. The five user-uploaded benchmarks remain evaluation-only after export, renaming, public projection, or a change of training framework. An asset with unknown licensing is not redistributable merely because it appears in the repository.

## Release-candidate checklist

These preparation and review steps do not automatically create tags, upload packages, or publish releases:

1. Confirm scope, versions, and public contracts; compare against the frozen baseline for differences/compatibility, and update migration notes and changelog.
2. Check MIT text, copyright notices, and metadata for every package. Ensure candidate source packages/wheels contain license files, and review independent terms for new third-party content.
3. Check README, installation paths, examples, and adapter versions. Users must not rely on a particular machine's absolute paths, private attachments, or credentials.
4. Run relevant regressions, isolated packaging checks, and necessary native acceptance. Save reports and identify conditional skips and uncovered platforms.
5. Inspect final sdist/wheel inventories, hashes, metadata, and optional dependencies; ensure project packages do not enter the core namespace.
6. Prepare core and adapter artifacts, third-party notices, and release notes separately, matching the verified versions.
7. Review all files/attachments intended for publication for credentials or restricted data, and check stated limitations and security-reporting availability.
8. Only tag, upload, or announce after explicit authorization through the repository's release process. This guide defines no automated publication credential or workflow.

To retain candidate artifacts, call the current setuptools backend from a **copied source directory** to avoid polluting the working tree:

```bash
# 先自行把候选核心源码复制到 /tmp/gymts-release-source。
cd /tmp/gymts-release-source
mkdir -p /tmp/gymts-release-artifacts
python -c 'import setuptools.build_meta as b; b.build_sdist("/tmp/gymts-release-artifacts"); b.build_wheel("/tmp/gymts-release-artifacts")'
```

Build adapters the same way from their own source copies. This creates local artifacts only; it does not publish to a package index. Formal candidates still require the check scripts. A successful build alone is not complete acceptance.

Core `MANIFEST.in` intentionally excludes `docs/`, `adapters/`, and local experiment outputs; adapters distribute independently. Complete usage documentation ships with the Git repository and can be built into a local static site following [documentation maintenance](documentation.md), without automatic deployment. The teaching adapter lives in a full checkout, and `examples/adapters/` is explicitly excluded from core distributions. Do not claim installing a core wheel supplies all documentation, projects, or experiment data.
