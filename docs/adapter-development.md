# 适配器开发指南

本指南面向为 GymTS 接入新项目、数据源、任务、算法、模型或 Agent 的开发者。对应当前 `gymts==0.5.0` 和正式接口规范 `1.2.0`。完整的消息字段以[接口规范](feishu/GymTS接口规范/GymTS接口规范.md)与[公共 Python 协议](../gymts/contracts/protocols.py)为准；下文的生命周期表使用当前实现的签名。

交付目标是一个单向依赖 GymTS 公共接口的独立包。核心无需导入你的项目，无需增加项目名称分支；调用方选择兼容的来源、任务、方法和评分器。仓库的 `adapters/` 只是独立包的源码位置，不意味着这些项目成为框架内置模块。

## 1. 先决定接入什么角色

EnvironmentTS 管执行与证据，AutoBenchTS 管独立评价。具体数据格式、原生后端调用与领域评分留在适配包。

| 需求 | 实现位置 | 应复用的边界 |
| --- | --- | --- |
| 读取静态数据、生成数据、推进仿真、连接实时源 | Environment | 来源、范围、时钟、观测与动作协议 |
| 定义窗口、问题、目标、轮次、动作含义与完成条件 | Task / TaskSession | 公共 TaskInput、CandidateOutput、TaskResult 与 TaskRequest |
| 调用算法、模型、流水线或 Agent | Candidate | 当前 TaskInput 与受限资源；原生 SDK 可在内部组合 |
| 用独立参考或封存事件计算领域指标 | Scorer | AutoBenchTS 的固定结果、参考和事件快照 |
| 从资源资产解码出记录 | DatasetReader | 精确获准的资产引用 |
| 把复用 benchmark 定义解析成可执行评价 | BenchmarkResolver | 原生 EvaluationSpec；不另建评价循环 |
| 从固定实验轨迹导出训练集 | DatasetBuilder | RecordSnapshot、DatasetBuildSpec、DatasetManifest |
| 给 Agent 提供工具 | 外部工具 / Agent SDK 适配 | Agent 决策、实际工具执行证据、环境读写权限 |

一个包可以实现一个或多个角色；无需为了接入一个新模型而复制数据读取器、Task 与 Scorer。领域合同也可单独发包，例如现有 `gymts-timeseries` 与 `gymts-interaction`：合同包不依赖某个模型或服务，具体实现各自依赖它。

普通算法 Candidate 直接运行算法。Agent Candidate 则由 Agent 决定调用哪个工具、传入什么参数以及如何消费结果。LibraryTS、MCP 等工具集是可替换的外部能力，不是固定核心组件。完整职责见[外部工具集与 Agent](agent-toolsets.md)。

## 2. 第一个独立包：只增加一个 Candidate

[minimal_demo](../examples/adapters/minimal_demo/README.md) 是可运行的教学包，实现时间尺度感知的漂移预测，复用已有回放 Environment、`window_forecast` 和 `forecast-mae`。它不增加框架功能，不读取私有标签，不需要网络或模型。

```text
examples/adapters/minimal_demo/
├── pyproject.toml                       # 独立发行包与 entry point
├── README.md
├── rescore_without_adapter.py           # 卸载后只依赖 GymTS 的评分检查
└── src/gymts_minimal_demo/
    ├── __init__.py                      # register(registries, schemas)
    ├── candidate.py                     # Candidate 生命周期
    └── __main__.py                      # 原生运行、独立参考、同 Run 重评
```

从完整仓库检出安装，Python 3.9+：

```sh
python -m venv /tmp/gymts-adapter-tutorial-env
/tmp/gymts-adapter-tutorial-env/bin/python -m pip install . ./examples/adapters/minimal_demo
cd /tmp
/tmp/gymts-adapter-tutorial-env/bin/python -I -m gymts_minimal_demo \
  --root /tmp/gymts-adapter-tutorial-runs
```

