# GymTS 使用指南

本文面向安装、运行和比较方法的用户，适用于 **GymTS 0.5.0 / 接口规范 1.2.0**。所有未特别标注的命令在仓库根目录执行。最小链路只使用 Python 标准库和本地确定性数据，无需 GPU、模型账户或外部服务。

接口字段的最终依据是[正式规范](feishu/GymTS接口规范/GymTS接口规范.md)；命令参数和 Python 方法速查见[参考手册](reference.md)。新增项目适配见[开发者指南](adapter-development.md)，各独立包的原生依赖和命令见[适配包目录](../adapters/README.md)。

## 1. GymTS 用来做什么

GymTS 将一次实验拆为可独立替换的数据环境、任务和被测方法，并把执行事实与评价依据分开保存。

| 对象 | 作用 | 例子 |
| --- | --- | --- |
| Environment | 提供受限观测，执行获准动作，报告时钟与结束原因 | 静态序列、仿真 step、外部 WS 会话、只读指标 |
| Task | 决定公开输入、输出含义、环境请求和结果对齐 | 窗口预测、问答、交互控制 |
| Candidate | 产生输出；可以是算法、模型、流水线或 Agent | last-value、本地模型、外部推理服务 |
| Scorer | 从封存输出与独立依据计算指标 | MAE、答案准确率、episode return |
| Dataset | 可复用的固定数据资源 | 公开问题、私有参考、用途策略 |
| Benchmark | 固定数据、任务和评价规则的配方 | 固定测试集上的候选比较 |

**EnvironmentTS 管执行与证据；AutoBenchTS 管评价与重评。** 核心不内置 LibraryTS、ChatTS、TimeSigma 等项目，也不实现其模型、数据格式或领域评分。项目通过独立适配包提供这些能力。工具的选择由被测 Agent 完成，实际调用由其 SDK/适配器执行；框架记录关联与证据，详见[Agent 与工具职责](agent-toolsets.md)。

`run` 创建新实验，`evaluate` 创建一组固定的新实验并评价，`score` 只评价指定的旧输出。重新运行模型与对原结果重新评分是不同操作。

## 2. 安装与检查

### 2.1 从源码安装

当前文档以源码安装为准，不假定已经在 PyPI 发布。

```bash
git clone https://github.com/Jurmean/GymTS.git
cd GymTS
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -c 'import gymts; print(gymts.__version__)'
gymts --help
```

如果已经取得源码目录，直接进入该目录，从创建虚拟环境开始。Python 要求 **3.9+**；本地记录后端要求 Linux/macOS 的 POSIX 文件操作。核心 JSON 工作流没有第三方运行依赖，构建安装由 pip/setuptools 完成。安装工具需要来自本机环境或可用的软件包索引；完全离线部署应事先准备构建工具和 wheel。

按需安装格式支持：

```bash
python -m pip install -e '.[yaml]'
python -m pip install -e '.[datasets]'
```

`yaml` 增加 PyYAML；`datasets` 增加用于本地 Parquet 读取的 PyArrow，**不是** Hugging Face `datasets` 的别名。需要 `DatasetHandle.to_hf()` 时另装 `datasets`，或者安装 HF 适配包的运行依赖。

### 2.2 安装与启用适配包

安装提供入口元数据，显式启用才会注册能力。例如：

```bash
python -m pip install . ./adapters/timeseries ./adapters/chatts
gymts --integration chatts plugins
```

```python
from gymts import GymTS

print(GymTS.available_integrations())
with GymTS(root="/tmp/gymts-chatts-runs", integrations=("chatts",)) as gym:
    print(gym.enabled_integrations)
```

`integrations` 是名称序列，单项也要写成 `("chatts",)`，不能传字符串。一个适配包可能声明其他独立领域包作为依赖；采用其 README 中的安装组合。科学解释器、模型权重和原生服务仍按适配包要求准备，安装轻量包不代表已具备完整原生运行环境。

## 3. 第一次完整运行

```bash
python examples/quickstart.py --root /tmp/gymts-first-run
```

脚本验证以下完整链路：

