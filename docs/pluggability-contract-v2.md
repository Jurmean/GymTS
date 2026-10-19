# GymTS 三端公共消息与调用协议草案

状态：`2-draft.1`，设计与消息推演，尚未实现，不替代接口规范 1.0.0。本次只增加文档、JSON schema、输入文件和证据样例，没有修改运行代码。ChatTS 响应是明确标记的合成 fixture；独立方法的结果来自临时参考计算，均不表示新插件已安装或部署。

三端的稳定连接是：Source 交付来源数据，Binding 生成任务数据视图，Task 交付公共任务输入，Method 把输入适配成原生调用。Runtime 承载 Method 会话，不解释任务。方法替换不能要求数据端生成另一种 model_input，也不能要求 Task 根据模型名称分支。

本版固定一个可检查的最小配置：冻结方法、单个标量序列、规则时间戳、有限只读窗口、单请求串行执行。预测与趋势任务完整展开；查询和动作有消息合同及调用规则，但本轮组合样例不构成这些能力的执行验收。拟合、在线更新、并行调度和原生训练导出需要各自的扩展合同。

## 1 交付文件与阅读顺序

| 文件 | 用途 |
| --- | --- |
| [schema.json](contracts/pluggability-v2/schema.json) | JSON Schema 2020-12，定义消息、角色描述、配置与公共 payload 的字段、枚举、必填及判别联合 |
| [fields.md](contracts/pluggability-v2/fields.md) | 与 schema 对应的逐字段索引，便于人工审阅 |
| [payload-registry.json](contracts/pluggability-v2/payload-registry.json) | schema_ref 到具体 payload 或配置定义的解析表 |
| [walkthrough/index.json](contracts/pluggability-v2/walkthrough/index.json) | 2 个来源、2 个任务、2 个方法的组合与语义摘要 |
| [validation-report.json](contracts/pluggability-v2/validation-report.json) | 结构、跨消息约束、替换比较和负例的检查结果 |

schema 定义结构约束；本文规定跨字段、跨消息和时间语义。二者共同构成草案。嵌套 Payload 的 schema_ref 必须经过注册表二次解析，不能因为外层 Payload 结构合法就跳过 value 校验。

## 2 公共类型与字段规则

每个对象默认拒绝未声明字段，全部字段必填；允许缺值的字段显式为 null。扩展信息使用带 schema_ref 的 Payload，不往公共消息随意增加字典键。JSON 数值必须有限，禁止 NaN 和 Infinity。

| 类型 | 字段与语义 |
| --- | --- |
| ComponentRef | `id: string, version: x.y.z`；精确任务合同或组件身份，不使用 latest |
| ArtifactRef | `uri, sha256, media_type, schema_ref: string|null, size_bytes: int`；只引用已提交内容，摘要校验原始字节 |
| Payload | inline 为 `{schema_ref, storage: inline, value}`；artifact 为 `{schema_ref, storage: artifact, artifact_ref}`，两种内容互斥 |
| TimePoint | UTC RFC3339 字符串或非负整数；同一 Source 的 clock_domain 决定使用哪一种，不混用 |
| TimeScope | `{start, end}`，区间为 `[start,end)`；end 可为空，开始必须早于非空结束 |
| Clock | `{domain: event_time|sample_index|step, now, visible_until}`；now 是交付时钟，visible_until 是已授权的可读时间上界，均不等于游标 |
| Error | `{code, stage, message, retry: never|idempotent_only, effect_state: none|unknown|committed, details}` |

ArtifactRef.uri 是服务可解析的位置，不授予访问权，不包含凭证。消息引用制品后，仍需对当前角色授予读权；不能通过一个引用递归打开整个仓库。

`recorded_at` 是宿主记录事件的时间，与序列 timestamps、available_at、decision_time 分开。样例使用固定的历史时间，便于逐项核对。生产比较须先把时间解析为统一时间值，不能依靠字符串排序代替时间计算。

所有消息采用同一个包络：