运行目录须为本次新目录。教学包不随核心 wheel/sdist 发布；上面的安装命令从仓库根目录执行。正式接入可单独建立仓库、构建 wheel 并向自己的包索引发布；不要假定所有适配包已发布到 PyPI。

检查项包括：纯计划不构造 Candidate；真实 `evaluate`；缺参考时明确 `insufficient_evidence`；用独立线性函数生成参考后 `score`；禁止再次推理后重复评分；Run ID、原始 RunResult 和事件摘要保持一致。该构造数据上预期 MAE 为漂移方法 `0.0`、last-value `1.0`，仅用于接入验证，不代表预测质量。

### 2.1 三种名称各自独立

| 名称 | 教程值 | 用途 |
| --- | --- | --- |
| Python 发行包 | `gymts-minimal-demo==0.1.0` | 安装、升级、卸载 |
| integration entry point | `minimal-demo` | 显式启用一组注册 |
| 组件引用 | `example-drift@1.0.0` | 固定一次实验所选实现与兼容协议 |
| 参数 schema | `example.minimal/drift-params/1` | 校验这个组件接受的 JSON 参数 |

版本固定不能使用 `latest`、`main` 或 `master`。发行包版本、协议版本和组件语义版本不是同一个概念。

### 2.2 发现和启用

`pyproject.toml` 定义：

```toml
[project.entry-points."gymts.integrations"]
minimal-demo = "gymts_minimal_demo:register"
```

注册函数只登记 schema、manifest 与工厂：

```python
def register(registries, schemas):
    schemas.register(PARAMS, parameter_schema)
    registries.candidates.register(manifest, CandidateClass)
```

调用方先发现，再显式选择：

```python
from gymts import GymTS

print(GymTS.available_integrations())
with GymTS(root="/tmp/my-runs", integrations=("minimal-demo",)) as gym:
    candidate_spec = {
        "adapter": "example-drift", "version": "1.0.0",
        "artifact": None, "params": {"damping": 1.0}, "inherited_state": [],
    }
```

安装不自动启用。元数据发现不导入插件代码；显式启用才执行注册函数。重名 entry point 报冲突，不按安装顺序偷偷挑选。重复启用同名 integration 不重复注册。注册失败由框架回滚注册状态，但这不撤销插件自身执行过的文件或网络副作用，因此注册必须无副作用。

### 2.3 Manifest 要声明真实能力

Candidate manifest 包含固定 `component_ref`、`implementation_ref`、`component_refs`，支持的协议及输入输出 schema，参数 schema，以及 `supports_fit`、`fit_requires_targets`、`supports_update`、`model_revision_mode`、`capture_profiles`。教学包声明不训练、不更新、无模型制品、无内部模型调用采集。

不要为通过组合检查声明实际没有实现的能力。支持一种输入形状，不等于支持所有同名时序任务；能够发出一个 seed 参数，不等于后端实际执行了该 seed；拿到 IO，也不等于拿到原生 token、logprob 或训练权重身份。

完整注册示例见[教学注册函数](../examples/adapters/minimal_demo/src/gymts_minimal_demo/__init__.py)。Environment、Task、Scorer manifest 的完整字段见[公共 Registry](../gymts/registries/__init__.py)。

### 2.4 Candidate 生命周期

```python
prepare(context, training) -> PreparationResult
infer(task_input) -> CandidateOutput
update(feedback) -> UpdateResult
finish() -> list[ArtifactRef]
```

工厂在运行阶段接收 CandidateSpec。`prepare` 获取本 Run 的受限 `resources`、`learning`、独立随机上下文及可选 `traces`。纯算法在 `load_only/frozen` 下拒绝训练与更新；模型加载放在运行阶段，不放在 import、注册或纯计划回调中。

