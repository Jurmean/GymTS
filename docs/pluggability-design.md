# GymTS 数据任务与执行端可插拔设计草案

状态：初稿 2026-10-15；2026-10-20 更新至 GymTS 0.5.0 / 接口规范 1.2.0。§0 说明已实现的独立交付、纯装配、资源目录和 RL 训练至新评价闭环；§1 保留历史诊断，§2 起仍是完整 v2 边界提案。通用 Runtime 和 `gymts.wire/2-draft.1` 尚未实现，不能把部分设计落地表述为整个 v2 已交付。

字段级细化见[三端公共消息与调用协议草案](pluggability-contract-v2.md)，包含机器可读 schema、完整消息序列及 ChatTS 与独立 OLS 方法的设计推演。

GymTS 应允许使用者独立选择数据来源、任务规则和被执行的方法，再选择运行位置与评价方式。新增某个来源、任务或模型，应交付外部插件和配置；框架核心不增加对应名称、导入或条件分支。可插拔以兼容组合的替换实验为证据，不要求任意组件都能组合。

## 0 用项目接入推动框架演进

最终交付物是 GymTS 框架。持续接入真实项目，是检验公共接口、发现缺口和修正框架的过程；项目数量增加不应要求核心积累同样数量的专属实现。普通新项目通过适配即可接入；遇到已有公共合同无法表达的新能力时，框架可以有依据地演进，不承诺框架从此不再修改。

框架仍由 EnvironmentTS 与 AutoBenchTS 两个主模块组成。EnvironmentTS 组织执行、访问边界和轨迹；AutoBenchTS 组织 benchmark 构建维护、固定评价计划、独立评分和报告。所有项目均通过外部适配接入，框架不内化项目实现。LibraryTS 是工具提供方之一，与其他工具集、训练器和 Research 调用方遵守相同边界。

Agent 决定调用哪些工具、使用什么参数，并根据返回结果继续决策；外部工具集提供实现和可调用声明。框架提供通用接入、实验边界与证据关联，不把某个工具集的目录、算法或资产平台变成自身业务功能。Run 内 Agent 与 Run 外实验编排 Agent 的职责、逐工具效果分类及当前实现缺口见 [Agent 与工具集接入边界](agent-toolsets.md)。

交付边界如下：

| 交付内容 | 应包含 | 与项目的关系 |
| --- | --- | --- |
| 框架与公共 SDK | 公共合同、注册和兼容检查、生命周期、权限与用途、Run/轨迹/CAS/快照、评价编排与报告、通用训练导出合同 | 不导入具体项目，不保存项目名称分支；不强制安装模型或训练运行时 |
| 独立适配包 | 数据读取与生成、任务及领域 schema、模型/工具封装、项目评分器、原生训练后端和所需依赖 | 单向依赖公开 SDK 与公共任务合同；可独立安装、启用、升级、移除 |
| 项目资源与实验配置 | Dataset Card、benchmark 定义、数据/权重引用、配方、预算和版本锁定 | 由外部资源包或显式目录提供；原始数据和权重放部署配置指定的资产存储 |

同一适配包可以提供数据、任务、模型和 Scorer 多个角色；目标是让这几侧通过版本化任务合同协作，不互相依赖具体实现类。独立共享领域包 `gymts-timeseries` 交付中立数值 Source、Task 和 Scorer，ChatTS 新默认路径的数据侧不再构造模型消息或调用 Task parser；模型 codec 留在模型适配器。原 `/1` 路径显式保留为 legacy。原题目的规范化改写是另一个派生提示实验，不能当作与原 benchmark 完全等价。可复用领域合同可以另行成包，不能因为被多个项目使用，就自动成为核心业务代码。可以在同一主仓库内开发这些发行包；独立安装和依赖关系才是边界，目录位置不是验收依据。

### 接口不适配时如何处理

| 发现的问题 | 修改位置与要求 |
| --- | --- |
| 文件格式、模型请求、原生 API、任务解释或评分规则不同 | 修改外部 reader、Task、Candidate/Codec、Scorer 或配置；不在核心按项目名称判断 |
| 需要新的领域任务语义，但已有生命周期和证据合同足够 | 新增带版本的任务合同及适配实现；其他组件明确声明支持或拒绝 |
| 生命周期、可见性、身份、证据、错误或评价组织缺少通用表达 | 提出最小公共合同扩展，说明触发案例、旧合同为何不足、兼容/迁移影响；通过旧接入回归及第二种独立实现或最小反例验证后更新框架 |
| 组合本身缺少必要能力 | 明确报告不兼容及可行适配路径，不补造数据、轨迹或成功结果 |

