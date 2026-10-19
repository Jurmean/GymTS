# GymTS接口规范

**GymTS 接收实验计划，通过 EnvironmentTS 运行实验并保存证据，交付 RunResult；BenchTS 使用固定评价方案和独立结果依据生成 EvaluationReport。** 本文集中定义这条流程的服务入口、配置、数据对象和内部调用契约，其他文档以此为准。签名表达逻辑接口，不表示已有 SDK 实现。

GymTS 的主要模块只有 EnvironmentTS 和 BenchTS。Runner、Environment、Task、ExperimentRecords 是 EnvironmentTS 内部执行与记录实验所用的对象；Candidate 是运行时通过适配调用的算法、模型、流水线或 Agent。基础调用为进程内同步、单实例串行；底层服务可通过平台或本地适配实现。

## 对外服务：提交计划，取得结果与证据

一次 Run 有明确范围或结束条件。批量、流式、交互运行都使用同一个入口。完成 Run、达到评价门槛和获得交付批准是三个不同结果：前两者由 GymTS 交付，版本选择、评审与批准由 LabTS 完成。

## 实验计划、数据视图与制品引用

### 2\.1 ExperimentSpec 的组成

```Plain Text
ExperimentSpec
  name
  scene: {environment: EnvironmentSpec, task: TaskSpec, binding: BindingSpec}
  candidate: CandidateSpec
  execution: ExecutionSpec
  recording: RecordingSpec
```

scene 可内联或引用已登记的场景版本，进入运行前解析为完整配置。name 是可选的可读名称。adapter/plugin 与 version 固定所选扩展；凭证通过现场服务解析，不写入普通配置快照。

同一原始字段的解析归 Environment 适配器；环境变量到公共任务变量的单位换算、窗口和重采样归 Task/Binding；方法自身的插补、特征与模型处理保留在其适配内部。采样周期本身不隐含平均、求和或插值。

### 2\.2 ExecutionSpec：本次怎么运行

Runner 将 training\_view 交给 prepare，将 training\_targets 放入准备上下文。适配器按 alignment\_keys 将训练输入与标签配对，例如实体、变量、目标时点。无监督训练无需标签；运行后的在线反馈另走 CandidateFeedback，BenchTS 私有评价依据不自动用作训练标签。

### 2\.3 引用与现场服务

配置可使用逻辑引用字符串，装配时先解析固定版本再调用和记录。一个可变文件路径不等于不可变制品；DataViewRef 也不等于开放整个数据仓库。所有 schema\_ref 指向具体版本的结构说明，明确字段类型和必需性。

`EnvironmentServices` 由 EnvironmentTS 注入，适配现场的 `resolve(ref) -> LocalResource`、`credential(ref) -> Credential`、`read_view(ref: DataViewRef) -> TimeSeriesData`、`save_artifact(content, metadata) -> ArtifactRef`。Environment 适配器使用连接/凭证能力；Task 经 TaskExecutionContext\.data 仅获得受限 read\_view；被测对象仅获得本次制品和获准视图的读取、保存能力。接口需对接实际平台或本地服务，不假定某平台已原生实现同名方法。

## 环境接入：把后端变成可运行、可查询的实验环境

### 3\.1 登记、装配与五个方法

```Python
class EnvironmentRegistry:
    def register(self, adapter: str, version: str,
                 factory: EnvironmentFactory) -> None: ...
    def create(self, spec: EnvironmentSpec,
               services: EnvironmentServices) -> Environment: ...

class EnvironmentFactory:
    def create(self, spec: EnvironmentSpec,
               services: EnvironmentServices) -> Environment: ...

class Environment:
    def describe(self) -> EnvironmentDescription: ...
    def start(self, spec: EnvironmentStart) -> SessionInfo: ...
    def observe(self, request: ObservationRequest) -> ObservationBatch: ...
    def act(self, command: EnvironmentCommand) -> ActionReceipt: ...
    def finish(self) -> EnvironmentSummary: ...
```

每个 Environment 实例只拥有一个会话。装配顺序为：

> 解析 source/mapping/options → create → describe → Task/Binding 检查变量语义和可用能力 → 编译 EnvironmentStart → start → 保存配置与 SessionInfo。只读回放的 operations=\[\]，名称相同不意味着单位、时间尺度和控制能力相同。
> 
> 