1. 线性合成序列上的窗口预测。
2. 计数器环境的 3 次真实动作。
3. 对两个候选创建正式评价；没有真值时返回 `insufficient_evidence`。
4. 追加独立真值，对原 Run 重评分，得到 MAE 1 和 2。
5. 检查重评前后 Run ID 与原 RunResult 未改变。

成功输出中应有 `counter_operations: 3`、`rescored_verdict: "pass"`、`same_run_ids: true`、`original_results_unchanged: true`。不同执行会生成不同 Run ID，使用本次实际输出中的 ID。`/tmp` 适合试用，可能被系统清理；需要长期保留时改用本机持久磁盘目录。

## 4. 校验、规划与单次实验

### 4.1 先规划，再执行

```bash
gymts --store /tmp/gymts-guide-runs plan examples/forecast_experiment.json \
  --output /tmp/gymts-guide-plan.json
gymts --store /tmp/gymts-guide-runs validate examples/forecast_experiment.json
gymts --store /tmp/gymts-guide-runs run examples/forecast_experiment.json \
  --output /tmp/gymts-guide-run.json
```

`plan` 解析默认值、固定组件版本、核对声明和组合约束，返回变量/动作绑定及 `read_scope`。它不实例化项目 Environment/Task/Candidate，不打开数据、模型或网络，不提交计划 CAS；构造 `GymTS` 本身仍会初始化本地存储目录。`validate` 返回 `valid`、`issues` 和内联 `resolved_spec`，其 `resolved_spec_ref` 为 null。需要保存计划时使用 CLI 的 `--output` 或自己保存返回值。

规划成功不能证明文件存在、模型能加载或服务可连接。真正打开资源发生在 Run 建立以后；打开失败会进入失败 Run 的轨迹。`run` 返回的是 RunResult，首先检查 `status`，再看 `completion`、`errors` 与 `summary`，不能仅凭拿到 `run_id` 判定成功。

### 4.2 Python 等价调用

```python
import json
from pathlib import Path
from gymts import GymTS

spec = json.loads(Path("examples/forecast_experiment.json").read_text())
with GymTS(root="/tmp/gymts-guide-sdk") as gym:
    check = gym.validate(spec)
    if not check["valid"]:
        raise ValueError(check["issues"])
    plan = gym.plan(spec)
    result = gym.run(plan["resolved_spec"])
    print(result["run_id"], result["status"], result["completion"])
    if result["status"] != "succeeded":
        raise RuntimeError(result["errors"])
```

一个 `GymTS` 实例可执行多个 Run。使用 `with` 在结束时关闭记录库；不要把同一个 SQLite 连接跨进程传递。

### 4.3 读懂 ExperimentSpec

以 [forecast_experiment.json](../examples/forecast_experiment.json) 为可直接执行的完整配置。顶层结构如下：

| 字段 | 决定什么 | 修改时注意 |
| --- | --- | --- |
| `protocol_version` | 消息合同，当前 `gymts.experiment/1` | 不等于发行版本 0.5.0 |
| `name`、`purpose` | 名称和用途 | 用途影响准备/训练授权 |
| `scene.environment` | 来源、字段映射、时钟与操作能力 | `source.kind` 只是来源类型，具体语义由适配器提供 |
| `scene.task` | 任务插件及其参数 | Task 决定窗口、输入与结果含义 |
| `scene.binding` | 任务变量/动作到环境的绑定 | 单位、类型和操作 schema 必须兼容 |
| `candidate` | 精确版本、模型制品、参数、继承状态 | 换模型通常改这里，不改 Task 或 Runner |
| `execution` | batch/stream/interactive、启动方式、scope、seed、学习与限额 | 环境不支持的 reset/seed 必须拒绝 |
| `recording` | 输入输出和内部调用证据策略 | 核心执行证据不能关闭 |
| `extensions` | 显式扩展字段 | 不用于绕过合同或偷偷传私有标签 |

时间窗口使用 `[start, end)`，`end: null` 时必须由有效限额保证结束。时间型 scope 使用带时区的时间字符串；仿真步数使用非负整数，两种时钟不能混算。UTC 示例形如 `2026-01-01T00:00:00Z`。Duration 必须带单位，例如 `1min`、`500ms`，不把一步强行解释为一秒。

