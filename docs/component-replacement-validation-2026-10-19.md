# LibraryTS、三侧替换与训练扩展验证

日期：2026-10-19。主仓库：Jurmean/GymTS；核心 0.4.1，正式接口规范 1.1.0，独立包 0.1.0。未提交 Git，未调用付费模型，未重新训练大模型。

## 本轮落地的边界

GymTS 保留 EnvironmentTS 与 AutoBenchTS。中立时序领域语义由独立 `gymts-timeseries` 提供，不进入核心。数据 Source 返回数值与公开来源事实；Task 生成问题和输出约束；Candidate 内部 codec 构造具体模型请求。解析和 Scorer 通过版本化领域合同复用。核心不导入具体项目，领域包不导入 ChatTS、LibraryTS 或 RL。

LibraryTS 使用用户指定 [NetmanAIOps/sktime](https://github.com/NetmanAIOps/sktime)，固定提交 `080f4c3c3695f239e328548bac7d7a3ef7aa9127`、原生源码版本 sktime 0.40.1。独立 `gymts-libraryts` 接入十种真实工具、原生数据加载、两种方法及预测 Scorer。原生 worker 校验来源、固定 commit、tracked cleanliness、实际导入路径与模块摘要。未用另一个 PyPI sktime 代替指定仓库。

通用训练服务现在公开 `build_dataset(spec, records, artifacts)`、`DatasetBuilderProvider`、`DatasetBuilderRegistry`；按精确版本选择 provider，检查固定组件引用、目标格式、BuildSpec/CAS 与 Manifest 一致性。具体 native rollout、mask、reward 和用途校验在 RL provider。TRL 通过注入的 `rollout_provider` 消费已发布 shard，继续复用上游 GRPO loss、backward 和 optimizer。公开接口没有新增 QA 行假设。

这与[项目网页](https://netman.aiops.org/contacts/projects/)中 GymTS 执行与评价、LibraryTS 提供可复用实现、训练更新作为可选能力的职责一致。没有新增第三个核心主模块，也不以训练或评价结果自动更新业务 Agent。

## 真实替换实验

运行 [component_swap_matrix.py](../examples/component_swap_matrix.py)，只替换配置：

| 来源 | Task | 方法 | Run 数 | 初次评价 | 独立参考到达后 |
| --- | --- | --- | --- | --- | --- |
| 数值 JSON 快照 | 数值预测 | Naive(drift)、Polynomial(degree=1) | 2 | insufficient_evidence | pass |
| 数值 JSON 快照 | 趋势判断 | 同上 | 2 | insufficient_evidence | pass |
| 不可变长表 CSV | 数值预测 | 同上 | 2 | insufficient_evidence | pass |
| 不可变长表 CSV | 趋势判断 | 同上 | 2 | insufficient_evidence | pass |

八个 Run 使用明确的线性观测 0…11；预测独立参考为 [12,13]，趋势为 increasing。预测 Gate 为 MAE≤1e-8，趋势 Gate 为 accuracy≥1。它们验证组合与证据管线，不是科学泛化或模型质量结论。两个方法每次对当前获准输入真实拟合、预测后丢弃临时状态；没有持久模型训练或未来标签输入。

每个 Run 保存实际 ModelCall、子 ToolCall、输入输出和来源/方法修订。对同一 Task，跨来源和方法的 TaskInput 摘要相同；输入不含模型 messages、model_input 或私有参考。补充 evaluation-only Outcome 后，通过原生 AutoBenchTS `score` 重评同一 Run，RunResult 摘要、事件数、原生调用数和输入摘要全部不变。Scoring 显式保留原计划的 source/task tags。

完整配置、Run ID、输入/结果摘要、调用数、报告身份及快照引用见[紧凑机器记录](reports/component-swaps-2026-10-19.json)。完整 CAS、SQLite 与 summary 已封存到本地忽略目录 `output/component-replacement-20261019/evidence.tar.gz`；[归档摘要](reports/component-evidence-archive-2026-10-19.json)提供 SHA-256。归档不含模型权重、上游 checkout 或凭证。活动记录库在 `/tmp/gymts-component-swaps-20261019/records`；归档可恢复其全部封存证据。

复现需要准备各包与固定上游源码，步骤见 [LibraryTS README](../adapters/libraryts/README.md)：

```bash
python -I -B examples/component_swap_matrix.py \
  --root /tmp/gymts-component-swaps-new \
  --repository /path/to/fixed-sktime \
  --python /path/to/native-env/bin/python
```

## 适配器与训练验收

以下 `.log` 路径指向本地原始日志，不随源码分发；公开保留的 JSON 摘要记录相应实验事实与证据身份。

- 核心 wheel/sdist 独立安装、sdist 重建与 140 项回归全部通过；另验证外部公共 SDK 插件的安装、运行和移除，见[核心检查](reports/components-core-package-check-2026-10-19.json)。
- 五个独立包干净环境共 234 项（198 通过、36 项按科学依赖/原生开关跳过）；发行物、依赖解析、共同启用、卸载与核心旧 Run 重评分见[本轮发行检查](reports/components-adapter-package-check-2026-10-19.json)。各包独立环境只安装其声明依赖；本地 wheelhouse 供共享领域包解析，不把所有项目装进每个环境。
- LibraryTS 科学环境 9/9 全通过、零跳过；十个真实工具、airline 数据加载、两次真实 CPU fit/predict、原生 MAE/RMSE 独立评分均通过。详见[原生检查](reports/libraryts-native-check-2026-10-19.json)；本地原始日志为 `docs/reports/libraryts-native-check-2026-10-19.log`。Airline 示例未配置验收 Gate，其 verdict 正确保持 insufficient_evidence，不把指标可计算误当验收通过。
- 训练服务 8/8 通过，含 provider 注入/发现、只加载选中实现、错误 Manifest、固定引用拒绝等，本地服务日志为 `docs/reports/training-service-check-2026-10-19.log`。RL 科学环境 78 项中 77 通过、1 项真实来源检查按开关跳过；CPU 测试实际执行上游 TRL loss、backward 和 SGD.step 并确认权重改变，本地 RL 日志为 `docs/reports/training-extension-rl-check-2026-10-19.log`。唯一跳过的真实来源检查随后单独显式运行，1/1 通过、零跳过，使用最终离线安装 wheel、真实缓存 GSM8K 与 ChatTS 数值生成，见[来源验收](reports/rl-native-source-final-2026-10-19.json)，本地原始日志为 `docs/reports/rl-native-source-final-2026-10-19.log`。该检查不重复训练。
- RL 新注册 `rl-qa-scorer`，旧评测 Run 可通过 `score_rollout_runs` / `gymts-rl score` 生成 AutoBenchTS 报告、配置显式 Gate，并用新参考修订重评，不加载模型或生成新回答。
- 收尾修复 ChatTS 重评分漏传 tags，真正按 tags.task_id 分组的回归通过，并禁止重评分触发 infer。独立新 wheel 的 neutral 6/6、legacy pipeline 4/4、legacy text pipeline 3/3 通过，本地 neutral 日志为 `docs/reports/chatts-prompt-tags-neutral.log`。

历史拆包、TimeSigma CPU 和大模型训练证据保持原内容；本轮不将它们重记为新实验。版本与测试次数以对应机器报告为准。

## 明确的限制

当前 ChatTS 中立 source/codec/pipeline 使用格式 fixture 和本地 HTTP mock 做合同验证。本轮没有真实 ChatTS-Bench-new 生成 profile，不能证明原七类 benchmark 的真实题干全部等价保留。默认 canonical prompt 是派生实验，导入 manifest 和自有 summary 的 `prompt_policy` 明确 `equivalent_to_original_benchmark_prompt=false`；原材料保留为受限来源证据，原 `/1` 路径通过 `--legacy` 保留。

未来导入用户五份真实 QA 测评集时，必须把公开题干、选项和条件解码为中立 question/context，不能直接套全局 task 模板。五份附件仍为 evaluation-only，数据/benchmark 目录尚未实施，未混入训练。

LibraryTS 统一资产登记/发布与持久训练 bundle、RL 新 evaluate 的可装载 checkpoint/重复 seed 绑定、完整 v2 Runtime、多轮/verl/分布式训练仍待适配。不支持的组合明确失败，不宣称任意来源、任务和模型都兼容。当前源代码、数据加载与 native tools 已实际接入；上游 trainer 的可复用 fit/序列化边界已记录于适配器指南，但其目录选数、可变模型 ID 和独立评价不能直接作为 GymTS 训练合同。
