# 第三方来源与独立许可

GymTS 框架、独立适配包与教学示例采用 [MIT License](LICENSE)。所调用的上游项目、
数据集和模型权重是不同交付物，不会因此改为 MIT；安装或使用 GymTS 不会替这些
资产授予许可。核心 wheel 不携带科学运行库、上游服务器、
数据文件、模型权重或本地实验数据库；下载与部署由调用方显式完成。

本清单提供来源与审核入口，不是对所有依赖版本和用户资产完成的许可兼容性审计。
发布者在实际分发第三方代码、数据、权重或二进制时，需核对该精确版本的 LICENSE、
NOTICE、Dataset / Model Card 与再分发条件；保留上游要求的归属声明。

| 来源 | 使用方式 | 固定身份与安装入口 |
| --- | --- | --- |
| [NetmanAIOps/sktime](https://github.com/NetmanAIOps/sktime) | LibraryTS 外部工具、loader、方法和评分 | [独立适配器](adapters/libraryts/README.md)记录指定仓库的提交；不替换成另一个同名 PyPI 项目 |
| [TimeSigma-GymTS](https://github.com/WithAnOrch1d/TimeSigma-GymTS) | 外部数据、Schema、CPU 模型和 Research 对接 | [TimeSigma 文档](adapters/timesigma/README.md) |
| [ChatTS](https://github.com/NetManAIOps/ChatTS) | 外部合成与模型 codec，独立包/运行时 | [ChatTS 文档](adapters/chatts/README.md)；具体数据和模型按原来源审核 |
| [Hugging Face Datasets](https://github.com/huggingface/datasets) / [Hub](https://huggingface.co/docs/huggingface_hub/) | 可选静态加载与下载依赖 | [HF 适配器](adapters/hf_datasets/README.md)保留原始字节、提交、文件和投射配方 |
| [Monash TSF](https://huggingface.co/datasets/Monash-University/monash_tsf) | 显式下载固定 test 文件并构造局部评价视图 | [HF 验收](docs/reports/hf-environment-2026-10-19.json)；不随源码包提供完整数据 |
| [Gymnasium](https://github.com/Farama-Foundation/Gymnasium) | 可选仿真运行时 | [Gymnasium 适配器](adapters/gymnasium/README.md) |
| [OpenEnv](https://github.com/huggingface/OpenEnv) | 官方 SDK 与单独部署的服务 | [OpenEnv 适配器](adapters/openenv/README.md)记录固定源码；服务器不进入 core wheel |
| [Prometheus](https://github.com/prometheus/prometheus) | 外部遥测服务，适配器使用 HTTP API | [Prometheus 适配器](adapters/prometheus/README.md)；本机服务验收记录二进制摘要 |
| [TRL](https://github.com/huggingface/trl)及相关模型运行库 | 外部 GRPO loss / backward / optimizer 与模型执行 | [RL 文档](adapters/rl/README.md)记录真实使用版本、profile和权重来源 |
| [GSM8K](https://github.com/openai/grade-school-math) | 显式下载的可验证推理样本 | [RL 数据说明](docs/rl-integration.md)；数据用途与划分独立记录 |
| PyYAML / PyArrow | 核心可选 YAML / Parquet 功能 | `setup.cfg` extras；不属于默认 JSON 运行依赖 |
| MkDocs | 可选本地文档构建工具 | [文档构建](docs/documentation.md)与 `requirements-docs.txt`，不属于框架运行依赖 |

五份用户提供的 benchmark 附件具有单独来源和用途记录；它们被声明为 evaluation-only。
用户声明测评用途不自动授予公开再分发权。公开数据、公开 Git 仓库和可下载权重也不
自动表示没有许可条件。

GymTS 的 MIT 许可及适用边界见[许可说明](docs/licensing.md)。发布前逐包审核新增 vendored
文件与依赖清单；若并未分发上游内容，说明其为独立下载/服务依赖，避免把来源清单
当作已经完成对上游的再许可。
