# Changelog

本文件记录代码与公共合同的变化。工作树版本、Git 标签和包索引发布分别表示；
下列条目不会证明已创建 GitHub Release 或上传 PyPI。日期仅用于已有明确记录的事件。

## 0.5.0 — Unreleased

当前源码版本，公共接口规范为 1.2.0；相对已登记的 0.3.1 初始提交有以下主要变化。

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
- 仿真保留原生终止标记、最后状态与奖励；实验范围结束单独表达。
- OpenEnv 使用官方有状态 WebSocket，未知 reward / 终止原因明确保留，不自动重发不确定操作。
- Prometheus 保留源样本时间与实际接收时间；历史只读已交付的固定区间。

### 文档与验证

- 补齐中英文项目入口、使用手册、接口参考、适配开发、贡献、安全、行为准则与维护流程。
- 增加问题/PR 模板、引用、MIT 许可说明、第三方来源和本地文档构建说明。
- 采用 MIT License，增加标准许可原文并同步核心、独立适配包、教学包和引用元数据；第三方项目、模型、数据及用户附件继续遵循其原有条款。
- 核心、独立发行及原生验证的范围见[项目状态](docs/project-status.md)；
  各次实际版本与制品摘要以对应验收报告为准。

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
