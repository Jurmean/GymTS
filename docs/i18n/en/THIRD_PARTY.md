# Third-party sources and independent licenses

The GymTS framework, independent adapters, and teaching examples use the [MIT License](LICENSE). Upstream projects, datasets, and model weights are separate deliverables and do not thereby become MIT-licensed; installing or using GymTS does not grant permission for those assets. The core wheel does not include scientific runtimes, upstream servers, datasets, model weights, or local experiment databases. Callers explicitly perform downloads and deployment.

This list provides sources and review entry points, not a completed license compatibility audit of every dependency version or user asset. Distributors of third-party code, data, weights, or binaries must check the exact version’s LICENSE, NOTICE, Dataset / Model Card, and redistribution conditions, retaining required upstream attribution.

| Source | Usage | Fixed identity and installation entry point |
| --- | --- | --- |
| [NetmanAIOps/sktime](https://github.com/NetmanAIOps/sktime) | External LibraryTS tools, loaders, methods, and scoring | The [independent adapter](adapters/libraryts/README.md) records the specified repository commit; do not substitute a different same-name PyPI project |
| [TimeSigma-GymTS](https://github.com/WithAnOrch1d/TimeSigma-GymTS) | External data, Schemas, CPU models, Research integration | [TimeSigma documentation](adapters/timesigma/README.md) |
| [ChatTS](https://github.com/NetManAIOps/ChatTS) | External synthesis and model codecs; independent package/runtime | [ChatTS documentation](adapters/chatts/README.md); review specific data and models at their original sources |
| [Hugging Face Datasets](https://github.com/huggingface/datasets) / [Hub](https://huggingface.co/docs/huggingface_hub/) | Optional static loading and download dependencies | The [HF adapter](adapters/hf_datasets/README.md) preserves original bytes, commit, files, and projection recipes |
| [Monash TSF](https://huggingface.co/datasets/Monash-University/monash_tsf) | Explicit fixed test-file download and local evaluation view | [HF acceptance](docs/reports/hf-environment-2026-10-19.json); the complete dataset does not ship with the source package |
| [Gymnasium](https://github.com/Farama-Foundation/Gymnasium) | Optional simulation runtime | [Gymnasium adapter](adapters/gymnasium/README.md) |
| [OpenEnv](https://github.com/huggingface/OpenEnv) | Official SDK and separately deployed service | The [OpenEnv adapter](adapters/openenv/README.md) records fixed source; servers do not enter the core wheel |
| [Prometheus](https://github.com/prometheus/prometheus) | External telemetry service accessed through HTTP API | [Prometheus adapter](adapters/prometheus/README.md); local acceptance records binary hashes |
| [TRL](https://github.com/huggingface/trl) and model runtimes | External GRPO loss / backward / optimizer and model execution | [RL documentation](adapters/rl/README.md) records actual versions, profiles, and weight sources |
| [GSM8K](https://github.com/openai/grade-school-math) | Explicitly downloaded verifiable reasoning samples | [RL data notes](docs/rl-integration.md); record purposes and splits separately |
| PyYAML / PyArrow | Optional core YAML / Parquet features | `setup.cfg` extras; not default JSON runtime dependencies |
| MkDocs | Optional local documentation builder | [Documentation build](docs/documentation.md) and `requirements-docs.txt`; not a framework runtime dependency |

The five user-provided benchmark attachments have separate source and usage records and are declared evaluation-only. Declaring an evaluation purpose does not grant public redistribution rights. Public datasets, public Git repositories, and downloadable weights also have license conditions.

See [licensing notes](docs/licensing.md) for GymTS’s MIT license and boundaries. Review newly vendored files and dependency lists package by package before release. Where upstream content is not distributed, identify it as an independent download/service dependency; a source list is not proof of upstream relicensing.