| 字段 | 类型 | 所有者与约束 |
| --- | --- | --- |
| protocol | 固定 `gymts.wire/2-draft.1` | 宿主检查主协议 |
| kind | 消息类型枚举 | 如 Observation、TaskInput、MethodResponse |
| message_id | string | 宿主分配，同一 Run 内唯一 |
| sequence | 正整数 | 宿主持久化时分配，从 1 连续递增；跨进程事件也按宿主接受顺序记录 |
| run_id | string | 宿主分配，参与者不得改写 |
| caused_by | string|null | 当前 Run 中已经记录的触发消息 ID；独立后到的 Outcome 可为空 |
| recorded_at | UTC RFC3339 | 宿主在持久化时赋值 |
| body | 对应类型对象 | 具体字段由 kind 决定 |

TaskInput 的 `message_id` 就是它的 input_id，不再在 body 重复存一份。TaskResult 同理。invocation_id 标识一次方法调用，即使同一个输入被显式重跑，也必须有新的调用 ID 和完整记录。

## 3 装配与访问上下文

Selection 为 `{component: ComponentRef, params_schema_ref, params: object}`。先验证 params_schema_ref，再验证 params；插件配置的自定义字段不进入核心消息。

RunSpec 包含 `source, task, binding, method, runtime` 五项选择，以及 `read_scope, decision_scope, decision_as_of, seed, limits, recording`。Limits 包含 max_inputs、max_turns_per_case、max_operations、call_timeout_ms 和 require_hard_timeout。recording 在本版固定为 strict_io，learning 固定为 frozen。

| 对象 | 关键字段与检查 |
| --- | --- |
| SourceDescription | component、clock_domain、advance_mode、observation_schema_ref、variables、read_modes、operations、start_modes、supports_seed、public_context_schema_ref |
| TaskDescription | component、contract_ref、input/answer/alignment_schema_ref、required_variables、required_read_modes、required_operations、clock_domain、minimum_points、missing_policy、max_turns |
| MethodDescription | component、contracts、accepted_modalities、accepted_runtime_kinds、supports_fit、supports_update、supports_cancellation、required_capture |
| RuntimeDescription | component、kind、persistent_sessions、hard_timeout、supports_cancellation |
| Plan | spec_sha256、components、resolved_binding、method_description、runtime_description、deployment_verified、issues |

Task 的变量要求包含变量名、单位、dtype、shape；Source 的变量还包含 value_schema_ref。Binding 每项给出 task_variable、source_variable、source_unit、task_unit 和 transforms。operations 映射任务操作到来源操作，未声明操作不可执行。

第一版数值样例使用恒等绑定，transforms 为空。可配置的逐值 Transform 接口为 `apply(series: Series, selection: Selection) -> Series`，不得连接模型，必须保留实体、时间、掩码和可用时间，只修改声明的变量名、单位和值并记录前后引用。重采样会改变时间与可用性，不能套用此接口；本版不宣称已有重采样合同。

Plan.components 锁定角色、组件、发行包、实现摘要和配置摘要，包含被选中的公共任务合同及 Codec。草案中的发行包名是目标设计，实现摘要为 null；这使计划可以用于离线审阅，但不满足可部署的锁定验收。正式运行须解析实际代码身份；远程服务权重无法核实时保持 weights_verified=false。

describe/plan 仅查声明和配置，不调用 factory 创建会话，不读取凭证、连接服务或下载权重。可用性检查单列为 probe；open 再核对实际能力。inprocess 不支持强制中断，require_hard_timeout=true 必须拒绝，不把调用边界计时当成强制超时。

上下文也使用显式字段，禁止传整个 GymTS 或 Source 对象：

| 上下文 | 字段 | 接收者可获得什么 |
| --- | --- | --- |
| SourceContext | run_id、handles | 明确授予的数据读取服务；数据文件路径由 Source 配置解释 |
| TaskContext | run_id、task_session_id、read_scope、decision_scope、decision_as_of、max_turns | 定义任务范围；没有模型配置和私有标签 |
| MethodContext | run_id、method_session_id、handles、learning、input_grants | 本次调用的已授权输入、证据出口，以及显式授予的凭证/工具句柄 |
| ServiceHandle | id、service、operations、resource_refs | 可序列化的服务引用和允许操作；不是任意 Python 对象 |