`execution.learning.prepare="load_only"` 不拟合持久权重，`online="frozen"` 不调用权重更新。需要训练时显式声明 `fit`、固定训练视图与允许反馈，且 Candidate 和数据用途均须支持。Agent 在一次 Run 内保留会话上下文不等于更新模型权重。

至少设置一个可达的停止边界：有限 `scope.end`、`max_inputs`、`max_operations` 或 `max_wall_time_s`。实时等待不能仅靠动作数约束；同步 wall limit 只在调用边界检查，后端还应设置自己的 I/O 超时。

## 5. 评价、晚到标签与原结果重评

### 5.1 新实验评价

```bash
gymts --store /tmp/gymts-guide-evaluation evaluate examples/forecast_evaluation.json \
  --output /tmp/gymts-guide-evaluation.json
```

此配置有 1 个案例、2 个候选、1 次重复，因此固定 2 个预期单元。计划在首个 Run 前保存；失败或未启动单元仍留在清单中，不能通过删除它们提高覆盖率。当前示例没有标签，流程可正常完成，但 `verdict` 为 `insufficient_evidence`。

`EvaluationReport.status` 表示评价流程是否完成；`verdict` 表示指标、证据要求与 Gate 的结论。CLI 退出 0 不保证 Gate 通过。接入 CI 时读取报告字段，例如：

```bash
python - <<'PY'
import json
from pathlib import Path
report = json.loads(Path("/tmp/gymts-guide-evaluation.json").read_text())
print(report["status"], report["verdict"])
# acceptance CI 可采用：
# raise SystemExit(0 if report["status"] == "completed" and report["verdict"] == "pass" else 1)
PY
```

评分关注每个指标自己的 eligible/scored/missing/invalid 等计数和覆盖率。缺标签不是零误差；未定义的奖励不是零奖励。即使取得一个平均数，也应检查证据是否覆盖计划要求的样本。

### 5.2 一个可直接执行的晚到标签示例

以下脚本从示例合成源的定义生成独立真值，不读取候选预测来制造标签。它保留计划的真实单元身份，追加标签后构造 ScoreSpec。整段可在仓库根目录执行：

```bash
python - <<'PY'
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from gymts import GymTS
from gymts.contracts import digest, inline, utc_now

evaluation = json.loads(Path("examples/forecast_evaluation.json").read_text())
with GymTS(root="/tmp/gymts-guide-late-labels") as gym:
    first = gym.autobench.evaluate(evaluation)
    plan = gym.artifacts.read_json(first["plan_ref"])
    manifest = gym.artifacts.read_json(first["run_manifest_ref"])
    units = {unit["unit_id"]: unit for unit in plan["expected_units"]}
    run_ids = [entry["run_id"] for entry in manifest["entries"]]
    before = {run_id: digest(gym.records.get_run(run_id)["result"]) for run_id in run_ids}

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    def stamp(index):
        return (start + timedelta(minutes=index)).isoformat().replace("+00:00", "Z")
    truth = [{"timestamp": stamp(index), "value": index} for index in range(12)]
    source_ref = gym.artifacts.save_json(truth, "gymts.json/1")
    outcomes = []
    for index in range(11):
        alignment = {"entity": "demo", "variable": "value",
                     "issued_at": stamp(index), "target_time": stamp(index + 1)}
        outcomes.append({
            "outcome_id": "guide-label-" + digest(alignment), "revision": "1",
            "alignment_key": alignment,
            "payload": inline({"value": index + 1}, "gymts.builtin/forecast-outcome/1"),
            "event_time": stamp(index + 1), "available_at": "2026-01-01T01:00:00Z",
            "recorded_at": None, "source_ref": source_ref,
            "supersedes_ref": None, "allowed_uses": ["evaluation"]})
    for run_id in run_ids:
        gym.records.attach_outcomes(run_id, outcomes)

    cutoff = utc_now()
    frozen = gym.records.read_outcomes({"run_ids": run_ids,
        "outcomes_as_of": cutoff, "purpose": "evaluation"})
    labels_ref = gym.artifacts.save_json(frozen, "gymts.outcome-records/1")
    scoring = copy.deepcopy(evaluation["scoring"])
    scoring["outcomes"] = {"sources": [{
        "view_id": "guide-fixed-labels", "revision": labels_ref["revision"],
        "source_refs": [labels_ref],
        "selection": inline({"kind": "all", "source_index": 0}, "gymts.selection/1"),
        "as_of": None, "purpose": "evaluation"}], "as_of": cutoff}
    selected = []
    for entry in manifest["entries"]:
        unit = units[entry["unit_id"]]
        selected.append({"unit_id": unit["unit_id"],
            "evaluation_case_id": unit["evaluation_case_id"],
            "candidate_id": unit["candidate_id"], "repetition": unit["repetition"],
            "run_id": entry["run_id"], "unavailable_reason": None,
            "unit_spec_ref": unit["resolved_spec_ref"]})
    spec = {"protocol_version": "gymts.score/1", "name": "guide-rescore",
        "purpose": "regression", "runs": selected,
        "baseline_id": evaluation["baseline_id"], "scoring": scoring,
        "comparison": evaluation["comparison"], "failure_policy": evaluation["failure_policy"],
        "previous_evaluation_id": first["evaluation_id"]}
    Path("/tmp/gymts-guide-score.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2))
    report = gym.autobench.score(spec)
    assert report["verdict"] == "pass"
    assert all(digest(gym.records.get_run(run_id)["result"]) == before[run_id] for run_id in run_ids)
    print({"initial": first["verdict"], "rescored": report["verdict"], "run_ids": run_ids})
PY
```

