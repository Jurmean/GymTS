# MIT licensing and third-party boundaries

GymTS uses the **MIT License**. See the root [LICENSE](../LICENSE) for complete permission, copyright, and disclaimer terms. Framework code, independent adapters, teaching examples, and documentation use this license; separately identified third-party content retains its original terms. Preserve applicable copyright and license notices when distributing; the `LICENSE` text governs.

## Separate deliverables have separate permissions

GymTS’s MIT license does not relicense external projects, model weights, datasets, binaries, or user attachments. Installing an adapter, calling a service, or converting formats does not change their licenses or usage restrictions. The five existing benchmark attachments remain evaluation-only; adopting MIT for the framework does not authorize training on them or public redistribution without source permission.

The [third-party source list](../THIRD_PARTY.md) provides review entry points for projects, datasets, and weights. When distributing third-party materials, check the exact version’s LICENSE, NOTICE, and Dataset / Model Card and preserve required attribution and other notices. This list is not a completed compatibility audit of every third-party license.

## Maintenance and distribution

Core and adapter metadata, source distributions, and wheels should declare MIT and include the corresponding license text. `CITATION.cff` records the software license and version; citation does not replace licensing notices. See the [maintainer guide](maintainer-guide.md) for build and verification steps. Historical acceptance reports preserve their original licensing state and artifact hashes rather than being rewritten for this decision. Adopting MIT does not establish a Git tag or package-index release.

See the [final MIT validation summary](reports/mit-license-2026-10-20.json) for this round’s license text, distribution metadata, and artifact verification.