### 3\.2 describe：环境提供什么

能力描述针对当前已解析配置。可推进仿真可以在 observe 时推进；原生 step 推进的后端保持 on\_action；真实系统保持 external。纯观察任务使用 on\_action 时，Runner 在初始状态后显式调用 default\_command 并记录，不能把默认动作藏在 observe 中。

### 3\.3 start：本次可读什么、运行到哪里

Runner 根据任务预热和反馈需要编译 read\_scope；execution\.scope 控制产生新任务/动作的范围，feedback\_until 只延长读取。on\_action 后端没有独立可读反馈时，最后转移交付后结束，不为等待反馈追加动作。

SessionInfo 固定返回 `session_id,run_id,environment_id,source_revision,actual_mode,actual_scope:{start,end},clock,initial_cursor,seed_used,ownership:created/attached,public_context`。未知或不适用项为 null；duration 在 start 时换算实际范围，由 Runner 执行截止，Task 不另选起点。

回放定位固定数据版本与起点；仿真建立初态；Gym reset 后缓存初始 observation/info；Live attach 建立订阅或读取会话，不重置运行中的系统。历史预热需要相应 history 能力。

会话 start 后为 active；observe\(next\) 返回 end 后为 exhausted，可查已授权历史和 finish，不再 act；finish 后为 closed。同一实例不再次 start，新 Run 创建新会话。

### 3\.4 observe：请求与返回

range/query 是一次只读请求，即使结果为空也返回 data，不用 end 表示查询完成。批量任务处理完计划片段即可 finish，不必再 next。查询范围或变量不被允许时明确报错，不返回伪装成合法的空数据。

waiting 的 data/coverage/snapshot\_time 均为 null、feedback=\[\]，cursor 和 visible\_until 不变；wall 环境的 now 可以前进。data 可只含反馈或空窗进展。源耗尽后再次 next 返回相同结束原因，不重复末批内容。

EndInfo 为 `{reason,terminated,truncated,detail}`；reason 为 source\_exhausted/read\_scope\_end/backend\_terminated/backend\_truncated，detail 可为 null。原生 terminated/truncated 均保留、可同时为 true；reason 说明主要原因，不把范围到期解释为任务成功。

### 3\.5 观测格式与时间可见性

```Plain Text
TimeSeriesData: {series: list[Series]}
Series:
  entity: string
  variable: string
  unit: string
  timestamps: list[TimePoint]
  values: list[scalar | tensor | null]
  valid_mask: list[bool]
  available_at: list[TimePoint] | null
```

timestamps/values/valid\_mask 逐点等长，available\_at 非 null 时也等长；单点类型与形状遵循 VariableSpec。mask=false 对应值为 null，mask 描述整个时点值。不同序列可不等间隔；缺失整行和显式无效点分别保留。适配器不自行做 Task 窗口、插值或聚合；非时序附件用公开 context 中的 ArtifactRef，结构化原生观测按公开字段映射，不丢弃未能映射的部分。

available\_at 表示数据实际可被会话读取的时间。实时源使用后端时间或适配器收到时间；缺少该字段的历史数据可声明 event\_time 假设并记录，不能据此声称恢复了实际传输延迟。

对 time\_window，设读取前沿为 p，目标 q=min\(p\+advance\_by,read\_scope\.end\)，本批 coverage=\[p,q\)。回放或可推进仿真完成此区间即推进，即使无样本也返回 data 与 coverage；外部源到达 q、完成该段读取后才交付，否则在 max\_wait\_ms 后返回 waiting。

采集窗口关闭不意味着迟到样本全部到齐。默认保留迟到数据，按到达顺序在后续批交付并保留 available\_at，其事件时间可早于该批 coverage。Task 决定是否修订窗口，记录保存原交付顺序；丢弃策略须在 options 与摘要中说明数量。

transition 每次只交付一个状态/转移。on\_action 的 start 缓存初态，成功 act 缓存下一转移；消费初态后未 act 再 next 是顺序错误。最多一个未交付转移，再次 act 前先 observe。原生 on\_observe 后端才允许读取驱动转移；observe 取 Gym 缓存不再次 step。

cursor 是本会话的交付令牌，不是时间戳或跨 Run 恢复点，也不承诺跨后端恰好一次执行。首次 next 用 initial\_cursor，其后用最近一次 next 的返回值；act 不改交付游标，waiting 不重发已接受动作。失效游标报 cursor\_mismatch，不自动倒带。末次转移交付后不得再越界 act。

