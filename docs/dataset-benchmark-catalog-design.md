# EnvironmentTS 数据资源与 AutoBenchTS 基准管理

状态：GymTS 0.5.0 已实现本地资源目录，2026-10-20。正式合同见[接口规范 1.2.0 §19](feishu/GymTS接口规范/GymTS接口规范.md)，验收证据及剩余差距见[本轮交付记录](framework-delivery-2026-10-20.md)。修改前提案保存在[历史快照](archive/2026-10-20-before-api-v1.2/dataset-benchmark-catalog-design.md)。

GymTS 保留 **EnvironmentTS 与 AutoBenchTS 两个主模块**。数据目录服务 EnvironmentTS，benchmark 定义的登记、维护和解析服务 AutoBenchTS。解析得到现有 EvaluationSpec，执行仍用 `evaluate`，封存输出重评仍用 `score`，交付原生 EvaluationReport。没有独立的 benchmark 执行器或另一套报告体系。

此分工与[总体设计](feishu/GymTS总体设计/GymTS总体设计.md)、[运行机制](feishu/GymTS%20运行机制/GymTS%20运行机制.md)和[项目网页](https://netman.aiops.org/contacts/projects/)一致。网页将 benchmark 构建维护、复现、验收、回归和安全评价归 AutoBenchTS。具体安全场景和系统连接器仍需要适配，存在入口不代表所有用途均已验收。

## 1. 存什么、归谁管理

| 对象 | 职责 | 不可变身份 |
| --- | --- | --- |
| DatasetAssetRef | 原始字节、公开 Parquet、私有参考、质量报告和说明卡 | SHA-256、字节数、媒体类型 |
| SourceDatasetRevision | EnvironmentTS 数据资源：schema、reader、分区、用途、输入/参考和导入血缘 | dataset_id + config + 内容 revision |
| BenchmarkDefinition | AutoBenchTS 可复用评价配方：固定数据、resolver 和规则参数 | benchmark_id + 内容 revision |
| EvaluationSpec / Plan | 本次候选、案例、重复 seed、比较与 Gate；运行前固定全部预期单元 | 现有 evaluation_id / unit_id / plan_ref |
| Run / RecordSnapshot | 实际执行、采集和封存证据 | 现有 Run 与快照身份 |
| EvaluationReport | 独立评分、覆盖、比较和 Gate | 现有原生报告引用 |

源数据协议是 `gymts.source-dataset/1`。已有 `gymts.dataset/1` 继续用于轨迹的训练导出，两者不混用。修改源内容、分区、用途、reader 或导入表示产生新的源修订；修改已声明的评分/提示/筛选规则产生新的基准修订。固定版本的 resolver 持有领域 Task/Binding/Scorer 配方，未知规则必须拒绝，不能忽略。

## 2. 放在哪里

| 内容 | 当前位置或配置 | 发布边界 |
| --- | --- | --- |
| 通用资源合同、store、reader 服务 | `gymts/contracts/resources.py`、`storage/resources.py`、`environment_ts/datasets.py` | 核心安装包，不含题库 |
| 通用 benchmark 资源解析 | `gymts/autobench_ts/catalog.py` | 核心安装包，不按项目名分支 |
| 本批题库导入器、卡片、Task、Candidate、Scorer、resolver | `adapters/bench_tsqa/`，发行包 `gymts-bench-tsqa` | 独立安装、显式启用 |
| 原始与规范化资产、数据和基准清单 | `GymTS(data_home=...)` 或 `GYMTS_DATA_HOME`；默认 XDG data/gymts | 长期资源，独立于某个 Run |
| 校验后的本地资产副本 | `GymTS(cache_home=...)` 或 `GYMTS_CACHE_HOME`；默认 XDG cache/gymts | 可删除重建的缓存 |
| 活动 SQLite、Run CAS、报告 | 显式 `GymTS(root=...)` | 本机 POSIX 文件系统 |
| 封存证据归档 | 部署方选择的持久归档目录 | 本轮放仓库忽略的 `output/`，不入核心 wheel |

本轮五份实际资源位于 `/zzr/zmx/GymTS/Jurmean-GymTS/output/resources-20261020`。该位置是本次部署配置，核心没有硬编码它；源码 wheel/sdist 不包含上传题库。导入后日常读取不依赖 Codex attachments 路径。`/zzr` 为 S3FS，活动 SQLite、缓存、构建与测试放 `/tmp`，完成后归档。

```text
<data_home>/
  objects/sha256/<前两位>/<完整hash>
  datasets/<namespace>/<name>/<config>/
    revisions/<hash>/manifest.json
    aliases/1.0.0.json
  autobench/benchmarks/<namespace>/<name>/
    revisions/<hash>/manifest.json
    aliases/1.0.0.json

<cache_home>/objects/sha256/...
<run_root>/records.sqlite3
<run_root>/artifacts/...
```

资源字节按 hash 去重，读取校验摘要和尺寸；manifest 的 revision 是排除 revision 字段后 canonical JSON 的 SHA-256。显式 release alias 只能绑定一次，不支持 latest/main/master。当前资源发布的并发保障限于同一主机、提供 POSIX 锁的文件系统；没有跨主机对象存储事务、远程下载或多租户权限服务。

## 3. 数据格式与公开/私有边界

通用 AssetRef 严格包含 `{uri,sha256,size_bytes,media_type}`，内置 URI 为 `gymts-data://sha256/<hash>`，与 Run CAS 的 ArtifactRef 分开。具体对象进入当前实验 CAS 后，才作为执行证据引用。

SourceDatasetRevision 的字段为 `{protocol_version,dataset_id,config,revision,schema_ref,reader_ref,features,splits,usage_policy,source_files,importer_ref,inputs,series,targets,quality_report_ref,card_ref}`。split 声明 `{row_count,split_origin,input_indices,target_indices}`；source_files 保存原文件名与资产引用。reader/importer 使用固定 ComponentRef。

本批导入器保存原样 JSONL、公开 Parquet、私有参考 Parquet、JSON 质量报告及 Markdown 卡片。公开行保留 sample_id、dataset_id、source_row、task_kind、完整 question_original、可逆 attachment_projection、公开 choices 与有序 ragged Float64 series。仅将字面 `<ts><ts/>` 换成中立序列引用；不缩写、重写题目，不舍入、截断数值。原始字节和实际 Parquet codec 往返校验均保留。当前本批 series 内联在公开行中，通用 manifest 的独立 series 资产列表为空；没有声称已实现跨数据集序列表去重。

`answer`、`attributes`、未审核原始 metadata 和完整原文件保存在私有资产。公开 DatasetHandle 的 info、索引、批读取及 HF 转换不提供私有资产引用；reader 只得到所选公开 shard 的读取服务。AutoBenchTS resolver 单独取得定义内数据的 EvaluationDatasets 服务和私有参考。这是可信插件的服务边界，不是对恶意 Python 代码的系统沙箱。

用途策略固定为 `allowed_uses=['evaluation']`、`training_allowed=false`。公开 runtime 投影不改变原用途。数据读取、training_collection Run 和通用训练构建入口均拒绝将这些来源用于 training、prepare 或 dataset_build；改用另一个 exporter 不构成授权。

## 4. 五份已登记资源

全部源行为 `test / user_declared_evaluation`，保留重复、源顺序及源行身份，共 **19,354** 行。来源及许可证未提供，使用 `local/` 命名空间，不声称官方发行。

| dataset / benchmark ID | 行数 | 当前规则可判定参考 | 未决参考 |
| --- | ---: | ---: | ---: |
| local/bedtime | 394 | 394 | 0 |
| local/dataset-a-rlvr | 411 | 0 | 411 |
| local/mcq2 | 100 | 100 | 0 |
| local/timemqa-full | 17,703 | 16,983 | 720 |
| local/tsexam-mcq | 746 | 746 | 0 |

`mcq2` 参考中的 `1.` 是题号，不作为选项编号。timemqa 的 720 个未决项包括 683 个公开选项/格式未解析和 37 个参考不在解析选项内的样本，是 parser 复核标记，不等于确认标注错误。RLVR 的结构化参考等待原 verifier 或明确批准的任务规则；文件名不授权训练，也不自动提供 reward。

私有 Scorer 使用显式的本地 `tsqa.single-answer/1` 规则，不能宣称复刻未提供的官方评分脚本。接受唯一公开答案 token/text 或一个独立的 answer 标签；多答案、标签外推理不静默容错。所有源行保持 eligible；参考未决为 missing，输出无效为 invalid，格式有效率单独报告，不删题、不缩分母、不补零答案。

本轮先对 `tsexam-mcq` 全量 746 行跑通原生评价与同 Run 重评分，其他四份已登记、可读取，未声称全部跑过正式模型全量评测。第一公开选项基线的 332/746 准确率用于检查接线和覆盖，不表示训练带来能力提升。

## 5. 怎样调用

从主仓库安装：

```bash
python -m pip install . './adapters/bench_tsqa[runtime]'
```

一次性导入：

```bash
gymts-bench-tsqa import \
  --attachments /path/to/five-jsonl-files \
  --data-home /path/to/persistent/resources --root /tmp/gymts-import
```

公开读取和正式评价均已实现：

```python
from gymts import GymTS
from gymts_bench_tsqa.benchmark import first_choice_candidate

with GymTS('/tmp/gymts-runs', data_home='/path/to/persistent/resources',
           cache_home='/tmp/gymts-cache', integrations=('bench-tsqa',)) as gym:
    ds = gym.environment_ts.datasets.load_dataset(
        'local/tsexam-mcq', revision='1.0.0', config='default', split='test')
    print(ds.info, len(ds), ds[0]['question_original'])
    view = ds.select([0, 1, 2])
    for batch in view.iter_batches(batch_size=2):
        print(len(batch))
    spec = gym.autobench.resolve_benchmark(
        'local/tsexam-mcq', revision='1.0.0',
        candidates=[first_choice_candidate()], purpose='regression',
        repetitions={'count': 1, 'seeds': [0]})
    report = gym.autobench.evaluate(spec)
```

DatasetHandle 还支持 `filter`、`sample_ids`、`read_series` 和安装 HF Datasets 后的 `to_hf`。当前是本地已物化读取，不等价于完整 HF Hub：没有远程仓库同步、流式大数据读取或分布式查询索引。上例子集仅用于浏览，正式 full resolver 不将它替代全量 benchmark。

CLI 对应 `gymts --store ... --data-home ... datasets list/info/register` 及 `autobench list/register/resolve`。`autobench resolve --candidate` 接收含 candidate_id/spec 的 JSON 文件；输出原生 EvaluationSpec，再交 `gymts evaluate`。现有 `gymts score` 对封存 Run 和固定参考重评分。完整配置、HTTP 模型边界和重复导入方式见[适配包指南](../adapters/bench_tsqa/README.md)。

## 6. 血缘、扩展与剩余设计

解析时将固定源 manifest、用途策略和 BenchmarkDefinition 提交到本次 CAS；provenance 传播到 EvaluationSpec、每个 Run 的配置/metadata 和报告证据，不把私有参考授予 Candidate。候选权重/算法配置身份保持固定，seed 通过执行上下文传递，不通过改变候选身份表达 repetitions。

Registry 的纯 describe/compatibility 提供离线 `plan/validate`。不读资源、不创建环境、不加载模型；实际 open/prepare 发生在 Run 建立后，资源损坏或原生接口失败保留失败 Run。新 reader、Task、Candidate、Scorer 和 resolver 走独立适配包，无需在核心添加题库名称分支。

RL checkpoint → 新进程 Candidate → 原生 AutoBenchTS.evaluate 重复 seed → 独立 score 也已跑通，具体范围见[RL 指南](rl-integration.md)及[实际报告](reports/rl-checkpoint-loop-2026-10-20.json)。训练仍复用 TRL；这五份测评附件未用于训练。

尚需未来项目验证或扩展的内容包括：结构化 RLVR verifier、更多 benchmark 的正式评分/模型验收、人工审核与资产发布流程、异构 suite 报告导航、远程资源同步、真正 streaming、多进程 Runtime/强制超时，以及现场安全/控制测试。它们不通过目录便利 API 另写执行、聚合或 Gate 逻辑。完整 v2 Runtime 合同仍为草案。
