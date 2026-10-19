# GymTS

GymTS 是时序实验与评价框架：让开发者在固定的数据、任务和预算下比较方法，查看失败案例，并在标签到达后对原结果重新评分。EnvironmentTS 负责运行与证据记录，AutoBenchTS 负责独立评价。

当前版本 **0.3.1**，实现基线为[接口规范 1.1.0](docs/feishu/GymTS接口规范/GymTS接口规范.md)。本版本提供同步本地 Python SDK、CLI、显式插件注册、不可变制品和实验记录；企业多团队平台处于[路线设计阶段](docs/enterprise-platform-roadmap.md)。Python **3.9+**，当前本地存储后端支持 **Linux/macOS**；JSON 工作流没有第三方运行依赖。

## 五分钟运行完整链路

在源码目录执行：

```bash
python3 examples/quickstart.py --root .gymts/demo
```

示例验证预测、交互、无标签评价、追加标签和旧 Run 重评分，使用本地合成序列，无需 GPU、模型或服务凭证。预期结果：

- 控制环境执行 3 次动作。
- 标签到达前为 `insufficient_evidence`，追加标签后评价为 `pass`。
- 两个候选的 MAE 分别为 1 和 2。
- 重评分保留原 Run ID 和原始 RunResult，不再次调用候选。

安装命令行：

```bash
python3 -m pip install -e .
gymts run examples/forecast_experiment.json
```

YAML 为可选功能，使用 `python3 -m pip install -e '.[yaml]'`。更多可运行配置见 [examples](examples/README.md)。

## 命令行

```bash
python3 -m gymts validate examples/forecast_experiment.json
python3 -m gymts run examples/forecast_experiment.json --output .gymts/forecast-result.json
python3 -m gymts run examples/counter_experiment.json
python3 -m gymts evaluate examples/forecast_evaluation.json --output .gymts/evaluation.json
python3 -m gymts plugins
```

全局选项放在子命令前，例如 `gymts --store .gymts/demo inspect RUN_ID`。`inspect --events` 查看执行事件；`attach-outcomes labels.json --run-id RUN_ID` 追加结果依据；`score score.json` 复用旧输出评分。

配置错误退出码为 2，运行失败或取消为 1。评价完成但依据不足时退出码为 0，调用方应读取 `verdict`；流程成功与业务指标通过分别表达。

## Python API 与插件

```python
import json
from gymts import GymTS

with GymTS(root=".gymts") as gym:
    with open("examples/forecast_experiment.json", encoding="utf-8") as stream:
        spec = json.load(stream)
    validation = gym.validate(spec)
    if not validation["valid"]:
        raise ValueError(validation["issues"])
    result = gym.run(spec)
    record = gym.records.get_run(result["run_id"])
    original_results = gym.artifacts.read_json(result["result_ref"])
```

业务代码可直接调用自己的 `register(registries, schemas)`，或在独立分发包中声明 `gymts.integrations` entry point，再通过 `GymTS(integrations=("myteam",))` 显式启用。`GymTS.available_integrations()` 读取可用集成元数据，发现阶段不导入插件实现。插件能力通过 Manifest 与 schema 检查，新任务不需要给 Runner 添加名称分支。

默认仅启用确定性参考插件，**不导入或注册 ChatTS**。从 0.3.0 迁移时，使用 ChatTS 的 Python 调用改为：

```python
with GymTS(root=".gymts", integrations=("chatts",)) as gym:
    result = gym.run(chatts_experiment)
```

通用 CLI 使用 `gymts --integration chatts run CONFIG.json`。数据源、任务和方法的现行接入规则见[框架指南](docs/framework.md)；更细粒度的下一版协议仍为[设计草案](docs/pluggability-contract-v2.md)，尚未作为运行合同实施。

## 可选 ChatTS 集成

ChatTS 集成提供合成数据导入、七类 QA Task、数值基线、原生时序与普通文本 HTTP Candidate、独立评分及固定快照的 QA IO 导出。

需要另外取得兼容的源生成器仓库或已生成 profile：

```bash
python3 -B -m gymts.integrations.chatts.pipeline \
  --source-repo /path/to/ChatTS-Bench-new \
  --output .gymts/chatts-experiment-001
```

默认使用明确标识的数值算法基线；连接真实 ChatTS 服务时加 `--candidate-config examples/chatts_http_candidate.json`。专用 pipeline 自动启用 ChatTS 集成。生成器依赖由其自己的 Python 环境提供，输出目录必须是新目录。

普通文本 LLM 可使用 [DeepSeek 配置](examples/deepseek_candidate.json)，凭证通过环境变量提供。时序以完整精度的数值 JSON 文本发送；服务 alias 不能证明固定了模型权重。具体依赖、输入表示、失败政策及运行步骤见 [ChatTS 指南](docs/chatts-integration.md)。

## 代码结构

| 目录 | 职责 |
| --- | --- |
| [contracts](gymts/contracts/) | 公共消息、Protocol、结构化错误与 schema |
| [registries](gymts/registries/) | 精确版本 Manifest/Factory 登记 |
| [environment_ts](gymts/environment_ts/) | 校验、Runner、受限服务与清理 |
| [storage](gymts/storage/) | SQLite WAL、不可变制品、Outcome 修订与快照 |
| [autobench_ts](gymts/autobench_ts/) | 固定计划、独立评分、聚合、比较与 Gate |
| [plugins](gymts/plugins/) | 回放、窗口预测、控制和 MAE 参考实现 |
| [integrations](gymts/integrations/) | 显式可选集成与第三方入口发现 |
| [tests](tests/) | 合同、失败路径、存储及端到端回归 |

## 验证与发布准备

```bash
python3 -B -m unittest discover -s tests -v
python3 -B scripts/check_release.py --output output/release-check.json
```

发布检查需要本地已有 setuptools 和 wheel；检查过程离线构建 wheel/sdist，核对发行物内容，从源包重建 wheel，并在源码目录外的新虚拟环境中安装和运行测试。GitHub CI 配置 Python 3.9、3.12、3.13；跨版本结果以实际 CI 为准。

`.gitignore` 排除本地实验输出、数据库、缓存与常见凭证文件。发行物检查覆盖已知凭证模式，不替代对实际提交内容的检查。修复范围与验证结果见[本次修复报告](docs/release-readiness-2026-10-18.md)。

## 当前边界

- 插件是受信任的进程内代码；受限服务不构成 Python 沙箱。
- 同步 wall limit 在调用边界检查；后端负责 I/O 超时，尚无强制中断、分布式 worker 或企业租户隔离。
- HTTP QA 保存实际请求和响应，尚无模型内部 token/logprob/mask 采集及 RL rollout/训练器适配。
- 原生 ChatTS 权重推理、GPU 训练与生产业务效果不在本版本的离线验收范围。
- 本地实验产物不随源码发布；平台路线和 v2 字段推演均属于设计材料。

仓库尚未指定开源许可证。公开分发和复用授权需由项目所有者确定后写入 LICENSE。