### 3\.6 act：操作、回执与后续反馈

operation\_status 的 payload 为最新 state/detail，reward 为 name/value/unit，event 使用公开事件结构。operation\_id 负责关联，不自动提供后端幂等。

Task/Binding 把任务操作转换为环境命令，适配器再转原生 API。即时回执由 TaskSession\.on\_action 接收并记录；后续 observe 只交付变化和新反馈。成功原生 step 的回执先登记，再读取转移后形成下一决策；rejected 无新转移时可继续纠正。末批 end 仍交给 Task 处理，但不再发新控制。

### 3\.7 finish：结束会话及后端对应关系

EnvironmentSummary 返回 `session_id,actual_scope,last_cursor,final_clock,end,counts,pending_operations,artifact_refs,backend_disposition`。counts 为 batches/points/operations/late\_points/dropped\_points；pending\_operations 是未完成操作 ID 列表；end 为 EndInfo 或 null，backend\_disposition 为 closed/detached。

created 会话释放所建实例，attached 会话关闭连接或订阅并脱离，不关闭真实业务系统、不撤销已执行操作。finish 也用于启动失败的清理；重复调用返回缓存摘要，无 session 时相关字段可为空、计数为 0。上层停止原因由 RunResult\.summary 说明。

Gym 的原生 info 只按明确公开字段映射到 context/feedback，其余可保留为受限调试证据，不整包透传为任务输入。

协议错误类别为 invalid\_config、unsupported\_capability、invalid\_request、invalid\_state、cursor\_mismatch、backend\_failure，携带 method/message 和适用的 request\_id/operation\_id。合法操作的 rejected/unknown 以回执表达。统一接口不保证各后端具有相同重置、延迟、动作集合或可重现性。

## EnvironmentTS 内部：整理任务、调用方法、组织运行

### 4\.1 Task 把观测变成任务和环境请求

```Python
class Task:
    def describe(self) -> TaskDescription: ...
    def bind(self, spec: TaskSpec, binding: BindingSpec,
             environment: EnvironmentDescription,
             execution: TaskExecutionContext) -> TaskSession: ...
class TaskSession:
    def next_observation(self) -> ObservationRequest: ...
    def consume(self, batch: ObservationBatch) -> TaskUpdate: ...
    def on_action(self, receipt: ActionReceipt) -> TaskUpdate: ...
    def interpret(self, task_input: TaskInput, output: CandidateOutput,
                  output_id: str) -> TaskEffect: ...
    def finish(self, reason: str) -> TaskSummary: ...
```

TaskSession 是逐 Run 的状态。consume 整理窗口及允许反馈，interpret 标准化结果并映射请求。方法自身的特征/学习留在其适配内部；统一任务输入也不强制使用某一种数组形状。

case\_id 表示一个窗口、预测发出时点、诊断问题或控制决策。query 的 complete=false 会保持 case\_id 并递增 turn\_id；command 可按任务定义继续同一 case，也可完成本决策后使用新 case。基础模板先完成当前交互，再处理后续输入；原始输出分配 output\_id 后先保存，标准化不使用后来信息改写原预测。

### 4\.2 运行时调用对象的适配契约

这一小节定义 EnvironmentTS 怎样调用选定的实现。Candidate 可封装算法、模型、pipeline 或 Agent，保留原生计算和多轮状态。

```Python
class CandidateRegistry:
    def register(self, manifest: CandidateManifest,
                 factory: CandidateFactory) -> None: ...
    def resolve(self, adapter: str, version: str) -> CandidateManifest: ...
    def create(self, spec: CandidateSpec) -> Candidate: ...
class CandidateFactory:
    def create(self, spec: CandidateSpec) -> Candidate: ...
class Candidate:
    def prepare(self, context: CandidateContext,
                training: DataViewRef | None) -> PreparationResult: ...
    def infer(self, task_input: TaskInput) -> CandidateOutput: ...
    def update(self, feedback: CandidateFeedback) -> None: ...
    def finish(self) -> list[ArtifactRef]: ...
```

扩展装载时登记，Runner 按 adapter/version resolve，匹配任务协议与输入条件，再每 Run create 一次。实现版本、适配版本、制品版本分别记录；方法和评分器分别通过固定版本工厂装配。

