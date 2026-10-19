# GymTS 数据任务与执行端可插拔设计草案

状态：设计提案，2026-10-15。本文用于讨论下一版边界，不是已经实现的 API，也不替代当前接口规范 1.0.0。代码迁移前需要按本文确定公共消息和生命周期的字段级合同。

字段级细化见[三端公共消息与调用协议草案](pluggability-contract-v2.md)，包含机器可读 schema、完整消息序列及 ChatTS 与独立 OLS 方法的设计推演。

GymTS 应允许使用者独立选择数据来源、任务规则和被执行的方法，再选择运行位置与评价方式。新增某个来源、任务或模型，应交付外部插件和配置；框架核心不增加对应名称、导入或条件分支。可插拔以兼容组合的替换实验为证据，不要求任意组件都能组合。

## 1 当前接入暴露的问题

当前框架已有 Environment、Task、Candidate 和 Scorer 协议，核心执行循环主要依据这些角色工作。需要修正的是装配和语义边界，不能仅通过移动目录解决。

| 当前事实 | 对可插拔性的影响 |
| --- | --- |
| `gymts/plugins/__init__.py` 的内置注册直接加载 ChatTS 集成 | 默认创建框架依赖具体集成包；移除插件会影响无关实验的启动 |
| ChatTS 数据导入生成包含 messages、timeseries 和 output_schema 的 model_input，任务层把它放进 TaskInput | 现有路径适合既有 QA 数据回放，但数据格式、任务输入与模型表达没有分别得到替换验证 |
| 普通文本 Candidate 继承 ChatTS HTTP Candidate，且共享 ChatTS QA 协议 | HTTP 传输复用和任务适配复用混在一起，普通文本能力难以独立使用 |
| 集成依赖 `gymts.plugins._common` 私有实现 | 外部插件缺少足够的公共 SDK |
| 校验调用 `_assemble` 并实例化 Environment 与 Task | 新插件的构造函数可能连接服务；仅靠当前代码无法保证所有插件的离线校验没有副作用 |

现有 QA 数据中的问题文本和标签可以保留。设计要求是让数据读取保留来源事实，由任务适配解释其用途，再由方法适配构造具体模型请求。

## 2 角色与依赖方向

对使用者保留三个主要选择：数据端、任务端、执行端。执行端内部区分方法适配和运行后端，评价单独配置。

| 角色 | 负责 | 不承担的职责 |
| --- | --- | --- |
| Source 数据或交互环境 | 打开文件、生成序列、读取实时源、推进仿真；返回观测并执行声明过的操作 | 决定预测步长、构造某个模型的消息、计算某个任务的最终结论 |
| Binding 数据视图绑定 | 把来源变量对应到任务变量，显式配置单位转换、选段和重采样 | 猜测缺失值处理或替模型归一化 |
| Task 任务 | 定义可见信息、窗口、目标、轮次、允许工具、输出含义和完成条件 | 导入 CSV 或 ChatTS 类、连接模型服务、更新模型权重 |
| Method 方法适配 | 包装算法、模型、流水线或 Agent，将公共任务输入转换为原生调用，返回输出 | 绕过任务读取完整来源或评价标签，修改任务标准 |
| Runtime 运行后端 | 在当前进程或独立 worker 中承载方法会话，管理调用、状态、超时和退出 | 解释时序任务、决定奖励、拼装 ChatTS 请求 |
| Scorer 评分 | 将标准任务结果与获准的结果依据对齐并计算指标 | 重新调用模型或修改原始回答 |
| Orchestrator 核心运行组织 | 解析计划，按协议调度角色，执行通用权限与状态检查，保存证据 | 按模型或任务名称增加业务分支 |

Method 对应现有 Candidate 的逻辑角色；Runtime 是新增的部署边界。本草案不要求仅为改名替换现有公共 Candidate 名称。

依赖方向如下：

```text
应用或实验配置 ──选择──> 各角色插件
核心运行组织 ──依赖──> 公共 SDK
各角色插件   ──依赖──> 公共 SDK 与所需的公共任务合同

核心不导入具体插件；插件不导入核心私有实现。
Source 插件和模型插件互不导入。
Task 按来源描述和任务合同工作，不检查来源类名或模型名。
```

