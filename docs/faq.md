# 常见问题

本文区分当前能力、使用约束和后续设计。完整入口见[文档导航](README.md)，具体报错的最小复现要求见
[支持说明](../SUPPORT.md)。

## 项目与边界

### GymTS、EnvironmentTS、AutoBenchTS 分别是什么？

GymTS 是统一 SDK 和项目入口。EnvironmentTS 管一次实验的执行、访问范围、生命周期与证据；
AutoBenchTS 管固定评价计划、独立评分、比较和原 Run 重评。数据、任务、模型、工具集和领域评分由
公共接口连接。它们不是每接入一个项目就复制一套执行器或评价系统。

### LibraryTS、TimeSigma、ChatTS、HF 等是不是核心内置模块？

不是。项目均作为独立适配包安装并显式启用，核心发行包不包含它们。共享领域包
`gymts-timeseries` 和 `gymts-interaction` 也独立发行。核心只带小型、确定性的参考插件，供自检和示例使用。
目录布局见[适配包指南](../adapters/README.md)。

### 工具集处于哪里？GymTS 会替 Agent 决定调用工具吗？

工具集是外部提供方。Agent 决定工具选择和参数，Agent SDK/工具适配器或外部后端执行，GymTS 保存相关权限和证据。
当前环境示例的原生调用及固定动作 Candidate，不等于通用自主 Agent 已完成工具选择循环验收。
详见[Agent 与工具集](agent-toolsets.md)。

### 这已经是多用户云平台或不可信代码沙箱吗？

当前是同步、本地 Python 框架。尚无已验收的通用远程 worker、强制进程中断、恢复、租户权限服务或云端资源调度。
插件必须可信；需要隔离时由外部运行环境提供。平台扩展见[路线图](enterprise-platform-roadmap.md)，安全边界见
[安全策略](../SECURITY.md)。

## 安装与首次使用

### 需要 GPU、大模型、数据库服务或密钥才能开始吗？

基础 quickstart 不需要。源码根目录运行：

```bash
python3 -B examples/quickstart.py --root /tmp/gymts-first-run
```

它使用本地合成序列和参考组件验证运行、评价、后到标签与重评。核心 Python 要求是 3.9+；
Gymnasium 1.2.1、本轮官方 OpenEnv SDK 等可选原生运行时有自己的更高版本要求。

### 为什么 Windows 或挂载盘上创建存储失败？

当前本地制品后端依赖 POSIX 目录相对访问、no-follow 和持久化操作，面向 Linux/macOS。
网络/对象存储挂载也不应假定支持活动 SQLite 和所需的文件系统语义。把 Run root、cache 和临时构建目录放本机磁盘，
关闭写入者后再归档到共享存储；Windows 可使用具备这些语义的 Linux 环境，不能假定原生 Windows 已验证。

### 安装了适配包，为什么 `plugins` 没有出现对应组件？

安装用于发现，启用才注册。用 `GymTS.available_integrations()` 查看集成元数据，在 Python 传入
`integrations=("集成名",)`，或在通用 CLI 子命令前写 `--integration 集成名`。
例如 `gymts --integration chatts plugins`。集成名与 pip 分发名可能不同，以各适配包 README 为准。
发现不应导入模型运行时，启用后也不应在规划阶段加载模型。

### YAML 配置为什么不能读取？

JSON 无额外运行依赖。YAML 需要 `gymts[yaml]` 可选依赖，在源码目录可用
`python -m pip install -e '.[yaml]'`。这与模型、HF 或仿真后端依赖分别安装。

### CLI 的 `--store` 为什么被拒绝？

全局参数应在子命令之前，例如：

```bash
gymts --store /tmp/gymts-first-run inspect RUN_ID --events
```

`RUN_ID` 替换为你自己的实际标识；存储目录也必须是生成该 Run 的目录。完整命令用 `gymts --help` 和子命令 `--help` 查看。

## 数据、benchmark 与模型

### 能像 HF Datasets 一样保存和读取数据吗？

有本地不可变 SourceDatasetRevision、DatasetHandle 和 BenchmarkDefinition，可按 ID/revision/config/split
读取、选择、分批浏览、转换为可选 HF 视图，并解析为原生 EvaluationSpec。它不是完整 HF Hub，当前没有通用的
远程仓库同步、任意模态、流式服务或分布式查询。[资源设计](dataset-benchmark-catalog-design.md)说明存放和接口；
[HF 适配包](../adapters/hf_datasets/README.md)支持固定 Hub 提交、save_to_disk 和明确本地文件的有限数值时序视图。

### 数据集和 benchmark 为什么是两个东西？

数据集保存源字节、公开输入、私有参考、特征和用途政策。benchmark 固定题目/切分、任务、评分和比较规则，
经 resolver 生成 EvaluationSpec；它不再实现另一套执行和报告。改变评分规则通常产生新 benchmark/评价修订，
而不是篡改已封存 Run。

### 能把已经登记的 benchmark 直接用于 RL 训练吗？

