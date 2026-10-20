# GymTS 项目适配包

最终交付的是 GymTS 框架。接入真实项目用于检验公共合同、发现缺口和修正框架；项目适配器与资源独立交付。当前核心 `gymts==0.5.0`，正式接口规范为 1.2.0。五个原适配包为 0.2.0，TSQA 及本轮五个来源/领域包为 0.1.0，均依赖 `gymts>=0.5,<0.6`。当前共十一份独立适配包。公共 SDK 随核心发布，共享领域合同另行成包；纯装配、最小资源目录和 RL checkpoint 新评价已实现，完整 v2 Runtime 仍是提案。

## 角色与依赖

```text
实验配置 ──选择──> Source / Task / Candidate / Scorer / DatasetBuilder
                       │             │
                       ├──单向依赖──> GymTS 公开 SDK
                       └──按需依赖──> 独立领域合同

GymTS
  EnvironmentTS：源数据目录、执行、访问边界、Run、轨迹、制品与快照
  AutoBenchTS：benchmark 登记/解析、评价计划、独立评分、比较、Gate 与报告
  公共注册、版本、错误、训练构建与资源存储服务
```

| 交付物 | 目录与模块 | 内容 |
| --- | --- | --- |
| `gymts` | 仓库根 / `gymts` | 两个主模块、公共 SDK、轨迹、存储、训练构建与资源目录服务 |
| `gymts-timeseries` | [timeseries](timeseries/README.md) / `gymts_timeseries` | 中立数值 JSON/CSV Source、七类 Task、解析、独立 Scorer；不依赖具体模型 |
| `gymts-libraryts` | [libraryts](libraryts/README.md) / `gymts_libraryts` | 指定 NetmanAIOps/sktime 的十个真实工具、原生数据加载、Naive/Polynomial Candidate、预测 Scorer |
| `gymts-chatts` | [chatts](chatts/README.md) / `gymts_chatts` | ChatTS 数据读取与生成、模型内部 codec、时序/文本 HTTP、旧 QA 合同兼容 |
| `gymts-timesigma` | [timesigma](timesigma/README.md) / `gymts_timesigma` | 原生数据/Schema、检测器、预处理、评分、工具和 Research 父轨迹 |
| `gymts-rl` | [rl](rl/README.md) / `gymts_rl` | GSM8K/ChatTS 数据、HF policy、奖励、native exporter、TRL、不可变 checkpoint 与独立 Scorer |
| `gymts-bench-tsqa` | [bench_tsqa](bench_tsqa/README.md) / `gymts_bench_tsqa` | 五份 evaluation-only QA 资源导入、Parquet、原题保留 Task/codec/Scorer、BenchmarkDefinition resolver |
| `gymts-hf-datasets` | [hf_datasets](hf_datasets/README.md) / `gymts_hf_datasets` | 固定 HF Hub、save_to_disk、本地文件冻结；公开数值预测视图、私有参考与 benchmark resolver |
| `gymts-interaction` | [interaction](interaction/README.md) / `gymts_interaction` | 独立中立 JSON 控制合同、Task、示例策略与 sealed 事件 Scorer；无原生项目依赖 |
| `gymts-gymnasium` | [gymnasium](gymnasium/README.md) / `gymts_gymnasium` | 自有 Gymnasium 实例 reset/step/close，复用外部 interaction 合同 |
| `gymts-openenv` | [openenv](openenv/README.md) / `gymts_openenv` | 官方 SDK 持久 WS 会话、原始请求响应证据，复用 interaction 合同 |
| `gymts-prometheus` | [prometheus](prometheus/README.md) / `gymts_prometheus` | 只读附着实时指标，PromQL、接收时间和历史缓存；不拥有 Task、模型或 Scorer |
| 资源与实验配置 | 外部资源包或部署目录 | 版本化卡片/基准定义、数据和权重引用、预算、配方 |

核心不导入项目包，不保存项目名称分支；适配器不依赖核心私有实现。领域包可被多个项目共享，但不能因共享就搬进核心。RL 调用上游 ChatTS 数值生成函数，不依赖 `gymts-chatts` 包。

数据 Source 只交付数值和明确公开的来源事实；Task 决定问题、输出含义、解析与可见边界；模型 codec 在 Candidate 内构造原生请求。ChatTS 默认走这个中立路径，旧 `/1` ID、schema 和行为通过 `--legacy` 保留。默认规范化题目是另一个派生提示实验，manifest/report 明确不等价原 benchmark prompt；原始材料仍保留为来源证据。已有 benchmark 的任务约束不随意改变，换任务需要新视图及独立参考。

