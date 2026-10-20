# gymts-chatts

独立发布的 ChatTS-Bench 来源与 ChatTS 原生模型/文本模型适配包；它不是 ChatTS 产品界面。核心 `gymts` 不包含本包。本包依赖 `gymts>=0.4.1,<0.5` 和共享领域包 `gymts-timeseries>=0.1,<0.2`，不依赖 TimeSigma、LibraryTS 或 RL 适配器。

在主仓库根目录安装核心与适配包：

```bash
python3 -m pip install . ./adapters/timeseries ./adapters/chatts
gymts-chatts --help
```

分别安装已构建的 `gymts` 和 `gymts-chatts` wheel 后，可在任意目录使用相同命令，无需设置 `PYTHONPATH`。安装不会启用插件或运行源生成器；只有显式选择 `GymTS(integrations=("chatts",))`、`gym.enable_integration("chatts")` 或 `gymts --integration chatts ...` 才注册组件。专用 `gymts-chatts` pipeline 自行启用该集成。

```python
from gymts import GymTS

with GymTS("/tmp/chatts-experiment", integrations=("chatts",)) as gym:
    print(gym.enabled_integrations)
```

Python 导入位置为 `gymts_chatts`；原 `gymts.integrations.chatts` 导入路径已移除。组件 ID、版本、任务协议、数据 schema 和历史记录保持原有身份，例如 `chatts-synthetic-qa@1.0.0`、`gymts.task/chatts-qa/1`；安装适配包并启用后仍可对原 Run 评分，无需转换历史制品。

新实验默认使用共享 `gymts.task/timeseries-qa/1`：来源仅提供 series/context/公开 annotations，Task 生成 question 和 response_schema，模型 codec 才生成 messages、ChatTS 占位符与原生数组请求。通用数值 Source 和七类 Task/Scorer 属于独立共享领域包；本包的新 Candidate 为 `timeseries-chatts-http`、`timeseries-text-http` 和 `timeseries-signal-baseline`。Task 与其他来源/LibraryTS 模型通过同一数值合同协作，不导入本包。

这是一种**派生的 canonical prompt 实验**：共享 Task 生成问题文本，替代原 profile 的 messages，不等价于原 benchmark prompt。原题指令仍完整保存在私有原始来源制品中，不进入新 TaskInput。中立导入 Manifest、pipeline 汇总及逐任务摘要均记录 `prompt_policy`，其中 `original_source_messages_used=false`、`equivalent_to_original_benchmark_prompt=false`；正式 EvaluationReport 的公共 schema 保持不变。需要按原题指令评价时使用 legacy 路径。

`run_pipeline` / `gymts-chatts` 默认使用这条路径。历史路径使用 `run_legacy_pipeline` / `gymts-chatts --legacy`，并选择示例中的 `.legacy.json` 连接配置；所有旧 `/1` schema、组件 ID 和旧 source 语义检查保持原值。原 benchmark 的任务身份作为公开来源约束保留，不能换 Task 后继续沿用原 gold；通用 JSON/CSV 来源的 `annotations={}` 则允许同一数据选择不同兼容 Task。

数据生成需要另外取得兼容的 ChatTS 生成器仓库或已有 profile；源生成器、数据、模型权重和推理服务不包含在 wheel 中。HTTP Candidate 仅使用标准库，默认不下载权重、不调用付费服务。参见仓库中的[完整接入指南](../../docs/chatts-integration.md)与本包的[连接配置示例](examples/README.md)。

本包包含独立回归测试与测试 fixture。安装核心和本包后执行：

```bash
python3 -m unittest discover -s adapters/chatts/tests -p 'test_*.py'
```

解压本包 sdist 后，在解压目录执行 `python3 -m unittest discover -s tests -p 'test_*.py'`，不需要主仓库示例或其他适配器。

新版本的 Source/Task 提供纯 `describe_spec` 和配置兼容检查；`gym.plan`/`gym.validate` 不读取 snapshot 或连接模型服务。旧版和中立路径的 baseline task_id 错配会在计划阶段拒绝，具体样本的 series/horizon/benchmark 约束在 Run 内检查并保留失败证据。执行 seed 由 CandidateContext 传入，不改变 CandidateSpec 身份：普通文本 OpenAI 路由和 ChatTS vLLM envelope 路由发送请求参数 `seed`，旧 `chatts-timeseries/v1` 路由只记录请求意图、不新增未知参数。deployment、请求制品与输出 evidence 都记录 `requested_seed`、`parameter_sent` 和 `backend_enforcement=unverified`；服务端采样确定性尚未验证。

## License

GymTS-owned code in this package is licensed under the [MIT License](LICENSE).
Third-party libraries, upstream projects, datasets, model weights and services
retain their own licenses and terms; this package does not relicense them.