`infer` 只处理获准的 TaskInput。用公共 `gymts.plugin_support.unpack(payload, resources)` 读取 inline 或获准 artifact payload；用 `payload(schema_ref, value)` 生成输出。输出必须关联原来的 `input_id` 与 `task_protocol_ref`，真实记录 `produced_at` 和 `model_revision`。不要自行生成 Run ID，不要把整个 GymTS、records、私有数据目录或 Environment 实例传给方法。

`finish` 释放本 Candidate 创建的资源，并返回需要保留的制品引用。发生部分失败时保留已有证据。每个 Run 使用独立会话；跨 Run 继承必须通过显式、固定制品引用，不能藏在全局变量或共享模型缓存中的隐式更新。

## 3. 数据与 Environment 适配

### 3.1 先声明，再打开

现行 API：

```python
describe_spec(environment_spec) -> EnvironmentDescription  # 纯声明回调
check_compatibility_spec(context) -> None                   # 可选，纯校验

describe() -> EnvironmentDescription
start(environment_start) -> SessionInfo
observe(observation_request) -> ObservationBatch
act(environment_command) -> ActionReceipt
finish() -> EnvironmentSummary
```

Environment 和 Task 的纯 `describe_spec` 用于规划；也可以在 Registry 注册时传入独立的 `describe=`、`compatibility=` 回调。Candidate 可提供纯兼容校验；当前规划不要求 Candidate 实现 `describe_spec`。

纯计划回调只能检查 JSON 配置与已声明能力，不构造运行对象、不读源文件、不读凭证、不连接服务、不加载模型、不写 CAS。`validate` 与 `plan` 成功表示配置和声明兼容；文件存在、服务可达、模型可加载等检查在 Run 建立后的运行阶段完成，失败进入实际失败轨迹。

EnvironmentSpec 的 `source.kind` 支持 `dataset`、`generator`、`simulator`、`live`。只有声明过的能力才可使用：静态数据不冒充可控制仿真；附着真实服务不宣称能重置或按 seed 重建世界。

### 3.2 来源事实与任务含义分开

来源描述负责原始变量、类型、形状、单位、可用范围、操作、时间域及推进模式。`mapping` 属于来源自身字段解析。`binding` 把来源变量/操作对应到 Task 的公共变量/操作，转换须显式声明。窗口、预测步长、题目、标签含义、奖励解释和评分标准属于 Task 或 Scorer。

公共观测保留时间戳、valid mask、游标、进展/等待/结束、上下文与来源身份。静态 QA 使用样本游标，不伪装成业务事件时间。大数组或原生格式可保存为 ArtifactRef；框架不要求将所有内容转为文本。

Environment 可通过 `source.connection.artifact_refs` 获得精确输入制品授权。框架不会递归授权制品里嵌套的全部引用，这些引用也不会自动交给 Candidate。授予当前输入访问不等于授予原文件、未来数据或私有答案访问。

### 3.3 时钟、游标与末状态

| 概念 | 开发要求 |
| --- | --- |
| `clock.domain` / `clock.now` | 按真实 event_time、wall_time 或 step 语义表达；不倒退 |
| `visible_until` | 已交付信息边界，不因等待或任意历史 query 扩大 |
| `event_time` / `available_at` | 事件发生与实际获知分开；不知道原始摄入时间时明确说明 |
| `cursor` | 表达真实推进位置；waiting 不偷偷前进 |
| 半开范围 | GymTS 范围按 `[start, end)`；后端端点语义不一致由适配器转换 |
| 空窗与结束 | 有进展的空窗、尚未成熟的 waiting、正常结束和失败分别表达 |
| 最后一次 transition | 即使终止或达到边界，也保留末观测、实际奖励与结束原因 |

EnvironmentSummary 必须包含 `session_id`、`actual_scope`、`last_cursor`、`final_clock`、`end`、`counts`、`pending_operations`、`artifact_refs`、`backend_disposition`。`counts` 包含 batches、points、operations、late_points、dropped_points；未启动字段可为空。`backend_disposition` 只能是 `closed`、`detached`、`not_started`。不要用一个项目专有字符串替代正式枚举；详细清理结果放入独立证据制品。