随后可通过 CLI 再次评价同一批封存输出：

```bash
gymts --store /tmp/gymts-guide-late-labels score /tmp/gymts-guide-score.json \
  --output /tmp/gymts-guide-rescore.json
```

`score` 创建新的评价报告和 `evaluation_id`，不推进 Environment，不重新调用 Candidate，不覆盖旧报告。`previous_evaluation_id` 保存报告之间的关系。示例模板 [forecast_score_template.json](../examples/forecast_score_template.json) 中的 `REPLACE_WITH_ACTUAL_RUN_ID` 不能直接执行；生产流程应从原计划/清单保留真实身份，如上例所示。

### 5.3 标签修订规则

OutcomeRecord 保存 `alignment_key`、真值 payload、独立 `source_ref`、事件时间、可用时间和用途。`recorded_at` 由记录库分配，调用方传 null 或省略。同一个 `(outcome_id, revision)` 同内容重复提交幂等，异内容报 `conflict`。修正标签时创建新 revision，并用 `supersedes_ref` 引用该标签的已提交旧修订。

历史截止同时约束 `available_at` 和 `recorded_at`，避免后来回填的旧事件进入过去的评价。仅执行 `attach_outcomes` 不会自动把新标签送入 Scorer：还需选出固定 Outcome 集合，构造带 `purpose="evaluation"` 的视图，再发起新的 `score`。私有评价标签不会自动成为训练数据或 Candidate 的在线反馈。

## 6. 数据资源与 Benchmark

### 6.1 数据放在哪里

将运行证据、长期数据和可重建缓存分开配置：

```python
from gymts import GymTS

with GymTS(root="/tmp/gymts-work/runs",
           data_home="/tmp/gymts-work/data",
           cache_home="/tmp/gymts-work/cache") as gym:
    print(gym.environment_ts.datasets.list_datasets())
    print(gym.autobench.list_benchmarks())
```

示例使用 `/tmp` 以便试用；正式部署将 `data_home` 和 Run root 改为持久本地磁盘。`data_home` 的默认值为 `$XDG_DATA_HOME/gymts` 或 `~/.local/share/gymts`；缓存默认 `$XDG_CACHE_HOME/gymts` 或 `~/.cache/gymts`。显式参数优先于 `GYMTS_DATA_HOME` / `GYMTS_CACHE_HOME`。

