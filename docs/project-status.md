# 项目状态与支持范围

当前工作树：GymTS **0.6.0**，公共接口规范 **1.4.0**；F2.1 组织技术验收通过，尚未发行。这里描述实现与已有证据，
不宣称已发布 PyPI 包、Git 标签、托管平台或支持 SLA。发布变化见[CHANGELOG](../CHANGELOG.md)。

本轮新增 `gymts.experiment-group/1`、`gymts.stage-request/1`、`gymts.stage-attempt/1`、`gymts.experiment-event/1`，提供固定实验定义、阶段输入/输出绑定、独立尝试、显式重试/恢复、Run 关联查询和 `publish_build` 长期数据回库。阶段声明输入的用途与 provenance 继承到嵌套 Run 和评价计划；重评历史 Run 只增加关联。已运行本地五阶段示例：12 条公开观测入库、一次真实 Run、两次独立评分与相同输出重评，第二次执行不新增 attempt，原 RunResult 不变。F2.1 已通过源码外 196 项核心回归、16 包兼容检查（417 项发现、356 项通过、61 项可选依赖跳过），以及独立 ETTh1 适配包的真实运行、卸载后读取与重评。证据见[本轮报告](reports/experiment-organization-2026-10-21.json)；历史 F1 保留原身份。见[实验组织指南](experiment-organization.md)与 [ADR 0002](adr/0002-experiment-organization.md)。

历史 F1（0.5.1 / 1.3.0）新增四类来源定义、dataset `/2`、快照登记、来源绑定、sealed Run 采集与 `run_data`。168 项核心回归和源码外发行检查已通过，F1 已冻结；独立四类真实来源、可移植读取与零模型重评已通过技术验收，旧十六包在 F1 上共 407 项发现、346 项执行通过、61 项可选依赖跳过，共存、移除与核心运行检查通过。该轮含当前 AReaL V13 CPU 草案，不能替代其原生训练或留出评价证据。旧 19 个核心 schema 摘要与 F0 相同，新增仅四个数据协议。原 0.5.0 与五项目报告保留原基线，AReaL 用户选择和成功留出评价仍 pending。见 [ADR 0001](adr/0001-core-data-source-catalog.md)。

## 可用能力

| 范围 | 当前实现 | 证据或限制 |
| --- | --- | --- |
| 实验组织 | 固定 group 修订、stage request/attempt/event、依赖与具名产物、显式 retry/rerun/recover、数据与 Run 查询 | 本地五阶段示例已运行；阶段边界恢复，不接管原生进程状态；F2.1 独立外包验证通过 |
| 核心执行 | 同步本地 SDK / CLI，纯装配、校验、执行、范围检查、清理 | Python 3.9+；JSON 默认无第三方运行依赖 |
| 记录与存储 | SQLite、不可变内容制品、事件、结果、后到 Outcome、Snapshot | 活动 Run store 使用本机 POSIX；可信插件 API 边界不是进程沙箱 |
| 独立评价 | 固定预期单元、独立 Scorer、比较/Gate、旧 Run 重评 | 缺失、失败和不足证据显式保留；领域计数由 Scorer 定义 |
| 可替换交付 | 16 个独立适配包，entry point 发现和显式启用 | 同仓库不等于随核心打包；科学依赖另行安装 |
| 数据与 benchmark | 本地长期资源目录、公开读取、私有参考、不可变别名、benchmark resolver | 不是远程 HF Hub 服务或通用 streaming 平台 |
| 环境来源 | 合成、HF 静态、Gymnasium、OpenEnv、Prometheus | HF 为有限数值视图；外部服务验收使用真实 localhost 服务 |
| 训练扩展 | 公共 DatasetBuilder，外部 native rollout 导出、TRL GRPO；Chronos-2 原生 fit 与检查点重载评价；AReaL TIR / PPOTrainer 接口 | Chronos-2 已完成 60 次更新和 16 个留出窗口；AReaL 已验证一次真实参数更新和检查点发布，留出评价/重评 pending；不是通用 RL trainer 或已完成 verl 适配 |
| 模型和工具轨迹 | 显式 ModelCall / ToolCall 采集、关联与失败政策 | 需 provider 配合；不自动拦截所有 SDK，不承诺自动脱敏 |
| 原生 Agent 闭环 | TimeCopilot 原生工具选择、工具返回续推及独立评价/重评 | 实际 6 次 HTTP 模型请求、四类原生工具；不是跨项目通用 Agent Runtime 或模型质量通过 |
| 原生模型与数据加工 | ITFormer 严格模型推理；Data-Juicer 原生过滤/去重/QA、血缘评价和派生数据登记 | 8 QA 小视图和固定合成 train-only 视图；生成标签未验证，不等于完整 benchmark 或论文复现 |