同进程可信插件仍可能绕过 API 自行访问文件或网络。这些上下文是接口边界；真正的访问隔离需要独立进程或容器策略，不能由字段声明自动保证。

## 4 数据端消息与接口

| 接口 | 输入 | 返回 | 允许的副作用 |
| --- | --- | --- | --- |
| SourceProvider.describe | Selection | SourceDescription | 无 |
| SourceProvider.open | SourceOpen.body | SourceSession 和 SourceOpened.body | 此时才打开数据或连接现场 |
| SourceSession.read | SourceRead.body | Observation.body | next 可推进读取游标；query 不推进 |
| SourceSession.act | SourceAct.body | ActionReceipt.body | 仅声明支持操作的来源可实现 |
| SourceSession.close | Close.body | Closed.body | 关闭自己创建的资源，或脱离自己的附着会话 |

SourceOpen 字段为 source、context、start_mode、read_scope、availability_cutoff、allowed_entities、allowed_variables、allowed_operations、seed。读范围、变量和可用时间三项限制共同生效。

SourceOpened 返回 session_id、source_component、source_revision、dataset_revision、actual_read_scope、clock、cursor、ownership 和 public_context。source_revision 标识物理来源修订；dataset_revision 可标识同一逻辑数据快照，不能代替物理来源血缘。

SourceRead 字段为 session_id、kind、cursor、selection、as_of、max_wait_ms、limit。selection 包含 entities、variables、scope。as_of 不得超过本会话的 availability_cutoff。每个交付点必须同时满足选择范围、事件时间不晚于授权时间，以及 available_at 不晚于 as_of。

Observation 字段为 session_id、request_id、source_revision、dataset_revision、status、cursor_before、cursor_after、clock、coverage、data、feedback 和 end。request_id 必须等于实际 SourceRead 的 message_id。

| status | data 与 end | 游标规则 |
| --- | --- | --- |
| data | data 可为有进展的空帧；end=null | next 需要推进；query 保持主游标 |
| waiting | data/coverage/end 均为空，feedback 为空 | 不推进，不触发重复方法调用 |
| end | end 必填，可以携带最后一批 data | 最后数据只交付一次，后续 next 不重发 |

coverage 表示固定来源已完成读取的选择区间，不授予额外时间权限。它可以是 `[00:00,00:06)`，而实际交付点和 visible_until 只到 `00:05`；方法只能看到实际授权交付的数据。外部实时源不能借这种覆盖表示尚未开放的未来数据。

数值数据使用 SeriesFrame，字段为 `series: list[Series]`。每条 Series 包含 entity、variable、unit、timestamps、values、valid_mask、available_at。四个逐点数组必须等长；mask=false 对应 value=null；同一帧中时间严格递增，不丢失缺失点或实际可用时间。其他数据模态使用另一个明确声明的 payload schema，不能假装是标量 Series。

Binding 在宿主中生成 BoundObservation：task_session_id、source_observation_ref、binding、status、clock、coverage、data、feedback、end。它保留原观测引用，将 cpu_pct 映射为任务变量 signal，并留下转换记录。Task 接收此任务视图，不解析 CSV 列名或来源类名。

## 5 任务端消息与接口

| 接口 | 输入 | 返回 |
| --- | --- | --- |
| TaskProvider.describe | Selection | TaskDescription |
| TaskProvider.bind | TaskBind.body | TaskSession；task_session_id 由宿主预分配 |
| TaskSession.next_read | 无 | ReadIntent 或 null |
| TaskSession.consume | BoundObservation | TaskUpdate.body |
| TaskSession.interpret | TaskInput 和 MethodResponse | TaskEffect.body |
| TaskSession.on_action | ActionReceipt | TaskUpdate.body；仅操作任务需要 |
| TaskSession.finish | Close.body | Closed.body |

