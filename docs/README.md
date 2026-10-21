# GymTS 文档

当前源码为未发行的 **0.6.0** 工作树，公共合同 **1.4.0**，F2.1 组织层技术验收已通过。文档以 EnvironmentTS 数据组织/执行/证据、
AutoBenchTS 评价两个稳定职责组织。设计草案和历史实验记录与当前使用文档分别列出。

## 开始使用

| 你想做什么 | 文档 |
| --- | --- |
| 了解项目目标、角色、实验边界与系统位置 | [完整项目说明](overview.md) |
| 安装、第一次运行、评价和原 Run 重评 | [使用手册](user-guide.md) |
| 固定数据引用、阶段依赖、失败续接与数据回库 | [实验组织指南](experiment-organization.md) |
| 查命令、参数、API 和配置结构 | [API / CLI 参考](reference.md) |
| 找能直接运行的脚本和配置 | [示例目录](../examples/README.md) |
| 排查常见错误 | [FAQ](faq.md) |
| 核对当前版本可用能力 | [项目状态](project-status.md) |
| 阅读英文项目入口 | [English README](../README.en.md) |

## 核心概念与使用专题

- [框架实现指南](framework.md)：公开 SDK、组件生命周期、装配、访问边界、记录、独立评价与训练扩展。
- [环境接入](environment-adapters.md)：合成、HF 静态、Gymnasium、OpenEnv 和 Prometheus；调用、时钟、所有权与真实验收范围。
- [数据与 benchmark 目录](dataset-benchmark-catalog-design.md)：EnvironmentTS 数据读取、公开/私有资源、AutoBenchTS 基准解析与长期存放。
- [实验组织与数据回库](experiment-organization.md)：固定数据引用、阶段依赖、attempt、显式重试/恢复与全链查询。
- [ADR 0002：实验组织协议](adr/0002-experiment-organization.md)：本轮核心改动理由、适配器边界与历史兼容。
- [ADR 0001：四类核心数据组织](adr/0001-core-data-source-catalog.md)：真实缺口、核心职责修正、旧协议兼容与 F1 冻结验证。
- [Agent 与外部工具集](agent-toolsets.md)：Agent 决策、工具执行、环境读写与私有评分的边界，以及当前尚未验收的通用工具循环。
- [正式接口规范 1.4.0](feishu/GymTS接口规范/GymTS接口规范.md)：字段、状态、顺序、错误、轨迹和接入合同；第 21 节定义本轮组织合同，第 20 节保留历史 F1 数据层验收范围。

## 项目与领域适配器

先看[独立适配包总览](../adapters/README.md)。每个包有独立元数据、依赖、启用名和测试；
数据、权重、服务器与 API key 需按各包说明准备，不因安装框架自动下载或公开。

| 接入 | 文档 |
| --- | --- |
| 中立时序领域与 LibraryTS | [timeseries](../adapters/timeseries/README.md)、[指定 LibraryTS 工具集](../adapters/libraryts/README.md) |
| ChatTS | [包文档](../adapters/chatts/README.md)、[完整接入说明](chatts-integration.md) |
| TimeSigma | [包文档](../adapters/timesigma/README.md)、[接入说明](timesigma-integration.md) |
| RL rollout 与训练 | [包文档](../adapters/rl/README.md)、[GSM8K / ChatTS / TRL 指南](rl-integration.md) |
| 问答 benchmark | [TSQA 包](../adapters/bench_tsqa/README.md)，五份附件保持 evaluation-only |
| HF 静态来源 | [HF Datasets 包](../adapters/hf_datasets/README.md) |
| 控制领域与仿真 | [interaction](../adapters/interaction/README.md)、[Gymnasium](../adapters/gymnasium/README.md) |
| 外部服务与 live testbed | [OpenEnv](../adapters/openenv/README.md)、[Prometheus](../adapters/prometheus/README.md) |

## 开发、协作与发布