LibraryTS 使用用户指定 [NetmanAIOps/sktime](https://github.com/NetmanAIOps/sktime)，固定提交 `080f4c3c3695f239e328548bac7d7a3ef7aa9127`，没有替换成另一个 PyPI sktime。方法、生成器、数据算子和评分实现分别接入对应角色；LibraryTS 实现与某一次 Run 中的 Candidate 实例分别记录版本。真实原生 API 已接通；该工具集自身的统一资产登记/发布属于外部项目，GymTS 只提供通用引用和接入接口。当前两个数值方法每次仅对获准输入窗口真实拟合后预测，不复用跨调用状态，不接触未来标签；没有宣称是已训练持久权重。

数据、权重、上游 checkout 和科学解释器路径由部署配置指定。`/zzr/models` 是本机资源，不是全局默认协议。活动 SQLite/CAS/训练输出使用本地 POSIX 存储；封存归档可放共享或对象存储。数据和权重不打进核心 wheel。

## 安装与启用

按需安装，安装共享合同不安装项目模型：

```bash
python -m pip install .
python -m pip install ./adapters/timeseries
python -m pip install ./adapters/libraryts ./adapters/chatts
python -m pip install './adapters/timesigma[runtime]'
python -m pip install './adapters/rl[runtime]'
python -m pip install './adapters/bench_tsqa[runtime]'
python -m pip install './adapters/hf_datasets[runtime]'
python -m pip install ./adapters/interaction './adapters/gymnasium[runtime]'
python -m pip install ./adapters/openenv ./adapters/prometheus
```

各包通过 `gymts.integrations` 发布入口。发现只读取元数据，显式启用才注册；不会自动加载模型、执行训练或下载数据。

```python
from gymts import GymTS

print(GymTS.available_integrations())
with GymTS('/tmp/gymts-records', integrations=('timeseries', 'libraryts')) as gym:
    pass
```

项目入口可以注册它声明依赖的领域组件，无需在核心登记项目表。同名插件冲突报错，注册失败回滚。移除适配包不会删除旧轨迹；该项目执行或旧 Run 重评分需要其原合同实现，核心和其他独立包仍可运行。`[runtime]` 仅属于对应适配包；原生源码与科学解释器按各包 README 准备。

Gymnasium/OpenEnv 调用显式启用 `('interaction','gymnasium')` 或 `('interaction','openenv')`；HF 和 Prometheus 分别使用 `hf-datasets`、`prometheus`。Gymnasium 1.2.1 与本轮官方 OpenEnv 原生环境要求 Python 3.10+；安装适配包不自动启动服务器。四类来源的调用、存放、权限和事实边界见[环境接入指南](../docs/environment-adapters.md)。

0.3.x 的 `gymts.integrations.chatts/timesigma/rl` 改为独立模块 `gymts_chatts/gymts_timesigma/gymts_rl`。核心不反向转发；旧组件/Schema/builder/mask 和已提交证据 ID 保留。新中立协议采用新身份，不把新源码冒充旧实现。

## 声明式装配与资源边界

Environment/Task 提供纯 `factory.describe_spec(spec)` 或注册 `describe=`；额外限制用 `compatibility=` 或 `factory.check_compatibility_spec(context)`。`gym.plan/validate` 不创建组件、不读取数据/模型/凭证、不连接服务、不提交 CAS。缺少纯描述的旧插件不能依赖实例构造作为回退。`run` 建立 Run 后才实际打开资源、核对声明和内容，失败留下已有证据；静态通过不证明资源可用，也不意味着已有通用 worker Runtime。

源数据读取属于 `gym.environment_ts.datasets`，基准登记和解析属于 `gym.autobench`。独立资源包发布固定源清单、Dataset Card、质量报告和 BenchmarkDefinition；领域 resolver 返回原生 EvaluationSpec，不自己执行候选或创建另一种报告。`data_home` 放长期原始/派生资产和清单，`cache_home` 放可重建缓存，Run root 继续保存 SQLite/CAS。安装和启用不会自动导入附件。

五份附件已由 `bench-tsqa` 显式登记为 5 个 `test/user_declared_evaluation` 数据集，共 19,354 行，训练、prepare、dataset_build 均被禁止。公开 DatasetHandle 支持索引、select/filter、iter_batches，不暴露 raw/targets 或答案引用；解析 benchmark 的 evaluation 服务单独读取私有参考。原题、条件、选项、时序数值及重复行保留，未知参考保留 missing 与 eligible。完整 746 行 Python/CLI 读取、原生 evaluate 与原 Run 重评已验证；first-public-choice 基线只检验集成，不声称真实模型质量或全部 19,354 行已运行。详见 [TSQA 说明](bench_tsqa/README.md)和[验收](../docs/reports/bench-tsqa-full746-final-2026-10-20.json)。

## 训练扩展与正式评价

核心公开 `gymts.training.build_dataset(spec, records, artifacts)`、`DatasetBuilderProvider` 与 `DatasetBuilderRegistry`。provider 经 `gymts.dataset_builders` 按精确版本选择；服务校验固定引用、目标格式、BuildSpec/CAS 与 DatasetManifest 一致性。具体 token/mask/reward/样本血缘由独立 provider 验证，框架不写 RL 行格式。

RL 的 `NativeRolloutBuilder` 实现既有原生轨迹导出；旧两参数 helper 兼容保留。TRL 通过 `rollout_provider` 与 artifact services 接收已发布 shard，继续使用上游 GRPO loss、backward、optimizer。CPU 小模型测试验证真实参数更新，不以镜像实现的测试代替上游训练。没有新增训练框架；verl、多轮和分布式后端尚未适配。

正式评价始终由 AutoBenchTS `evaluate/score` 负责。RL 现有 `rl-qa-scorer` 与 `gymts-rl score` 支持旧评测 Run、独立参考、显式 Gate 和新参考修订，不重新加载模型；训练 heldout 摘要不变成正式报告。RL 现已发布固定基础身份、adapter/config、tokenizer/processor 和训练血缘的单 archive；新进程 Candidate 从 `artifact` 装载，execution seed 不进入候选身份，原生 evaluate 后可重复同 seed 和零推理重评，历史身份不伪合并。[完整工程验收](../docs/reports/rl-checkpoint-loop-2026-10-20.json)包含真实 TRL 两步更新与 28 个封存 Run，实际 accuracy=0.0、format_valid=0.5；技术 Gate 只看执行和覆盖。微型模型的有效训练仅使用两个官方 GSM8K train 题，ChatTS 真实准备并独立评价，五附件未用于训练；不声明大型模型或全部 processor 的新轮验收。

[项目网页](https://netman.aiops.org/contacts/projects/)中的 ChatTS 工作台、共享 ChatTS FM 与本包各有职责；本包不实现整个工作台或 FM。网页 AutoResearchTS 与本地 LabTS/调用方按上位职责对应，不认定名称迁移。软件包发行、资产发布和业务 Agent 更新分别处理，评价报告不自动更新共享模型。

## 验证与后续接入

```bash
python -B scripts/check_release.py --output /tmp/gymts-core-check.json
python -B scripts/check_adapters.py --output /tmp/gymts-adapter-check.json
```

检查需要本地 setuptools/wheel，离线构建全部 wheel/sdist、源包重建；每个包在源码目录外的干净环境独立安装，依赖仅从本地 wheelhouse 解析，验证发现、启用、CLI、回归、移除与核心旧 Run 重评分；上一轮六包的[发行检查](../docs/reports/adapter-package-check-2026-10-20.json)保留。本轮全部十一包独立构建/安装/共同启用/移除已通过[新发行检查](../docs/reports/environment-adapter-package-check-2026-10-19.json)，各新增来源另有原生零跳过验收，见[环境接入指南](../docs/environment-adapters.md)。原生项目和大模型测试显式开启，不调用付费服务。历史验收保留，最新版本与真实八组合、原生调用和训练扩展证据见[本轮验证](../docs/component-replacement-validation-2026-10-19.md)。

后续项目先核对真实语义与当前规范，以最小真实实验定位差距。格式、任务解释和原生 API 放外部适配器；共享领域语义放独立合同包；生命周期、权限、身份、轨迹或评价组织缺口才扩展核心并保留旧项目回归。接入完成需验证兼容角色替换、非法组合拒绝、独立交付、移除与历史重评分。最小资源目录、纯装配与 RL checkpoint 链已交付；完整 v2 生命周期、通用隔离/远程 Runtime、Agent 对可替换工具集的真实工具循环、更多训练 profile/后端仍待验收；外部 LibraryTS 资产平台和上位 Research/Memory 编排各自独立。资源别名并发不可变性修复后的最终同版核心、746 行 benchmark、RL 检查点链、TimeSigma 原生 75 项与 LibraryTS 原生 10 项均已复验；精确身份和实际范围见[本轮交付](../docs/framework-delivery-2026-10-20.md)。

## 工具集由 Agent 调用

LibraryTS 与其他工具集都是可替换的外部提供方。被测 Agent 在 Task/配置允许的能力内选择工具，原生 SDK 或平台通过适配执行，并把结果交回 Agent。GymTS 只承担公共接口、实验环境边界、调用关联和证据保存；不强制安装某个工具集，不因同仓库有 adapters 目录就内化项目。

当前工具包装、固定算法 Candidate 和 Research journal 的验收分别保留；它们没有证明自主 Agent 已完成工具选择和续推。内部纯计算、额外环境读写、Run 外实验编排和私有评分按实际效果分路，见[工具职责与现状](../docs/agent-toolsets.md)。