ReadIntent 使用任务变量：kind、selection、as_of、max_wait_ms、limit、case_key。宿主通过 Binding 映射为来源变量，填入 source_session_id 和当前游标，生成 SourceRead。Task 不持有或修改来源游标。

TaskUpdate 为 `{task_session_id, inputs: list[InputDraft], closed_cases, stream_done}`。InputDraft 字段如下：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| case_key | string | Task 生成的本 Run 逻辑案例键，宿主据此分配 case_id |
| turn_id | 非负整数 | 首轮为 0；同案例续轮必须连续递增 |
| contract_ref | ComponentRef | 公共任务合同；不使用具体模型名称 |
| decision_time | TimePoint | 本次决策时点，位于 decision_scope 内 |
| alignment | Payload | 结果与后到依据的匹配键；不同任务有不同 schema |
| observation_refs | list[ArtifactRef] | 构成当前输入的已记录 BoundObservation，不包含评价标签 |
| input | Payload | 任务输入值，按任务协议解析 |
| tools | list[ToolSpec] | 本次允许工具，单轮样例为空 |

宿主验证草稿，再加入 task_session_id 和 case_id，生成有 message_id 的 TaskInput。首轮窗口不足时 inputs 为空，不能补出预测。stream_done 仅表示不再开启新案例，已有输入和续轮仍须处理；它不表示可以立即跳过最后一批。

TaskEffect 为 `{task_session_id, case_key, results, requests, complete}`。results 使用 TaskResult.body，requests 为至多一个 query 或 command。complete=true 时关闭案例；query 要求 complete=false。一个结果合法但回答错误仍是 valid；invalid 表示结构或领域约束不满足。

TaskResult 包含 case_id、input_id、invocation_id、contract_ref、decision_time、alignment、status、answer、error。valid 必须有 answer 且 error=null；invalid 必须 answer=null 并给出 error。Task 不根据实际模型名修正输出，不用后来真值改写历史结果。

## 6 两个任务的具体 payload

### 数值预测

合同为 `timeseries.forecast@1.0.0`。

| 对象 | 字段与含义 |
| --- | --- |
| ForecastParams | entity、variable、unit、window_points≥2、horizon_points≥1、sample_period_seconds≥1 |
| ForecastInput | window、target_times、output_unit |
| Window | entity、variable、unit、timestamps、values、valid_mask；本版必须全有效、规则间隔 |
| ForecastAnswer | values、unit；数组按 target_times 顺序对应 |
| ForecastAlignment | entity、variable、issued_at、target_times |

输入最后时点等于 decision_time。每个 target_time 都晚于 decision_time，且按任务周期递增；输出长度必须恰好等于目标时点数量，单位等于 output_unit。核心不猜测 horizon，也不把错长度回答截断或补齐。

### 窗口趋势

合同为 `timeseries.trend@1.0.0`。

| 对象 | 字段与含义 |
| --- | --- |
| TrendParams | entity、variable、unit、window_points≥2、sample_period_seconds≥1、slope_threshold≥0 |
| TrendInput | window、criterion；criterion 为 `{type: ols_slope, time_unit: minute, threshold}` |
| TrendAnswer | direction：increasing、decreasing 或 stable |
| TrendAlignment | entity、variable、issued_at、window_start、window_end_inclusive |

任务定义的趋势以窗口上最小二乘直线的每分钟斜率为依据：大于 threshold 为 increasing，小于负 threshold 为 decreasing，其余含边界为 stable。此处不是用一个主观的自然语言“趋势”同时评价不同方法。

这两个合同可以被同一个方法包支持，但方法不必支持所有任务。新增不受支持的任务时，装配应拒绝或选择新的外部适配器，不改变来源实现或核心分支。

## 7 执行端消息与接口

| 接口 | 输入 | 返回 |
| --- | --- | --- |
| MethodProvider.describe | Selection | MethodDescription |
| RuntimeProvider.describe | Selection | RuntimeDescription |
| Runtime.open_method | MethodOpen.body | MethodHandle 与 MethodOpened.body |
| MethodProvider.open | Method 选择和 MethodContext | MethodSession，由 Runtime 在目标进程调用 |
| MethodHandle.infer | Invoke.body | MethodResponse.body |
| MethodSession.infer | TaskInput 与 InvocationContext | MethodResponse.body |
| MethodHandle.close | Close.body | Closed.body |