每次接入保留一份差距记录：触发场景、预期与实际合同、归属判断、改动、版本影响和验收证据。只有确需公共合同变化时才改核心；也不以“保持核心不动”为理由强迫项目伪造字段或改变实验语义。涉及实验含义、数据权限或不兼容公共接口的选择，先形成可核对的方案与用户讨论。

### 当前交付与剩余差距（2026-10-20，GymTS 0.5.0）

核心 `gymts==0.5.0` 保留 EnvironmentTS、AutoBenchTS、公共 SDK、注册、轨迹、存储、通用训练构建和资源服务。仓库级 `adapters/` 交付五个既有独立包（0.2.0）：共享领域合同 `gymts-timeseries`，以及 LibraryTS、ChatTS、TimeSigma、RL；新增 `gymts-bench-tsqa`（0.1.0）；均依赖核心 `>=0.5,<0.6`，具体元数据为准。核心没有项目导入、项目清单或科学依赖。

| 原设计目标 | 已实现及证据 | 仍需补齐 |
| --- | --- | --- |
| 数据、任务、方法独立替换 | 中立 JSON/CSV × 预测/趋势 × 两个真实 LibraryTS 方法已完成八组合，原 Run 支持后到标签重评，见[组合验收](component-replacement-validation-2026-10-19.md) | 更广任务和真实模型组合；并非任意组件都兼容 |
| 纯装配后再打开资源 | `plan/validate` 仅读声明、schema 与纯 hook，不调用 factory、不读数据/权重/凭证、不写 CAS；run 建立后才打开并重新核对资源，失败保留轨迹 | 通用 probe、独立进程/容器 Runtime、强制中断、远程状态和取消 |
| 数据集与 benchmark 目录 | EnvironmentTS 提供公开数据句柄，AutoBenchTS 登记/解析固定定义并使用原生 evaluate/score；五附件 19,354 行已 evaluation-only 导入 | 远程 Hub、多租户资源运营、卡片编辑和发布审批 |
| 轨迹导出与外部训练 | 固定 snapshot → DatasetBuildSpec/Manifest → 注入式 rollout provider → 既有 TRL GRPO，核心公共三参数服务不解释 RL 行格式 | SFT/偏好/多轮、verl、分布式、optimizer 恢复等各自适配 |
| 训练产物进入新实验 | 不可变 checkpoint archive → 新进程 Candidate → 原生 evaluate 多 seed → 同 seed token 复现 → 零推理重评已实测，见[RL 完整链](reports/rl-checkpoint-loop-2026-10-20.json) | 大型外部基础模型及全部 processor 的同等新轮验收；微型模型验收不证明质量 |
| Agent 与外部工具集 | 固定 sktime 原生工具/数据/方法/Scorer，TimeSigma Research 父轨迹；已有 CPU 原生证据 | 验收可替换 Agent 对工具的选择、实际执行、结果续推与完整轨迹；按实际缺口完善公共接口。工具集资产平台和上位研制审批不属于框架交付 |

LibraryTS 适配固定用户指定 NetmanAIOps/sktime 提交 `080f4c3c3695f239e328548bac7d7a3ef7aa9127`，不要求其他工具集使用相同原生 API。Standalone 工具保存真实 CAS 调用证据，不制造 Run；当前两个数值 Candidate 只在每次获准窗口执行 fit/predict，丢弃临时估计器。它们是直接算法执行，尚不能证明 Agent 自主选择工具；Research journal 的显式调用记录也不能替代该验收。工具集的持久模型与资产发布可另做外部适配，不是 GymTS 必须内建的项目平台。TimeSigma 在最终冻结核心上完成真实 AR train/score/replay、八项原生评分与同 Run 重评，native 75/75 通过，见[最终原生验收](reports/timesigma-frozen-core-final-2026-10-20.json)。

通用 model/tool-call 采集、原生 token/logprob 身份、用途、RecordSnapshot 与证据存储留在框架。RewardRecord 必须有明确来源，trace 不是 reward；项目生成器、Schema/scaler/fit、processor、verifier、HF policy、TRL/LoRA 与训练 journal 留在适配包。公共 `gymts.training.build_dataset(spec, records, artifacts)` 和 provider Registry 核对固定组件引用、目标能力、BuildSpec/CAS/Manifest，并拒绝禁止训练的来源。具体 native QA 选择、token/mask/reward 与血缘由外部 `NativeRolloutBuilder` 校验。训练不是第三个核心主模块，也不自动更新共享 FM。

