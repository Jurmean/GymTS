# EnvironmentTS 数据资源与 AutoBenchTS 基准管理

状态：当前 GymTS **0.6.0 / 接口 1.4.0**，F2.1 技术验收已完成。主线是**存储数据、接入数据、组织实验、记录实验**。实验组、阶段记录与回库见[实验组织指南](experiment-organization.md)，当前范围和固定身份见[验收报告](reports/experiment-organization-2026-10-21.json)。下文 0.5.1 / 1.3.0 的四类数据层 F1 验收、0.5.0 / 1.2.0 的资源目录与附件记录均保留原历史身份。数据层变更理由见 [ADR 0001](adr/0001-core-data-source-catalog.md)，当前字段见[接口规范](feishu/GymTS接口规范/GymTS接口规范.md)，0.5.0 验收见[交付记录](framework-delivery-2026-10-20.md)，修改前提案见[历史快照](archive/2026-10-20-before-api-v1.2/dataset-benchmark-catalog-design.md)。

GymTS 保留 **EnvironmentTS 与 AutoBenchTS 两个主模块**。数据目录服务 EnvironmentTS，benchmark 定义的登记、维护和解析服务 AutoBenchTS。解析得到现有 EvaluationSpec，执行仍用 `evaluate`，封存输出重评仍用 `score`，交付原生 EvaluationReport。没有独立的 benchmark 执行器或另一套报告体系。