### 3.4 动作只执行一次

控制型后端建议使用：`act` 调用一次原生 step，缓存实际 transition，返回关联 operation 的 receipt；随后 `observe` 消费缓存，不能再调用一次 step。取消发生在 act 和 observe 之间时，保留已发生但尚未消费的 transition，不能把它写成未执行或完整 episode。

超时或丢连接不证明动作没生效。记录未知/不确定状态，不自动重发；只有后端明确提供已验证的幂等键与保证时才实现相应重试。TaskRequest、environment_request_id、operation_id 与回执必须关联真实执行。

自然终止、后端截断、实验 scope 截断分开。OpenEnv 只有 `done` 时保留该原始字段与未知分类，不能猜成 Gymnasium 的 `terminated`。后端未提供奖励时保留 `null`，Scorer 报缺证据，不能补成零奖励。

可复用的外部实现见 [gymts-interaction](../adapters/interaction/README.md)。它不进入核心；Gymnasium/OpenEnv 等适配包可复用其缓存和中立控制合同。

### 3.5 资源所有权与实时可复现性

区分本 Run 创建的 session 与附着的 host。本 Run 创建的仿真实例可以关闭；连接别人运行的服务不能在 finish 中杀服务器。关闭自己的 WebSocket 不等于拥有远程服务。测试脚本启动的本地服务由脚本在验证完成后清理，不由通用适配器越权清理。

现场声明版本不等于已验证部署身份。动态源 revision 也不能承诺未来值不可变。记录已验证与调用方声明的部分、实际请求/响应和接收时间；需要不同 Candidate 公平比较同一现场数据时先冻结为静态快照。顺序执行两个 live Run 本身不能重放相同世界时间。

现有实现与实际调用范围见[环境适配指南](environment-adapters.md)：HF 数值时序快照、Gymnasium、OpenEnv 持续会话、Prometheus 只读抓取；各包 README 记录支持与拒绝的能力。

## 4. Task 适配：保持公共任务合同

```python
describe_spec(task_spec) -> TaskDescription
describe() -> TaskDescription
bind(task_spec, binding, environment_description, execution) -> TaskSession

# TaskSession
next_observation() -> ObservationRequest
consume(batch) -> TaskUpdate
on_action(receipt) -> TaskUpdate
interpret(task_input, candidate_output, output_id) -> TaskEffect
finish(reason) -> TaskSummary
```

TaskDescription 声明任务协议、输入/输出/结果/参考/对齐 schema、所需变量及操作、warmup 与能力。Task 根据公共环境描述与 Binding 工作，不检查来源 Python 类名、某个模型名或外部项目名。

TaskSession 把公开观测转换成 TaskInput；解释 CandidateOutput，生成领域结果或 TaskRequest。Candidate 想读新环境数据或操作现场，必须经过 TaskRequest → Runner 检查 → Environment，再把实际观测/回执交回同一会话。Task 不根据标准答案修正模型结果，也不直接计算最终 benchmark 结论。

定义公共合同不仅要有 JSON 形状，还要有单位、时间索引、有效掩码、目标、结束与多轮语义。相似字段不等于可替换任务。改变语义时新增版本或适配层，不把旧输入重新解释成新任务。

## 5. Scorer：独立评价与重评

```python
score(results_view, outcomes_view, context) -> ScoreResult
```

Scorer 的输入由 AutoBenchTS 固定。通过 `context["services"]` 读取获准的结果/参考制品，按声明的 alignment 对齐并计算指标。需要核对控制 episode 的实际回报时，读取固定 `event_snapshot_ref`，验证 action/receipt/transition 链；不要信任 Candidate 自报的回报。

每项指标声明方向、单位、是否需要参考、eligibility 合同。先固定 eligible 分母，再报告 scored、missing、invalid、excluded；缺标签、未知结束原因、未采集奖励等必须明确缺证据，不能删掉困难样本来提高覆盖率。Scorer 只输出度量及证据，AutoBenchTS 按配置进行组/聚合、覆盖门槛、比较和 gates。