MethodOpen 包含 method、runtime、contract_ref、context。MethodOpened 返回 session_id、runtime_component、identity、state=ready。Runtime 必须保持同一 Run 的方法会话，不能每次 infer 都重新创建 Agent 状态。

Invoke 包含 session_id、invocation_id、deadline_at、task_input。它封装完整的已记录 TaskInput。协议接口不要求把 CPU/GPU 张量对象直接跨进程 pickle；内联 JSON 或 ArtifactRef 通过声明过的格式传输。

Runtime 从 Invoke 和会话配置构造 InvocationContext，其字段为 run_id、method_session_id、invocation_id、input_id、deadline_at 和 handles。Method 只获得本调用的证据/工具服务句柄；调用 ID 不从模型文本中解析，也不允许方法自行指向另一个 Run。

MethodResponse 的字段如下：

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| session_id | string | 对应已打开的方法会话 |
| input_id | string | 等于 TaskInput.message_id |
| invocation_id | string | 等于 Invoke 中的调用 ID |
| contract_ref | ComponentRef | 与输入一致 |
| status | ok、invalid_output 或 failed | 分别表示适配成功、返回无法解码、调用失败 |
| action | MethodAction|null | 成功为 answer 或 tool_call；失败为空 |
| request_ref | ArtifactRef|null | strict_io 成功和解码失败必须保留原始请求 |
| response_ref | ArtifactRef|null | strict_io 成功和解码失败必须保留原始返回；无返回的调用失败可为空 |
| identity | MethodIdentity | 实现身份、配置模型、响应模型、权重修订、验证标志和证据来源 |
| error | Error|null | ok 时为空，其余必填 |

AnswerAction 为 `{kind: answer, answer: Payload}`。ToolCall 为 `{kind: tool_call, call_id, name, arguments: Payload}`；只有 TaskInput.tools 和 MethodDescription 同时允许时才能使用。

MethodIdentity 的 evidence_origin 为 live、synthetic_fixture 或 reference_calculation。configured_model、reported_model、weight_revision 可为空；weights_verified 不能仅根据配置声明设为 true。ChatTS 运行地址、凭证引用、配置模型、预期 fingerprint、wire dialect 和 processor_revision 通过 [DeploymentRecord 样例](contracts/pluggability-v2/walkthrough/deployment-registry.json)解析，不放入任务输入。

在每次调用中，证据服务先提交原始请求，记录 EvidenceSaved.stage=request，再执行原生调用；返回后先提交原始返回并记录 stage=response，最后才解码。EvidenceAppend 包含 invocation_id、stage、content_base64、media_type、schema_ref；摘要计算解码后的原始字节。记录不包含 Authorization 等凭证。

MethodResponse.status=ok 不等于任务有效：例如它返回一个合法数值数组，但只有 1 项，Task 仍须将 2 步预测判为 invalid。底层完全没有返回时由 Runtime 记录 RpcFailure，再归一化为 failed 响应；不能编造 raw response。异步迟到返回只作为原调用证据关联，不恢复已经关闭的案例。

## 8 查询操作与终止规则

单轮路径只需要 answer。支持交互时仍沿用三端边界：

1. Method 返回 ToolCall，Task.interpret 根据允许工具生成 TaskEffect.request。
2. query 包含 request_id、case_key、input_id、invocation_id 和 read；read 是逻辑变量的 ReadIntent，kind 必须是 query。
3. 宿主验证权限并经 Binding 生成 SourceRead；query 不改主游标，结果经 BoundObservation 回到 Task.consume。
4. Task 为同一 case_key 生成 turn_id+1 的 InputDraft；宿主保留同一 case_id，分配新的 TaskInput 和调用 ID。
5. command 包含上述关联 ID，以及 operation 和 arguments。宿主先持久化操作意图，再映射为 SourceAct。
6. SourceAct 包含 session_id、operation_id、request_id、input_id、invocation_id、operation、arguments 和 idempotency_key。非幂等操作不能用一个字符串幂等键冒充幂等保证。
7. ActionReceipt 包含 session_id、operation_id、request_id、status、received_at、payload、feedback、error。unknown 表示可能已生效，停止 Run，不自动重发。回执先交 Task.on_action，再读取后态；反馈按 feedback_id 去重。

