# 五项目接入与验收记录

日期：2026-10-21。**进行中的验收汇总**：本页区分已取得的证据与 pending 项，不把准备完成或合同测试通过视为原生验收通过。最终结果以各项目封存的 Run、Evaluation、Snapshot 和验收摘要为准。

本轮依据[五项目调研与提案](five-project-integration-research-2026-10-20.md)，选择 TimeCopilot、ITFormer、Chronos-2、Data-Juicer 和 AReaL。目标是检验冻结框架能否通过独立适配包承接不同工作流，交付框架和适配接口，不把五个项目变成核心内置功能。职责依据[框架设计](framework.md)、[工具集边界](agent-toolsets.md)和[项目网页](https://netman.aiops.org/contacts/projects/)。

## F0 冻结与验收口径

| 项目 | 固定身份或规则 |
| --- | --- |
| 主仓库基线 | `121abca88b65094e899b294a3d3416ccd004a25d` |
| 核心 / 公共合同 | GymTS `0.5.0` / `1.2.0` |
| 本轮 F0 wheel SHA-256 | `8883e708dbfcc46301939335f594884b40239ddd8bbe201a66e6af2f18e012cf` |
| 安装身份核对 | 39 个已安装核心文件；核对实际 import 路径与文件内容，不使用仓库源码 `PYTHONPATH` 回退 |
| 核心改动 | 五项目全部已执行范围均为 0，39 个核心文件保持 F0；十六包发行与跨项目 CPU 替换已验证；AReaL 训练和发布完成，留出评价/重评 pending |
| 资源边界 | 用户批准最多 2 张当时空闲 GPU、串行实验、累计 12 GPU 小时；仅本地模型，无付费 API，不调整系统驱动 |

核心 wheel 固定，适配包、配方、数据投影和文档可以独立迭代。只有真实需求无法由现有公开接口表达时，才提出核心变更：保留最小失败证据，说明已尝试的扩展点、适配器不足的原因、新合同和旧项目兼容方式。需要改核心时形成 F1，再复验旧项目，并由另一个独立新接入检验 F1。不能把每个项目各改一次核心称为一次冻结验证。

每个项目至少分别核查：源码外 wheel/sdist 安装；真实原生执行；固定数据用途和成员；完整成功/失败证据；需要训练的路径确实更新参数；AutoBench 独立评价及零推理重评；可执行的准备、运行和结果读取文档。mock、import 成功、上游单元测试和事后轨迹导入都不能替代这些证据。

## 五个适配器的职责

| 层次 | 稳定职责 | 本轮外部实现 |
| --- | --- | --- |
| EnvironmentTS | 获准环境访问、执行生命周期、Run、CAS、事件和 Snapshot | 数据源、原生 harness 与模型/工具协议由适配包转换 |
| AutoBenchTS | 固定评价计划、独立参考、领域 Scorer 调用、比较与同 Run 重评 | 各领域指标、答案解释和质量边界留在外部包 |
| Agent 与工具集 | Agent 决定调用哪个获准工具及参数；工具返回进入后续决策 | TimeCopilot 原生工具；LibraryTS 等仍是其他可选外部工具集 |
| 原生训练后端 | 真实采样、优化器更新和检查点 | Chronos 原生 `fit`；AReaL 原生 rollout 与优化器，验收状态分别记录 |
| 数据加工 | 固定原始/派生成员、血缘与质量证据 | Data-Juicer 原生算子；数据发布/用途登记由执行结束后的显式调用决定 |

工具集不是框架内置项目，也不要求新增通用 ToolBroker。TimeCopilot 的内部回测工具只使用获准历史；独立未来目标不交给 Agent。执行轨迹、训练 reward、数据加工 filter 和正式评价分别记录。Candidate 不自行批准模型部署、数据发布或训练用途。

数据、任务、模型是否能替换，取决于它们明确声明的合同是否兼容。共享时序合同本身也可由外部领域包提供。AReaL 是训练后端、Data-Juicer 是数据加工基础设施，不能把它们当成与所有预测 Candidate 任意互换的同类组件。

## 当前分项状态

| 项目 | 官方源码固定点 | 已确认范围 | 尚待完成 |
| --- | --- | --- | --- |
| [TimeCopilot](https://github.com/TimeCopilot/timecopilot/tree/961aa330f71afcf53a6ecf2d4b499cb39b44da3e) | `961aa330f71afcf53a6ecf2d4b499cb39b44da3e` | **已完成工程闭环**：本地 14B、6 次模型请求、四个原生工具阶段、Agent 自选 AutoETS、独立未来评分与禁用模型重评 | 无质量 Gate，verdict 为 `insufficient_evidence`；保留前三次失败及预算，不声称预测优势或论文复现 |
| [ITFormer](https://github.com/OpenTSLab/ITFormer-ICML25/tree/b80142fc8b6ab2be8f148f3bb7a7534bb32f318b) | `b80142fc8b6ab2be8f148f3bb7a7534bb32f318b` | **已通过小视图工程验收**：8 QA、真实模型、独立评分、无模型依赖重评、发行与卸载验证 | 全量 42,477 测试 QA 的质量、训练和论文复现均不在本次已验证范围 |
| [Chronos-2](https://github.com/amazon-science/chronos-forecasting/tree/1224fafa91e1ecd6674f5204066b159e40b5e4a1) | `1224fafa91e1ecd6674f5204066b159e40b5e4a1` | **已完成工程闭环**：16 个基线 Run、60-step 原生训练、16 个新 worker 检查点留出评价、零推理重评 | 评价没有质量 Gate，verdict 为 `insufficient_evidence`；不能声称质量门槛通过或论文复现 |
| [Data-Juicer](https://github.com/datajuicer/data-juicer/tree/abb9e49897bdd0e0e2f44ce3272cc1ea5c5a6111) | `abb9e49897bdd0e0e2f44ce3272cc1ea5c5a6111` | **已通过工程验收**：原生过滤/去重/QA、12 次模型调用、独立质量、无模型重评、9 行派生数据显式登记及新进程训练用途读取 | 生成标签仍未验证；未进行下游训练，不声称模型质量提升或论文复现 |
| [AReaL](https://github.com/areal-project/AReaL/tree/3b93679888e9f4929f6f155f13c6a286a62dfd72) | `3b93679888e9f4929f6f155f13c6a286a62dfd72` | **训练与发布已实证**：32 个真实 Run、CAS tensor 消费、非零优势、Adam 更新和原生检查点/精确 FP32 部署投射 | **评价 pending**：新进程留出评价、零模型重评与封存摘要核对尚待最终报告；不宣称模型改进或论文复现 |

十六包共同安装/启用与移除回归、明确兼容合同下的跨项目 CPU 替换、两类非法组合的原生前拒绝均已验证，详细范围见下文。AReaL 第五次配方已取得真实训练与检查点发布证据；前四次失败/无效更新尝试保留，新进程留出评价和重评仍 pending。各阶段分别判断，CPU fixture 不替代训练，采样或工具成功也不替代优化器更新。

## TimeCopilot 已取得的真实证据

使用真实 AirPassengers 月度数据，前 120 点是公开历史，后续 12 点单独用于评价。原生 `TimeCopilot.analyze` 及其系统提示、工具闭包、参数校验和输出 validator 均保留。模型选择特征、回测模型及最终预测模型；枚举仅从原生 `TSFEATURES` 和实际 forecaster registry 发布，未脚本指定工具参数或预测答案。

成功实验使用完整本地 14B checkpoint，内容树 SHA-256 为 `d0d6f379d2324a9748b6c5e45179102113f9887fb22e0872b0c9480556c6c935`。用户明确同意后，配方显式选择 `tool_choice_mode=auto`；默认模式仍为 `required`。实际 HTTP 请求及 session 记录该策略。这是公开的请求策略配置，不声称服务拒绝 `required`，也不放宽原生输出校验、四工具成功和最终模型一致性条件。

| 指标或证据 | 实际结果 |
| --- | --- |
| Run | `run_654e248d308a48c9a1e7ca45ca802c78` |
| 独立未来 Evaluation | `evaluation_e06bc7e353c14b86ac8417b13229cee6` |
| 首次禁用模型重评 | `evaluation_6b91f9b88e9c46b192d451e5e357f455` |
| 停止模型服务后的新进程重评 | `evaluation_a30df0bae04d4424a8fa1c4ae6bc4ad9` |
| 正式调用与预算 | 6 次成功 HTTP ModelCall、4 次成功原生 ToolCall；provider usage 合计 31,389 tokens，无缺失 usage |
| 原生工具 | `tsfeatures_tool` → `cross_validation_tool` → `forecast_tool` → `detect_anomalies_tool`，各一次 |
| Agent 的选择 | AutoETS；真实回测至少比较两个模型并包含 SeasonalNaive，工具返回原样进入后续模型请求 |
| 独立未来 MAE / RMSE | `44.41334215619239` / `52.018265022593305` |
| 正式计数与 verdict | 两个指标均 eligible=1、scored=1：一个含 12 个未来点的预测单元；`gates=[]`，verdict 为 `insufficient_evidence` |

停止本地模型服务后，在新解释器中明确禁止 Popen、Candidate 构造和 native invoke；没有导入 torch、TimeCopilot、PydanticAI 或 statsforecast。重评的全部指标逐字相同，封存结果和事件摘要均不变。IO 记录是真实请求、响应及工具返回，没有 native token IDs/logprobs，不把 provider usage 当成 RL rollout。工程工具闭环完成不能改写成预测优势或未设置的质量门槛通过。

前三次失败全部保留：7B 选择不存在的 `seasonality` 特征；增加原生枚举后的 7B 重复特征调用达到 12 次工具上限；14B 在 `required` 策略下重复四阶段达到同一上限。之后的成功没有重置历史预算或删除失败。late outcome 重试复用不可变 `available_at`，原失败 Run 也已零模型完成 `score`；缺失 Run 保留在计划分母。13 项 CPU 合同与生命周期测试通过，其中五项使用实际自有 `sleep` 进程验证父终止、启用保护前父已退出和残留子进程清理，不涉及模型推理。

## ITFormer 已取得的真实证据

### 官方资产与派生数据

采用 [ITFormer-7B](https://huggingface.co/pandalin98/ITFormer-7B/tree/a5f52d265b7303bae513e77512453d86d477c44b) 和外部 [Qwen2.5-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct/tree/a09a35458c702b33eeacc393d103063234e8bc28)，共 11 个实际分片的长度与 SHA-256 全部匹配官方固定快照的 LFS 身份。原生基础 Qwen 加载的 missing/unexpected/mismatched keys 均为空；150 个非 LLM 权重键及加载后张量全部验证，未接受随机 encoder 回退。

[EngineMT-QA](https://huggingface.co/datasets/pandalin98/EngineMT-QA/tree/ea2051a15512212976c22c1a075ec549c7d48eef) 固定 revision 为 `ea2051a15512212976c22c1a075ec549c7d48eef`。完整原 HDF5 为 18,838,039,816 字节，`seq_data` 形状为 `(118921, 600, 33)`。本轮范围读取 29 次、共 3,328,912 字节，得到 21 条真实原信号的紧凑派生 HDF5，未下载完整原文件。

派生清单记录官方整体 LFS 身份、实际字节范围及摘要、原始数值和 native float32 摘要、原信号 ID→派生行映射、展开 QA 索引和新资产摘要。不补零、不把派生文件称为完整原文件。固定 HTTPS 来源和范围摘要不是对原完整文件 LFS hash 的重新计算或 Merkle 包含证明。17 MB QA 文件的完整 SHA-256 已核对官方 LFS。

选择展开索引 `[0,1,2,3,4,11,12,35]`，四个阶段各 2 条。公开信号/原问题与 evaluation-only 答案分开；原生严格 Dataset/Collator 仅收到空答案占位，模型只收到五个获准输入张量，没有真实 labels/reference。不同 QA 即使共用信号或源行也不会去重。

### 运行与质量

| 指标或证据 | 实际结果 |
| --- | --- |
| Run | `run_00abb98bd1a3481ca5b34f1964c36e24` |
| 首次独立 Evaluation | `evaluation_9aeab3ec4361429c9d01ef985d442517` |
| 最终发行 wheel 的零推理重评 | `evaluation_455cf0985af946f494d9a117fdde720f` |
| 实际模型/工具调用 | 8 次成功 ModelCall，0 次 ToolCall；该模型没有 Agent 工具行为 |
| native token IDs | 672 prompt tokens、144 completion tokens；无 128-token 上限截断 |
| 格式有效率 | 8/8 |
| 混合任务精确匹配 | 2/8；Stage 2 为 2/2，Stage 3 为 0/2，开放 Stage 1/4 的全文匹配均为 0/2 |
| 词面 token F1 | `0.49763887682055463`；不表示语义正确率，也不是论文 BLEU/ROUGE |
| GPU | 一张 A800，预算记录 415.744 秒，约 0.1155 GPU 小时；无训练 |
| 原执行证据 | 62 个事件与封存 execution Snapshot 摘要一致 |

工程 Gate 检查 Run 成功和全部固定 QA 的评分覆盖。其 `pass` 不等于全部问题答对、模型改进或整篇论文复现。IO profile 额外保留真实 token IDs 和输入张量，但没有 logprobs，不声称是可用于 RL 的 native rollout。

### 独立重评与发行

从 sdist 重建 wheel，并在源码目录外安装。26 项 CPU 合同测试通过，包括源/答案隔离、原生 pickle 优先级拒绝、实际 range 边界、权重/分片结构负例、实际已安装 core 字节的完整 wheel 身份与错误摘要拒绝，以及部分失败仍保留全体计划 QA 分母。

测试按可选依赖分层：真实安装 `data` extra 的环境完成全部 26 项、零跳过；仅安装核心和轻量适配包的环境执行 21 项，并明确 skip 5 项 HDF5/NumPy native-data CPU 测试。注册、Schema、核心冻结、纯规划、真实 SDK 评分/重评和失败分母均在轻量环境继续执行，使用明确标记的 test-only JSON 视图，不把 skip 计作已验证数据准备。生产包全部 12 个 Python 模块与此前已验证 wheel 逐字节一致；本次只修测试分层和文档。

在没有 torch、transformers、h5py、timm 的独立解释器中重评成功。新 Run 执行和 Candidate.prepare 都被明确禁止且计数为 0，指标与原评价一致。卸载整个适配包后，核心的 39 个文件仍匹配 F0，并能读取 8 条历史结果和 62 个事件；缺少领域包时不宣称还能执行该领域评分。

实际执行 wheel 与最终发行 wheel 均留有摘要。最终包增加一命令准备、许可/文档、拒绝 pickle 覆盖的预检及纯 CPU 的可移植核心身份生成；原生加载、预处理、生成与评分算法没有替换。最终 wheel SHA-256 为 `28cf434e3bb70b9db019a559c994aa83c69152d09deb12ff6e0e07af3d6b157b`。重评实际使用最终发行 wheel，未为打包修改重复扩大 GPU 验证。

## Chronos-2 已取得的真实证据

采用固定官方 ETTh1，历史长度 128、预测长度 24，两个目标与历史变量、由时间网格验证的未来日历协变量。train `[0,8640)`、validation `[8640,11520)`、test `[11520,14400)` 按时间隔离；最终评价覆盖固定 16 个不重叠测试窗口。未来测量目标与传感器值不进入公开输入。

原生训练 Run 为 `run_508b298211354d21a174757c57f9bde3`：60 个请求步骤、60 次优化器更新及 60 条梯度记录；全梯度与最终权重均有限，存在非零有效梯度，`weight_decay=0`，训练前后权重摘要变化。不可变完整检查点归档 SHA-256 为 `d832567797c90493bed17286cdf816b1ed04bf73fbe76d1ecda6bf0a70140792`。训练 Run 内的输出作为诊断，正式训练后结果来自 16 个新 worker 重新加载检查点后的独立评价。

| 指标 | 基线 16 窗口 | 训练后重载 16 窗口 |
| --- | --- | --- |
| MAE | `1.1235232855` | `1.0884078331` |
| RMSE | `1.4479391914` | `1.3950889680` |
| pinball | `0.3647506867` | `0.3400679019` |
| 80% 区间覆盖 | `0.6927083333` | `0.73046875` |
| 区间宽度 | `2.7135988895` | `2.9040314918` |

所有指标为 16/16 已评分窗口。点预测来自原生 q=0.5，即 median；覆盖率和区间宽度须同时解释。这里观测到的是固定小视图上的数值变化，不推断总体泛化提升，也不把覆盖率升高单独称为校准通过。

训练后留出 Evaluation 为 `evaluation_334191dce7e24616beac8a3c08338657`；没有 torch/chronos 且禁止 Worker 与模型 identity 调用的重评为 `evaluation_4d99686833a743d5828c4efb4c350a67`。16 个封存 Run 的结果与事件摘要保持不变，基线零推理重评为 `evaluation_0dfcd60d61224c53be77150284e6d476`。由于配方的 `gates=[]`，评价 verdict 为 `insufficient_evidence`；工程证据完成不能改写成未设置的质量门槛已通过。

12 项合同测试及 sdist 重建检查通过。首次 Scorer 的 list/dict 边界错误、Run `run_17a39973b1c045e7b945d8bf004f971a` 在 fit 前因训练 Payload 未展开而失败，以及重试时 outcome 可用时间变化导致的冲突均保留。后两项分别由真实 ArtifactStore 回归和复用不可变 outcome revision 处理；不把 fit 前失败计为已训练，也不删除预算或失败记录。该项目没有修改核心。

## Data-Juicer 已取得的真实证据

固定 Data-Juicer `1.6.1` 的 `init_configs`、`DefaultExecutor.run` 和原生本地 HF QA mapper。输入由 ChatTS 自身生成器产生，按完整 family 先分出 12 个训练 family 和 4 个隔离 holdout family，再仅向训练输入加入 2 条重复记录和 1 条过短记录。holdout 及用户提供的 benchmark 均不进入 Candidate。原生 worker 使用独立依赖环境和本地 Qwen2.5-7B-Instruct；不调用付费服务，不修改核心。

| 指标或证据 | 实际结果 |
| --- | --- |
| Run | `run_f1b1d96a6c514a9986f41d343531bea5` |
| 独立 Evaluation / 零模型重评 | `evaluation_17905a0425034944a8fff1beeee62aac` / `evaluation_979a941b750a4294a188fd670142fc81`，均 completed/pass |
| 原生阶段 | 15 输入 → 长度过滤 14 → exact document dedup 12 → QA 输出 9 |
| 正式调用 | 3 个算子 ToolCall、12 个真实 HF ModelCall；生成请求均为 `return_full_text=False` |
| 源级质量分母 | 固定 12 个合法源：6 个正确、3 个数值错误、3 个没有原生 QA 输出 |
| 源级正确率 / 结构率 / 源覆盖 | `0.50` / `0.75` / `0.75` |
| 唯一率 / 血缘 / holdout 隔离 | 均为 `1.0` |
| AutoBench 计数层级 | 一份完整加工视图为一个评价单元；6 个指标的聚合 counts 均为 eligible=1、scored=1，源级 12 条分母在质量诊断中固定 |
| 派生消费 | 9 行全部显式登记为 `model_generated_unverified`；新进程以 training 用途读取 9 行，不导入原生依赖 |

审计包装调用原始 QA 实现，只记录真正的 pipeline 请求、返回和完整阶段成员。原生 mapper 解析的是新增生成文本，没有将输入格式模板误当成生成 QA；完整模型 IO 没有被改写。独立 Scorer 重新计算数值答案、结构、源覆盖、去重残留、全阶段血缘和 holdout 污染。`pass` 只表示运行、血缘和用途隔离 Gate 通过；0.50 的正确率不能改写成全部答案正确。

重评在无 torch 的轻量环境完成，明确禁止 Popen、Candidate.prepare 和 Source 执行，全部 6 个指标及 counts 与原评价相同，Run 不变。派生数据必须在 Run 成功封存后，由调用者提交同 Run 的正式不可变质量报告显式登记；血缘或 holdout Gate 未通过则拒绝训练用途发布。3 条错误答案仍保留为未验证标签，没有用独立答案进行 oracle 筛选；3 个无输出源也保留在评分分母中。数据读取通过不等于下游训练更新或效果提升。

此前四次失败证据保留，包括旧提示下 12 次真实调用只生成 `Assistant:`、原生解析零 QA 的实验。最终增强公开格式指引并生成新的 source revision，没有附加当前答案或修改原生输出。完整原始轨迹本机保存，公开的小型[机器可读摘要](../adapters/datajuicer/examples/native-validation-2026-10-21.json)不包含原始题目、答案、模型或活动 CAS。

## AReaL 已取得的真实证据

### 原生配方与训练

独立适配包使用原生 TIR、calculator、GRPO 优势、PPOTrainer、LoRA 参数和 HF saver，没有改动核心或使用 TRL 代替原生训练。公开样本来自固定 GSM8K train 与 ChatTS train-only 合成视图，独立测试参考不进入模型提示。用户批准的公开投射 `areal.public-calculator-verification@3.0.0` 说明纯算术工具语法与核验要求，由模型选择表达式、调用工具并继续生成。V10 与 V11 的八组完整 `native_messages` 字节相同。

配方保留原生 `max_turns=2`，另设物理 HTTP cap=8、单段 180 秒、episode 600 秒和远程 group `4 * 600 + 120 = 2520` 秒。工具 start/end 可能各占一段，结果消费还需后续模型段；这几个预算不能混为工具次数。第五次配方在新身份下重新采样，没有改写此前 Run 的输出或奖励。

| 训练证据 | 第五次原生 job 的实际结果 |
| --- | --- |
| 实际采样 | 32/32 个真实 native Run succeeded；17 次成功原生工具调用 |
| 训练输入 | 32 份原 CAS tensor 的成员 Counter 与实际消费精确一致；不是优化结束后补导入 |
| 优势 | 10,356 个非零且有限的 advantage token |
| 梯度 / 优化器 | gradient norm `0.0681703474`；Adam step `0 → 1`；`weight_decay=0` |
| 实际参数变化 | 196 个 LoRA 参数 tensor 变化；delta L2 `0.7870101283` |
| 原生保存 | 三次 HF save，各 392 个 tensor 与原生显式 key/dtype cast 后的实际参数等值；initial 与 final saved hash 不同 |
| 原生版本 | 最终观测 native policy version 为 `1`；不以适配器版本冒充原生增量 |
| 尚待结果 | 新进程留出 Evaluation、禁止模型的重评、对应 ID 与封存结果/事件摘要核对均 pending |

这是一次有参数更新的受限工程训练，不是完整论文复现，也不证明测试集效果提升。评价未完成前不宣称五项目全部通过。

### 答案合同、检查点与不同身份

`areal.boxed-to-verifiable-qa@2.0.0` 仅依据原始文本及原生声明的停止 token 投射格式，不读取 gold。它最多剥除八个实际匹配的尾部停止 token，读取最后一个完整终结 box，允许其后只有空白、一个闭合 LaTeX 定界符和可选句末标点。GSM8K 仍要求有限纯整数/十进制数，规范化为 `#### <number>`，不计算表达式或修正答案。ChatTS 接受 boxed JSON；仅当全文没有 boxed 标记时才允许唯一显式 json fenced block。坏的末尾 box 不回退到更早答案，原 parser、四字段校验和数值评分不变。原文本/hash、投射 hash、移除 token 与格式来源均保留，格式率明确针对 canonical projection。

builder `gymts.areal.sealed-tir-builder@2.0.0` 与 `gymts.areal/native-tir-training-shard/2` 要求采样当时记录 CODEC2、reward audit 身份一致，transform 明示 `already_applied_in_live_Run`、`reapply=False`；拒绝重新套用 CODEC2 到 CODEC1 历史数据。旧合同仍使用原冻结 builder。

原生 BF16 checkpoint 在独立 CAS zip 中保留原始字节；部署另建 FP32 投射，392 个 tensor 逐个记录原/部署 dtype、shape、hash，并验证精确提升与精确往返。初始 rollout 的 `rollout_policy_revision`、最终原生 `training_policy_revision` 与可加载部署 bundle 的 `policy_revision` 分开记录。投射不修改原目录，不恢复 optimizer FP32 master precision，也不承诺 logits 逐位相同。

独立 tiny CPU publisher fixture 已实际通过原 `gymts_rl.checkpoint.load_checkpoint_policy` / PEFT 加载，投射 hash 与已加载 tensor hash 一致；错 saved hash、初末相同、消费替换及无成功 fixture 工具均被拒绝。其 synthetic bridge/FakeRecords 为明确测试数据，真实 Run/工具/optimizer 为 0，不是 RL 验收。V11 科学依赖 CPU 环境 19/19 零跳过另行记录，也不能替代上述真实训练。

### 五次 attempt 与失败保留

| Attempt | 实际边界与结果 |
| --- | --- |
| job1 | 上游裸 `python3` 误选环境；0 rollout、0 update；部署 PATH 与原生子启动 CPU 预检随后修正 |
| job2 | 原生远程 group 180 秒导致整组超时，保留失败/取消封存；0 update，scripted CPU probe 不计入真实训练 |
| job3 | physical HTTP cap=4 阻断工具 start/end 后续推；保留真实工具成功与失败，但 0 update |
| job4 | P3/cap8 下 32 个真实 Run 全成功，32 个原奖励均 0；all-zero advantages 门禁拒绝，0 update |
| job5 | 用户批准 CODEC2 后 V11 重新采样，取得上列非零优势、参数更新与检查点发布；独立评价/重评 pending |

对 job4 旧文本的只读 CODEC2 诊断为 22/32 可解析、六组反事实奖励非恒，仅作前检，`diagnostic_only=true`、`used_for_training=false`。旧 Run、reward、tensor 和身份保持原状；不能将反事实奖励算为已完成训练。最终 attempt-chain 将记录各次精确分母、预算和制品身份，不删除失败、重置预算或混入 CPU fixture。

### 留出评价失败与待决兼容投影

原生训练环境使用 Transformers `5.3.0`。首次新进程留出评价 `evaluation_9c7daf8f6e014512b5bb07c19e5ee400` 固定四个预期单元，实际 0 个 succeeded Run、4 个 failed Run。报告本身为 `completed` / `insufficient_evidence`，accuracy 与 format_valid 的 aggregate counts 均为 eligible=4、scored=0、excluded=4。四个 `capture_incomplete` 的底层原因是 HF5 不再接受既有共享 RL Candidate 的 `generate(use_model_defaults=...)` 参数；检查点 loader/hash 不是此次错误来源。原报告、失败 Run、模型调用错误和 host log 均保留，未覆盖输出、重训或事后添加质量 Gate。这次失败评价消耗 `762.100938` GPU 秒；截至此状态，已关闭分配累计为 `3.3442259951432547` GPU 小时，尚无后续 GPU 评价。

另一个独立问题是 CLI 曾把工程完成强制等同 `verdict=pass`。V12 仅修正 adapter CLI 的完成性检查：没有 Gate 的完整评价可以保留 `insufficient_evidence`，仍检查实际覆盖、失败与错误；它不能把上述四个失败 Run 改为成功，也不改变 Scorer、原生训练、模型生成或 checkpoint 内容。V11 实际训练和后续 CLI 修正分别保留身份，不声称最终所有模块与原执行 wheel 逐字相同。

独立 HF `4.57` 环境的 tiny CPU 实际生成、teacher-forced log probabilities 和原共享 RL loader 已通过预检。真实生产资产预检随后正确拒绝 native HF5 tokenizer 配置：`extra_special_tokens` 是含 **13** 项的有序 list，HF4 期待的是命名 token dict；并非空 list 转换问题。该 list 与原 base 配置的 `additional_special_tokens` 逐项有序相同。候选版本化投影将完整 13 项保留到 HF4 `additional_special_tokens`，使用空命名 map，其余配置保留；`tokenizer.json` 与 chat template 原字节不变。

CPU 已对真实资产证明：HF5 原 tokenizer 与 HF4 候选投影的全部 **151,665** 个 vocab 映射、长度、13 项特殊 token ID、BOS/EOS/PAD、decode，以及三组通用 chat template 渲染、input IDs 和 attention mask 一致。报告 `v13-actual-tokenizer-metadata-cpu.json` 同时核对其余四个资产字节不变。这是 tokenizer 等价证据，不是新模型推理或训练，也不保证跨 HF 运行时 logits 逐位相同。

V13 optional publisher 草案拟以显式 `--tokenizer-compatibility hf4` 生成新部署资产；默认仍保留 native 配置，原 native archive、旧 bundle 和已封存 Run 不改。草案检查发现 22 项，20 项 CPU 执行通过、2 项条件 skip。**用户对兼容路线的选择仍 pending；草案未向主 store 发布，未运行 GPU，也未取得成功留出评价或零模型重评。**V13 草案数字不替换下文 V2 + V11 的已登记发行组合口径，不能把 tiny/metadata fixture 当作生产测评成功。

训练成功部分已另行作 **INTERIM** 持久归档并恢复核验，不等待 tokenizer 选择而只留临时目录。ignored 相对目录为 `.gymts-five-projects/evidence/`，完整 receipt 文件名为 `areal-before-tokenizer-choice-receipt-20261020T152725Z.json`，SHA-256 为 `71f0d1df91e6aa99a8979ed5cb4564ec9b96ceb48b752e8c03bb6a63f92f77ae`。同目录 archive 为 `areal-before-tokenizer-choice-evidence-20261020T152725Z.tar.gz`，111,097,271 字节，SHA-256 为 `b8a723381763bde32792766399705eec7acd70a1a0597457e9bd7d69c7471240`。这些是部署机器的本地私有归档位置，不是公开下载地址，不替换最终 master receipt。

恢复验证覆盖 92 个 sealed Run：83 个 train 用途 Run（79 succeeded、4 failed）、5 个独立 scripted CPU probe（3 succeeded、2 failed）、4 个 heldout Run（0 succeeded、4 failed）；不能写成 92 次真实训练或 83 次参数更新。共 1,398 个事件、5,131 个 CAS ref 及各 Run metadata/result/event 与原 sealed trace 摘要一致，prepared train=8 / eval=4 的三份资源文件可恢复。验证使用轻量 CPU 与 F0 的 39 个核心文件，没有模型、评分或 GPU 调用；原 SQLite/CAS 未改。tokenizer 选择、成功留出评价及重评仍 pending。

## 跨项目替换与发行验证

十六个独立包在 V2 冻结快照通过离线 wheel/sdist 构建、源码外安装、依赖解析、共同启用与移除回归；Python 3.11.8 原报告为 398 项发现、339 项执行通过、59 项 skip。已登记的 V11 组合口径使用 V2 其余十五包加 V11 AReaL 独立发行补检：以 19 项发现、17 项执行通过、2 项 skip 替换旧 AReaL 的 13/13/0，合计 **404 项发现、343 项执行通过、61 项条件跳过**。这是两个明确冻结报告的组合，不声称已经对全部最终源码执行一份全量报告。V11 完整科学 CPU 环境 19/19 零跳过另列，不重复加到总数。十六包共同启用、移除 AReaL 后其余十五包及核心 Run 正常的 V2 证据继续保留；条件跳过不视为原生模型验收。

另行建立仅安装 F0 与必要轻量 wheel 的宿主，原样复制 TimeCopilot 已有 AirPassengers 公开 snapshot，保持 CAS 身份、120 点历史和独立 12 点未来参考不变。替换为旧 LibraryTS 的原生 NaiveForecaster（drift）和 PolynomialTrendForecaster（degree=1），复用中立 timeseries 的 Task/Scorer。再将相同公开值导入 `csv-numeric-snapshot`；它具有新的派生 revision，但两个来源生成的实际 TaskInput、预测和分数逐字一致。同一公开 snapshot 也可改为 trend Task，使用另行声明的历史 OLS 斜率符号参考，不将换任务称为相同预测 holdout。

| Task / Source | Candidate | 独立评价结果 |
| --- | --- | --- |
| forecast.numeric / snapshot 与 CSV 各运行一次 | naive-drift | MAE `79.04341736694678`，RMSE `102.57890694158483` |
| forecast.numeric / snapshot 与 CSV 各运行一次 | polynomial-linear | MAE `50.08248547352826`，RMSE `67.42081565543427` |
| pattern.trend_direction / 原 snapshot | 两种 Candidate 各运行一次 | accuracy 均为 `1.0`；每种仅一个独立任务单元 |

共 6 个真实 CPU Run、6 次当前输入原生 fit、6 个正式 ModelCall 和 6 个内部 ToolCall，新增 LLM 请求和 GPU 使用均为 0；不持久训练权重。三个独立评分分别在新进程重评，明确禁止 Popen、Candidate、Source 和原生调用，全部指标、封存结果与事件摘要不变。原 TimeCopilot store 全部文件内容摘要保持不变；完整工作使用独立 store。两个非法组合经真实 `gym.validate` 和 `gym.plan` 在 Popen 禁止时拒绝：Chronos 分布 Candidate 配 point-QA Task，以及 LibraryTS 请求持久 `prepare=fit`。两个拒绝的进程调用均为 0。

宿主和已有 LibraryTS 科学解释器的核心均核对全部 39 文件匹配 F0，未改核心或任何现有 adapter 生产代码。旧 host wheel 与 native 环境的 `source.py/candidate.py/tools.py` 包装字节不同，身份分别保留；实际执行的 worker/runtime 字节相同，源校验函数 AST 相同，差异中的 source 仅增加 scope/effect 元数据。未悄改旧环境，也不声称整个包装完全一致。证据读取脚本的两处 manifest/event 名称假设错误保留日志，从已有封存结果恢复，未重跑已完成原生模型。

具体 Run、Evaluation、重评 ID、计数与边界见[跨项目机器可读摘要](reports/cross-project-role-replacement-2026-10-21.json)。三份评价均保留 `gates=[]` 和 `insufficient_evidence`。这证明所列兼容合同下的数据、任务和 Candidate 替换；固定 LibraryTS Candidate 不构成新的 Agent 循环，也不证明 TimeCopilot 已能任意替换外部工具集，更不表示质量提升或论文复现。

## 失败与适配修正

| 真实问题或边界 | 处理与证据 | 核心影响 |
| --- | --- | --- |
| 本机一个 Qwen 分片少 82,746 字节 | 在加载前拒绝；改用只读的完整副本，11 个实际分片随后全部核对官方 LFS | 0 |
| 18.8 GB HDF5 单连接下载缓慢且不完整 | 不使用残缺文件；改为固定官方范围读取，明确登记紧凑派生资产 | 0 |
| 原生 ITFormer 的缺权重/预处理回退 | 检查完整键和实际张量，启用严格预处理，并核对原生 tokens/信号；拒绝 pickle 文件优先覆盖 | 0 |
| TimeCopilot 的工具 schema 未列原生合法值 | 从原生特征/模型 registry 发布枚举，保留闭包、参数与输出 validator；原无效特征失败不删除 | 0 |
| TimeCopilot 在工具预算内未终止 | 保留三次真实失败；用户明确同意后新实验配置 `auto`，不放宽四工具/最终模型一致性条件，不重置预算 | 0 |
| 独立 worker 可能在宿主硬终止后残留 | 适配器设置 Linux 父亡保护并仅清理自有会话进程组；五项实际进程回归验证，无关进程仍存活 | 0 |
| Chronos record snapshot 可以是 list 或包装 dict | 修正在外部 Scorer；训练已验证有限梯度、有限权重、60 次实际更新及新进程检查点评价 | 核心保持 F0 |
| Chronos 训练视图返回 Payload | 适配器显式展开后读取获准训练字段；保留 fit 前失败 Run，新增真实 ArtifactStore 回归 | 0 |
| 重试时同一 outcome revision 的可用时间改变 | 复用已存在的不可变 outcome；参考内容变化则拒绝，不改旧结果或旧标签 | 0 |
| Chronos 原生返回值名为 mean，实际取 q=0.5 | 证据与文档明确点预测是 median，避免声称条件均值 | 0 |
| AReaL 上游硬编码 `python3` 误选其他本机解释器 | 首次 job 失败、0 rollout/0 update；随后显式 PATH 与原生子启动预检已修正；前四 attempt 与 job5 训练分别记录，不改旧证据 | 0 |
| 重评仍需要 Candidate manifest | 保留轻量适配注册元数据与领域 Scorer，移除重型原生依赖；这是 core 0.5 的现有边界 | 未改核心 |

后续失败不能从覆盖率或预算中删除。错误、取消、超时和未知终态与成功记录一起保留；训练失败或无效 advantage 不能用一次成功推理替代。尚未取得最终报告的失败/重试数量不在本页猜测。

## 使用入口与存储

准备、安装、运行、检查点和重评使用各包文档中的实际命令：

- [TimeCopilot](../adapters/timecopilot/README.md)：真实 Agent、AirPassengers 历史/隐藏未来、模型与工具预算。
- [ITFormer](../adapters/itformer/README.md)：官方范围投影、原生模型、独立答案、源码外发行。
- [Chronos-2](../adapters/chronos/README.md)：ETTh1 多变量/日历协变量、分位数、原生 fit 和检查点。
- [Data-Juicer](../adapters/datajuicer/README.md)：ChatTS train-only 加工、完整成员血缘、显式派生数据登记。
- [AReaL](../adapters/areal/README.md)：原生 TIR/PPO 训练、检查点发布和轻量发行已验证；新进程留出评价与重评 pending。

ITFormer 的固定 8-QA 小视图已经验证可以一条显式命令准备：

```bash
gymts-itformer prepare-official --output /tmp/gymts-itformer/prepared
```

完整准备会验证 QA 内容，再读取所需官方信号范围；后续 `--view` 使用 `/tmp/gymts-itformer/prepared/view`。实际新运行仍需配置明确的原生 checkout、模型、基础 Qwen 与已授权设备，按包文档执行，不能仅凭此命令声称模型已运行。

按包 README 构建并安装核心 wheel 后，用户可自行生成后续命令必需的核心身份，不依赖本轮 `/tmp` 验收目录：

```bash
gymts-itformer freeze-core \
  --wheel /tmp/gymts-itformer-wheels/gymts-0.5.0-py3-none-any.whl \
  --output /tmp/gymts-itformer/core-identity.json
```

该命令逐文件比较实际导入的完整已安装包与提供 wheel 的原始字节，记录版本和 wheel SHA-256；拒绝 editable/source 回退。实际 F0 wheel 已验证成功，指定错误 `--expected-sha256` 会失败且不写身份。生成文件不含本机绝对路径或历史 Git 要求；已用它在无模型依赖环境完成 `plan` 和重评。自行构建 wheel 的身份不等于本轮固定 F0 的来源认证，若需复核 F0，还应对照上表的固定 wheel 摘要。

活动 SQLite/CAS、构建、检查点和 worker 工作目录位于本机 POSIX 文件系统；模型、原始数据和下载缓存另外保存，不进入 Git。公开源码保留接口、配方、文档和无私有原题/答案的小型摘要；完整 CAS、原始/派生数据、模型、训练输出和大日志本机归档，不随源码发布。

本轮完整 ITFormer 验收摘要位于运行工作区的 `itformer/acceptance.json`；Run store 为同工作区的 `itformer/runs`。这些是本机验收产物，不是已公开下载的 benchmark 或模型发布。公开文档中的身份和指标不能替代完整 CAS 复查。

## 尚未作出的承诺

本页不承诺五项目已全部通过、不承诺所有异构角色任意互换，也不承诺整体论文复现。TimeCopilot 的真实工具循环和独立重评、十六包发行/移除回归和所列跨项目替换均已完成；AReaL 已取得有效训练和检查点发布证据，仅新进程留出评价与重评仍待最终报告。Data-Juicer 派生数据登记和实际读取已完成，生成标签仍未验证；Chronos 训练重载的工程证据已经完成，但没有设置正式质量 Gate。

轨迹不是 reward，独立评分不是训练标签审批，数据加工成功不代表生成答案正确。用户提供的五份 benchmark 附件始终仅用于评价。公开数据、代码和模型的许可分别记录；受信任 Python 适配包也不等于操作系统沙箱。模型部署、远程发布、扩大资源或修改核心均不由 Candidate 自行决定。