`evaluate(EvaluationSpec)` 产生新 Run 并评价；`score(ScoreSpec)` 选择已有封存 Run，产生新评价报告。重评可以使用新到达但明确固定的参考或新版 Scorer；记录 previous_evaluation_id、参考 cutoff、组件版本与全部选择。不得修改旧预测、旧 RunResult 或旧报告，也不得为了评分重新推理、训练、step 或请求 live 服务。

卸载教程方法后仍可重评：

```sh
GYMTS_CHECKOUT=/absolute/path/to/Jurmean-GymTS
/tmp/gymts-adapter-tutorial-env/bin/python -m pip uninstall -y gymts-minimal-demo
/tmp/gymts-adapter-tutorial-env/bin/python -I \
  "$GYMTS_CHECKOUT/examples/adapters/minimal_demo/rescore_without_adapter.py" \
  --root /tmp/gymts-adapter-tutorial-runs --require-absent
```

该脚本只恢复归档的 Candidate manifest 与参数 schema，并注册一个一旦被执行就报错的工厂；不恢复算法实现。现行 AutoBenchTS 即使不调用方法，仍要读取这些声明完成兼容检查。该例的 Task 合同与 Scorer 仍可用；一般项目若将合同和 Scorer 一并卸载，仍需从独立合同包或原版本归档恢复解码与评分能力。不能把“无需原模型”误解为“无需声明或原合同”。

## 6. 数据目录和 benchmark 扩展

资源目录不是新的运行引擎，也不是完整 Hugging Face Hub。当前本地服务提供版本化资产、dataset 定义、公开读取与 benchmark 解析；远程门户、账号权限、托管上传、搜索服务不在当前实现内。详见[目录设计](dataset-benchmark-catalog-design.md)。

### 6.1 DatasetReaderProvider

```python
read(resources, assets) -> list[dict]
registries.datasets.register(fixed_reader_ref, reader_instance)
```

这是格式解码钩子，不是完整数据集 importer。`resources.read_asset(ref)` / `local_asset(ref)` 仅允许本次选择的资产。JSONL 与 Parquet 已有读者；新格式可在独立包注册固定 reader。按真实行顺序与 schema 返回，不静默丢行、去重或修改内容。

导入器在 Run 外显式完成文件解析、验证、公开输入/私有目标分离和资产发布。调用 `gym.environment_ts.datasets.publish_asset(...)` 与 `register_dataset(manifest, aliases=...)`；source-dataset manifest 声明 features、splits、source_files、inputs、series、targets、reader/importer 引用和用途策略。内容 revision 固定，release alias 只是入口标签。

公共 `load_dataset(..., purpose="runtime")` 不返回私有答案；训练用途还要显式允许。`EvaluationDataset.read_targets()` 只经 benchmark 解析侧的评价服务获得。原始文件本身也可能泄露答案，不能默认把 source_files 路径交给 Candidate。使用过某数据作测评并不授权训练，文件名包含 `rlvr` 也不改变这一点。

### 6.2 BenchmarkResolverProvider

```python
resolve(definition, resources, candidates, purpose, repetitions) -> EvaluationSpec
registries.benchmarks.register(fixed_resolver_ref, resolver_instance)
```

benchmark 定义固定 dataset/config/revision/split、resolver_ref 与任务参数。解析器只能加载定义选中的评价数据，按公共行构造 Environment/Task/case，并从私有参考构造独立 Outcome 视图。保留调用方传入的 candidates、purpose 与明确指定的 repetitions，不另开模型循环或产生第二套正式报告。

```python
spec = gym.autobench.resolve_benchmark(
    "my/benchmark", revision="fixed-release",
    candidates=selected_candidates, purpose="regression",
    repetitions={"count": 1, "seeds": [7]},
)
report = gym.autobench.evaluate(spec)
```