## 已有验证如何阅读

核心 0.5.0 冻结身份和已有 160 项核心回归记录见
[冻结身份](reports/core-frozen-identity-2026-10-20.json)与
[核心发行检查](reports/core-package-check-2026-10-20.json)。较早报告文件名保留生成时的
日期；以报告内的版本、SHA 与范围判断是否适用，不按文件名日期推断版本新旧。

较早的[环境接入总验收](reports/environment-acceptance-2026-10-19.json)记录：

- 十一包独立构建、源包重建、安装、发现、共同启用、移除及核心旧 Run 重评。
- 最小依赖环境的 319 项测试中 265 通过、54 条按依赖条件跳过。
- 新增适配包在完整运行依赖环境下另行执行 58 项测试，零跳过。
- 固定官方 HF 来源、真实 Gymnasium、官方 OpenEnv 服务/SDK和真实 Prometheus 调用。
- 已封存失败、末状态/奖励、未知结果不重发，以及零模型/环境新调用的同 Run 重评。

这组数值是对应源码与依赖环境的已登记结果，不是未来每次 CI 的实时状态。
HF 的三行视图不是完整 Monash benchmark；固定动作、last-value 与微型 RL 训练的
技术验收也不能当作模型质量或 Agent 智能结论。

本轮[五项目接入与验收](five-project-integration-acceptance-2026-10-21.md)固定 F0 的
39 个核心文件，新增接入没有修改核心。TimeCopilot、ITFormer、Chronos-2 与 Data-Juicer
完成各自列出的原生执行、独立评价和零推理重评；AReaL 已验证 32 个真实 Run、
非零优势、一次 Adam 更新和检查点发布，新进程留出评价与重评 pending；前四 attempt 保留。没有质量 Gate 的评价保留 `insufficient_evidence`，工程通过与
模型正确率、泛化或完整论文复现分别判断。

AReaL 首次 HF5 留出评价记录 4 个预期、0 个成功、4 个失败 Run（共享 HF4 generation
参数在 HF5 移除），原报告和预算保留。HF4 tiny CPU 与生产 tokenizer 无损 metadata
投影的 151,665 项 vocab/ID/template 等价检查通过；兼容路线仍待用户选择，V13 optional
publisher 仅为未发布、未运行 GPU 的草案。训练、CPU 兼容证明和成功留出评价分别判断。

十六包 V2 冻结发行快照原为 398 项发现、339 项通过、59 项跳过。以 V11 AReaL
19/17/2 替换旧 AReaL 13/13/0 后，合计 404 项发现、343 项执行通过、61 项条件跳过；
这是 V2 + V11 两份冻结报告的组合，不是全体最终源码的一份全量报告。V11 科学 CPU
19/19 零跳过另列，不双计；V2 安装、共同启用、移除及核心兼容证据保留。另有六个跨项目 CPU Run 验证同一公开
snapshot 更换 LibraryTS Candidate、等值 CSV Source 和独立 trend Task；三份评价在新
进程禁止模型/来源调用后重评，两个非法组合在原生调用前拒绝。具体身份与范围见
同一验收文档，不能将条件跳过、固定 Candidate 或单任务数值当成新 Agent 实验。

## 暂未交付的完整能力

多租户鉴权/配额、通用远程 worker、操作系统级进程与网络隔离、任意后端内部执行状态的自动恢复、
生产 testbed 身份与写权限、通用 Agent Runtime、任意 HF 模态/streaming、任意训练
profile 和 verl 后端均需各自接入与验收。已验收的原生 TimeCopilot 循环及适配器自有
Linux 进程组清理不等于上述通用能力；公开扩展点也不等于已有生产实现。

[下一版协议草案](pluggability-contract-v2.md)和[企业平台评审](enterprise-platform-roadmap.md)
是设计资料，不能替代本版本的运行合同。

## 平台与兼容

核心本地存储目前支持 Linux/macOS；Windows 尚未作为支持平台验收。CI 配置包含
Python 3.9、3.12、3.13，但配置存在不代表当前远程检查已绿。Gymnasium 1.2.1 与本轮
官方 OpenEnv 运行时需 Python 3.10+；GPU、模型权重和其他科学依赖以各包 README 为准。

适配包声明的核心版本范围与任务协议必须同时满足。安装成功只说明依赖解析完成；
`plan` / `validate` 不验证实际模型文件、凭证和远端可用性，这些在有 Run 后打开并记录。