| 内容 | 存储位置 | 是否可删除重建 |
| --- | --- | --- |
| Run、执行事件、Outcome 索引 | `<root>/records.sqlite3` | 否，属于实验记录 |
| 输入输出、调用、计划和报告制品 | `<root>/artifacts/` | 否，引用它们的记录需要这些字节 |
| 固定源文件、公开输入、私有参考和资源清单 | `<data_home>/` | 否，除非另有完整备份 |
| 已校验数据对象缓存 | `<cache_home>/` | 可从完整数据资源重建 |
| 环境/模型原生文件 | 适配包显式配置的位置 | 取决于其固定资产和部署方式 |

活动 SQLite WAL、CAS 原子发布和资源锁要求本机 POSIX 语义，勿把活动 Run root 放到 S3FS、对象存储挂载或不保证相同语义的共享文件系统。本项目没有自动远程同步和跨主机资源事务。备份前关闭写入方，再完整保存记录库与 artifacts；有引用的 CAS 不应单独清理。`GymTS.close()` 只关闭本地记录服务，外部服务的生命周期取决于适配器的会话所有权。

### 6.2 从零登记并读取本地数据

下面的完整示例发布公开问题与独立私有答案，绑定一次性的发布标签 `1.0.0`。它仅演示资源登记/读取，不把数据自动转成某个预测或 QA Task。

```bash
python - <<'PY'
import json
from gymts import GymTS
from gymts.environment_ts.datasets import JSONL_READER

public = [{"sample_id": "case-0", "question": "数列的下一个值是什么？", "values": [1, 2, 3]}]
private = [{"sample_id": "case-0", "answer": 4}]
with GymTS(root="/tmp/gymts-guide-catalog/runs",
           data_home="/tmp/gymts-guide-catalog/data",
           cache_home="/tmp/gymts-guide-catalog/cache") as gym:
    catalog = gym.environment_ts.datasets
    def publish(rows):
        content = ("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n").encode()
        return catalog.publish_asset(content, media_type="application/jsonl")
    manifest = {
        "protocol_version": "gymts.source-dataset/1", "dataset_id": "local/guide-series",
        "config": "default", "revision": None, "schema_ref": "gymts.json/1",
        "reader_ref": JSONL_READER, "features": {"values": "list[float64]"},
        "splits": {"test": {"row_count": 1, "split_origin": "user_declared_evaluation",
                            "input_indices": [0], "target_indices": [0]}},
        "usage_policy": {"allowed_uses": ["evaluation"], "training_allowed": False},
        "source_files": [],
        "importer_ref": {"name": "guide.explicit-jsonl", "version": "1.0.0", "origin_ref": None},
        "inputs": [publish(public)], "series": [], "targets": [publish(private)],
        "quality_report_ref": None, "card_ref": None}
    fixed = catalog.register_dataset(manifest, aliases=("1.0.0",))
    dataset = catalog.load_dataset("local/guide-series", revision="1.0.0", split="test")
    print(fixed["revision"], dataset.info, dataset[0])
    assert "answer" not in dataset[0]
    assert not hasattr(dataset, "read_targets")
PY
```

`schema_ref="gymts.json/1"` 是教程的宽松 JSON 合同。真实发布应由独立适配包注册明确的行 schema、reader 和 importer；manifest 的 `features` 用于描述，不替代逐行 schema 校验。

资源 revision 根据规范化清单计算，源字节按 SHA-256 存放。别名一次绑定后不能换内容；修改数据、划分、用途或表示时产生新修订和新发布标签，不使用 `latest`、`main`、`master` 作为固定版本。

### 6.3 HF 风格的公开读取

在完成上一步后：

```python
from gymts import GymTS

with GymTS(root="/tmp/gymts-guide-catalog/other-runs",
           data_home="/tmp/gymts-guide-catalog/data",
           cache_home="/tmp/gymts-guide-catalog/cache") as gym:
    ds = gym.environment_ts.datasets.load_dataset("local/guide-series", revision="1.0.0")
    print(ds.info, ds.features, len(ds), ds[0])
    subset = ds.select([0]).filter(lambda row: len(row["values"]) > 0)
    print(subset.sample_ids())
    for batch in subset.iter_batches(batch_size=16):
        print(batch)
    # 安装 Hugging Face datasets 后可执行：hf_dataset = subset.to_hf()
```