AutoBenchTS 负责来源用途交集、资源 provenance 与原生计划检查，resolver 不自行覆盖 provenance。真实例子见 [HF resolver](../adapters/hf_datasets/src/gymts_hf_datasets/benchmark.py) 与 [bench-tsqa](../adapters/bench_tsqa/README.md)。

## 7. 训练导出与复用现成训练后端

训练导出入口是公共 `gymts.training.build_dataset(spec, records, artifacts)`；项目实现独立 DatasetBuilder。它不是 EnvironmentTS/AutoBenchTS 之外的第三个核心业务模块，也不意味着框架会自动更新模型。

```python
class MyBuilder:
    builder_ref = {"name": "my.rollout-builder", "version": "1.0.0", "origin_ref": None}
    target_formats = ("my-fixed-format",)
    output_schema_refs = ("my.training-row/1",)

    def build(self, spec, records, artifacts):
        ...  # 读取固定快照，保存 shard、血缘、排除摘要，返回正式 Manifest。
```

通过单独的 entry-point group 发布 provider：

```toml
[project.entry-points."gymts.dataset_builders"]
"my.rollout-builder" = "my_package.builder:MyBuilder"
```

也可以使用 `DatasetBuilderRegistry(discover=False)` 显式注册实例，并将 `builders=` 传给 build_dataset。此注册不使用 `gymts.integrations`；构建器按 DatasetBuildSpec 固定的 builder_ref 单独选择并加载。

构建器声明 target 格式/schema，核对选定轨迹、训练许可、reward 来源、token/mask 与样本血缘，输出 DatasetManifest、shard 引用、build_spec_ref、lineage_ref、exclusion_summary_ref 和计数。框架检查公共包络、固定身份、来源用途、制品与 Manifest 一致性；领域 mask 与奖励规则由适配器校验。缺失采集不能伪造成原生 token/logprob。

RewardRecord 必须来自明确的环境、verifier、人工或指定规则，trace 本身不是 reward。评价专用数据不能因换一个 builder 变成训练数据。训练器优先复用 TRL/verl 等外部实现；原生模型、processor、优化器、checkpoint 发布和训练 journal 留在训练适配包。现有具体流程见 [RL 集成](rl-integration.md)与 [gymts-rl](../adapters/rl/README.md)。

## 8. 模型与工具调用证据

Candidate 在 infer 期间可通过 `context["traces"]` 提交真实 `record_model_call(...)` / `record_tool_call(...)`，是否启用由 recording 与支持的 capture profile 决定。框架绑定当前 Run、input 和预分配 output 关联；按正式 schema 保存原始请求/响应、attempt、status/error、版本与实际可获得的计量。

多个工具调用关联原生 call ID、parent_call_id 和 attempt_id。模型提出 tool_call 只是意图；必须另记工具实际成功、失败或未知状态。普通计算工具可以不含环境 operation_id；新增环境读取/动作必须关联 TaskRequest 与 Runner 的真实请求/操作。工具调用不能成为绕过未来数据和私有参考边界的入口。

保留已知失败与部分证据；原始返回先留存，再解码。不要用空成功结果覆盖失败，不伪造 tokens、费用、后端 seed 生效或部署摘要。凭证只通过运行阶段的显式 provider 或环境变量名获取，不写进配置、URL、CAS、日志或示例。

接口限权是可信同进程插件的职责合同，不是操作系统沙箱。安装、启用第三方 Python 包意味着信任其代码。需要隔离时在外部进程、容器或服务提供隔离，并单独验证资源与网络边界。

## 9. 兼容升级与独立发行

适配器只从 `gymts.contracts`、`gymts.contracts.schema`、`gymts.plugin_support`、公开目录/训练入口等公共接口导入；不要依赖 `_common`、Runner 内部状态或某个项目的私有类。若依赖共同领域合同，将其声明为独立依赖，不反向要求核心导入项目。

