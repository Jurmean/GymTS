# 实验组织与数据回库

本页对应 GymTS **0.6.0** 工作树与接口规范 **1.4.0**；尚未表示已发行。GymTS 围绕四件事工作：存储数据、接入数据、组织实验、记录实验。本页说明如何把固定数据引用、多个执行阶段和长期数据目录组织成一条可查询的链。核心变更理由与兼容约定见 [ADR 0002](adr/0002-experiment-organization.md)。

## 先区分三个身份

| 身份 | 表达什么 | 什么时候变化 |
| --- | --- | --- |
| dataset / source 的固定 revision | 已登记的数据内容或来源定义 | 数据、配方或固定来源配置改变时产生新修订 |
| experiment group 的固定 revision | 阶段、依赖、输入绑定、执行配置与输出选择 | 实验定义改变时产生新修订 |
| stage attempt | 一次实际阶段执行 | 每次实际调用都新增；失败后重试也新增 |

一个阶段可以产生一个 Run、多个评价 Run，或只执行数据发布。attempt 记录该阶段做了什么；Run 继续保存具体环境执行的事件。两者不能互相替代。

EnvironmentTS 管数据、执行和证据；AutoBenchTS 管评价与重评。`gym.experiments` 与 `gym.environment_ts.experiments` 指向同一组织服务，连接已有入口，领域格式、模型调用、转换和评分仍由适配器实现。

## 数据与实验放在哪里

```text
<data_home>/
  objects/sha256/                 长期数据与清单引用的字节
  sources/...                    来源定义
  datasets/...                   数据集固定修订
  autobench/benchmarks/...        benchmark 定义

<run_root>/
  records.sqlite3                Run、事件和实验组织索引
  artifacts/blobs/...            不可变配置、产物、阶段结果与报告
  artifacts/refs/...             制品引用
```

`cache_home` 只存可重建缓存。数据登记或实验登记不自动下载模型、启动服务或调用付费模型。活动 SQLite 和制品存储应放在本地支持正常文件事务的路径；下文示例使用 `/tmp`。

## 组织一份实验

实验清单使用 `gymts.experiment-group/1`。每个阶段声明：

| 字段 | 含义 |
| --- | --- |
| `stage_id` | 实验内唯一名称 |
| `executor_ref` | 实际执行入口的固定 ComponentRef |
| `depends_on` | 必须先成功的阶段；引用 `stage_output` 时自动补入依赖 |
| `purpose` | 本阶段的数据用途；内置 evaluate/score 默认 evaluation，publish-build 默认 dataset_build，其余默认 runtime |
| `spec` | 执行入口原本需要的配置 |
| `inputs` | 固定数据、来源、制品或上游阶段输出 |
| `bindings` | 将具名输入写入 `spec` 的 JSON Pointer |
| `outputs` | 用 JSON Pointer 从阶段返回对象选择具名产物 |

绑定指针以 `spec` 自身为根，例如 `/candidate/artifact`，不加 `/spec` 前缀；父容器必须存在。输出指针以执行器返回对象为根，例如 `/run_id`；空字符串 `""` 选择整个返回对象。JSON Pointer 只选择或绑定值。它不会把 HF 行转换成时序窗口，也不会把 checkpoint 转成另一后端可读的模型。此类转换使用外部 executor 或适配器，并保存转换后的固定产物。

登记时固定数据和来源修订。执行前解析本阶段输入并保存本次配置，随后调用已有执行服务。阶段返回的具名输出成为后续阶段的输入，调用方无需手工复制返回的制品引用。

## 一个本地示例

在仓库根目录安装核心后运行：

```bash
python -m pip install .
python examples/experiment_organization.py --work /tmp/gymts-organization-demo
```

[完整示例](../examples/experiment_organization.py)先登记 12 条公开 ramp 观测，再执行五个阶段：forecast → capture / outcomes → score → rescore。一次真实 Run 支撑两次独立评分；重复执行不新增 attempt，原 RunResult 保持不变，按源数据集可查到该组。两个简短外部执行器分别处理公开行的格式投射和独立 Outcome 依据构造。示例不需要外部模型或在线服务；本地示例通过不等于新核心冻结验收已经完成。

下面是最小的单 Run 登记与查询。它可以在仓库根目录直接执行；现有完整 ExperimentSpec 不需要改写为另一种执行协议。

```python
import json
from pathlib import Path
from gymts import GymTS

spec = json.loads(Path("examples/forecast_experiment.json").read_text())
with GymTS("/tmp/gymts-group-runs", data_home="/tmp/gymts-group-data") as gym:
    definition = gym.experiments.register({
        "group_id": "demo/forecast",
        "name": "Local forecast experiment",
        "stages": [{
            "stage_id": "forecast",
            "executor_ref": {
                "name": "gymts.run", "version": "1.0.0", "origin_ref": None},
            "spec": spec,
            "outputs": {"run_id": "/run_id", "result": ""},
        }],
    })
    revision = definition["revision"]
    state = gym.experiments.execute("demo/forecast", revision=revision)
    print(state["status"], state["stages"][0]["outputs"]["run_id"])
    print(gym.experiments.query(group_id="demo/forecast"))
```

