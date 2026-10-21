<div class="eyebrow">GYMTS DOCUMENTATION · v0.6.0</div>

# 时序数据与实验，统一组织。

<p class="lead">存储数据、接入数据、组织实验、记录实验。固定数据与配置，保留每个阶段的输入、产物、失败和评价依据。</p>

<div class="hero-actions"><a class="button-primary" href="../../../docs/quickstart.md">五分钟开始 <span aria-hidden="true">→</span></a><a class="button-secondary" href="../../../docs/experiment-organization.md">组织一次实验</a></div>

<p class="hero-note">Python 3.9+ · 核心无第三方运行依赖 · MIT · 从源码安装</p>

<div class="workflow" aria-label="GymTS 的四项主线"><div class="workflow-step"><span class="workflow-number">01</span><strong>存储数据</strong><small>统一目录、固定版本、用途与血缘。</small></div><div class="workflow-step"><span class="workflow-number">02</span><strong>接入数据</strong><small>连接静态、合成、仿真和 live 来源。</small></div><div class="workflow-step"><span class="workflow-number">03</span><strong>组织实验</strong><small>声明阶段依赖，绑定输入和产物。</small></div><div class="workflow-step"><span class="workflow-number">04</span><strong>记录实验</strong><small>保留每次尝试、Run、结果与评价。</small></div></div>

## 从数据入库到实验记录

```bash
git clone https://github.com/Jurmean/GymTS.git
cd GymTS
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
python examples/experiment_organization.py --work /tmp/gymts-organization-demo
```

这个示例不需要 GPU、外部数据或 API key。它将观测入库，按阶段完成预测、采集快照、
登记评价参考、评分与重评。再次执行相同清单会沿用成功阶段；你可以按数据或实验查询记录。
完整步骤见[实验组织指南](../../../docs/experiment-organization.md)，预测与控制入门见[快速开始](../../../docs/quickstart.md)。

<p class="note-line">当前实现为 0.6.0，公共合同为 1.4.0，F2.1 已通过实验组织、数据回库、关联查询与独立外包技术验收。仓库代码可直接安装；不假定此版本已发布到 PyPI。活动 SQLite / CAS 请放在本机 POSIX 文件系统，<code>/tmp</code> 仅用于快速体验。</p>

## 两个稳定职责，一个开放边界

**EnvironmentTS** 在核心管理四类数据的来源目录、快照、血缘、运行与证据。**AutoBenchTS**
管 benchmark、评价计划、独立评分、比较与重评。项目数据格式、模型调用、领域任务和
评分规则由独立适配包提供。数据层边界见 [ADR 0001](../../../docs/adr/0001-core-data-source-catalog.md)，实验组织、回库与查询协议见 [ADR 0002](../../../docs/adr/0002-experiment-organization.md)。

LibraryTS、TimeSigma、ChatTS 以及其他工具集都通过接口接入。
Agent 决定调用哪些工具；适配器转换调用并保留证据。TimeCopilot 已完成 6 次真实模型请求、
四种原生工具及独立重评，见[五项目验收](../../../docs/five-project-integration-acceptance-2026-10-21.md)。
这不等于跨项目通用 Agent Runtime。详见[架构](../../../docs/framework.md)、
[Agent 与工具集](../../../docs/agent-toolsets.md)和[当前验收边界](../../../docs/project-status.md)。

## 从你需要的地方进入

<div class="resource-list"><div><strong><a href="../../../docs/dataset-benchmark-catalog-design.md">数据目录与存储 →</a></strong><p>来源、dataset 与 benchmark 的存放位置、版本和读取。</p></div><div><strong><a href="../../../docs/experiment-organization.md">实验组织与数据回库 →</a></strong><p>阶段清单、输入产物绑定、显式重试与阶段级恢复。</p></div><div><strong><a href="../../../docs/reference.md">记录、查询与 API →</a></strong><p>按数据、实验与执行尝试查 Run、产物和评价。</p></div><div><strong><a href="../../../docs/adapter-development.md">接口与独立适配 →</a></strong><p>格式、连接器、模型调用和领域评分的适配边界。</p></div></div>

## 当前验证范围

196 项源码外核心测试通过；16 个适配包的兼容检查中，356 项通过、61 项可选依赖测试跳过。
独立 CSV 适配包在冻结核心上完成真实运行，卸载后仍可读取数据、查询实验和重评原输出。
完整范围与限制见[验收报告](../../../docs/reports/experiment-organization-2026-10-21.json)和[项目状态](../../../docs/project-status.md)。

## 适配生态，按需安装

| 需求 | 独立适配包 |
| --- | --- |
| 时序领域合同与工具 | [timeseries](../../../adapters/timeseries/README.md)、[LibraryTS](../../../adapters/libraryts/README.md) |
| 合成时序与模型问答 | [ChatTS](../../../adapters/chatts/README.md)、[TimeSigma](../../../adapters/timesigma/README.md) |
| 静态数据与测评资源 | [HF Datasets](../../../adapters/hf_datasets/README.md)、[TSQA benchmark](../../../adapters/bench_tsqa/README.md) |
| 仿真、交互与 live testbed | [interaction](../../../adapters/interaction/README.md)、[Gymnasium](../../../adapters/gymnasium/README.md)、[OpenEnv](../../../adapters/openenv/README.md)、[Prometheus](../../../adapters/prometheus/README.md) |
| 原生 Agent 与信号问答 | [TimeCopilot](../../../adapters/timecopilot/README.md)、[ITFormer](../../../adapters/itformer/README.md) |
| 分位数预测与原生 fit | [Chronos-2](../../../adapters/chronos/README.md) |
| 加工、血缘与派生数据 | [Data-Juicer](../../../adapters/datajuicer/README.md) |
| Rollout 与外部训练后端 | [RL / TRL](../../../adapters/rl/README.md)、[AReaL](../../../adapters/areal/README.md)（训练/发布已验证，留出评价与重评 pending） |

所有适配包分别安装并显式启用。核心不因某个项目的接入而自动依赖它。
[完整安装矩阵](../../../adapters/README.md)列出依赖、可运行示例和验收范围。
当前十六包通过所列离线发行检查；本轮 TimeCopilot、ITFormer、Chronos-2 和 Data-Juicer
原生工程闭环已完成，AReaL 训练/发布已验证，留出评价与重评待最终证据。工程完成与模型质量分别判断。

## 参与 GymTS

从[最小教学适配包](../../../examples/adapters/minimal_demo/README.md)接入你的方法，或阅读
[贡献指南](../../../CONTRIBUTING.md)与[路线图](../../../docs/roadmap.md)。
框架与本站文档采用 [MIT](../../../LICENSE)；外部项目、数据集和权重保留各自许可。