可控制来源必须遵守 open 缓存初态、read 消费初态、act 产生并缓存一个转移、read 消费转移的顺序。未消费转移前不允许下一动作。TaskInput 中工具只提供公开参数与结果 schema，不直接提供 Source 对象。

run 完成、case 完成、source 结束是不同状态。收尾按 Method、Task、Source 逆序进行；已经打开但启动失败的资源也需释放，清理失败追加记录，不覆盖主要失败。close/finish 重复调用返回同一终态，不执行第二次释放。

## 9 用 ChatTS 与独立方法逐步推演

完整消息见 [ChatTS 预测路径](contracts/pluggability-v2/walkthrough/draft-snapshot-forecast-chatts.json)和[独立方法预测路径](contracts/pluggability-v2/walkthrough/draft-snapshot-forecast-ols.json)。文件包含完整 RunSpec、Plan、ReadIntent、26 条消息、原生请求和原生返回。

### 固定来源与任务

公开数据是 server-7 的 cpu_pct，单位 percent，每分钟一个点，数值为 `[10,12,14,16,18,20]`，事件时间和可用时间为 00:00 至 00:05。来源读取范围为 `[00:00,00:06)`，as_of 为 00:05。评价真值 `[22,24]` 位于独立私有文件，available_at=00:07，不进入 Task 或 Method。

Binding 将 cpu_pct 对应为 signal。预测任务使用 6 点窗口，目标时点是 00:06 和 00:07，决策时点为 00:05。相同任务的两个方法得到的 input.value 都是：

```json
{
  "window": {
    "entity": "server-7",
    "variable": "signal",
    "unit": "percent",
    "timestamps": ["2026-01-01T00:00:00Z", "2026-01-01T00:01:00Z", "2026-01-01T00:02:00Z", "2026-01-01T00:03:00Z", "2026-01-01T00:04:00Z", "2026-01-01T00:05:00Z"],
    "values": [10, 12, 14, 16, 18, 20],
    "valid_mask": [true, true, true, true, true, true]
  },
  "target_times": ["2026-01-01T00:06:00Z", "2026-01-01T00:07:00Z"],
  "output_unit": "percent"
}
```

### 调用顺序与字段关联

| 顺序 | 调用或记录 | 两条方法路径的关系 |
| --- | --- | --- |
| 0 | 用描述编译 Plan，验证合同、Binding 和 Runtime | 只选择不同的 Method/Codec；数据和 Task 不变 |
| 1 | SourceOpen → SourceOpened | 同一来源配置和读取范围；不同 Run 使用不同 session_id |
| 2 | TaskBind | 同一个预测 Task 实现和参数 |
| 3 | MethodOpen → MethodOpened | 分别选择 method.chatts 或 method.ols |
| 4 | Task.next_read → ReadIntent → SourceRead | 逻辑变量 signal 被 Binding 映射成 cpu_pct |
| 5 | Observation → BoundObservation | 最后一批 status=end 仍保留全部 6 点 |
| 6 | Task.consume → TaskUpdate → TaskInput | stream_done=true 但 inputs 中的最后一个输入必须处理 |
| 7 | Invoke → EvidenceSaved.request | 同一语义输入，生成不同的原生调用 |
| 8 | EvidenceSaved.response → MethodResponse | 原始证据先提交，随后解码 |
| 9 | Task.interpret → TaskEffect → TaskResult | 同一 Task 检查长度、单位、目标含义和案例关联 |
| 10 | Method Close → Task Close → Source Close → RunSummary | 不同方法使用相同收尾规则 |
| 11 | 独立 Outcome → ScoreRequest → Evaluation | 使用同一评分合同，不再次调用模型 |