`register` 补齐缺省字段，并把明确资源别名解析成内容 revision。保存返回的 `revision`，后续 `get/execute/inspect` 显式使用它。

## 输入、绑定与执行入口

`inputs` 是具名对象。四种值的形状如下；其中实际 ID、revision 和 ArtifactRef 由对应服务返回。

```python
inputs = {
    "data": {"kind": "dataset", "ref": {
        "dataset_id": "local/example", "config": "default",
        "revision": fixed_dataset_revision, "split": "test"}},
    "source": {"kind": "source", "ref": {
        "source_id": "local/example-source", "config": "default",
        "revision": fixed_source_revision}},
    "artifact": {"kind": "artifact", "ref": artifact_ref},
    "previous": {"kind": "stage_output", "stage_id": "previous-stage", "output": "result"},
}
```

声明输入会固定身份并进行用途检查。其清单与收紧后的共同用途通过 attempt 上下文传播到嵌套 Run 和评价计划，包括自定义执行器调用这些服务的情况；provenance 不自动授予 Candidate 私有资源。`bindings` 决定哪些值写入执行配置。例如，采集阶段用以下字段接收上游 Run ID：

```python
{
    "inputs": {
        "run": {"kind": "stage_output", "stage_id": "forecast", "output": "run_id"}
    },
    "bindings": {"run": "/run_id"},
    "outputs": {"dataset": ""},
}
```

这里指针作用于采集阶段的 `spec`。领域格式转换不由绑定完成。

| 固定 executor | `spec` 与实际入口 |
| --- | --- |
| `gymts.run@1.0.0` | 原 ExperimentSpec → `gym.run`；声明的 source 输入绑定其来源与用途证据 |
| `gymts.evaluate@1.0.0` | 原 EvaluationSpec → `gym.autobench.evaluate` |
| `gymts.score@1.0.0` | 原 ScoreSpec → `gym.autobench.score` |
| `gymts.capture@1.0.0` | `run_id`、`source_ref`、`dataset_id` 及采集参数 → `datasets.capture_run` |
| `gymts.publish-build@1.0.0` | `manifest`、`reader_ref` 及发布参数 → `datasets.publish_build` |

每个 ComponentRef 均包含 `name`、`version` 与 `origin_ref`。需要适配器特有步骤时，调用 `gym.experiments.register_executor(reference, executor)`；执行器签名为 `executor(spec, gym) -> dict`。进程重新启动后须再次注册所需执行器。返回值必须是可保存的 JSON 对象；创建 Run 时使用传入 `gym` 的现有服务，框架会把这些 Run 关联到当前 attempt。

## 执行、失败与续接

调用组织服务会为实际执行的阶段建立 attempt。成功阶段留下固定返回值；失败阶段留下错误与已经建立的 Run。依赖未满足的阶段不会运行。

默认再次执行仅运行尚未执行或已经 stale 的就绪阶段，跳过成功、失败及中断的尝试。显式选择重试或重跑：

```python
# 重试 failed / cancelled 阶段；不会重复成功阶段。
gym.experiments.execute(group_id, revision=revision, retry_failed=True)

# 明确重跑一个阶段；依赖其旧 attempt 的后续阶段会变 stale 并重新执行。
gym.experiments.execute(group_id, revision=revision, rerun=["forecast"])
```

旧 attempt、Run 和报告都保留。若需要改变数据、配置或依赖，应登记新修订。续接发生在阶段边界，不恢复进程内 Python 对象，也不恢复某次评价矩阵的内部执行位置。

进程中断后，组织记录可能仍显示阶段在运行。确认旧进程及相关后端已经结束，再显式恢复：

```python
gym.experiments.recover(attempt_id, reason="Previous worker has stopped")
gym.experiments.execute(group_id, revision=revision, rerun=[stage_id])
```

默认恢复将该 attempt 记录为 `interrupted`，随后必须显式重跑。若 `gymts.run` 阶段实际上已封存唯一一个 Run，只是阶段结束记录未写入，可用 `recover(attempt_id, reason=..., adopt_run=True)` 采纳该 Run 及原输出，避免再次执行。其他执行器不支持这条采纳路径。

恢复更新组织状态，不能证明远端操作已停止，也不接管旧 Run 的内部执行游标。

## 把构建数据回存长期目录

固定证据构建使用既有入口：

```python
from gymts.training import build_dataset

built = build_dataset(build_spec, gym.records, gym.artifacts)
```

这里返回的 `gymts.dataset/1` 描述本次构建：输入 RecordSnapshot、构建配置、输出 shard、奖励、tokenization 和血缘都引用 Run CAS。长期目录使用另一种资源：`gymts.source-dataset/1` 或 `/2`。显式发布会把必要字节复制到 `data_home`，然后登记可发现的数据集修订。