公共任务合同可以定义 forecasting、anomaly 等 schema，但应放在独立的合同命名空间或包中，不要求核心预装全部任务实现。方法适配依赖它支持的任务合同是合理依赖；依赖另一种具体模型的实现类应有明确复用理由，否则应使用公共传输组件组合。

## 3 数据和消息边界

### 数据端交付来源事实

Source 的公开观测包含数据或固定引用、数据 schema、实体与变量、单位、事件时间和可用时间、来源身份与版本、游标及结束状态。规则采样、非规则采样、缺失掩码和不支持的字段必须明确表达，不能默默补齐。

大数组、张量、图像和其他原生数据使用带格式、摘要与版本的 ArtifactRef，不统一转成文本或逐点 JSON。SDK 提供引用与消息包络；具体存储格式由相应插件和读写器支持。

历史文件、生成器、实时订阅和可控制仿真共享基础 SourceSession，但能力分别声明：顺序读、范围读、历史查询、重置、附着、动作推进、外部推进。只读文件不能冒充可响应动作的仿真器。静态 QA 样本使用样本游标，不伪装成业务事件时间。

标注通过独立的 OutcomeProvider 或独立结果视图交付，配置在评价或明确授权的训练入口。它可以与观测来自同一文件，但给方法的视图不包含私有标签；生成参数等可能泄漏答案的信息也不默认公开。

### 任务端交付公共任务含义

例如一个预测输入应表达：实体、输入序列及掩码、发出时点、目标时点、预测长度、单位、允许的查询和结果 schema。它不要求所有方法接收 OpenAI messages，也不含 ChatTS 占位符。

任务消息分为通用包络和带版本的任务 payload。核心检查身份、版本、权限、关联和外层 schema；具体任务插件检查领域约束。结构相同不等于语义相同：任务合同还要规定时间索引、单位、预测目标、缺失值和动作含义。

Binding 只把来源字段映射到公共任务变量。需要单位转换或重采样时，配置转换实现和参数，并记录转换前后引用。方法自己的标准化、插补、tokenizer 和 TS encoder 处理仍属于 Method，保存其实现版本。

既有 QA 数据由数据插件读取原始 sample；任务包中的 CaseAdapter 把问题、公开时序和目标映射成 TaskCase。CaseAdapter 负责理解数据集的任务注释，不负责调用模型。只有同一任务语义成立时，才承诺跨来源复用同一个 Task；不同任务不靠改名强行等同。

### 执行端适配原生模型格式

同一公共任务输入可以通过不同方法适配传给数值算法、原生时序模型或文本 LLM。模型输入编码、输出解码可以实现为 Method 内部可复用的 Codec，也可作为显式配置的独立适配组件。

```text
公共任务输入
  → 选定方法的输入适配
  → 原生算法参数或模型请求
  → 原始返回与调用证据
  → 输出适配
  → 公共任务响应
  → Task 校验任务结果或解释下一步请求
```

Codec 声明所接受的任务合同和目标模型接口，记录版本及是否有损。数值序列转文本、舍入、截断、归一化、提示词模板等均不能成为核心隐藏行为。解码失败保留原始返回和失败原因，不自动修补成正确答案。

协议解码与任务判断分开：Codec 解析工具调用的 wire 格式；Task 判断该工具在本任务是否允许、答案是否符合目标长度等领域规则。模型可返回错误答案，正确性由独立评价判断。

方法响应至少关联 `raw_ref`、解码状态、解码后的 payload 和调用身份。原始返回先提交再解码；解码失败仍交付失败状态及原始证据引用。传输异常或进程退出没有完整返回时，记录已知调用状态和已有证据，不能伪造一个空成功响应。

公共任务协议减少来源与模型之间的适配组合，但不消除所有适配工作。通用文本 Codec 可以覆盖一组结构化任务，某些数值算法只支持一个任务合同。新任务超出已有方法声明时，新增外部方法适配或拒绝组合，不要求框架增加特判，也不自动改写旧方法的语义。

## 4 最小生命周期合同

以下为角色签名草图，不是可直接调用的现行 API。异步、批量和学习更新作为能力扩展，不让所有实现被迫提供空方法。

