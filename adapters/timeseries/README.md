# gymts-timeseries

独立的时序领域合同与实现包，依赖 `gymts>=0.4.1,<0.5`。它提供通用数值来源、七类 QA Task 和独立 Scorer，**不包含模型，不依赖 ChatTS、LibraryTS 或 RL 适配器**。LibraryTS 与模型适配器可以依赖这些公共合同。

在主仓库根目录安装 `python -m pip install . ./adapters/timeseries`，显式启用 `GymTS(root, integrations=('timeseries',))`。独立 wheel/sdist 安装同样支持，无需源码路径或 `PYTHONPATH`。

公共模块：

- `gymts_timeseries.contracts`：协议 `gymts.task/timeseries-qa/1`，源快照、TaskInput、CandidateOutput、TaskResult、Outcome 和对齐 schema，以及数值/形状验证。
- `gymts_timeseries.sources`：`publish_snapshot` 提交数值 JSON 快照，`import_csv` 固定真实 CSV 字节及公开 context。
- `gymts_timeseries.task`：`make_task_input`、七任务 schema/版本/指标与严格解析；Task 根据参数选择含义并生成 question、response_schema。
- `gymts_timeseries.experiments`：`scene`、`scoring` 生成现有 GymTS 配置；执行与正式评价仍由 EnvironmentTS / AutoBenchTS 负责。

源样本为 `{sample_token, series:[{name,values}], context, annotations}`。通用来源允许 `annotations={}`，无需预先选任务；同一数值样本可分别绑定 `forecast.numeric` 和 `pattern.trend_direction`。预测长度来自显式公开的 `context.horizon`。来源中的 benchmark 固定任务可用 `annotations.benchmark_task_id/benchmark_task_version` 声明，改变这类原题的任务必须发布明确的新视图和独立参考，不沿用原 gold。

TaskInput payload 为 `{task_id,task_version,question,series,context,response_schema}`，不包含模型消息、ChatTS 占位符、tokenizer 或 model_input。模型内部 codec 才构造其原生请求。

两种来源使用相同公开数值合同：`numeric-snapshot` 读取 JSON 快照；`csv-numeric-snapshot` 直接解析不可变长表 CSV，列顺序为 `sample_token,series_name,index,value`，每条序列 index 从 0 连续增长，不插值、排序修复或截断。CSV context 必须在配置中显式给出并参与数据修订摘要。

示例：

```python
from gymts import GymTS
from gymts_timeseries.sources import publish_snapshot
from gymts_timeseries.experiments import scene, scoring

with GymTS('/tmp/numeric-example', integrations=('timeseries',)) as gym:
    source = publish_snapshot(gym, [{
        'sample_token': 'a' * 64,
        'series': [{'name': 'Series 1', 'values': [1., 2., 3.]}],
        'context': {'horizon': 2}, 'annotations': {},
    }])
    task_scene = scene(source['snapshot_ref'], source['dataset_revision'],
                       'a' * 64, 'forecast.numeric', '0.2.0')
    scoring_spec = scoring('forecast.numeric', '0.2.0')
```

选择模型后将 scene 放入 ExperimentSpec 或 AutoBenchTS EvaluationSpec。真实 Outcome 必须单独以 `gymts.timeseries/qa-outcome/1` 提供 `{task_id,task_version,expected_output}`，通过 `dataset_revision/sample_token` 精确对齐；缺参考保留 `insufficient_evidence`，评分不重新调用模型。预测输出为 `{"forecast":[...]}`；趋势输出为 `{"trend_direction":"increasing"}`（另允许 decreasing/stable）。

本包从七类 QA 已有的严格 JSON、形状和计分实现提取共享领域语义，历史 ChatTS `/1` 实现保留在原适配器。测试使用明确的数值 fixture 和测试 Candidate，不是模型质量证据：安装本包后，在其 sdist 根目录运行 `python -m unittest discover -s tests -v`。

`gym.plan(spec)` 和 `gym.validate(spec)` 仅使用纯声明与配置兼容检查，不加载 JSON/CSV 内容，也不构造 Source、Task 或模型。来源字节、样本数量/series 结构、公开 horizon 和 benchmark 约束在 Run 开始后的 open/consume 阶段检查；这些运行失败仍保留封存轨迹。纯声明不是对外部插件的沙箱，第三方 provider 必须遵守无 I/O 的注册合同。

## License

GymTS-owned code in this package is licensed under the [MIT License](LICENSE).
Third-party libraries, upstream projects, datasets, model weights and services
retain their own licenses and terms; this package does not relicense them.