- [适配开发教程](adapter-development.md)：一个可独立安装的最小 Candidate，以及 Source、Task、Scorer、资源和训练扩展入口。
- [贡献指南](../CONTRIBUTING.md)：开发环境、测试、Issue / PR、核心变更理由和冻结兼容验证。
- [维护者指南](maintainer-guide.md)：版本、发布准备、分发检查、数据/凭证与兼容性；不自动发布。
- [双语文档构建与发布](documentation.md)：源码为唯一文本来源，检查链接并构建可导航的文档站。
- [支持](../SUPPORT.md)、[安全](../SECURITY.md)、[行为准则](../CODE_OF_CONDUCT.md)。
- [变更记录](../CHANGELOG.md)、[路线图](roadmap.md)、[引用](citing.md)、[MIT 许可说明](licensing.md)、[许可原文](../LICENSE)、[第三方来源](../THIRD_PARTY.md)。

## 当前验收与工程证据

- [0.6.0 / 合同 1.4.0 实验组织验收](reports/experiment-organization-2026-10-21.json)：F2.1 冻结身份；196 项核心测试通过；十六包兼容为 356 项通过、61 项可选依赖跳过；独立 ETTh1 32 行视图完成运行、独立评价和适配包卸载后重评。
- [历史 0.5.1 核心四类数据层验收](reports/core-data-organization-2026-10-21.json)：固定 F1 的真实来源、目录/可移植附件、独立评价与零模型重评。

报告记录特定源码、运行依赖和数据的事实，不是实时 CI 状态、完整 benchmark 排名或
生产可用性证明。部分历史报告文件名使用较早环境的日期；按内部版本、提交、摘要和
验收范围判断适用性。

- [四类环境总验收](reports/environment-acceptance-2026-10-19.json)与[十一包独立发行检查](reports/environment-adapter-package-check-2026-10-19.json)。
- [HF 静态](reports/hf-environment-2026-10-19.json)、[Gymnasium](reports/gymnasium-environment-2026-10-19.md)、[OpenEnv](reports/openenv-environment-2026-10-19.md)、[Prometheus](reports/prometheus-environment-2026-10-19.json)。
- [0.5.0 阶段交付](framework-delivery-2026-10-20.md)、[核心冻结身份](reports/core-frozen-identity-2026-10-20.json)、[核心发行检查](reports/core-package-check-2026-10-20.json)。
- [数据/任务/模型替换](component-replacement-validation-2026-10-19.md)、[LibraryTS 原生验收](reports/libraryts-native-final-2026-10-20.json)、[TimeSigma 原生验收](reports/timesigma-frozen-core-final-2026-10-20.json)。
- [问答 746 行验收](reports/bench-tsqa-full746-final-2026-10-20.json)、[RL 检查点链](reports/rl-checkpoint-loop-2026-10-20.json)、[RL 验证说明](rl-validation-2026-10-19.md)。
- [较早版本发布准备](release-readiness-2026-10-18.md)与[TimeSigma 接入前核对](timesigma-repository-review.md)保留为历史参考。

完整 CAS / SQLite / 权重或数据归档可能位于被忽略的本地 `output/`，不会因为报告可见就
自动随 Git 或软件包公开。需要复现时，按报告中的来源、摘要、配置和授权单独准备。

## 原始设计与未来提案

- [总体设计](feishu/GymTS总体设计/GymTS总体设计.md)、[运行机制](feishu/GymTS%20运行机制/GymTS%20运行机制.md)、[场景接入](feishu/场景接入/场景接入.md)、[项目理解](项目理解.md)。
- [框架演进原则与可插拔设计](pluggability-design.md)：包含现行对齐原则及下一版建议，不能把建议当作已实现合同。
- [v2 消息与调用协议草案](pluggability-contract-v2.md)：字段与消息推演；不是现行 SDK。
- [企业多团队平台评审](enterprise-platform-roadmap.md)：远程执行、身份、隔离与协作的调研提案。
- [修改前历史快照](archive/2026-10-12-before-api-v1/)与 `archive/2026-10-20-before-api-v1.2/` 保留旧文本。
- [项目组网页](https://netman.aiops.org/contacts/projects/)作为外部项目分工来源；不将上位业务系统自动内化为 GymTS 核心。

原始 PDF、PPT 和图片可能采用旧命名；保留来源材料，不回写成新版规范。发生冲突时，
现行正式合同确定消息语义，项目状态与已登记组件确定当前真正可运行的支持范围。
