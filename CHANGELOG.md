# Changelog

本文件记录代码与公共合同的变化。工作树版本、Git 标签和包索引发布分别表示；
下列条目不会证明已创建 GitHub Release 或上传 PyPI。日期仅用于已有明确记录的事件。

## 0.6.0 — Unreleased

当前源码版本，公共接口规范 1.4.0。按存储数据、接入数据、组织实验、记录实验四项主线补齐组织合同；核心变更理由、适配器边界和兼容方式见 [ADR 0002](docs/adr/0002-experiment-organization.md)。

- 新增不可变实验集合、封存阶段输入、执行尝试与追加组织事件四个协议；阶段复用既有 Run、AutoBench、采集与发布服务，领域 executor 保持外置。
- 固定数据引用与产物依赖，明确失败重试、上游重跑后的依赖更新，以及中断后采纳已封存 Run 或显式重跑的语义。
- Run 建立时在同一 SQLite 事务关联阶段身份；新增实验、数据与 Run 查询，独立评分可以关联已有 Run 而不改写其归属。
- 新增 `publish_build`，把既有构建数据和可移植来源证据持久化到数据目录，保留外部 reader、原始 shard 和用途限制。
- 增加 `experiments`、`runs`、`datasets publish-build` CLI，双语指南与完整数据→运行→采集→评分→重评示例。旧 F1 的 23 个 schema 不变，历史冻结与报告保留原身份。

## 0.5.1 — F1 源码基线

历史 F1 源码版本，公共接口规范 1.3.0；四类数据的通用组织与存储明确纳入 EnvironmentTS 核心，项目实现继续外置。决策与兼容理由见 [ADR 0001](docs/adr/0001-core-data-source-catalog.md)。

- 新增 DataSourceDefinition `gymts.data-source/1` 与 `gymts.source-dataset/2`，统一静态、合成、仿真、live 来源定义、实际数据快照和父资源血缘。
- 增加来源 register/load/list、快照登记、来源绑定和 sealed Run 采集；公开 dataset 可读取可移植附件与 capture 元数据。
- 增加 `run_data` / `run-data`、`sources` 与 `datasets capture`；复用真实 ExperimentSpec、原运行与 AutoBenchTS，不增加另一套执行/评分引擎。
- 旧 19 个核心 schema 与 F0 规范化摘要相同；新增四个数据协议，旧 v1 数据、benchmark、Run 与报告不回写。168 项核心回归、源码外发行检查已通过；固定 F1 的真实四类来源、可移植读取和独立重评已通过技术验收；旧十六包在 F1 上的兼容检查共 407 项发现、346 项执行通过、61 项可选依赖跳过，含当前 AReaL V13 CPU 草案；共存、移除与核心运行检查通过，不改变原生留出评价状态。
- F0 五项目与 AReaL pending 证据保留原版本，不因本次数据层修改改写。当前尚无本版本发布声明。

## 0.5.0 — F0 源码基线

已登记基线，公共接口规范为 1.2.0；不据此补造 Git 标签或 PyPI 发行。相对已登记的 0.3.1 初始提交有以下主要变化。

### 框架与交付

- 保持 EnvironmentTS 执行/证据与 AutoBenchTS 评价两个主职责。
- 项目实现拆成独立发行包，通过 entry point 发现、显式启用；核心不维护项目名称分支。
- 增加纯 `plan` / `validate`、声明式组件描述与兼容检查；资源核验延迟到有 Run 后执行。
- 增加执行 seed / RNG 上下文、固定模型与检查点身份、受限制品访问和采集关联。
- 增加 DatasetCatalog、公开 DatasetHandle、私有评价参考、不可变资源别名和 BenchmarkDefinition resolver。
- 提供公共 DatasetBuilder provider 接口，领域导出与外部训练后端继续位于独立包。

### 独立适配与环境

- ChatTS、TimeSigma、RL、LibraryTS、中立 timeseries 与 benchmark TSQA 分别独立安装。
- 新增 HF 静态快照、外置 interaction 领域、Gymnasium、OpenEnv 与 Prometheus 五个包。
- 再增加 TimeCopilot、ITFormer、Chronos-2、Data-Juicer 与 AReaL 五个独立包；真实 Agent、严格原生问答推理、分位数预测/fit、数据加工和多轮 RL 后端分别由适配器接入，未内化到核心。
- 仿真保留原生终止标记、最后状态与奖励；实验范围结束单独表达。
- OpenEnv 使用官方有状态 WebSocket，未知 reward / 终止原因明确保留，不自动重发不确定操作。
- Prometheus 保留源样本时间与实际接收时间；历史只读已交付的固定区间。

### 文档与验证

- 补齐中英文项目入口、使用手册、接口参考、适配开发、贡献、安全、行为准则与维护流程。
- 增加问题/PR 模板、引用、MIT 许可说明、第三方来源和本地文档构建说明。
- 采用 MIT License，增加标准许可原文并同步核心、独立适配包、教学包和引用元数据；第三方项目、模型、数据及用户附件继续遵循其原有条款。
- 核心、独立发行及原生验证的范围见[项目状态](docs/project-status.md)；
  各次实际版本与制品摘要以对应验收报告为准。
- [五项目接入与验收](docs/five-project-integration-acceptance-2026-10-21.md)固定 F0 的 39 个核心文件，新增接入的核心改动为 0。TimeCopilot、ITFormer、Chronos-2、Data-Juicer 完成所列真实工程闭环和独立重评；AReaL 已验证真实参数更新与检查点发布，留出评价/重评 pending，不宣称完整论文复现或未设置的质量 Gate 通过。
- V2 十五包与 V11 AReaL 补检组合的十六包离线发行口径为 404 项发现、343 项执行通过、61 项条件跳过（不是对全部最终源码运行单份全量报告）；另完成六个跨项目 CPU Run、三次新进程重评和两类非法组合拒绝。发行检查与真实模型验收分别报告，具体 scope、失败历史和资源边界见同一验收文档。
- 保留 AReaL HF5 留出评价的四个真实失败与底层 generation 参数不兼容；V12 只修正无 Gate 报告的 CLI 完成性判断。HF4/tokenizer 兼容路线仍待用户选择；V13 optional publisher 只有 CPU 草案证据，未发布、未运行 GPU，不计为成功留出评价。

### 迁移提示

- 旧 `gymts.integrations.chatts/timesigma/rl` Python 路径不再由核心转发；安装对应独立包，
  使用 `gymts_chatts` / `gymts_timesigma` / `gymts_rl`。
- 缺少纯描述 provider 的旧插件须显式迁移，计划阶段不再构造运行实例作回退。
- 核心 CLI 用 `--integration NAME` 显式启用项目；项目专用命令由对应发行包提供。
- 已封存的组件、Schema 与 builder 身份不因新源码自动改写；重评仍需原任务/评分合同实现。
- 新资源视图、任务语义或评分规则需要新身份与独立参考，不能冒充原 benchmark 定义。

详见[框架指南](docs/framework.md)、[适配包指南](adapters/README.md)与
[正式接口规范](docs/feishu/GymTS接口规范/GymTS接口规范.md)。

## 0.3.1 — 已有初始提交

仓库历史记录包含提交 `cffa38f`，提交说明为 `Initial release of GymTS 0.3.1`。
该说明是代码历史，不代表已验证存在同名 Git 标签、包索引发行或长期支持分支。
保留原始 Git 历史，不为未核实的中间工作树版本补造发布时间与发布记录。
