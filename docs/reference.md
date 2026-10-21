# GymTS CLI 与公共 API 参考

适用版本：GymTS **0.6.0** 工作树，正式合同 **1.4.0**；尚未发行。本文按当前代码列出公开入口，不把设计草案写成可调用接口。完整工作流见[使用指南](user-guide.md)，字段与插件生命周期见[正式接口规范](feishu/GymTS接口规范/GymTS接口规范.md)。

## 1. CLI

安装后使用 `gymts`；等价入口为 `python -m gymts`。JSON 为默认格式，`.yaml` / `.yml` 需安装源码 extra `.[yaml]`。

### 1.1 通用参数与命令

```text
gymts [--store PATH] [--data-home PATH] [--cache-home PATH]
      [--integration NAME ...] COMMAND ...
```

全局参数必须放在子命令前。`--integration` 可重复，如 `--integration timeseries --integration libraryts`。

| 参数 | 默认 | 含义 |
| --- | --- | --- |
| `--store PATH` | `.gymts` | 活动 Run SQLite 与 CAS 根目录，需本地 POSIX 语义 |
| `--data-home PATH` | 环境变量或 XDG data 目录 | 四类来源定义、固定数据资源及 benchmark 清单 |
| `--cache-home PATH` | 环境变量或 XDG cache 目录 | 可重建的校验后资源缓存 |
| `--integration NAME` | 无 | 显式启用已安装的受信任集成；可重复 |
| `--help` | — | 显示帮助；各子命令也支持 `--help` |

| 命令 | 参数 | 返回内容及行为 |
| --- | --- | --- |
| `plan SPEC` | `[--output FILE]` | 纯声明 AssemblyPlan；不打开项目运行资源 |
| `validate SPEC` | `[--output FILE]` | ValidationResult；不执行实验 |
| `run SPEC` | `[--output FILE]` | 执行一个 ExperimentSpec，返回 RunResult |
| `evaluate SPEC` | `[--output FILE]` | 固定 EvaluationSpec 计划，执行新 Runs 并独立评价 |
| `score SPEC` | `[--output FILE]` | 对 ScoreSpec 指定的旧输出评价，不调用 Candidate |
| `attach-outcomes SPEC` | `--run-id ID [--output FILE]` | SPEC 为 OutcomeRecord **数组**，追加后返回固定 OutcomeSnapshotRef |
| `inspect RUN_ID` | `[--events]` | 读取已存 RunRecord；默认省略 events/event_refs |
| `plugins` | 无 | 列举当前启用的 Environment/Task/Candidate/Scorer 精确 Manifest |
| `run-data SPEC` | `--source ID --source-revision REV --dataset-id ID [--source-config default] [--config default] [--split recorded] [--output FILE]` | 绑定来源、执行原 ExperimentSpec 并采集 dataset；返回 run/dataset |
| `sources list` | 无 | 列出当前 data_home 的来源定义 |
| `sources register SPEC` | `[--alias LABEL ...] [--output FILE]` | 登记 DataSourceDefinition，不启动后端 |
| `sources info SOURCE_ID` | `--revision REV [--config default] [--output FILE]` | 读取固定来源定义 |
| `datasets capture RUN_ID` | `--source ID --source-revision REV --dataset-id ID [--source-config default] [--config default] [--split recorded] [--output FILE]` | 将已封存 Run 的实际环境数据登记为 dataset v2 |
| `datasets list` | 无 | 列出当前 data_home 的固定数据清单 |
| `datasets info DATASET_ID` | `--revision REV [--config default] [--split test] [--output FILE]` | 公开 DatasetHandle.info；不输出私有参考 |
| `datasets register SPEC` | `[--alias LABEL ...] [--output FILE]` | 登记 SourceDatasetRevision；其引用的资源字节须先存在 |
| `experiments register SPEC` | `[--output FILE]` | 登记不可变实验组定义，返回补齐字段与固定 revision |
| `experiments run GROUP_ID` | `--revision REV [--retry-failed] [--rerun STAGE_ID ...] [--output FILE]` | 执行就绪阶段；重试和重跑须显式指定 |
| `experiments info GROUP_ID` | `--revision REV [--output FILE]` | 阶段派生状态、全部 attempt 与关联 Run |
| `experiments list` | `[--group-id ID] [--dataset-id ID] [--dataset-revision REV] [--status STATUS] [--output FILE]` | 按实验或数据查询实验组修订 |
| `experiments events GROUP_ID` | `--revision REV [--after-seq N] [--output FILE]` | 有序组织事件 |
| `experiments recover ATTEMPT_ID` | `--reason TEXT [--adopt-run] [--output FILE]` | 显式恢复开放 attempt；调用方先确认原工作已停止 |
| `runs` | `[--group-id ID] [--revision REV] [--attempt-id ID] [--dataset-id ID] [--dataset-revision REV] [--status STATUS] [--output FILE]` | Run 摘要及原始 organization / 全部 associations |
| `datasets publish-build SPEC` | `[--output FILE]` | SPEC 含 manifest、reader_ref 和发布选项；把固定构建结果回存长期目录 |
| `autobench list` | 无 | 列举当前 data_home 的 benchmark 定义 |
| `autobench register SPEC` | `[--alias LABEL ...] [--output FILE]` | 登记 BenchmarkDefinition，解析并固定数据 revision |
| `autobench resolve BENCHMARK_ID` | `--revision REV --candidate FILE ... [--purpose regression] [--output FILE]` | 调用已安装 resolver，返回原生 EvaluationSpec |