RL 完整工程验收采用声明过的微型 Qwen2、两个官方 GSM8K train 题、真实 ChatTS 准备及留出评价；两步 TRL 更新有非零组内奖励差异/梯度、weight_decay=0、权重改变且重载一致。新进程从 archive 装载，16 个训练 Run + 6 个新评价 + 6 个重复 seed Run 完整保存；重评不加载模型、不修改封存记录。实际 accuracy=0.0、format_valid=0.5；技术 Gate 只检查执行与评分覆盖，不代表模型质量达标。旧显式 Candidate seed 身份保留，新 repetition seed 使用执行上下文。

五附件通过独立 `bench-tsqa` 包显式导入资源目录，保留所有 19,354 行、原始问题及公开条件/数值，私有答案/attributes 独立存储。全为 `test/user_declared_evaluation`，训练用途拒绝；不因文件名 rlvr 允许训练。未知参考保留 missing 与原 eligible。[完整 746 行验收](reports/bench-tsqa-full746-final-2026-10-20.json)使用透明 first-public-choice 基线，经原生 evaluate 和旧 Run 重评分，Python/CLI 公共输入一致；不是全部 19,354 行或真实模型质量验收。最终同版核心的全量 746 行复验已通过，精确 wheel/hash 见[最终报告](reports/bench-tsqa-full746-final-2026-10-20.json)。

0.3.x 项目导入改为 `gymts_chatts`、`gymts_timesigma`、`gymts_rl`；核心不反向转发。历史组件/Schema/builder/mask ID 和已提交 Run 不重标、不改写。新中立合同及保留原题的 TSQA 合同采用各自身份；canonical prompt 是派生提示实验，不能冒充原 benchmark。完整 v2 消息与通用 Runtime 仍不在当前交付范围。

### 后续每次接入的交付检查

1. 先阅读项目与当前正式规范，记录任务语义、数据权限、运行边界和已有能力，不直接套用上一项目字段。
2. 用最小真实实验暴露合同缺口；将问题分别落到适配、领域合同或框架扩展，按上表更新设计。
3. 通过外部适配包交付，固定框架/插件/数据/模型版本，保存成功与失败轨迹；正式评价继续使用 AutoBenchTS 的 `evaluate/score`。
4. 在不依赖源码 checkout/PYTHONPATH 的环境中验证安装、启用和移除；验证兼容角色替换、非法组合拒绝、已有项目回归与旧 Run 重评分。

独立发行检查涵盖 wheel/sdist、源包重建、源码目录外安装、元数据发现、显式启用、移除及核心旧 Run 重评分；本地 wheelhouse 依赖解析、六包共同启用及移除一个项目后其他包/核心继续运行均通过[最终六包发行检查](reports/adapter-package-check-2026-10-20.json)。原始拆包验收见[历史发行记录](reports/adapter-package-check-2026-10-19.json)，本轮版本和真实组合证据见[本轮验证](component-replacement-validation-2026-10-19.md)。包安装通过不能替代角色替换与原生运行；两类证据分别保留。

### 与原设计及网页的对照（2026-10-20）