| 角色 | 最小接口 | 状态与限制 |
| --- | --- | --- |
| SourceProvider | `describe(config)`、`open(config, context)` | describe 仅读取声明和配置，不连接现场 |
| SourceSession | `read(request)`、`close()`；可选 `act(command)` | cursor、clock、所有权和操作回执由本 session 管理 |
| TaskProvider | `describe(config)`、`bind(binding, source_description, context)` | 所需变量、操作和消息合同在装配时可知 |
| TaskSession | `next_read()`、`consume(observation)`、`interpret(response)`、`finish()` | 可选动作回执处理；输出继续输入、领域结果或有类型的请求 |
| MethodProvider | `describe(config)`、`open(config, context)` | 接受的任务合同、输入模态及运行要求明确 |
| MethodSession | `infer(task_input)`、`close()` | 每个 Run 独立状态；跨 Run 继承使用明确的 ArtifactRef |
| RuntimeProvider | `describe(config)`、`open_method(component_ref, config, context_handles)` | 返回保留同一会话状态的 MethodHandle |
| MethodHandle | `infer(task_input)`、`close()`；可选学习方法 | 本地直接代理，远程通过有版本的 RPC 代理；不传任意宿主 Python 对象 |
| Scorer | `describe(config)`、`score(result_view, outcome_view, context)` | 只读固定输入视图，生成新报告 |

首轮 Runtime 只承载 Method 会话，Source 和 Task 留在协调进程。把 Source 或 Task 迁到 worker 属于后续 placement 扩展，需要单独声明和验收，不能凭 Method 可远程就声称所有插件支持分布式运行。

HTTP 有两种不同含义：连接既有 ChatTS 服务是 Method 的传输适配；把相同 MethodSession 搬到通用 RPC worker 才是 Runtime。更换运行位置不能自行改变模型、prompt 或预处理。两种模型服务的 API 可以不同，不强求换服务时只改 Runtime。

执行顺序为：读声明并编译计划，显式打开来源，绑定任务，通过 Runtime 打开方法，读取观测，任务构造输入，方法返回响应，任务解释结果或请求，记录并继续。对每个成功打开的资源登记清理，失败时逆序释放；只释放本 Run 所有的资源。

`waiting`、有进展的空窗、正常结束和失败分别表达。最后一批观测、末状态与奖励保留，结束状态不吞掉数据。控制动作先记录意图再执行，不确定回执不自动重发；支持重试的操作必须声明幂等键和保证。

多轮 Agent 通过宿主注入的 ToolBroker 请求新的环境数据或操作。工具请求经过任务校验、权限检查与记录后才执行；方法不持有完整 Source 对象或整个宿主实例。纯计算工具可以在方法内部运行，其采集能力另外声明。

API 限权用于可信插件之间的职责划分；同进程 Python 插件仍可自行读文件或联网。需要真正隔离时，Runtime 必须提供进程、容器或服务隔离，不能将 SDK 限权宣称为沙箱。

## 5 插件发现与组合检查

### 插件是独立交付单元

建议的包职责如下；每类可以有多个实现，不必将每个小工具拆成一个发行包。

```text
gymts-sdk               公共协议、消息、错误、服务句柄
gymts-core              装配、运行组织、通用校验、记录与评价编排
gymts-data-local        CSV 与本地快照来源
gymts-data-chattsbench  ChatTS-Bench 生成和原始样本读取
gymts-tasks-timeseries  公共时序任务及任务合同
gymts-task-bench-qa     既有 QA 案例的任务解释与 CaseAdapter
gymts-method-chatts     原生 ChatTS 调用及编码
gymts-method-textllm    文本模型调用及编码
gymts-runtime-local    方法会话在本地进程执行
gymts-runtime-worker   方法会话在独立 worker 执行
```

示例配方可以把多类插件一起配置，但它不能被核心自动导入。核心单独安装后允许没有业务插件；用户使用某个示例时才安装对应 extras 或插件集合。所有插件只依赖公开 API，不依赖 `_common` 或 Runner 私有成员。

上述包名表达依赖边界，不要求首轮发布十个发行包。可以在同一仓库开发，先独立交付 SDK、核心及至少一个完整的外部插件，证明干净安装与移除成立，再按依赖和发布节奏拆分其余插件。把文件放进不同目录本身不构成独立交付。

使用 Python entry points 作为已安装插件的发现索引，并提供显式 factory 引用供开发期使用。发现只读取发行包元数据和随包静态声明；选中组件后才加载 factory。安装、发现、启用和实例化是四个不同步骤，不在启动时自动加载全部已安装插件。