此分工与[总体设计](feishu/GymTS总体设计/GymTS总体设计.md)、[运行机制](feishu/GymTS%20运行机制/GymTS%20运行机制.md)和[项目网页](https://netman.aiops.org/contacts/projects/)一致。网页将 benchmark 构建维护、复现、验收、回归和安全评价归 AutoBenchTS。具体安全场景和系统连接器仍需要适配，存在入口不代表所有用途均已验收。

## F1 修正：四类数据的组织属于核心

四类来源能执行，不等于四类数据都已统一组织。历史 0.5.0 基线提供通用静态资源目录和四类 Environment 接口；该轮新五项目中只有 Data-Juicer 的派生数据实际进入目录，其余四项主要使用各自 prepare manifest 与 Run CAS，五项也没有登记可复用 BenchmarkDefinition。这是数据层交付的缺口，不能只增加项目适配器后便称已统一。

F1 将来源目录、数据组织、存储、版本和来源→数据→Run→回流关系明确纳入核心，具体 provider、格式和领域语义继续外置：

| 核心来源类别 | 核心统一管理 | 外部 provider 仍负责 |
| --- | --- | --- |
| `static` | 固定来源、dataset 修订、split、资产、用途和父资源 | 文件/HF 读取、列解释与领域公开/私有投射 |
| `synthetic` | 生成配方、seed/重现方式、实际生成快照与来源关联 | 原生成函数及项目参数 |
| `simulation` | 仿真定义、episode/采集范围、实际观测与动作证据 | 原生 reset/step/close、状态 codec |
| `live_testbed` | 连接定义、实际采集窗口、来源与数据快照身份 | 外部 SDK、查询协议与指标解释 |

新增 `gymts.data-source/1` 表达可复用来源，新增 `gymts.source-dataset/2` 表达实际数据修订。二者分开：同一来源可产生多份数据，连接名称或配方版本不是未来数据的内容版本。通用工作流为**登记来源 → 绑定配置 → 采集/导入 → dataset → Run → 新 dataset**。静态/已生成快照可直接登记；`run_data` 保留完整 ExperimentSpec 的真实 Task/Candidate，组合绑定、原 Run 与采集，不虚构 Candidate，也不另建无 Candidate 的采集引擎。

v2 在保留 v1 资源字段的基础上补充 `kind`、`origin`、`lineage` 和 `attachments`。来源定义、父数据清单与实际采集记录成为可追溯资源；原生可变后端与已冻结数据分开保存。派生数据仍需显式登记，生成标签的状态和用途不因回流自动改变。SourceDatasetRevision 仍不同于训练导出的 `gymts.dataset/1`。

0.6.0 新增实验组/阶段尝试和显式回库：`gym.environment_ts.datasets.publish_build(...)` 将固定训练导出登记到长期数据目录，保留原 reader/schema、字节、血缘与用途，不合并源数据和训练导出协议。阶段绑定与可运行示例见[实验组织指南](experiment-organization.md)。

旧 `/1` 数据集、benchmark、Run 与报告原样保留，新协议 additive 接入；F0 身份和五项目验收不回写。历史 F1 先冻结核心，再让独立外部包接入四类真实来源，完成运行、血缘、独立评价与重评验证。准确入口与已运行的标准库数据链见[使用指南](user-guide.md#65-四类来源实际快照与回流)和[接口参考](reference.md#54-四类来源与-dataset-v2)。168 项核心回归及源码外发行检查已通过，固定 F1 的四类独立接入/独立重评已完成，旧十六包兼容单独记录；不宣称完整远程 Hub、分布式目录或任意 streaming。

## 1. 存什么、归谁管理

| 对象 | 职责 | 不可变身份 |
| --- | --- | --- |
| DatasetAssetRef | 原始字节、公开 Parquet、私有参考、质量报告和说明卡 | SHA-256、字节数、媒体类型 |
| DataSourceDefinition | 核心四类来源、provider 绑定、配方与重现方式 | source_id + config + 内容 revision |
| SourceDatasetRevision | EnvironmentTS 固定数据；v1 shard 合同，v2 增加来源/父清单/采集与附件 | dataset_id + config + 内容 revision |
| BenchmarkDefinition | AutoBenchTS 可复用评价配方：固定数据、resolver 和规则参数 | benchmark_id + 内容 revision |
| EvaluationSpec / Plan | 本次候选、案例、重复 seed、比较与 Gate；运行前固定全部预期单元 | 现有 evaluation_id / unit_id / plan_ref |
| Run / RecordSnapshot | 实际执行、采集和封存证据 | 现有 Run 与快照身份 |
| EvaluationReport | 独立评分、覆盖、比较和 Gate | 现有原生报告引用 |

源数据同时支持 `gymts.source-dataset/1` 和 `gymts.source-dataset/2`；来源定义使用 `gymts.data-source/1`。已有 `gymts.dataset/1` 继续用于轨迹的训练导出，不与长期源数据清单混用。修改源内容、分区、用途、reader 或导入表示产生新的源修订；修改已声明的评分/提示/筛选规则产生新的基准修订。固定版本的 resolver 持有领域 Task/Binding/Scorer 配方，未知规则必须拒绝，不能忽略。

## 2. 放在哪里

| 内容 | 当前位置或配置 | 发布边界 |
| --- | --- | --- |
| 通用资源合同、store、reader 服务 | `gymts/contracts/resources.py`、`storage/resources.py`、`environment_ts/datasets.py` | 核心安装包，不含题库 |
| 通用 benchmark 资源解析 | `gymts/autobench_ts/catalog.py` | 核心安装包，不按项目名分支 |
| 本批题库导入器、卡片、Task、Candidate、Scorer、resolver | `adapters/bench_tsqa/`，发行包 `gymts-bench-tsqa` | 独立安装、显式启用 |
| 来源定义、原始/派生资产、数据和基准清单 | `GymTS(data_home=...)` 或 `GYMTS_DATA_HOME`；默认 XDG data/gymts | 长期资源，独立于某个 Run |
| 校验后的本地资产副本 | `GymTS(cache_home=...)` 或 `GYMTS_CACHE_HOME`；默认 XDG cache/gymts | 可删除重建的缓存 |
| 活动 SQLite、Run CAS、报告 | 显式 `GymTS(root=...)` | 本机 POSIX 文件系统 |
| 封存证据归档 | 部署方选择的持久归档目录 | 本轮放仓库忽略的 `output/`，不入核心 wheel |

以下五份附件是 0.5.0 / v1 的历史导入实例，实际资源位于 `/zzr/zmx/GymTS/Jurmean-GymTS/output/resources-20261020`。该位置是本次部署配置，核心没有硬编码它；源码 wheel/sdist 不包含上传题库。导入后日常读取不依赖 Codex attachments 路径。`/zzr` 为 S3FS，活动 SQLite、缓存、构建与测试放 `/tmp`，完成后归档。

```text
<data_home>/
  objects/sha256/<前两位>/<完整hash>
  sources/<namespace>/<name>/<config>/
    revisions/<hash>/manifest.json
    aliases/1.0.0.json
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

SourceDatasetRevision v1 的字段为 `{protocol_version,dataset_id,config,revision,schema_ref,reader_ref,features,splits,usage_policy,source_files,importer_ref,inputs,series,targets,quality_report_ref,card_ref}`；v2 在此基础上增加 `kind/origin/lineage/attachments`，正式字段见规范 §20。split 声明 `{row_count,split_origin,input_indices,target_indices}`；source_files 保存原文件名与资产引用。reader/importer 使用固定 ComponentRef。

本批导入器保存原样 JSONL、公开 Parquet、私有参考 Parquet、JSON 质量报告及 Markdown 卡片。公开行保留 sample_id、dataset_id、source_row、task_kind、完整 question_original、可逆 attachment_projection、公开 choices 与有序 ragged Float64 series。仅将字面 `<ts><ts/>` 换成中立序列引用；不缩写、重写题目，不舍入、截断数值。原始字节和实际 Parquet codec 往返校验均保留。当前本批 series 内联在公开行中，通用 manifest 的独立 series 资产列表为空；没有声称已实现跨数据集序列表去重。

`answer`、`attributes`、未审核原始 metadata 和完整原文件保存在私有资产。公开 DatasetHandle 的 info、索引、批读取及 HF 转换不提供私有资产引用；reader 只得到所选公开 shard 的读取服务。AutoBenchTS resolver 单独取得定义内数据的 EvaluationDatasets 服务和私有参考。这是可信插件的服务边界，不是对恶意 Python 代码的系统沙箱。

用途策略固定为 `allowed_uses=['evaluation']`、`training_allowed=false`。公开 runtime 投影不改变原用途。数据读取、training_collection Run 和通用训练构建入口均拒绝将这些来源用于 training、prepare 或 dataset_build；改用另一个 exporter 不构成授权。

## 4. 五份已登记资源

全部源行为 `test / user_declared_evaluation`，保留重复、源顺序及源行身份，共 **19,354** 行。来源及许可证未提供，使用 `local/` 命名空间，不声称官方发行。

| dataset / benchmark ID | 行数 | 已读取参考 | 具备评价条件 | 输入待复核 |
| --- | ---: | ---: | ---: | ---: |
| local/bedtime | 394 | 394 | 394 | 0 |
| local/dataset-a-rlvr | 411 | 411 | 411 | 0 |
| local/mcq2 | 100 | 100 | 100 | 0 |
| local/timemqa-full | 17,703 | 17,703 | 16,983 | 720 |
| local/tsexam-mcq | 746 | 746 | 746 | 0 |

`tsqa.single-answer/2` 修正了原来把实现缺口写成“未知参考”的口径。19,354 行参考均已读到。Dataset A 的内容已与官方 ChatTS Dataset A 的 411 个子题逐项匹配；评分复用已存在的 RLVR 变体确定性规则，按私有结构化 attributes 计算 `task_score`，不冒充选择题准确率。来源、版本与转换差异见[上游说明](../adapters/bench_tsqa/UPSTREAM.md)。

TimeMQA 的答案字母与公开作答字母表独立解析；720 行仍需核对题目输入，其中 683 行未识别完整公开选项块，37 行参考字母不在可见选项中。问题原文、数组和答案不改、不猜补。这些行保留 eligible，准确率报告 missing/insufficient evidence，原因是输入待复核，而非没有答案。`mcq2` 参考中的 `1.` 仍视为题号。

新版资源及定义使用 `2.0.0` 别名，旧版 `1.0.0` 和封存 Run/报告保留。Scorer 接受旧版保存输出，新定义固定 v2 规则，不静默改写旧定义。[全量参考修正审计](reports/bench-tsqa-reference-repair-summary-2026-10-21.json)覆盖 19,354 行和 1,233 组确定性评分对照，未调用模型；参考文本自测不作为模型成绩。

本轮先对 `tsexam-mcq` 全量 746 行跑通原生评价与同 Run 重评分，其他四份已登记、可读取，未声称全部跑过正式模型全量评测。第一公开选项基线的 332/746 准确率用于检查接线和覆盖，不表示训练带来能力提升。

## 5. 怎样调用

四类来源的通用 API 与完整来源→Run→dataset→派生实例见[使用指南](user-guide.md#65-四类来源实际快照与回流)。下面保留五份 v1 测评附件的导入/读取/benchmark 示例；它们继续兼容，不替代新的来源目录。

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

通用 CLI 包括 `sources list/register/info`、`run-data` 与 `datasets capture`；既有 v1 资源继续使用 `gymts --store ... --data-home ... datasets list/info/register` 及 `autobench list/register/resolve`。`autobench resolve --candidate` 接收含 candidate_id/spec 的 JSON 文件；输出原生 EvaluationSpec，再交 `gymts evaluate`。现有 `gymts score` 对封存 Run 和固定参考重评分。完整配置、HTTP 模型边界和重复导入方式见[适配包指南](../adapters/bench_tsqa/README.md)。

## 6. 血缘、扩展与剩余设计

解析时将固定源 manifest、用途策略和 BenchmarkDefinition 提交到本次 CAS；provenance 传播到 EvaluationSpec、每个 Run 的配置/metadata 和报告证据，不把私有参考授予 Candidate。候选权重/算法配置身份保持固定，seed 通过执行上下文传递，不通过改变候选身份表达 repetitions。

Registry 的纯 describe/compatibility 提供离线 `plan/validate`。不读资源、不创建环境、不加载模型；实际 open/prepare 发生在 Run 建立后，资源损坏或原生接口失败保留失败 Run。新 reader、Task、Candidate、Scorer 和 resolver 走独立适配包，无需在核心添加题库名称分支。

RL checkpoint → 新进程 Candidate → 原生 AutoBenchTS.evaluate 重复 seed → 独立 score 也已跑通，具体范围见[RL 指南](rl-integration.md)及[实际报告](reports/rl-checkpoint-loop-2026-10-20.json)。训练仍复用 TRL；这五份测评附件未用于训练。

尚需未来项目验证或扩展的内容包括：结构化 RLVR verifier、更多 benchmark 的正式评分/模型验收、人工审核与资产发布流程、异构 suite 报告导航、远程资源同步、真正 streaming、多进程 Runtime/强制超时，以及现场安全/控制测试。它们不通过目录便利 API 另写执行、聚合或 Gate 逻辑。完整 v2 Runtime 合同仍为草案。
