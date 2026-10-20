<div class="eyebrow">GYMTS DOCUMENTATION · v0.5.0</div>

# 时序实验，有据可查。

<p class="lead">连接数据、环境与方法，保留每一次运行的证据，再用独立依据评价。让新的项目适配框架，让实验结果经得起重评。</p>

<div class="hero-actions"><a class="button-primary" href="../../../docs/quickstart.md">五分钟开始 <span aria-hidden="true">→</span></a><a class="button-secondary" href="../../../docs/reference.md">查看 API</a></div>

<p class="hero-note">Python 3.9+ · 核心无第三方运行依赖 · MIT · 从源码安装</p>

<div class="workflow" aria-label="实验工作流"><div class="workflow-step"><span class="workflow-number">01</span><strong>装配实验</strong><small>数据源、任务、方法分别注册与替换。</small></div><div class="workflow-step"><span class="workflow-number">02</span><strong>执行并留证</strong><small>EnvironmentTS 管生命周期、权限与轨迹。</small></div><div class="workflow-step"><span class="workflow-number">03</span><strong>独立评价与重评</strong><small>AutoBenchTS 固定依据，对原输出生成新报告。</small></div></div>

## 从一次可复现的实验开始

```bash
git clone https://github.com/Jurmean/GymTS.git
cd GymTS
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
python examples/quickstart.py --root /tmp/gymts-quickstart
```

这个示例不需要 GPU、外部数据或 API key。它完成预测、控制动作、候选比较、追加标签，
然后对同一组 Run 重评。运行结束后，你可以检查每次操作、输入、输出及评分依据。

<p class="note-line">当前实现为 0.5.0，公共合同为 1.2.0。仓库代码可直接安装；不假定此版本已发布到 PyPI。活动 SQLite / CAS 请放在本机 POSIX 文件系统，<code>/tmp</code> 仅用于快速体验。</p>

## 两个稳定职责，一个开放边界

**EnvironmentTS** 管运行、授权边界和证据。**AutoBenchTS** 管评价计划、独立评分、比较与重评。
数据格式、模型调用、领域任务和评分规则由独立适配包提供。

LibraryTS、TimeSigma、ChatTS 以及其他工具集都通过接口接入。
Agent 决定调用哪些工具；适配器转换调用并保留证据。当前已完成的工具包装与 Research 父轨迹，
不等于已经交付通用自主工具循环。详见[架构](../../../docs/framework.md)、
[Agent 与工具集](../../../docs/agent-toolsets.md)和[当前验收边界](../../../docs/project-status.md)。

## 从你需要的地方进入

<div class="resource-list"><div><strong><a href="../../../docs/user-guide.md">使用指南 →</a></strong><p>安装、第一次运行、读取轨迹、晚到标签与重评。</p></div><div><strong><a href="../../../docs/reference.md">API 与命令行 →</a></strong><p>GymTS、EnvironmentTS、AutoBenchTS 及公开合同。</p></div><div><strong><a href="../../../docs/environment-adapters.md">数据与环境 →</a></strong><p>合成、HF 静态数据、Gymnasium、OpenEnv 与 Prometheus。</p></div><div><strong><a href="../../../docs/adapter-development.md">接入新项目 →</a></strong><p>独立打包、发现与启用，以及卸载后独立重评。</p></div></div>

## 适配生态，按需安装

| 需求 | 独立适配包 |
| --- | --- |
| 时序领域合同与工具 | [timeseries](../../../adapters/timeseries/README.md)、[LibraryTS](../../../adapters/libraryts/README.md) |
| 合成时序与模型问答 | [ChatTS](../../../adapters/chatts/README.md)、[TimeSigma](../../../adapters/timesigma/README.md) |
| 静态数据与测评资源 | [HF Datasets](../../../adapters/hf_datasets/README.md)、[TSQA benchmark](../../../adapters/bench_tsqa/README.md) |
| 仿真、交互与 live testbed | [interaction](../../../adapters/interaction/README.md)、[Gymnasium](../../../adapters/gymnasium/README.md)、[OpenEnv](../../../adapters/openenv/README.md)、[Prometheus](../../../adapters/prometheus/README.md) |
| Rollout 与外部训练后端 | [RL / TRL](../../../adapters/rl/README.md) |

所有适配包分别安装并显式启用。核心不因某个项目的接入而自动依赖它。
[完整安装矩阵](../../../adapters/README.md)列出依赖、可运行示例和验收范围。

## 参与 GymTS

从[最小教学适配包](../../../examples/adapters/minimal_demo/README.md)接入你的方法，或阅读
[贡献指南](../../../CONTRIBUTING.md)与[路线图](../../../docs/roadmap.md)。
框架与本站文档采用 [MIT](../../../LICENSE)；外部项目、数据集和权重保留各自许可。