### ChatTS 路径

配置选择 `method.chatts@1.0.0` 与 `chatts.structured-ts@1.0.0`。本例选择[现有适配代码](../gymts/integrations/chatts/candidate.py)支持的 `chatts-timeseries/v1` dialect：Method 生成文本指令和 `<ts><ts/>`，并把原数值放在顶层 timeseries 数组。TaskInput 中不出现这些 wire 字段。

```json
{
  "model": "chatts",
  "messages": [{"role": "user", "content": "Forecast the next 2 points at one-minute intervals. Return exactly JSON {\"forecast\":[number,number]}. Values use percent.\nSeries signal: <ts><ts/>"}],
  "timeseries": [[10, 12, 14, 16, 18, 20]],
  "temperature": 0,
  "top_p": 1,
  "max_tokens": 128,
  "stream": false
}
```

这是本地现有适配器所声明的服务 dialect，不代表任意 ChatTS 服务都支持此 HTTP 格式。另一个已存在的 text-envelope dialect 需要不同的 wire 编码；它仍应只改变 Method/Codec。未核实的部署与 processor_revision 在计划中明确保留未验证状态。

离线调用现有 ChatTS `_wire` 编码函数，四份 ChatTS 原生请求均与本草案样例一致；没有调用 prepare、infer 或 HTTP 服务。但现有 `_model_input` 会以 schema_mismatch 拒绝新版 TaskInput，因为它硬性要求旧的 ChatTS QA 协议。因此迁移时必须在 Method/Codec 内实现公共任务输入到原生请求的适配，不能直接把旧 Candidate 改个注册名，也不能为了兼容旧适配器把 ChatTS 字段重新塞回 Task。

推演的示例响应内容为 `{"forecast":[21.5,23.5]}`，不是 ChatTS 实际推理。Codec 将 forecast 映射为 ForecastAnswer.values，从输入复制原单位 percent，不改变数值或目标顺序。MethodResponse 标记 synthetic_fixture，reported_model=chatts-fixture，weights_verified=false。

Task 校验后生成 valid 结果。与示例真值比较得到 MAE=0.5、RMSE=0.5，这只是用于验证消息和评分算术的 fixture 数值，不能用于比较模型能力。

### 独立方法路径

配置选择 `method.ols@1.0.0`，不导入 ChatTS、HTTP Candidate 或任何 LLM 库。方法从同一个 ForecastInput 取出序列，以相对分钟数 `[0,1,2,3,4,5]` 为 x，计算最小二乘直线，再在目标分钟 6 和 7 处求值。

这组数据给出斜率 2、截距 10，独立参考计算得到 `[22,24]`。原生调用记录是函数参数对象，原生返回记录斜率、截距和答案；它不构造 messages、ChatTS 占位符或模型输出文本。输出直接符合 ForecastAnswer。

Task、Binding、Source 和 Scorer 的实现或配置都不需要因方法变化而改变。此参考计算也不是已部署的 Method 插件；它检查接口是否容纳了真正不同的计算路径。

## 10 分别替换数据和任务

数据替换使用[JSON 快照](contracts/pluggability-v2/walkthrough/source-snapshot.json)与[CSV 文件](contracts/pluggability-v2/walkthrough/source.csv)，后者独立解析数值与时间。只改变 Source 选择和来源修订，字段绑定相同。每种方法的原生请求摘要在两种来源下相同，说明模型格式没有从文件读取路径泄漏进任务定义。

任务替换将预测换成按斜率阈值判定的趋势任务。Source、Binding 和两种 Method 的选择及配置保持，TaskInput.input 改为 TrendInput，任务/对齐/回答 schema 改成对应合同，评分改成趋势准确率。OLS 方法在自己的已声明合同内选择趋势计算分支；ChatTS Codec 在自己的已声明合同内生成趋势指令。核心不增加按任务名的分支。