`--purpose` 的选择是 `development` / `regression` / `acceptance`。每个 `--candidate FILE` 文件都包含一个 `{"candidate_id": "...", "spec": CandidateSpec}` 对象，可重复提供多个；它不是纯 CandidateSpec 文件。CLI 当前没有独立的 repetitions 参数，若需要指定重复 seed，使用 Python `resolve_benchmark(..., repetitions=...)`。

`plugins` 列的是当前已启用注册表，不是所有已安装 integration 入口；发现安装入口用 Python `GymTS.available_integrations()`。`datasets register` 不会自动导入任意本地路径，`autobench register` 也不会自动推断领域 Task/Scorer。使用对应适配包的导入器，或先通过资源 API 发布字节。

例如：

```bash
gymts --store /tmp/gymts-ref plan examples/forecast_experiment.json
gymts --store /tmp/gymts-ref validate examples/counter_experiment.json
gymts --store /tmp/gymts-ref run examples/counter_experiment.json --output /tmp/counter-result.json
gymts --store /tmp/gymts-ref plugins
gymts --data-home /tmp/gymts-guide-catalog/data datasets list
gymts --data-home /tmp/gymts-guide-catalog/data datasets info local/guide-series --revision 1.0.0
```

最后两条依赖[使用指南](user-guide.md#62-从零登记并读取本地数据)的登记步骤。项目专用 CLI 如 `gymts-rl`、`gymts-timesigma`、`gymts-hf-datasets` 属于各适配包，参数以其 README 和 `--help` 为准。

### 1.2 输出和退出码

配置驱动命令将格式化 JSON 写到 stdout；`--output` 额外保存同一内容，并创建需要的父目录。结构化顶层错误写到 stderr。`inspect`、`plugins`、`datasets list`、`autobench list` 没有 `--output`，可用 shell 重定向。

| 退出码 | 当前含义 |
| --- | --- |
| `0` | 命令处理成功；不保证业务 Gate 通过，也不保证证据充分 |
| `1` | 返回对象顶层 `status` 为 `failed` 或 `cancelled` |
| `2` | 参数/配置读取或结构化服务错误；也包括 `validate` 返回 `valid=false` |

`argparse` 参数错误也返回 2，但帮助/参数错误是标准 CLI 文本，不保证 JSON。`evaluate/score` 返回 `status="completed"` 且 `verdict="fail"` 或 `"insufficient_evidence"` 时仍可能退出 0；验收脚本必须读取报告的 `status` 和 `verdict`。`run.status="succeeded"` 仅表示实验执行成功，指标是否达标由 AutoBenchTS 报告表达。

## 2. 顶层 Python SDK

```python
from gymts import GymTS, EnvironmentTS, AutoBenchTS, GymTSError, __version__

with GymTS(root="/tmp/gymts-runs", integrations=(),
           data_home="/tmp/gymts-data", cache_home="/tmp/gymts-cache") as gym:
    ...
```

### 2.1 GymTS

```text
GymTS(root=".gymts", *, register_builtins=True, integrations=(),
      data_home=None, cache_home=None)
```

`root` 接受路径字符串或 Path。默认注册可重复运行的参考插件，不包含独立项目实现。`integrations` 只能是名称序列；注册失败回滚其注册表变更。`register_builtins=False` 用于完全自定义装配，用户需自行注册满足任务的组件。

| 方法/属性 | 用途 |
| --- | --- |
| `GymTS.available_integrations()` | 静态方法；只发现已安装入口元数据，不导入集成实现 |
| `gym.enable_integration(name)` | 显式注册受信任集成；重复启用相同名称幂等 |
| `gym.enabled_integrations` | 已启用名称 tuple |
| `gym.plan(spec)` | 转发 EnvironmentTS.plan |
| `gym.validate(spec)` | 转发 EnvironmentTS.validate |
| `gym.run(spec)` | 转发 EnvironmentTS.run |
| `gym.environment_ts` | EnvironmentTS 服务 |
| `gym.autobench` / `gym.autobench_ts` | 同一个 AutoBenchTS 实例 |
| `gym.records` | 本地 ExperimentRecords 服务 |
| `gym.artifacts` | 本地 ArtifactStore |
| `gym.registries` / `gym.schemas` | 公共注册与 schema 服务，供受信任接入方使用 |
| `gym.close()` | 关闭记录库；支持上下文管理器 |

### 2.2 EnvironmentTS

| 方法 | 输入 | 输出/失败语义 |
| --- | --- | --- |
| `plan(spec)` | 内联 ExperimentSpec | AssemblyPlan；无效声明抛 GymTSError |
| `validate(spec)` | 内联 ExperimentSpec | `{valid, resolved_spec_ref, resolved_spec, issues}`；声明错误收进 issues |
| `run(spec)` | ExperimentSpec | RunResult；规划错误可抛异常，建立后的运行错误通常封存为失败 Run |
| `datasets` | DatasetCatalog 属性 | 长期源数据服务，见第 5 节 |

AssemblyPlan 的核心字段为 `protocol_version="gymts.assembly-plan/1"`、`resolved_spec`、`manifests`、`descriptions`、`variables`、`operations`、`read_scope`、`resource_checks="deferred_to_open"`。`validate` 不写 CAS，`resolved_spec_ref` 保持 null。历史 `scene_ref` 可供执行展开；离线 plan/validate 要求使用内联场景，不能借规划读取制品。

RunResult 保存 `run_id`、`status`、`completion`、开始/结束时间、`resolved_spec_ref`、TaskResult 集合的 `result_ref`、不可变执行 `trace_ref`、`summary`、`artifact_refs` 与 `errors`。结果内容通过 `gym.artifacts.read_json(result["result_ref"])` 读取。

### 2.3 AutoBenchTS

```python
report = gym.autobench.evaluate(evaluation_spec)
new_report = gym.autobench.score(score_spec)
```

`evaluate` 固定全部预期案例 × 候选 × repetitions，再创建 Runs。`score` 固定旧 Run 清单和依据，禁止重新运行 Candidate。配置校验失败可直接抛 GymTSError；Scorer 失败可形成 `status="failed"` 报告；计划/报告提交失败抛出包含已提交引用的错误。

EvaluationReport 包含 `evaluation_id`、`status`、`verdict`、`plan_ref`、`run_manifest_ref`、`metrics`、比较/Gate、覆盖汇总、`evidence_refs`、`errors` 等。保存完整报告及其引用的 CAS，而非只存一个指标值。单次报告要求同构任务/结果/Outcome 合同；异构场景分别出报告，当前没有通用异构 suite 执行入口。

Benchmark 资源方法：

```text
gym.autobench.register_benchmark(definition, *, aliases=())
gym.autobench.list_benchmarks()
gym.autobench.load_benchmark(benchmark_id, *, revision)
gym.autobench.resolve_benchmark(benchmark_id, *, revision, candidates,
                                purpose="regression", repetitions=None)
```

`resolve_benchmark` 会物化所选固定源清单、用途和 BenchmarkDefinition 的 CAS 证据，再校验派生 EvaluationSpec；它不是无 I/O 的 `gym.plan`。resolver 得到独立的评价资源服务，不得到 Runner/Candidate 执行入口。

### 2.4 实验组织

`gym.experiments` 为现有执行与数据服务提供组织入口：

```python
org.register(definition)  # 返回规范化 group 定义，含固定 revision
org.get(group_id, revision=revision)
org.execute(group_id, revision=revision, retry_failed=False, rerun=())
org.inspect(group_id, revision=revision)
org.events(group_id, revision=revision, after_seq=0)
org.query(group_id=None, dataset_id=None, dataset_revision=None, status=None)
org.recover(attempt_id, reason=reason, adopt_run=False)
org.register_executor(component_ref, executor)  # executor(spec, gym) -> dict
```

这里 `org = gym.experiments`。协议为 `gymts.experiment-group/1`、`gymts.stage-request/1`、`gymts.stage-attempt/1`、`gymts.experiment-event/1`。默认不重试 failed/cancelled/interrupted；retry_failed 重试前两者，rerun 显式重跑。恢复发生在阶段边界，只有 gymts.run 可采纳唯一已封存 Run。输入、JSON Pointer 和完整本地示例见[实验组织指南](experiment-organization.md)。

## 3. 配置与消息索引

所有公共消息使用可序列化的 dict/list/scalar，不接受 NumPy 对象、NaN 或 Infinity 冒充 JSON。版本必须是已注册的精确版本，不能用 `latest/main/master` 代替固定组件。完整必填项及默认值以 schema/正式规范为准。

| 消息 | `protocol_version` / schema | 完整示例/说明 |
| --- | --- | --- |
| 单次实验 | `gymts.experiment/1` | [forecast_experiment.json](../examples/forecast_experiment.json)、[counter_experiment.json](../examples/counter_experiment.json) |
| 环境配置 | `gymts.environment/1` | ExperimentSpec.scene.environment；来源/映射/选项为具体适配器 schema |
| 新实验评价 | `gymts.evaluation/1` | [forecast_evaluation.json](../examples/forecast_evaluation.json) |
| 旧结果评分 | `gymts.score/1` | [forecast_score_template.json](../examples/forecast_score_template.json)，需填真实引用 |
| 依据视图 | `gymts.view/1` | 固定 source_refs、selection、用途与截止 |
| Outcome | `gymts.outcome/1` | [使用指南的晚到标签工作流](user-guide.md#52-一个可直接执行的晚到标签示例) |
| 源资源清单 | `gymts.source-dataset/1` | 第 5 节；不等于训练导出 DatasetManifest |
| 基准配方 | `gymts.autobench.benchmark/1` | 固定 datasets、resolver_ref 和 params |
| 训练构建 | `gymts.dataset-build/1` | 第 6 节及 [RL 指南](rl-integration.md) |
| 训练导出清单 | `gymts.dataset/1` | DatasetBuilder 的固定结果、分片和血缘 |

标识之间不要互换：`run_id` 是实际执行，`evaluation_id` 是一次评价；`unit_id` 是固定评价单元，`evaluation_case_id` 是测试条件，Task 内 `case_id` 是任务会话案例。`candidate_id` 是比较中的稳定方法身份，repetition seed 经执行上下文传递，不应通过改候选参数来伪装成不同方法。

### 3.1 RecordingSpec

| 字段 | 接受值/默认 | 规则 |
| --- | --- | --- |
| `store_ref` | `local` 或 `local://records/default` | 由当前本地 EnvironmentTS 认可；不是目标目录路径 |
| `inputs`、`outputs` | `full` / `reference` | reference 必须能解析到固定快照 |
| `artifacts` | `reference` | 制品使用固定引用 |
| `model_calls` | `none` / `io` / `native_rollout`；默认 none | 声明期望采集，不代替实际 completeness |
| `on_capture_failure` | `fail_run` / `mark_incomplete`；默认 fail_run | 仅用于可选内部调用采集 |
| `redaction_policy_ref` | ArtifactRef/null；默认 null | 适配器实施真实脱敏并记录变换 |
| `extra_event_kinds` | 已登记的 kind 列表；默认空 | 扩展不能替代核心事件 |

无“关闭全部轨迹”的模式。核心观测、原始输出、TaskResult、动作和回执等提交失败时停止后续调用；不能用 `mark_incomplete` 继续执行丢失核心证据的 Run。

## 4. 轨迹与制品 API

### 4.1 ExperimentRecords

| 方法 | 返回/用途 |
| --- | --- |
| `get_run(run_id)` | RunRecord，含 metadata、session、preparation、result、resolved_spec_ref、result_ref、events、event_refs、快照引用 |
| `read_events(run_id, query=None)` | `{events, next_after_seq}`，按持久 seq 分页 |
| `attach_outcomes(run_id, outcomes)` | 追加独立 OutcomeRecord 列表，返回 OutcomeSnapshotRef |
| `read_outcomes(query=None)` | 固定查询下的已提交 OutcomeRecord 列表 |
| `snapshot(run_ids, query=None)` | RecordSnapshot 包络，含 snapshot_ref、captured_at、runs、outcome_refs |
| `get_snapshot(ref)` | 验证并读取正式 RecordSnapshot |
| `list_outcome_refs(run_id)` | 当前可用 OutcomeRef 列表；需要冻结时使用 snapshot |
| `list_runs(*, group_id=None, revision=None, attempt_id=None, status=None, dataset_id=None, dataset_revision=None)` | Run 摘要查询，保留原 organization 和全部 associations |

`read_events` 的 query 支持 `after_seq`（默认 0）、`limit`（1..1000，默认 100）、`kinds`（null=全部，[]=不选）、`snapshot_ref`。有下一页时把 `next_after_seq` 传入；为 null 时结束。

`read_outcomes` query 支持 `run_ids`、`outcomes_as_of`（兼容别名 `as_of`，二选一）、`outcome_refs`、`purpose`、`snapshot_ref`。截止时间与显式修订列表互斥；使用 snapshot_ref 时不能另指定动态截止或修订。用途不授权时报错，不静默泄露。

`snapshot` 的 query 只支持 `through_seq`（run_id→seq）、`outcomes_as_of`、`outcome_refs`，**没有 purpose 字段**。默认在创建时固定当前已提交边界和可用 Outcome；指定前缀时不暴露更晚才封存的最终 RunResult。

`gym.experiments.events(group_id, revision=revision, after_seq=0)` 读取有序组织事件。评分已有 Run 只追加关联，不改变原归属或封存证据。

`begin_run`、`append`、`end_run` 是记录后端/Runner 集成协议。普通用户通过 `run/evaluate/score` 产生执行记录，不为现有封存 Run 手工补造执行事件。

### 4.2 ArtifactStore

```python
reference = gym.artifacts.save_json({"example": 1}, "gymts.json/1")
value = gym.artifacts.read_json(reference)
path = gym.artifacts.resolve(reference)
binary_ref = gym.artifacts.save_artifact(b"example", {
    "media_type": "application/octet-stream", "schema_ref": None})
```

`save_json(value, schema_ref)` 需要非空 schema_ref，规范化 JSON 后发布。`save_artifact(content, metadata)` 只接受 bytes；metadata 是有限 JSON。它们保存身份与字节，领域消息仍需相应 schema/合同校验。`resolve` 校验引用及实际内容后返回本地 Path，不接受任意 file URL 或未导入外部路径。无 schema 的原始字节通过 resolve/read_bytes 读取，不使用 `read_json`。

`read_view(DataViewRef)` 解析当前实现支持的固定选择视图，selector 支持 `all`、`json_pointer`、`rows`；不是任意 SQL/JSONPath 查询服务。此 JSON view reader 要求 `as_of=null`，时间筛选须先取得并保存固定源，或由另一个明确支持的视图适配器实现。Source 引用的显式授权只对精确引用生效，不递归授予所有嵌套制品或整个磁盘目录。

### 4.3 TraceCollector（适配器侧）

`gymts.contracts.protocols.TraceCollector` 是公共结构接口。`recording.model_calls` 非 none 且 Candidate 声明支持时，Runner 经 `Candidate.prepare(context, training)` 的 `context["traces"]` 注入采集器，适配器在 infer 内使用；none 模式传入 None。它不是 `GymTS` 顶层的全局 recorder。下面以局部变量 `trace` 指代该采集器：

```text
trace.context                      -> 当前 run_id/input_id/output_id
trace.record_model_call(value)      -> 固定 ModelCallArtifact 引用
trace.record_tool_call(value)       -> 固定 ToolCallArtifact 引用
```

由 Candidate 适配器在真实 infer 内调用；不要在普通用户脚本中伪造活跃绑定。内部模型尝试保存 call_id/attempt_id/parent_call_id、组件身份、时间、状态、请求/响应、实际参数与 capture；ToolCall 保存真实参数/结果/错误及必要的环境关联。`unknown` 表示未确认状态，不等于失败或成功。`native_rollout` 还要求原生 tokens、native_inputs、tokenizer/template 和策略修订；概率另声明 model/sampling 分布与 captured/recomputed 来源。

已有完整实现见 [LibraryTS](../adapters/libraryts/README.md)、[ChatTS](../adapters/chatts/README.md)和 [RL](../adapters/rl/README.md)。字段规范见[正式规范 §10.3](feishu/GymTS接口规范/GymTS接口规范.md#103-modelcallartifact-与-toolcallartifact)。

## 5. 数据与 Benchmark 资源 API

### 5.1 DatasetCatalog

```python
catalog = gym.environment_ts.datasets
asset_ref = catalog.publish_asset(content_bytes, media_type="application/jsonl")
fixed = catalog.register_dataset(manifest, aliases=("1.0.0",))
summaries = catalog.list_datasets()
dataset = catalog.load_dataset(dataset_id, revision="1.0.0",
                               config="default", split="test", purpose="runtime")
```

`publish_asset` 返回 DatasetAssetRef，字段恰为 `{uri, sha256, size_bytes, media_type}`。`register_dataset` 根据规范化内容固定 revision，校验用途与全部资产；源清单的 revision 输入可为 null，由登记服务计算。发布标签不能重新指向另一个修订。`load_dataset` 支持用途 runtime/evaluation/training/prepare/dataset_build，并核对已固定策略。

SourceDatasetRevision 字段：

```text
protocol_version, dataset_id, config, revision, schema_ref, reader_ref,
features, splits, usage_policy, source_files, importer_ref,
inputs, series, targets, quality_report_ref, card_ref
```

`splits[name]` 为 `{row_count, split_origin, input_indices, target_indices}`，索引指向相应公开/私有资产列表。reader/importer 是固定 ComponentRef；原始格式语义由适配器定义。`usage_policy` 为 `{allowed_uses, training_allowed}`，evaluation-only 不会因为读取公开输入或更换导出器而取得训练授权。

### 5.2 DatasetHandle

| 方法/属性 | 返回 |
| --- | --- |
| `.info` | 公开 ID/config/revision/split/行数/schema/features/用途与选择 |
| `.features` | 特征描述副本 |
| `len(ds)`、`ds[index]`、`ds[start:end]`、`iter(ds)` | 公开行或公开子视图；索引支持负数，切片返回 handle |
| `.select(indices)` | 保留源行身份的子视图，拒绝重复和越界索引 |
| `.filter(predicate)` | Python 谓词筛选后的子视图 |
| `.iter_batches(batch_size=100)` | 每批公开行 list |
| `.sample_ids()` | 含 sample_id 合同的数据对应的 ID 列表 |
| `.read_series()` | manifest 中独立 series 资产的公开行 |
| `.to_hf()` | `datasets.Dataset.from_list(...)`，需另装 HF datasets |

读取时校验行数/schema/样本 ID。当前第一次读取物化所选 split 的 shard，不是随机访问服务端、懒加载流式查询或自动分片训练器。公开 handle 没有 `read_targets`。

AutoBenchTS 只向选中的 benchmark resolver 提供 `resources.datasets.load_dataset(..., purpose="evaluation")` 返回的独立评价视图及其 `read_targets()`；允许访问的数据固定在 BenchmarkDefinition 中。这是可信插件服务授权，不是恶意 Python 插件的隔离沙箱。

### 5.3 BenchmarkDefinition

字段为 `{protocol_version, benchmark_id, revision, resolver_ref, datasets, params, card_ref}`。每个数据引用是 `{dataset_id, config, revision, split}`。resolver 将其转为原生 EvaluationSpec，不另写执行器；它不能改用户要求的 candidates/purpose/repetitions，也不能伪造框架的 provenance。

定义中数据发布标签在登记时解析为精确内容 revision；执行解析把源清单、用途策略和基准定义固定到 CAS，传播到 Run metadata 和报告。修改数据、提示、筛选、评分规则或 resolver 版本应发布新的定义修订。

### 5.4 四类来源与 dataset v2

以下为入口速查模板，变量由调用方提供；可直接运行的例子见[使用指南](user-guide.md#65-四类来源实际快照与回流)。核心公共接口已实现，并通过固定 F1 的四类真实来源、可移植读取和零模型重评验收。

```python
catalog = gym.environment_ts.datasets
source = catalog.register_source(definition, aliases=("1.0.0",))
source = catalog.load_source(source_id, revision=revision, config="default")
sources = catalog.list_sources()
manifest = catalog.load_manifest(dataset_id, revision=revision, config="default")
manifest = catalog.register_snapshot(
    rows, dataset_id=dataset_id, source_ref=source_ref, split="test", config="default",
    schema_ref="gymts.json/1", targets=None, parents=(), usage_policy=None,
    features=None, split_origin="explicit", attachments=(), capture=None, aliases=(), kind=None,
)
bound = catalog.bind_source(spec, source_id, revision=revision, config="default")
manifest = catalog.capture_run(
    run_id, source_id=source_id, revision=revision, dataset_id=dataset_id,
    config="default", source_config="default", split="recorded", event_kinds=None,
    usage_policy=None, aliases=(),
)
result = gym.run_data(spec, source_id=source_id, revision=revision, dataset_id=dataset_id,
                      source_config="default", config="default", split="recorded")
```

`definition` 使用 `gymts.data-source/1`；`source_ref` 为 `{source_id,config,revision}`，`parents` 每项为 `{dataset_id,config,revision,split}`。标签在登记快照时解析成固定内容摘要。来源类别为 static/synthetic/simulation/live_testbed；合成有 recipe，可 seeded（须 seed）或 recorded。声明 seed 与实际 session seed 分开记录。

`register_snapshot` 返回 `gymts.source-dataset/2`，复用 v1 公开/私有 shard 字段并增加 kind/origin/lineage/attachments。`load_manifest` 读取 v1/v2 完整清单；`load_dataset` 的公开 handle 还提供 `read_capture()`、`read_asset(asset_ref)`、`resolve_payload(value)`。采集元数据协议为 `gymts.data-capture/1`，环境事件行 schema 为 `gymts.data-capture-row/1`。

`bind_source` 接收完整 ExperimentSpec 并返回副本，核对既有 Environment provider/config，将固定来源、父数据及共同用途写入 provenance；不改原 spec。`run_data` 返回 `{"run": RunResult, "dataset": manifest}`，保留真实 Task/Candidate。`capture_run` 接受 sealed Run，默认仅采集环境 session/request/observation/operation/receipt/feedback，保留失败/部分结果；不包含模型对话和私有 Outcome。实际 JSON/二进制附件进入 data_home，读取快照不依赖原 Run CAS。

这些数据服务不另建执行器或评分器；benchmark `/1` 可固定 v1/v2 dataset，评价仍走原 AutoBenchTS。变更理由及旧合同兼容见 [ADR 0001](adr/0001-core-data-source-catalog.md)。

### 5.5 构建数据显式回库

```python
catalog.publish_build(build, reader_ref=reader_ref, dataset_id=None,
                      config="default", usage_policy=None, parents=(), aliases=())
```

将原 `gymts.dataset/1` Manifest、带 manifest_ref 的返回对象或其 ArtifactRef 发布为长期 `gymts.source-dataset/1`；保留原 shard 字节和私有可移植构建证据，不虚构 source。reader 由适配器提供，默认训练用途只可收窄，不自动增加 runtime/evaluation。详见[回库流程](experiment-organization.md#把构建数据回存长期目录)。

## 6. 训练数据构建扩展

```python
from gymts.training import build_dataset, DatasetBuilderRegistry

# spec 必须是有效且已固定的 DatasetBuildSpec；由相应领域适配包提供。
# manifest = build_dataset(spec, gym.records, gym.artifacts)
```

实际签名为 `build_dataset(spec, records, artifacts, *, builders=None)`。默认通过已安装的 `gymts.dataset_builders` entry point 按固定 builder_ref 延迟发现；可传自有 DatasetBuilderRegistry 并显式注册 provider。

provider 声明 `builder_ref`、`target_formats`、`output_schema_refs` 和 `build(spec, records, artifacts)`。输入固定 RecordSnapshot；输出是正式 `gymts.dataset/1` Manifest，包含分片、计数、tokenization、奖励与血缘引用。框架校验合同与用途，领域 provider 负责选择、配对、行布局和 masks，训练器另由适配包复用。不存在 `gym.train()` 通用训练 API。

现成 RL rollout/TRL 训练的可执行准备、采样、数据构建和 checkpoint 评价命令见[RL README](../adapters/rl/README.md)。不要把 evaluation-only 源 Run 交给另一 provider 规避训练禁止策略。

## 7. 结构化错误与重试

```python
from gymts import GymTSError

try:
    # gym.plan(spec)、资源读取或其他服务调用
    pass
except GymTSError as error:
    print(error.code, error.stage, error.info)
```

`GymTSError.info` 字段为 `code, stage, method, message, run_id, links, retryable, side_effect`。`side_effect` 为 `none` / `possible` / `confirmed`。不能仅因网络错误或 `retryable` 标志，就重新发送可能已经执行的设备动作。保存同一逻辑操作和实际尝试身份，依据回执或后端去重能力决定恢复。

常见 code 有 `invalid_config`、`schema_mismatch`、`unsupported_capability`、`permission_denied`、`conflict`、`recording_failure`、`capture_incomplete`；存储另可能返回 `artifact_integrity`、`persistence_failed`、`invalid_query` 等。用户应按结构字段处理，不依赖英文 message 字符串。Runner/AutoBenchTS 返回的失败结果也需要读取其中 errors，不能只捕获异常。

## 8. 版本、信任与接口稳定性

发行版本、消息 schema 版本、项目组件版本和数据内容 revision 是不同身份。历史 F1 核心 0.5.1 对应规范 1.3.0；本轮 0.6.0 / 1.4.0 工作树新增四个组织协议，保留既有运行消息与数据资源身份。这不等于完整 [v2 Runtime 合同](pluggability-contract-v2.md)已实施。

普通用户入口为本手册列出的 SDK/CLI、`gymts.contracts`、公开 Protocol、Registry、schema 与 training 扩展。项目内部辅助函数不保证公共兼容；新适配必须单向依赖公共 SDK，不导入 Runner 私有状态。详细扩展与兼容迁移见[开发者指南](adapter-development.md)。

当前执行和存储是同步本地实现。跨租户隔离、恶意代码沙箱、远程 Hub、完整分布式 Runtime、强制打断阻塞调用和通用自主 Agent 工具执行服务不属于已实现能力。应用程序应依据当前适配器的真实 capabilities 安排实验，不从项目名称推断支持。