entry points 只解决定位，不自动解决隔离、生命周期或语义兼容。插件模块导入与构造不得连接服务、下载权重或读取凭证；这些行为只发生在显式 open 阶段。可信插件必须通过导入副作用测试。

### Manifest 与实验锁定

每个组件声明唯一 namespaced ID、实现版本、SDK 兼容范围、角色、配置 schema、输入输出合同、能力、资源与运行要求、可选依赖，以及工厂入口。重复 ID 和版本有不同实现时拒绝加载，不采用安装顺序覆盖。

任务声明需求，来源和方法声明提供能力。装配器检查具体合同版本、模态、变量/单位/shape、操作、时钟、查询范围、批量/流式能力和 Runtime 支持，必要时检查配置决定的能力。同一个 Python 方法签名不能作为兼容证据。

允许按版本范围选择组件，但运行前必须解析并锁定实际版本、包或代码摘要、配置、任务合同、转换和 Codec、数据修订及模型身份。远程模型 alias 无法固定权重时保留这种限制，不将 alias 冒充 checkpoint。

静态 `plan` 不创建会话、不调用模型、不连接现场；文件和服务可用性检查是单独的显式 `probe`。依赖在线信息的能力在 open 阶段再次核对，实际声明与计划冲突时停止，不能偷偷换插件或扩大权限。

不兼容错误应包含失败连接、缺失能力和可行适配路径，例如：

```text
task.diagnosis 需要 query.history，source.live-cpu 只提供 subscribe。
method.chatts 接受 native_timeseries，所选 Codec 仅提供 text_messages。
task.forecast 需要未来目标的评价依据；当前允许执行，但暂不能计算 MAE。
```

## 6 一份组合配置

以下只是草案示意，字段和组件名尚未实现。这里选择的是一个预测任务；不同任务可以有不同参数与 payload schema。

```yaml
protocol: gymts.experiment/2-draft
plugins:
  - gymts-data-local
  - gymts-tasks-timeseries
  - gymts-method-chatts
  - gymts-runtime-local
source:
  component: local.csv
  version: 1.0.0
  params: {path: ./fixtures/cpu.csv, time_column: timestamp}
binding:
  variables: {signal: cpu_pct}
  transforms: []
task:
  component: timeseries.forecast
  version: 1.0.0
  params: {window_points: 60, horizon_points: 12}
method:
  component: chatts.http
  version: 1.0.0
  params: {deployment_ref: chatts-fixed-deployment}
  codec: {component: chatts.forecast-native, version: 1.0.0}
runtime:
  component: local.inprocess
  version: 1.0.0
evaluation:
  scorer: {component: timeseries.forecast-errors, version: 1.0.0}
  outcome_view: cpu-future-values
```

换成文本 LLM 时，只改变 Method、所需 Codec、模型配置和选中的插件；来源、任务、Binding 和评分规则保持。换数据时只更改 Source、必要字段绑定和评价依据；单位、时间语义相同才可直接复用任务。换任务时调整任务参数和所需评分/适配，不承诺不同任务可以共用同一 Codec。

## 7 记录评价与训练边界

核心记录来源观测、任务输入、实际方法请求与原始返回的引用、标准响应、领域结果、工具请求与回执、实际方法修订和运行后端身份。插件额外采集的信息通过带版本的扩展事件记录，核心不解析供应商专属字段。

方法调用证据至少标记输入表达、输出状态、实际可获知的模型身份和失败原因。token、logprob、reward、policy revision 等字段按实际采集能力声明，缺失时不能通过重分词伪装为原生 rollout。

Scorer 只接收固定的标准结果和 Outcome 视图。Task 判断结果合法性，Scorer 判断任务表现；训练 reward 可以复用某个显式评分实现，但训练反馈与最终评价依据的用途分别授权。迟到标签只生成新评价，不改写原始运行。

训练器独立消费版本化导出或公开 rollout 接口。新增 SkyRL 等训练适配应发生在独立集成插件；Method 可以声明在线更新能力，但训练调度、原生采集和更新一致性需有单独合同，不能只增加一个 update 空方法就宣布可训练。

## 8 可插拔验收

