# 项目状态与支持范围

当前工作树：GymTS **0.5.0**，公共接口规范 **1.2.0**。这里描述实现与已有证据，
不宣称已发布 PyPI 包、Git 标签、托管平台或支持 SLA。发布变化见[CHANGELOG](../CHANGELOG.md)。

## 可用能力

| 范围 | 当前实现 | 证据或限制 |
| --- | --- | --- |
| 核心执行 | 同步本地 SDK / CLI，纯装配、校验、执行、范围检查、清理 | Python 3.9+；JSON 默认无第三方运行依赖 |
| 记录与存储 | SQLite、不可变内容制品、事件、结果、后到 Outcome、Snapshot | 活动 Run store 使用本机 POSIX；可信插件 API 边界不是进程沙箱 |
| 独立评价 | 固定预期单元、独立 Scorer、比较/Gate、旧 Run 重评 | 缺失、失败和不足证据显式保留；领域计数由 Scorer 定义 |
| 可替换交付 | 11 个独立适配包，entry point 发现和显式启用 | 同仓库不等于随核心打包；科学依赖另行安装 |
| 数据与 benchmark | 本地长期资源目录、公开读取、私有参考、不可变别名、benchmark resolver | 不是远程 HF Hub 服务或通用 streaming 平台 |
| 环境来源 | 合成、HF 静态、Gymnasium、OpenEnv、Prometheus | HF 为有限数值视图；外部服务验收使用真实 localhost 服务 |
| 训练扩展 | 公共 DatasetBuilder，外部 native rollout 导出、TRL GRPO、检查点新进程评价 | 已验收 profile 有明确边界；不是通用 RL trainer 或已完成 verl 适配 |
| 模型和工具轨迹 | 显式 ModelCall / ToolCall 采集、关联与失败政策 | 需 provider 配合；不自动拦截所有 SDK，不承诺自动脱敏 |

## 已有验证如何阅读

核心 0.5.0 冻结身份和已有 160 项核心回归记录见
[冻结身份](reports/core-frozen-identity-2026-10-20.json)与
[核心发行检查](reports/core-package-check-2026-10-20.json)。较早报告文件名保留生成时的
日期；以报告内的版本、SHA 与范围判断是否适用，不按文件名日期推断版本新旧。

[环境接入总验收](reports/environment-acceptance-2026-10-19.json)记录：

- 十一包独立构建、源包重建、安装、发现、共同启用、移除及核心旧 Run 重评。
- 最小依赖环境的 319 项测试中 265 通过、54 条按依赖条件跳过。
- 新增适配包在完整运行依赖环境下另行执行 58 项测试，零跳过。
- 固定官方 HF 来源、真实 Gymnasium、官方 OpenEnv 服务/SDK和真实 Prometheus 调用。
- 已封存失败、末状态/奖励、未知结果不重发，以及零模型/环境新调用的同 Run 重评。

这组数值是对应源码与依赖环境的已登记结果，不是未来每次 CI 的实时状态。
HF 的三行视图不是完整 Monash benchmark；固定动作、last-value 与微型 RL 训练的
技术验收也不能当作模型质量或 Agent 智能结论。

## 暂未交付的完整能力

多租户鉴权/配额、远程 worker、进程与网络隔离、强制中断/恢复、生产 testbed 身份与
写权限、通用自主 Agent 工具循环、任意 HF 模态/streaming、任意训练 profile 和 verl
后端均需各自接入与验收。代码中公开的扩展点不等于已有相应生产实现。

[下一版协议草案](pluggability-contract-v2.md)和[企业平台评审](enterprise-platform-roadmap.md)
是设计资料，不能替代本版本的运行合同。

## 平台与兼容

核心本地存储目前支持 Linux/macOS；Windows 尚未作为支持平台验收。CI 配置包含
Python 3.9、3.12、3.13，但配置存在不代表当前远程检查已绿。Gymnasium 1.2.1 与本轮
官方 OpenEnv 运行时需 Python 3.10+；GPU、模型权重和其他科学依赖以各包 README 为准。

适配包声明的核心版本范围与任务协议必须同时满足。安装成功只说明依赖解析完成；
`plan` / `validate` 不验证实际模型文件、凭证和远端可用性，这些在有 Run 后打开并记录。