支持索引、切片、`select`、`filter`、批读取、sample ID 和 HF 转换；当前 reader 为本地物化读取，不提供 HF Hub 的远程托管、流式超大数据或分布式索引。`select` 不允许隐式复制同一个源行。`read_series()` 读取 manifest 声明的独立公开 series 资产；只有内联数值的资源可能没有这类资产。

公开 `DatasetHandle` 不暴露 target/source 原始私有资产。需要私有参考的 benchmark resolver 由 AutoBenchTS 取得单独的评价服务，Candidate 只得到 Task 公开输入。用途为 evaluation-only 的数据仍可供运行时读取公开题目，但禁止训练、prepare 和轨迹训练导出。

### 6.4 登记和调用 Benchmark

BenchmarkDefinition 固定数据 revision、resolver 版本及规则参数。它不是另一个执行器：`resolve_benchmark` 返回正式 EvaluationSpec，后续仍用 `evaluate`；旧输出仍用 `score`。

已经有题库文件时，使用[TSQA 适配包](../adapters/bench_tsqa/README.md)的显式导入器；从 HF 或本地 Arrow/Parquet 冻结数值时序时，使用 [HF 适配包](../adapters/hf_datasets/README.md)。导入器负责真实格式、schema、用途和配套 resolver，核心 CLI 不会猜测任意 JSONL 的任务/评分含义。

以下为**已安装 bench-tsqa、且在指定 data_home 完成导入之后**的调用模板；将路径改为自己的资源目录：

```python
from gymts import GymTS
from gymts_bench_tsqa.benchmark import first_choice_candidate

with GymTS(root="/tmp/gymts-benchmark-runs", data_home="/path/to/imported/resources",
           cache_home="/tmp/gymts-benchmark-cache", integrations=("bench-tsqa",)) as gym:
    spec = gym.autobench.resolve_benchmark("local/tsexam-mcq", revision="1.0.0",
        candidates=[first_choice_candidate()], purpose="regression",
        repetitions={"count": 1, "seeds": [0]})
    report = gym.autobench.evaluate(spec)
    print(report["status"], report["verdict"])
```

五份用户题库属于测评数据，不随核心发行，不授权训练；本地 `local/` 名称也不代表官方数据发行。一个已有数据资源可以服务多个独立 Run store，前提是各进程安装并启用了所需 reader/resolver。

## 7. 轨迹、制品和可复现证据

### 7.1 查看 Run 和事件

下面的 CLI 片段读取第 4 节生成的实际 Run ID：

```bash
RUN_ID=$(python -c 'import json; print(json.load(open("/tmp/gymts-guide-run.json"))["run_id"])')
gymts --store /tmp/gymts-guide-runs inspect "$RUN_ID"
gymts --store /tmp/gymts-guide-runs inspect "$RUN_ID" --events \
  > /tmp/gymts-guide-inspection.json
```

Python 可分页读取、只选事件类型并固定快照：

```python
import json
from pathlib import Path
from gymts import GymTS

run_id = json.loads(Path("/tmp/gymts-guide-run.json").read_text())["run_id"]
with GymTS(root="/tmp/gymts-guide-runs") as gym:
    record = gym.records.get_run(run_id)
    results = gym.artifacts.read_json(record["result"]["result_ref"])
    snapshot = gym.records.snapshot([run_id])
    cursor = 0
    while True:
        page = gym.records.read_events(run_id, {"after_seq": cursor, "limit": 100,
            "kinds": ["input", "candidate_output", "task_result"],
            "snapshot_ref": snapshot["snapshot_ref"]})
        for event in page["events"]:
            print(event["seq"], event["kind"], event["links"])
        cursor = page["next_after_seq"]
        if cursor is None:
            break
    print(len(results), snapshot["snapshot_ref"])
```

单 Run 的 `seq` 是持久提交顺序；不要按源时间重新排序后当作真实执行顺序。事件关联输入、输出、操作、回执和调用。执行封存后不可新增执行事件；追加 Outcome 和新评价不会改写原 RunResult 或执行快照。

`records.snapshot` 固定事件边界和当时可用且已提交的 Outcome 修订。读取快照时不会重新查询“最新标签”；训练和评价应保留固定引用，而不是记录一个会随时间改变的查询。