| 来源 | 任务 | ChatTS 路径 | 独立 OLS 路径 |
| --- | --- | --- | --- |
| JSON 快照 | 数值预测 | 示例 `[21.5,23.5]` | 参考计算 `[22,24]` |
| CSV | 数值预测 | 相同原生请求与示例响应 | 相同原生参数与参考结果 |
| JSON 快照 | 窗口趋势 | 示例 increasing | 参考斜率 2，increasing |
| CSV | 窗口趋势 | 相同原生请求与示例响应 | 相同原生参数与参考结果 |

不同 Run 的 message_id、case_id、session_id、observation_refs 和物理来源身份本来就不同。比较采用精确的语义投影：`contract_ref, turn_id, decision_time, alignment, input, tools`。这不是忽略数据变换；单位、时间、数值、掩码、目标和阈值全部在投影内。同时保留原始来源引用，不能用语义相同抹掉来源差异。

## 11 失败与评价推演

| 检查位置 | 失败输入 | 应有行为 |
| --- | --- | --- |
| payload schema | 在 ForecastInput 注入 messages 或 gold | 拒绝未声明字段 |
| Plan | Task 要求 query，而 Source 只有 next | 调用前拒绝组合 |
| Plan | 对 inprocess 要求强制超时 | 拒绝无法保证的部署 |
| Source 边界 | 某点 available_at 晚于 as_of | 拒绝越权交付，不能送到方法后再补救 |
| Source 会话 | 响应 cursor_before 与请求不一致 | cursor_mismatch，不倒带或重试 |
| 消息 schema | ok 响应缺原始返回证据 | strict_io 拒绝成功状态 |
| 消息 schema | waiting 携带数据或覆盖范围 | 拒绝不一致状态 |
| Task 领域检查 | 回答数组仅 1 项或单位变成 ratio | 保留原始响应，产生 invalid TaskResult |
| Method 解码 | ChatTS 返回被截断的 JSON | invalid_output，保留原始字节，不自动重试或修复 |
| 评价 | as_of 时尚无未来真值 | insufficient_evidence、metrics=[]，不填零分 |

对应材料为[负例集](contracts/pluggability-v2/walkthrough/negative-cases.json)、[截断回答路径](contracts/pluggability-v2/walkthrough/invalid-chatts-output.json)和[缺少标签路径](contracts/pluggability-v2/walkthrough/missing-outcome.json)。负例集表示各层应拒绝的输入，不是已经实现的框架拒绝记录。

Outcome 通过 alignment 对齐标准结果，包含 outcome_id、available_at、purpose=evaluation、answer 和 source_ref。ScoreRequest 固定 evaluation_id、result_ref、outcome_ref、as_of 和 scorer。Evaluation 返回状态和指标；只有 scored 可以有数值指标。重评分使用同一个 result_ref，新建 evaluation_id，不进入 Method 调用路径。

## 12 本轮结论与实现验收边界

本轮检查覆盖 8 组消息推演、208 条消息、10 个明确拒绝的负例，以及解码失败和缺少评价依据路径。所有输入、配置和已登记 payload 都通过相应 schema；制品原始字节摘要、输入输出关联、跨来源请求等价和同任务语义等价均已核对。

另有 4 份原生请求通过现有 ChatTS wire 编码函数的离线核对，旧输入协议对新版公共消息的预期拒绝也已确认。这项检查只验证编码边界，不验证模型服务支持、推理质量或插件生命周期。

在这两个任务和所选方法的消息层，三端有独立替换路径；没有发现必须把 ChatTS 特殊字段加入 Source 或公共 TaskInput 的地方。推演同时要求将旧接入的数据 model_input 拆开、区分解码与任务合法性、分配清晰的 ID 所有权，并在最后一批上保持输入处理顺序。

尚未证明的内容是外部插件的独立安装与卸载、真实 ChatTS 服务对此公共输入的运行结果、实际 SDK 生命周期，以及 worker 的状态与取消。这些需要在规格审阅后实施并验收，不能用本轮 schema 通过替代。针对本版的下一项验收应是一个无 ChatTS 依赖的外部 OLS 插件与独立来源插件，严格使用这些公共合同运行。