LibraryTS 接入时，`CandidateManifest.origin_ref` 关联固定的库条目/实现版本；`CandidateSpec.adapter/version` 选择已登记的调用适配，`artifact` 选择需要加载的模型或状态制品，`params` 指定本次参数。制品可来自库或此前训练，无需模型文件的函数使用 null。Registry 将匹配的 spec 交给已登记的 Factory，由其创建本 Run 的逻辑调用实例；prepare 完成制品加载或会话准备。适配层负责 TaskInput 与原生调用参数、原生返回与 CandidateOutput 的转换。一个库实现可供多个 Run 创建实例，一条流水线也可引用多个库组件；组件版本随实现或固定流水线制品记录。

冻结 Agent 仍可积累本 Run 的上下文、记忆和规划状态，这不等于模型/策略训练。内部工具可由原平台处理既有输入；需要新环境数据或影响本实验系统的调用须返回 TaskRequest。多轮查询结果以同一 case 的下一 TaskInput 送回，不要求 Agent 改成单次分类器。跨 Run 继承模型或记忆须显式选择固定制品；BenchTS 私有真值不进入准备或更新。

### 4\.3 Runner 的正常调用顺序

batch 使用 range，完成所选片段后结束；stream 使用 next，窗口形成才调用；interactive 由 next 提供状态，query 支持同一任务多轮。末批 status=end 仍先 consume，并完成任务规则允许、决策时点在 execution\.scope 内的非控制 TaskInput；预测按发出时点判断范围，不按未来目标时点裁剪。已终止环境不再 act。draining 阶段不产生新预测/动作；waiting 只继续读取。query、command 回执和末批触发的允许反馈按同一学习规则处理。

## RunResult 与实验记录：交付结果及其来源

### 5\.1 运行完成后交付什么

### 5\.2 记录服务及对象

```Python
class ExperimentRecords:
    def begin_run(self, meta: RunMetadata) -> RunRef: ...
    def append(self, run_id: str, events: list[TraceEvent]) -> None: ...
    def end_run(self, run_id: str, result: RunResult) -> None: ...
    def get_run(self, run_id: str) -> RunRecord: ...
    def read_events(self, run_id: str, query: EventQuery) -> EventPage: ...
    def attach_outcomes(self, run_id: str, outcomes: list[OutcomeRecord]) -> None: ...
```

Runner 调用前三个方法组织实验证据；获准调用方读记录；结果采集或评价流程用 attach\_outcomes 关联后到结果。Run 结束不禁止关联后续结果，也不因此自动调用方法学习或控制生产系统。

kind 包含 observation、input、candidate\_output、task\_result、environment\_operation、environment\_feedback、candidate\_update、artifact、run\_end；可显式扩展方法内部阶段事件，由 Runner 关联保存。

observation 保存完整 ObservationBatch 或不可变快照，包含 data、clock、coverage/snapshot\_time、feedback、EndInfo。末批即使未形成下一 TaskInput，也保留最终状态、最后奖励和 terminated/truncated。事件用 batch\_id/request\_id 关联读取；反馈以 operation\_id 经操作记录回到 output\_id。单列反馈事件与批次内相同反馈复用 feedback\_id，不重复计奖。

Agent Platform/现场服务提供通用执行、权限、采集与存储；ExperimentRecords 补齐实验领域关联。只有明确选入实验的生产片段进入本次证据，不能把导入材料标成此次被测对象刚执行的结果。实际流不能依赖可变查询路径复核，必要时保存观测快照。

## BenchTS：使用固定结果和独立依据评价

```Python
class Scorer:
    def score(self, results: ResultView, outcomes: OutcomeView,
              context: ScoringContext) -> ScoreResult: ...
```

BenchTS\.evaluate 为固定候选/基线与案例组合生成 ExperimentSpec，经 EnvironmentTS 执行，再读取记录形成 ResultView。Scorer 将其与独立 OutcomeView 对齐评分，BenchTS 按 comparison 汇总。BenchTS\.score 直接复用旧 Run，不要求方法生成“修正后预测”。

门槛判断为 pass/fail/insufficient\_evidence；缺少真值或样本不足表达为证据不足，不用零替代。重评分生成新 evaluation\_id，引用原 Run 和本次评分/结果版本；后到更正不覆盖原预测或旧报告。



