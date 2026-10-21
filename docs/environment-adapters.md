# EnvironmentTS 环境接入

当前核心为 **0.6.0**，接口规范为 **1.4.0**。GymTS 的主线是**存储数据、接入数据、组织实验、记录实验**。EnvironmentTS 管来源定义、dataset 快照、采集窗口、血缘、执行与证据；AutoBenchTS 管 benchmark、独立评价和重评。具体格式、生成器、原生 SDK 与领域评分继续放在适配器。

当前 F2.1 已通过技术验收。固定数据引用、阶段依赖、尝试记录、查询和显式回库见[实验组织指南](experiment-organization.md)，固定身份、范围与限制见[当前验收报告](reports/experiment-organization-2026-10-21.json)。`run_data` 仍组合来源绑定、原实验和采集，不替换真实 Task/Candidate。四类数据层的变更理由与可运行数据流程仍见 [ADR 0001](adr/0001-core-data-source-catalog.md)和[使用指南](user-guide.md#65-四类来源实际快照与回流)。

既有 Environment 接入验证日期为 2026-10-19（上海），覆盖合成、静态、可推进仿真和外部实时系统。HF 列解析、Gymnasium/OpenEnv 调用与 PromQL 均未进入核心。该次实际 Run、原生版本、发行检查及归档哈希保留在[历史验收索引](reports/environment-acceptance-2026-10-19.json)。下文 2026-10-19 与 F1 两组历史证据保持原身份，不改标为 F2.1 本轮新增原生运行。

## 历史 F1：0.5.1 四类核心数据层冻结验收

该轮先冻结核心 F1，再从源码目录外安装[独立四源示例包](../examples/data_organization/README.md)。来源定义、数据资产、快照、采集与血缘使用核心 API；独立包只组合既有 provider、领域投射与实验配置。它没有修改核心或另建目录、执行器、评价器。

| 类别 | 真实来源与固定视图 | 实际执行与证据 |
| --- | --- | --- |
| static | 固定 LibraryTS 原生加载的 AirPassengers，共 144 点；132 点公开历史、12 点独立未来；一个数值输入行 | 原生 NaiveForecaster drift 拟合，独立留出 MAE/RMSE |
| synthetic | ChatTS 原数值生成器，seed 27，共 40 点；32 点公开历史、8 点独立未来；一个数值输入行 | 复用独立 forecast Task/Candidate/Scorer，不重写生成器 |
| simulation | 真实 Gymnasium FrozenLake，reset seed 19 | 6 次真实动作、7 次观测、原生终态与 return=1 保留 |
| live_testbed | 真正 Prometheus 抓取本机 exporter | 137 批观测、11 份结果；保留实际时间与采集范围，服务停止后再评分 |

共 4 个真实 Run、4 份独立 AutoBenchTS 评价与 4 次轻量环境重评。技术 Gate 只检查执行和覆盖，不能据此推断预测质量、Agent 自主工具能力或因果在线预测。重评环境没有 NumPy/SciPy/pandas/sktime/Gymnasium/torch/Transformers，禁止执行 Run 和构造 Environment/Candidate；全部指标、覆盖与封存 Run 摘要保持不变。

另将 `data_home` 复制到独立目录，停止外部服务并移开原 Run store，再从新 Run root 重读四类数据、采集元数据与每个可移植附件。恢复原 Run store 后仍可独立评分。数据离线可读与旧 Run 可重评是两项分开的证据，不把 dataset 复制说成完整执行档案。

真实运行前后固定的 F1 wheel SHA-256 均为 `8944f39ffe516dbe22b7800f57fd18266cf6b3a4e84cf3a35b32cb6261ac2f1a`；核心代码树为 `dad5d6a1785c4fa440a51dd4c93307f47ca000aa0d955daa70e68e32dcfac319`。168 项核心回归及 wheel/sdist、源码外安装检查另行完成；发行重建 wheel 的字节摘要不必等于实际 F1 wheel，但核对同一代码树。完整身份、Run/评价/重评 ID 与范围见[机器可读报告](reports/core-data-organization-2026-10-21.json)。旧十六包在 F1 上的兼容检查共发现 407 项，346 项执行通过、61 项因可选依赖缺失跳过；包括该轮 AReaL V13 CPU 草案，不改写原生训练或留出评价状态。十六包共存及移除 AReaL 后十五包共存、核心运行与封存重评也通过。完整四类证据归档后已在新目录恢复，核对 567 个 CAS 引用和 60 个数据对象摘要，再次通过四类读取及轻量重评。没有发布 Git/PyPI，也未更改 F0 或 AReaL pending 状态。

## 四类来源与技术栈的位置

| 来源 | 接入方式与公开数据 | 本轮实际验证 | 范围 |
| --- | --- | --- | --- |
| 合成数据 | 既有 generator 或外部 ChatTS 生成器产生固定公开观测 | 冻结核心上重新运行确定性预测、counter、评价及后到参考重评 | 本轮未重新调用 ChatTS 生成；既有独立 ChatTS 集成与原合同保留 |
| 静态数据集 | 独立 `gymts-hf-datasets` 显式冻结 HF Hub、save_to_disk 或 local_files，成为长期资源 | 官方 Monash 数据固定提交、三种加载路径、离线执行与原 Run 重评 | 有限一维数值预测视图；非完整 HF Hub、任意模态或完整 Monash benchmark |
| 可推进仿真 | 独立 `gymts-gymnasium` 创建自有原生环境；act 推进一步，observe 消费缓存 | 真实 FrozenLake 与 CartPole、原生终止和 scope 边界、独立评价与重评 | 单 episode；不包含 vector、自动 reset 或现成 RL 训练后端 |
| 外部服务与 live testbed | `gymts-openenv` 连接外部有状态会话；`gymts-prometheus` 只读实时指标 | 官方 OpenEnv Echo/Connect4 服务与真实 Prometheus 抓取服务 | 验证本机真实服务；未验证用户生产 endpoint、认证和生产控制权限 |

HF Datasets 是静态资源加载技术；Gymnasium 是本地可推进仿真接口；OpenEnv 是外部环境
服务协议；Prometheus 是实时可观测数据源。它们不是新的 GymTS 主模块，也不强制未来
项目使用这些实现。其他文件格式、仿真器或 testbed 实现相同的公开合同即可注册。

`gymts-interaction` 是另行发行的中立领域包，供 Gymnasium 与 OpenEnv 复用 JSON
状态、控制 Task、示例 Candidate 和 episode Scorer。共享并不使它成为核心的一部分。
HF 自带预测领域合同；Prometheus 不拥有模型、Task 或 Scorer，示例通过配置复用既有
预测组件。工具集、数据源、Task、Candidate 和 Scorer 依然可以分别替换。

## 调用与存放

先安装需要的适配包；原生依赖和上游服务按各自 README 准备。以下命令在主仓库执行，
不涉及付费模型：

```bash
python -m pip install .
python -m pip install './adapters/hf_datasets[runtime]'
python -m pip install ./adapters/interaction './adapters/gymnasium[runtime]'
python -m pip install ./adapters/openenv ./adapters/prometheus
```

Gymnasium 1.2.1 与本轮官方 OpenEnv 原生运行时要求 Python 3.10+。安装 OpenEnv 适配包
不自动下载或启动服务器；其 SDK 与环境服务需按固定上游来源另行准备。

| 场景 | 可运行入口 |
| --- | --- |
| 确定性合成与后到评价 | `python examples/quickstart.py --root /tmp/gymts-synthetic-new` |
| HF 静态来源 | `python adapters/hf_datasets/examples/hf_static.py --work /tmp/gymts-hf-new --report /tmp/gymts-hf-new/report.json` |
| Gymnasium 仿真 | `python adapters/gymnasium/examples/native_cpu.py --output /tmp/gymts-gymnasium-new` |
| 官方 OpenEnv Echo 服务 | `python adapters/openenv/examples/echo_roundtrip.py --owned-local-echo --root /tmp/gymts-openenv-new` |
| 官方 OpenEnv Connect4 服务 | `python adapters/openenv/examples/echo_roundtrip.py --owned-local-server --environment connect4 --root /tmp/gymts-connect4-new` |
| Prometheus live 来源 | `python adapters/prometheus/examples/native_server_demo.py --output /tmp/gymts-prometheus-new --prometheus-binary /path/to/prometheus` |

示例的输出目录使用尚不存在的本机路径。HF 首次冻结可能需要网络；完成冻结后从资源
清单与内容制品执行，不依赖原 HF 目录或在线服务。OpenEnv 示例启动的是官方上游服务，
Prometheus 示例启动的是真实二进制和 exporter；服务停止由示例中拥有该进程的 harness
负责，Environment 本身不能停止别人的服务。

Python 调用仍使用原生服务，不增加另一套执行器或报告：

```python
from gymts import GymTS
from gymts_gymnasium import environment_spec
from gymts_interaction.experiments import evaluation_spec, rescore_spec

candidate = {
    "adapter": "interaction-sequence", "version": "1.0.0",
    "artifact": None, "inherited_state": [],
    "params": {"actions": [{"action": a} for a in (2, 2, 1, 1, 1, 2)],
               "repeat_last": False},
}
spec = evaluation_spec(
    environment_spec("FrozenLake-v1", kwargs={"is_slippery": False}),
    candidate, scope_end=6, seeds=(19, 29),
)
with GymTS("/tmp/gymts-python-new", integrations=("interaction", "gymnasium")) as gym:
    report = gym.autobench.evaluate(spec)
    rescored = gym.autobench.score(rescore_spec(gym, report, spec))
```

静态资源长期存放在 `data_home`，包含不可变原始字节、公开投射、私有参考、卡片和版本
清单；`cache_home` 可重建。运行中的 SQLite/CAS 放本机 POSIX 的 Run root，封存后才
归档至共享或对象存储。live 和仿真来源存下实际观测、来源、操作与响应，不能把一个
部署名称当作未来数据的不可变版本。需要重放相同输入时，应显式冻结已捕获观测。

## 可见边界、时钟与所有权

静态数据的公开上下文和留出参考分开存放。HF 本版导出的测评视图为 evaluation-only，
训练、prepare、dataset_build 均拒绝。通用 HF 可用于训练不等于这份测评视图获得了训练
授权；五份既有 benchmark 附件也继续只供评价。

仿真使用 step 时钟。start 只 reset 一次，act 执行一次原生 step，observe 只消费一个
缓存转移；重复请求、未消费前再次动作和终态后的动作均不能产生第二次执行。末状态与
奖励必须保留，包括恰好到达决策范围末端的动作结果。执行范围结束通过 read_scope_end
和领域指标 scope_limited 表达，不伪造原生 truncated。Gymnasium 核对原生 reset seed；
不能强制实现 seed 的 OpenEnv 接入明确拒绝非空 seed。

OpenEnv 通过官方 SDK 的持久 WebSocket 保留会话，不把无状态 HTTP reset/step 当作
同一 episode。Run 拥有新建的 WS session，host 由外部所有；结束只释放本次资源。
OpenEnv 原生只有 done，未知终止原因保留在外部领域状态中，EndInfo 使用已有
source_exhausted 与 detail.reason=native_done_unclassified，不添加核心枚举。
无法判断的 terminated/truncated 指标报告 missing；未知 reward 保留 null，只使回报
指标不足证据，不把未知值改为 0。

Prometheus 只支持 attach、seed=null 和只读数值指标，不能 reset 或控制真实系统。
wall clock 使用实际时间，样本时间、HTTP 接收可用时间和交付 coverage 分别记录。
Task 的历史查询只读取已交付的固定快照，不能越界提交任意 PromQL。当前示例使用的
参考预测 Task 把决策时间写为样本时间，早于 HTTP 接收时间，因此本轮不构成因果在线
预测验收。多个候选也不能依次重跑同一段现实时间，应安排各自窗口或使用共同冻结回放。

EnvironmentSummary 保持正式 §6.7 的字段与 closed/detached/not_started 取值。
未消费转移通过 artifact_refs 保存；未知操作列入 pending_operations，错误保留
operation_id 和可能副作用，不自动重发。记录失败仍尽力关闭自有资源，不能因发布证据
失败而泄漏环境。受限服务是可信插件的 API 边界，不能代替进程沙箱。

## 独立评价与冻结验证

AutoBenchTS 的 evaluate 先固定预期单元，再运行 Candidate；score 对固定旧 Run 重新
评分。静态预测 Scorer 使用私有留出参考；交互 Scorer 从封存状态、操作与回执独立计算
episode 指标；Prometheus 示例使用明确的外部 fixture 参考。重评不得重新创建模拟器、
调用模型或请求 live 服务。技术 Gate 检查执行和覆盖，不能变成模型质量结论。

本轮固定核心 **0.5.0**，代码树
`8990de5a08378498c47853f238f7ae27c6f0072c1ea61bd29328294c6b8b9e20`，
实际验收 wheel SHA-256 为
`cea1ab0bdccf479820d9e9cf20cfc4a82c733978e7c722151601067e8925d226`。
新来源分别在源码目录外安装，通过公开接口完成运行、封存、独立评价与原 Run 重评。
现存报告和归档索引：

- [合成来源](reports/synthetic-environment-2026-10-19.json)：既有生成器/counter、后到参考和原输出不变。
- [HF 静态来源](reports/hf-environment-2026-10-19.json)：固定官方数据、三种来源、公开/私有分离、离线执行和失败证据。
- [Gymnasium 仿真](reports/gymnasium-environment-2026-10-19.md)：真实 FrozenLake/CartPole、末奖励、合法结束语义、独立评价和重评。
- [OpenEnv 外部环境](reports/openenv-environment-2026-10-19.md)：官方 Echo/Connect4、WS 原始证据、未知原因和故障不重发。
- [Prometheus live 来源](reports/prometheus-environment-2026-10-19.json)：真实抓取服务、独立参考、零网络重评、非法查询失败证据与 host 保持运行。

[十一包独立发行验收](reports/environment-adapter-package-check-2026-10-19.json)已完成
wheel/sdist、源码重建、源码目录外安装、共同启用与移除检查。最小环境共执行 319 项，
265 项通过、54 项因未安装可选原生运行时而跳过；原生环境另有 interaction 14、
Gymnasium 16、HF 8、OpenEnv 8、Prometheus 12 项，全部通过且零跳过。
OpenEnv 另在未安装 SDK、原服务器已停止的环境中重评相同 Run，证明评分不依赖原生执行。

## 本轮零核心变更的判断

| 真实需求或差异 | 为什么适配器能表达 | 核心决策与兼容 |
| --- | --- | --- |
| HF 各种格式和固定来源 | reader、Source、资源清单、私有 Outcome 与 resolver 均已有扩展接口 | 无核心变更；原 benchmark 和读取 API 保持 |
| 仿真状态与真实动作 | Environment start/observe/act/finish、TaskRequest.command 已定义 | 无核心变更；新控制领域另成包，旧 Task 不受影响 |
| 空 reward、只有 done、远端 WS 生命周期 | native Payload 使用外部领域 schema，EndInfo.detail 已允许额外来源事实 | 无核心变更；外部领域增加可选信息，不把未知 cause 强转为核心 flags |
| 实时采样、接收时间与历史快照 | external 推进、wall clock、waiting、coverage、权限和 CAS 已定义 | 无核心变更；PromQL、缓存与来源时间语义在适配器 |
| 独立评价末奖励及重评 | ResultsView 的 event_snapshot_ref 已提供固定封存事件 | 无核心变更；原生 AutoBenchTS 执行与报告继续唯一负责评价 |

以后若真实需求无法由这些接口表达，先记录具体失败案例、适配器不能解决的原因、
拟改接口和旧项目回归，再决定核心变更。不要因为某个技术栈的原生字段不同就增加
项目名称分支。完整远程 worker、隔离、强制中断、恢复和任意控制 testbed 仍需独立验收。

本轮示例 Candidate 使用固定动作或简单数值基线，证明的是环境接口与证据闭环。
Agent 选择外部工具、消费结果并继续推理的通用循环尚未验收；环境原生调用也不等于
Agent 已自主选择了该工具。位置与职责见 [Agent 与外部工具集](agent-toolsets.md)。