生产适配包通常保留独立 pyproject/setup 配置、README、许可证信息、测试、示例、runtime extras 与固定兼容范围。重型科学依赖、原生 SDK、模型和服务二进制不应因仅安装或发现核心而加载。核心无模型环境下仍须可导入、运行参考案例和重评旧证据。

升级时新增语义版本，保留旧引用的含义与旧证据；不要把历史协议 ID 批量重命名或改写封存记录。新的实现可以支持旧合同，也可显式拒绝不兼容组合。数据端、Task、Candidate、Scorer 是否可替换，以双方合同、单位、形状、权限、seed/时钟和真实运行验证为准，不以注册成功为准。

发布前至少执行：

1. 构建 wheel、sdist；从 sdist 重建 wheel；检查不包含密钥、模型、实验数据库或未声明资产。
2. 在源码目录外的干净环境安装；发现不导入运行 SDK；显式启用；非法配置与非法角色组合在纯计划拒绝。
3. 跑最小真实后端，保存成功、失败、末状态与清理证据；协议 fixture 测试不能冒充真实后端验收。
4. 用独立参考评价；禁止模型/后端再调用后重评相同 Run；比较 Run ID、结果和事件摘要。
5. 替换兼容角色，测试来源/任务/方法独立组合；卸载一个项目后其他项目与核心案例继续运行。
6. 验证所声明的最小 Python 版本、可选依赖缺失路径、包兼容范围与 README 命令。

仓库的[适配包检查脚本](../scripts/check_adapters.py)针对 `adapters/*` 的正式包执行隔离构建、启用、卸载和组合检查；教学包位于 `examples/`，采用上面的独立原生 smoke 命令，不被列成生产适配器。

## 10. 何时才应修改核心

先用最小真实项目证明当前合同不能表达什么，再判断是否为跨项目职责。数据字段、模型 SDK 差异、PromQL、Gymnasium 空间转换、后端 done/reward 语义通常应由项目适配或外部领域合同解决。不要为接入一个项目在核心增加命名分支。

任何核心变更必须记录：

| 必填项 | 需要回答的问题 |
| --- | --- |
| 真实需求与最小复现 | 哪个已运行项目、何种有效操作当前无法表达？ |
| 适配器为何不够 | 是否缺少框架掌握的授权、关联、调度或不可变证据能力？为何不是领域格式问题？ |
| 最小公共改动 | 增加哪个跨项目接口或字段？哪些角色会实际使用？ |
| 兼容性 | 默认行为、旧调用方、旧协议引用、旧 Run 和旧 Scorer 如何保留？ |
| 验证 | 新项目原生运行、旧项目回归、失败清理、评价与同 Run 重评证据在哪里？ |
| 冻结依据 | 核心版本、源码摘要、确切 wheel SHA256、适配器与原生后端版本是什么？ |

定期冻结一个确切核心 wheel，让另一个项目通过独立包完成安装、运行、留轨迹、独立评价与重评，期间不改核心。记录“没有修改核心”与实际摘要校验；若确有缺口，更新决策、版本与兼容测试后再冻结。包安装通过不等于领域兼容；一次算法实验也不等于 Agent 自主工具循环验收。

## 11. 当前接口与设计草案的区别

本文使用现行 Environment/Task/Candidate/Scorer API。[可插拔设计](pluggability-design.md)与[合同 v2 草案](pluggability-contract-v2.md)中部分 `SourceProvider.open`、Method/Runtime 拆分、ToolBroker 是设计方向，不能当作已实现函数复制调用。

当前核心没有通用 ToolBroker，也没有经过交付验收的通用自主 Agent 工具循环。可用原生 Agent SDK 在外部 Candidate 内实现循环，按当前公共请求/证据协议接入；若遇到无法表达的真实需求，按上一节记录并讨论最小核心扩展。不要通过文档把尚未实现的草案变成发布承诺。