### 7.2 ArtifactRef 与数据 AssetRef

Run CAS 的 ArtifactRef 包含字节 hash、媒体类型、schema、大小及不可变身份；它不是任意本地文件路径或 HTTP URL。使用 `gym.artifacts.save_json` 或 `save_artifact` 显式导入，读取时经 `read_json` 或 `resolve` 验证。资源目录的 DatasetAssetRef 使用 `gymts-data://...`，与 Run 内 `gymts-artifact://...` 不混用。资源进入某次执行证据时会固定为本次 CAS 引用。

CAS 的 hash 保证引用的字节身份，不证明外部服务未来仍是同一权重、不保证数据许可、不代替生产服务证明。要复现实验还需保留原生版本、依赖、权重、生成参数、来源字节及适配器声明。服务 alias 或 URL 通常只固定配置，不足以证明固定权重。

### 7.3 ModelCall 与 ToolCall 采集

`recording.model_calls` 有三种配置：

| 值 | 用途 | 仍需核对 |
| --- | --- | --- |
| `none` | 不要求可选内部模型调用采集 | 观测、输入、原始输出、TaskResult 等核心证据仍记录 |
| `io` | 要求适配器记录真实请求/响应 | 实际 completeness、缺失原因、失败/未知状态 |
| `native_rollout` | 要求原生 token、输入、策略等训练证据 | 真正采集的 tokens/mask/概率分布和策略身份 |

配置期望不等于已经采集成功，也不能为未声明支持的 Candidate 自动增加采集能力。模型/Agent 适配器在 `Candidate.infer` 中使用传入的公共 `TraceCollector.record_model_call` / `record_tool_call`；请求、结果等先保存为制品。Runner 绑定真实 `run_id/input_id/output_id`，适配器报告原生调用/尝试/父调用身份。仅看到聊天消息中的 tool call 不证明工具已经执行。