没有真实来源定义的构建结果使用 `/1`。已有真实来源时，可以沿用快照或采集入口登记 `/2`。数据 reader 由适配器提供；发布前应选择与 shard 格式匹配的 reader。

直接调用如下。`built` 可以是原 Manifest、带 `manifest_ref` 的构建返回对象，或该 Manifest 的 ArtifactRef；reader 必须匹配原 shard 格式。

```python
published = gym.environment_ts.datasets.publish_build(
    built,
    dataset_id="local/derived-data",
    reader_ref=reader_ref,
    aliases=("1.0.0",),
)
rows = gym.environment_ts.datasets.load_dataset(
    published["dataset_id"], config=published["config"],
    revision=published["revision"], split="train", purpose="training",
)
```

调用签名为 `publish_build(build, *, reader_ref, dataset_id=None, config="default", usage_policy=None, parents=(), aliases=())`。发布保留原 shard 字节，在私有 `source_files` 保存可移植构建证据及原制品到长期资产的索引；公开读取不暴露这些原始证据。输入证据中的原始引用仍可用于核对，但数据读取不再依赖原 Run root。

发布默认维持训练用途，可进一步收窄。它不自动增加 runtime 或 evaluation 授权；评价专用数据不能在回库时改成训练数据，生成标签不能自动升级为人工 gold。私有参考保留独立读取边界。

## 查询一条实验链

查询应围绕已保存的身份，而不是日志文本中的路径：

- 按 group 与 revision 查看阶段、全部 attempts、解析配置、错误与具名输出。
- 从 attempt 查到它建立的一个或多个 Run，再查看原有事件和封存结果。
- 按固定 dataset 查询相关实验与 Run；source 定义及实际采集关系保留在阶段输入和数据清单中。
- 沿结果引用读取原评价报告，使用原 ScoreSpec 路径独立重评。

公开查询入口为：

```python
state = gym.experiments.inspect(group_id, revision=revision)
groups = gym.experiments.query(
    dataset_id="local/derived-data", dataset_revision=fixed_dataset_revision)
runs = gym.records.list_runs(
    group_id=group_id, revision=revision, status="succeeded")
events = gym.experiments.events(group_id, revision=revision, after_seq=0)
```

`inspect` 包含 stages、全部 attempts 与关联 runs。每个 attempt 的 `request_ref` 指向 `gymts.stage-request/1`，固定绑定状态、执行器、用途、输入、配置、数据清单身份与 provenance；绑定失败也保存 `binding_status="failed"` 的请求。`result_ref` 固定返回对象，`outputs` 保存具名结果。`query` 可按 group_id、dataset_id/dataset_revision 或组状态筛选；数据筛选也匹配输出清单中明确保存的父引用：source-dataset/2 lineage.parents，以及官方 source-dataset/1 构建发布的 features.parent_datasets，不递归搜索任意 payload。`list_runs` 还可按 attempt_id、Run 状态和数据筛选。`events` 为有序组织事件，不替代 Run 内部轨迹。Run 查询结果区分原始 `organization` 与 `associations`：重评已有 Run 只增加关联，不改变其原始归属、封存结果或事件。

阶段执行成功只表示该执行入口按约定完成。AutoBench 报告中的 coverage、missing、invalid、指标和 Gate 结论仍是评价事实；组织层不覆盖这些事实。

## 旧用法仍然可用

`gym.run(spec)`、`gym.run_data(...)`、`gym.autobench.evaluate(...)`、`gym.autobench.score(...)` 和数据目录接口继续可以独立使用，不要求先登记实验组。

历史 Run 没有新组织关联时，仍可读取、评分和重评。新索引不会修改旧事件，也不会把历史 Run 伪装成本轮新 attempt 的产物。

F1 是 GymTS 0.5.1 / 接口规范 1.3.0 的历史冻结基线。这里新增的组织能力属于 0.6.0 / 1.4.0 工作树，需要单独记录其冻结身份与验证证据；不能把 F1 四源验收当成本页全部新行为的验收。


## F2.1 验证记录

[2026-10-21 机读报告](reports/experiment-organization-2026-10-21.json)记录确切 F2.1 wheel、源码摘要、旧 23 个 schema 不变、196 项源码外核心回归，以及 16 包兼容检查的 356 项通过与 61 项可选依赖跳过。源码包和重建 wheel 也通过安装检查。

[独立 CSV 适配示例](../examples/adapters/organization_demo/README.md)在冻结核心上将 ETTh1 的 32 行视图入库，完成四阶段、两个真实 Run、独立数值评分、新进程重评，以及卸载适配包后的读取、查询与重评。核心运行文件未改，原 Run 结果与事件保持不变。该例未设质量 Gate，因此报告保留 insufficient_evidence；这不是全量 ETT 或模型质量通过声明。

构建数据发布经删除原 Run 目录后读取验证；父数据查询在确切 F2.1 wheel 上验证。原 F2 查询遗漏、两次适配配置失败和后续成功证据均保留。封存证据已本地归档，并经解包摘要、CAS/资源资产和再次独立重评核验；活动环境和缓存不随源码上传。