| 验收 | 通过条件 |
| --- | --- |
| 移除插件 | 未安装 ChatTS、文本模型和数据生成插件时，核心能导入、编译无关计划并执行已安装的其他场景 |
| 外部插件 | 在核心干净安装环境中安装独立示例插件，不依赖源码目录或 PYTHONPATH，即可被显式启用和运行 |
| 数据替换 | 同一数值序列分别经 CSV 与内存快照提供，固定语义与绑定后产生等价公共任务输入；Task 与 Method 源码不改 |
| 任务替换 | 同一来源支持趋势识别与异常定位，任务实现和评分可分别选择；来源与框架代码不改 |
| 方法替换 | 同一任务分别运行数值方法、文本 LLM 适配和原生时序模型适配，任务与来源实现不改，原生调用证据可查看 |
| Runtime 替换 | 同一确定性方法在当前进程与独立进程执行，任务含义、状态连续性与结果等价；进程版本能终止挂起 worker |
| 非法组合 | 缺少查询、控制、模态或协议能力时在 plan 拒绝；需要在线确认的条件在 open 拒绝并清理 |
| 无副作用装配 | discovery 与 plan 不下载、不创建现场会话、不推理；主动注入构造副作用的插件被合同测试识别 |
| 时间与用途 | 未来数据不可见、迟到标签不提前进入方法、query 不推进主游标；原始结果能独立重评分 |
| 失败与状态 | 最后一批、超时、格式错误、unknown 动作回执、重复游标、取消、清理失败有明确结果，不静默丢弃或重试 |

首轮选择两种来源、两个兼容任务、两种都支持这些合同的轻量方法，运行 2×2×2 组合，再对同一方法验证第二个 Runtime。矩阵用于检验边界，不要求所有方法支持所有任务。受控 HTTP fixture 用于合同测试，真实模型运行另行标记，不能把 fixture 当模型能力结果。

对历史只读来源，可以检查固定条件下输入等价；控制环境中不同方法会产生不同后续状态，应固定初始条件、预算和规则，不能要求全过程观测相同。

## 9 迁移顺序与设计选择

1. 先确定公共角色、消息字段、时序和动作状态机，把本文的替换验收写成合同验收规格。使用两个独立来源和不同方法共同检验抽象，避免再次围绕一个集成定接口。
2. 把公开插件 SDK 从 `_common` 等私有帮助函数中整理出来，停止默认加载 ChatTS；默认示例也通过同样的显式插件机制接入。
3. 增加静态 Manifest、纯计划编译、明确的 open 生命周期和组件锁定。保持现有注册器中可复用的校验，不为了新包结构重写存储。
4. 拆开 ChatTS-Bench 数据、QA 任务、ChatTS 模型与普通文本模型；将 HTTP 传输提为公共组合工具，保留 ChatTS 专属编码，先通过本地和 HTTP 合同替换验证。
5. 通过组合矩阵后再固定新协议主版本，提供旧 ExperimentSpec 的显式转换或兼容入口。旧 Run 和旧评分规则保留原版本，不把历史记录重标为新协议。
6. 在稳定 MethodHandle 边界上实现独立进程 Runtime，随后按需要扩展 Ray、容器或远程服务。并发、背压和取消合同在对应能力发布前补齐，不先宣称分布式支持。

本草案选择在 Run 边界装配插件，不支持运行中任意热替换；状态延续通过明确的 checkpoint 完成。第一阶段以可信插件和本地运行验证边界，进程隔离与分布式执行按能力逐项交付。

后续字段级规格仍需确定的实现选择包括：原生数组首选制品格式、服务句柄的 RPC 协议、远程 worker 的取消与状态恢复策略。这些选择不能改变已经明确的角色边界，依赖它们的能力在验收前保持未实现状态。

## 10 参考与设计依据

- [Python entry points 规范](https://packaging.python.org/en/latest/specifications/entry-points/)定义插件入口的元数据和定位方式；本提案增加显式启用、静态声明与延迟加载约束。
- [pluggy 文档](https://pluggy.readthedocs.io/en/stable/)区分宿主规范、插件实现和调用者；GymTS 可以采用这一分工，而不必将带状态的任务会话全部实现成广播 hook。
- [SkyRL 新环境教程](https://docs.skyrl.ai/docs/tutorials/new_env)展示外部定义并注册环境、再接入训练的路径；本提案保留更细的数据、任务和方法边界，以支持时序任务的独立替换与延迟评价。
- 当前实现基线见[接口规范 1.0.0](feishu/GymTS接口规范/GymTS接口规范.md)及[框架指南](framework.md)。本提案对默认加载、静态装配和执行部署边界提出调整，不声称这些调整已经完成。
