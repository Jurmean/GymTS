# 可运行示例

`quickstart.py` 和下列预测、计数器示例使用本地确定性数据，不需要模型文件、LLM API、GPU 或私有数据。文末的模型连接配置需要对应推理服务。所有组件均按精确的 `1.0.0` 版本登记。

在项目根目录执行：

```bash
python3 examples/quickstart.py --root .gymts-demo
```

脚本会执行预测和交互 Run，比较两个候选，在无标签时报告证据不足，再追加独立真值并对原 Run 重评分。它检查前后 Run ID 和原 RunResult 摘要保持一致，最后输出 MAE=1/2 与 gate 结果。记录和制品保存在指定的本地目录。

| 文件 | 用途 |
| --- | --- |
| `forecast_experiment.json` | 生成分钟级线性序列，积累 3 点窗口，预测 1 分钟后的值 |
| `forecast_evaluation.json` | 比较 `last-value` 和 `window-mean`；初始未提供标签，应报告证据不足 |
| `forecast_score_template.json` | 旧 Run 重评分模板；替换真实 `run_id` 并提供获准的标签视图 |
| `counter_experiment.json` | 交互式计数器：消费初态 → 请求 increment → 消费转移；3 次操作后自然终止 |

预测源的 `source.connection` 必须恰好提供 `generator` 或 `points`。显式点结构为：

```json
{
  "timestamp": "2026-01-01T00:00:00Z",
  "available_at": "2026-01-01T00:02:00Z",
  "entity": "demo",
  "values": {"value": 8}
}
```

`mapping.variables` 将原始 `values` 字段名映射为环境公开变量。`options.availability=explicit` 要求每个点提供实际 `available_at`；`event_time` 允许缺省并显式采用事件时间假设。主流按可用时间交付，保留原始事件时间。查询仅能读取已经开放的时间前沿，不能因为所有数据已在内存中就提前读取未来。

`window_forecast` 固定对同一实体、变量积累窗口；保留无效点的 null 和 mask；窗口不够不调用 Candidate。此参考版本跳过已经处理或早于当前窗口的迟到点，不修订已经发出的预测；原始迟到观测仍由框架完整记录。`last-value` 使用窗口中最后一个有效值，`window-mean` 使用有效值的平均数；没有有效值时返回明确的无效结果。

评分的计数单元是原始 TaskResult，缺标签不会缩小 eligible 分母。完整的线性序列真值下，这两个候选的 MAE 分别是 1 和 2；没有标签时两者均为 `insufficient_evidence`。`forecast-mae` 仅支持精确匹配和单位 `value`，其他匹配规则或单位应提供独立的版本化插件。

将标签保存为不可变制品后，通过 `purpose=evaluation` 的 DataViewRef 传入 `scoring.outcomes.sources`。OutcomeRecord 必须有真实 `source_ref`、可用/提交时间和 `allowed_uses=["evaluation"]`。对旧输出重新评分只调用 Scorer，不调用 Candidate、不推进环境。
## ChatTS 合成实验

ChatTS 为显式可选集成，Python 使用 `GymTS(integrations=("chatts",))`，通用 CLI 使用 `--integration chatts`。专用入口为 `python3 -B -m gymts.integrations.chatts.pipeline --help`，也可安装后使用 `gymts-chatts`。默认生成 native/classical 两类真实 profile，导出 bundle 隔离的 SFT 源数据，再完成七类 QA Task 的数值基线评价、追加 gold、旧 Run 重评分与轨迹导出。

`chatts_http_candidate.json` 是真实模型连接配置模板，服务需要支持选定的原生时序 dialect。其地址与 checkpoint 来自现有 ChatTS-Bench 配置，运行前应改成实际可用的固定部署。用 `--candidate-config examples/chatts_http_candidate.json` 加入模型比较。详见 [接入与运行指南](../docs/chatts-integration.md)。

`deepseek_candidate.json` 使用独立的 `chatts-text-http` Candidate，适配普通文本 LLM API。它把公开序列按名称与原顺序完整序列化为 `named_numeric_json/v1` 文本，不归一化或舍入，也不使用 ChatTS 原生 wire。原生数值数组继续保存在 TaskInput 中；gold、源样本 ID 和生成元数据不进入请求。

先在当前进程环境中通过本地密钥管理方式设置 `DEEPSEEK_API_KEY`，然后复用已有 profile 运行七任务小样本连接验收：

```bash
python3 -B -m gymts.integrations.chatts.pipeline \
  --profile-dir /path/to/profiles/native \
  --profile-dir /path/to/profiles/classical \
  --candidate-config examples/deepseek_candidate.json \
  --no-baseline --max-per-task 1 \
  --output .gymts/deepseek-text-example-001
```

配置只保存环境变量名，密钥不写入 JSON。示例选择 `deepseek-flash` API alias，关闭 thinking 并请求 JSON object 输出。`model_revision=deepseek-flash-api-alias` 表示配置身份，不是 checkpoint 摘要；证据记录 `weights_pinned=false`。删除 `--max-per-task 1` 可运行完整留出集，加入数值基线则删除 `--no-baseline`。输出目录必须是新目录；上述命令不预先声明真实 API 结果。