不能默认这样做。五份用户上传的 JSONL 已明确为测评用途，当前登记为 `evaluation-only`，训练、prepare 和 dataset_build
会拒绝。HF 测评投射也不自动具有训练权限。要训练须另备具有适当来源和用途许可的数据，不能通过换 exporter、
改文件名或移除标签绕过来源政策。[RL 指南](rl-integration.md)描述单独的训练数据与 TRL 复用路径。

### 怎样换数据、任务、模型或评分器？

通过注册的 Environment/Task/Candidate/Scorer 和固定 schema/组件修订进行组合，能力不兼容时应在计划或校验阶段拒绝。
格式转换、原生模型调用和领域解释放适配包；不要向核心添加项目名条件分支。
参见[组件替换验证](component-replacement-validation-2026-10-19.md)和[框架指南](framework.md)。

### 数据和轨迹到底存在什么位置？

`GymTS(root=...)` 或 CLI `--store` 是活动 Run/CAS/记录根目录，默认 `.gymts`。
长期数据与 benchmark 资源在 `data_home`（或 `GYMTS_DATA_HOME`，默认 XDG data 目录下 `gymts`）；
可重建资源缓存在 `cache_home`（或 `GYMTS_CACHE_HOME`，默认 XDG cache 目录下 `gymts`）。
命令行可用 `--data-home` 和 `--cache-home` 覆盖。长期 AssetRef 与实验 ArtifactRef 不同；必要内容进入本次 CAS 后才成为运行证据。
不要只复制 SQLite 文件或单个最终报告就假定搬走了完整实验，关闭存储并保留全部关联制品。

## 运行、评价与失败

### `run` 成功为什么不等于 benchmark 通过？

Run 状态表示执行结果；AutoBenchTS 的 verdict 表示按既定依据与规则评价的结果。
流程可以完成但缺少标签或不满足质量条件。CLI 配置/校验错误退出 2，Run 失败或取消退出 1；
评价依据不足但流程完成可退出 0，自动化应同时读取 `status`、`verdict` 和覆盖信息。

### `insufficient_evidence` 是运行失败吗？

通常表示当前参考、输出、可用指标或覆盖不足以给出结论，不应自动补零或删掉难例。
查看报告中的 missing/invalid、配对、失败单元和 Gate 原因。缺少标签时可在之后追加 outcome，再针对原 Run 重评。

### 重评分会再次调用模型或重启环境吗？

`AutoBenchTS.score`/`gymts score` 对固定旧 Run 和参考快照生成新评价，不应重新调用 Candidate 或 live 服务。
保留相同 Run ID、原始 RunResult 和事件证据；新评价链接旧评价。还需要安装并启用解释旧任务/结果的评分合同，
因此卸载模型 SDK 不等于可以卸载所有领域评分包。

### 能保证 live 或仿真重新跑出同样世界状态吗？

不能从部署名称或 seed 字段推导这种保证。静态来源可明确冻结字节；Gymnasium 的可复现性取决于原生环境、版本和 seed 实现；
OpenEnv 当前拒绝无法证实支持的 seed。Prometheus 是 attach-only 只读 live 来源，现实时间不会倒退。
比较多个 Candidate 时可使用共同冻结回放或明确分配不同窗口；原 Run 重评读取已经捕获的证据。

### 为什么未知 reward 没有变成 0，OpenEnv done 没有变成 terminated？

缺失值与真实数值 0 不同；原生 done 也未必区分自然终止和外部截断。适配器保留 null 和未知原因，
只有受影响的指标不足证据，其他有依据的指标仍可评价。Gymnasium 自有 terminated/truncated 则保留原生含义；
GymTS 范围结束独立表达，不伪造上游结束标志。详见[环境接入指南](environment-adapters.md)。

### 服务请求超时后为什么不自动重试？

服务端可能已经执行了动作。重试可能重复副作用或把会话推进两步；应记录 unknown/possible 状态、请求/响应和待定操作，
由明确的后端恢复规则决定后续处理。当前实现不能把所有超时都当成“什么也没发生”。

### 只有 Run ID，维护者能查看我的轨迹吗？

不能。ID 是本地记录标识，不是上传或分享链接。用同一个 `--store` 执行 `inspect RUN_ID --events`，
分享最小脱敏片段；私有参考、prompt、服务响应和原始附件可能在关联 CAS 中，分享完整目录前需要单独审核。
当前没有通用自动脱敏后端，见[安全策略](../SECURITY.md)。

## 贡献、验证与发布

### 最小安装中的 skipped 测试能说明后端可用吗？

不能。独立包检查故意在最小环境运行，可选原生依赖未安装时会条件跳过。完整后端需要另按固定依赖运行原生测试和真实调用。
[验收报告](reports/environment-acceptance-2026-10-19.json)明确区分了 319 项最小环境测试（54 跳过）与新增适配器 58 项原生测试。
报告证明特定快照和范围，不证明所有未来版本、生产服务或模型质量。

### 我应该怎样贡献，项目采用什么许可证？

先阅读[贡献指南](../CONTRIBUTING.md)，按现有接口优先新增独立适配包。GymTS 代码与文档采用
[MIT License](../LICENSE)，完整条款见许可原文。第三方数据、模型、代码和用户附件保留各自的来源、
许可与用途限制，不会因 GymTS 采用 MIT 而重新授权。发行验证流程见[维护指南](maintainer-guide.md)。