复核基线为[总体设计](feishu/GymTS总体设计/GymTS总体设计.md)、[运行机制](feishu/GymTS%20运行机制/GymTS%20运行机制.md)、[接口规范 1.2.0](feishu/GymTS接口规范/GymTS接口规范.md)与[项目网页](https://netman.aiops.org/contacts/projects/)。网页与本地设计均将实验和评价交给 GymTS，研制选择、评审与批准留给上位调用方；拆包不改变这层分工。

| 检查项 | 结论与实际边界 |
| --- | --- |
| EnvironmentTS / AutoBenchTS | 一致。项目发行包不是新主模块，正式评价仍只有既有 `evaluate/score` 路径 |
| 框架与项目依赖 | 独立交付；中立协议下 JSON/CSV × 预测/趋势 × 两个 LibraryTS 方法已真实替换。旧项目专有合同与完整 v2 生命周期不因此自动升级 |
| 外部工具集 / Agent / Candidate | LibraryTS 为一种外部接入；固定算法 Candidate、standalone 调用及 Research journal 已有证据，Agent 决策调用工具的完整循环另行验收；工具集资产平台不列为框架欠账 |
| 轨迹、奖励与训练 | 方向一致。通用采集留核心，明确来源的 RewardRecord 与具体 exporter/TRL 后端在适配包；训练不成为第三模块或自动更新共享 FM |
| 训练导出公共入口 | 已交付三参数公开服务与独立 provider；RL helper 兼容保留，TRL 使用注入式 rollout 和既有优化实现 |
| RL 正式评价 | 不可变 checkpoint、新进程装载、多执行 seed 的新 evaluate、重复 seed 与重评已实测；技术 Gate 与质量结论分开，历史身份不伪合并 |
| 数据集与 benchmark 目录 | 最小本地服务与五份附件导入已实现；EnvironmentTS 读取、AutoBenchTS 构建维护/解析及原生报告，远程平台和资源运营仍待做 |
| TimeSigma 标签分组重评分 | 原适配器漏传计划 tags，已按规范 §11.2 修复；新回归确认原 Run 不变且不增加 fit/score/replay 调用，见[回归证据](reports/timesigma-tags-regression-2026-10-19.json) |
| 名称与资料状态 | `gymts-chatts` 不等于网页的 ChatTS 工作台或整个 FM；旧目录示意、1.0.0 引用和“训练采集待做”的历史表述须与当前实现状态区分 |

接口规范 §16.1 的 `gymts/integrations/` 是早期职责目录示意；0.4 该目录只提供发现与显式启用，具体实现位于仓库级 `adapters/`。这是交付布局的变化，没有据此改变正式消息字段或调用顺序。网页 AutoResearchTS 与本地 LabTS/调用方按上位职责对应，不把它们表述为已经核实的名称迁移。

本轮对照不以发行测试通过推定正式规范所有能力均已实现，也不修改历史协议/证据来掩盖缺口。后续按新项目需求补充更多持久模型/训练 profile、资源运营和 Runtime 能力，并继续以真实组合和旧证据回归验收；当前已实施的最小目录、RL checkpoint/seed 闭环与纯装配不再重复列为未实现。

## 1 初稿接入问题记录（2026-10-15）

本节保留初稿时的诊断，不代表 2026-10-20 的逐项实现状态；当前交付差距见 §0，已支持范围以框架指南和代码为准。

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
| 外部 ToolSet 适配 | 向 Agent 提供版本化工具声明与调用实现，逐工具说明输入输出、权限、效果及可采集证据 | 代替 Agent 选择下一步、内置到框架成为项目专属工具目录、绕过 Task/Runner 的环境访问边界 |
| Runtime 运行后端 | 在当前进程或独立 worker 中承载方法会话，管理调用、状态、超时和退出 | 解释时序任务、决定奖励、拼装 ChatTS 请求 |
| Scorer 评分 | 将标准任务结果与获准的结果依据对齐并计算指标 | 重新调用模型或修改原始回答 |
| Orchestrator 核心运行组织 | 解析计划，按协议调度角色，执行通用权限与状态检查，保存证据 | 按模型或任务名称增加业务分支 |

Method 对应现有 Candidate 的逻辑角色；Runtime 是新增的部署边界。本草案不要求仅为改名替换现有公共 Candidate 名称。

Agent 是 Method/Candidate 的一种实现形态，工具调用由其决策。ToolSet 是 Agent 可以选择的外部能力提供方，不替代数据、任务和方法三侧，也不要求把每个工具包装为独立 Candidate。普通算法直接运行与 Agent 通过工具调用该算法是两种实验方式；共享原生实现不意味着共享调用语义或验收结论。

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

本草案中的 ToolBroker 是通用工具桥接的概念名称，现行 core 尚未提供该接口或通用 Agent 工具循环。已有输入上的纯计算工具可以由 Agent 在方法会话内部调用并采集真实证据。新实验环境数据或操作则须输出请求，经 Task 解释为 TaskRequest，再由 Runner 检查和调用 Environment，结果返回同一会话；方法不持有完整 Source 对象或整个宿主实例。逐工具的效果与范围必须明确声明，不能因某个工具集同时提供纯计算函数就开放其中全部数据或实验入口。

Run 外的 Research Agent 可以调用 GymTS 的公开实验与评价 API，并以父轨迹关联子 Run。其模型选择、规划循环和记忆机制由外部 Agent 实现；框架保存调用和实验之间的证据关联，不据此承担上位研究平台功能。

API 限权用于可信插件之间的职责划分；同进程 Python 插件仍可自行读文件或联网。需要真正隔离时，Runtime 必须提供进程、容器或服务隔离，不能将 SDK 限权宣称为沙箱。

## 5 插件发现与组合检查

### 插件是独立交付单元

以下是下一版职责拆分的概念示意，不是 GymTS 0.5 的发行包清单。当前发行包与安装方式见 §0 及[适配包入口](../adapters/README.md)；公共 SDK 当前随 `gymts` 发布。每类可以有多个实现，不必将每个小工具拆成一个发行包。

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

以下保留初稿迁移顺序。SDK、独立分包、纯计划和部分中立合同已按 §0 实施；原计划中的完整消息主版本与 Runtime 仍待交付，不将六项全部当作尚未开始。

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
- 当前实现基线见[接口规范 1.2.0](feishu/GymTS接口规范/GymTS接口规范.md)及[框架指南](framework.md)。本提案对装配、交付和执行部署边界提出调整；各项实现状态按 §0 与框架指南区分，不以设计草案代替验收证据。