环境取数和动作必须经 TaskRequest → Runner → Environment，并保留请求/操作关联；不能把新环境读写包装成输入内计算来绕过边界。不得事后分词冒充原生 token，或者编造未返回的 logprob、推理链和使用量。完整字段和开发接入见[参考手册](reference.md#4-轨迹与制品-api)、[正式规范 §10.3](feishu/GymTS接口规范/GymTS接口规范.md#103-modelcallartifact-与-toolcallartifact)和[RL 接入](rl-integration.md)。

`on_capture_failure="fail_run"` 是默认策略；`mark_incomplete` 仅适用于可选内部调用采集，不能放宽核心记录丢失。`redaction_policy_ref` 只是固定策略引用，不能自动替你移除密钥；真实脱敏变换须由适配器执行并记录版本。请求/响应可能含私有输入，归档与共享前按项目授权处理。

## 8. 使用不同来源与训练扩展

各包独立安装、显式启用，详细环境准备只维护在对应 README：

| 需求 | 入口与范围 |
| --- | --- |
| 合成实验 | [最小示例](../examples/README.md)、[ChatTS](../adapters/chatts/README.md) |
| 固定 HF/Arrow/本地文件 | [hf_datasets](../adapters/hf_datasets/README.md)：当前为数值时序公开上下文与私有预测目标 |
| Gymnasium | [gymnasium](../adapters/gymnasium/README.md) 与独立 [interaction](../adapters/interaction/README.md)：真实 step、末状态/奖励和结束原因 |
| 外部 OpenEnv | [openenv](../adapters/openenv/README.md)：官方有状态 WS，当前本机 Echo/Connect4 验收 |
| Prometheus | [prometheus](../adapters/prometheus/README.md)：只读 live 数值指标，已有观测的缓存查询和封存重评 |
| LibraryTS 工具 | [libraryts](../adapters/libraryts/README.md)：指定 sktime 分支、原生工具调用及科学解释器 |
| TimeSigma | [timesigma](../adapters/timesigma/README.md)：独立训练/推理与 Research 父轨迹 |
| RL rollout 与训练 | [rl](../adapters/rl/README.md)：本地采样、固定轨迹数据集、TRL GRPO 和 checkpoint 再评价 |
| 自有项目 | [扩展指南](adapter-development.md)：独立包注册，不向核心添加项目分支 |

离线数据支持固定内容重放；live 环境世界状态无法凭配置恢复，连续运行不同候选也不天然构成公平的同数据比较。需要对比时显式冻结共同观测，或由场景提供可恢复会话与受控试验设计。外部会话不支持 seed/reset 就应拒绝，不能记录一个没有实际生效的 seed。

训练数据构建使用公开 `gymts.training.build_dataset(spec, records, artifacts)`，输入是固定 RecordSnapshot；具体格式、奖励、token/mask 和训练后端由独立 DatasetBuilder provider 提供。核心不内置 TRL/verl；现有 RL 包复用 TRL，verl、多轮 RL 和分布式训练尚未适配。`gymts.source-dataset/1` 是源资源清单，`gymts.dataset/1` 是训练导出结果，二者不能互换。

## 9. 常见问题与故障排查

| 现象 | 检查与处理 |
| --- | --- |
| `gymts: command not found` | 激活安装所用的虚拟环境；也可用同一解释器执行 `python -m gymts` |
| 找不到集成或组件 | 用 `GymTS.available_integrations()` 查安装入口，用 `gymts --integration NAME plugins` 查启用后 Manifest；核对精确版本 |
| 已安装仍缺科学依赖 | 按适配包的 `[runtime]`/独立原生解释器说明准备，确认真正执行时使用的 Python |
| `validate` 成功但运行失败 | 规划不读资源；检查失败 Run 的 `errors`、事件和真实文件/服务配置 |
| `schema_mismatch` / `unsupported_capability` | 检查 Task/Candidate 协议、变量单位、时钟、seed/reset、动作 schema 和评分器合同 |
| `permission_denied` | 检查 scope、可见前沿、显式制品授权和数据用途；不要扩大 Candidate 权限解决标签访问错误 |
| 有预测但无分数 | 检查独立标签视图、匹配键、时间截止、metric counts、无效输出和最小覆盖要求 |
| 标签已追加但报告没变化 | 原报告不可变；选固定标签视图并发起新的 `score` |
| `conflict` | 同一个不可变身份被绑定了不同内容；发布新 revision/alias，不覆盖原证据 |
| `artifact_integrity` / `persistence_failed` | 检查字节、空间、权限和本地 POSIX 存储语义；保留故障材料，不手工改 CAS |
| HTTP 超时后不确定动作是否执行 | 查看 `side_effect`、operation_id 与原生回执；不得默认重试可能已生效的动作 |
| 模型采集失败或训练导出被拒绝 | 查看 capture 缺失项、原生 token/概率身份和数据用途；缺失信息不能靠事后编造补齐 |

Python 中可捕获 `GymTSError` 并读取 `error.info`；Run 已建立后的运行失败通常返回 `status="failed"`，不会都以 Python 异常表达。CLI 的退出码规则见[参考手册](reference.md#12-输出和退出码)。

提交可复现问题时附版本、平台、最小配置、脱敏错误、Run/evaluation ID 和相关事件。真实数据或模型受限时提供同形状的公开最小样例；不要在 issue 中粘贴密钥、私有标签或未经授权的请求/响应。

## 10. 当前实现边界

0.5.0 是同步本地 SDK/CLI，不是托管 HF Hub、企业多租户平台、分布式调度器或通用 Agent 引擎。插件是受信任的进程内 Python 代码，受限服务构成规范的访问边界，**不构成对恶意插件的系统沙箱**。核心没有 ToolRegistry/ToolBroker 自动注入任意工具集，完整 Agent 自主选择工具闭环仍需独立适配与验收。

本轮 HF、Gymnasium、OpenEnv 和 Prometheus 的验收范围及归档证据见[环境接入指南](environment-adapters.md)。本机真实服务可运行不代表用户生产 testbed 已验收；工程小模型更新、固定算法和已知常量 fixture 的评分也不代表模型能力提升。

现行规范与当前指南优先；[v2 合同](pluggability-contract-v2.md)和[企业平台路线](enterprise-platform-roadmap.md)是设计材料，不能直接当作已实现 API 调用。
