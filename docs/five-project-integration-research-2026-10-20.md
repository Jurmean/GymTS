# 首批五个新项目：调研与接入提案

状态：**用户于 2026-10-21 确认开始，五项目独立适配与真实验收进行中**。调研日期：2026-10-20；实际结果以分项目验收报告为准，不以提案代替运行证据。

本轮目标是用不同原生工作流检验 GymTS 的通用性。建议选择三个时序应用、一个 Agentic RL 框架、一个 LLM 数据基础设施；不将项目实现搬进核心，也不为了凑齐角色而要求每个包都提供 Source、Task、Candidate 和 Scorer。

## 当前基线与职责

主仓库为 Jurmean/GymTS，调研基线提交 `121abca88b65094e899b294a3d3416ccd004a25d`，核心版本 0.5.0、公共合同 1.2.0。本轮重新运行 `python3 -B -m unittest discover -s tests -q`，160 项全部通过。与[历史冻结身份](reports/core-frozen-identity-2026-10-20.json)比较，38 个核心 Python 文件均未变化；`setup.cfg` 有此前许可证与包元数据更新，因此不能沿用历史 wheel 的摘要声称是当前构建。

正式接入前，从当前确定提交构建新 wheel，记录 wheel、源码文件与依赖摘要，作为 F0；以上回归不代替五个新项目的原生验收。

按照[项目网页](https://netman.aiops.org/contacts/projects/)、[框架说明](framework.md)和[工具边界](agent-toolsets.md)：

- EnvironmentTS 负责执行、获准环境访问、数据资源入口、Run、轨迹和封存证据。
- AutoBenchTS 负责固定评价计划、独立参考、Scorer、比较及同 Run 重评。
- 适配包负责项目格式、原生 harness、模型 codec、工具桥接、训练后端、奖励映射和领域评分。
- Agent 决定工具及参数，原生执行平台实际调用工具。配置限制允许能力，不编排一个冒充自主决策的固定工具序列。
- 训练奖励、执行轨迹、正式评价分别登记；模型或数据的发布、持久更新不由 Candidate 自行批准。

## 建议的五个名额

下列 SHA 是调研固定点，不是已验收运行锁文件。模型、数据和实际依赖仍需在各项目预检后分别固定。

| 项目 | 官方源码固定点 | 新挑战 | 建议原生验收路径 | 成本与未决项 |
| --- | --- | --- | --- | --- |
| TimeCopilot | [961aa330](https://github.com/TimeCopilot/timecopilot/tree/961aa330f71afcf53a6ecf2d4b499cb39b44da3e)，MIT | 真实 Agent 自选统计、回测与预测工具，消费结果继续分析 | 本地 LLM + 原生 Agent；保存完整工具调用和实际选型；未来目标留给独立预测评价 | 当前依赖较重，需独立解释器；本地模型的工具格式与终止能力待真实预检 |
| ITFormer | [b80142fc](https://github.com/OpenTSLab/ITFormer-ICML25/tree/b80142fc8b6ab2be8f148f3bb7a7534bb32f318b)，MIT | HDF5 多变量传感器数据、信号与问答关联、processor/encoder 与语言模型组合 | 原生模型与 EngineMT-QA；固定测试视图，保留信号/问题身份与原答案；AutoBench 独立评分 | 本地已有权重；数据尚需准备；本地旧源码有修改，不能冒充官方冻结版本 |
| Chronos-2 | [1224fafa](https://github.com/amazon-science/chronos-forecasting/tree/1224fafa91e1ecd6674f5204066b159e40b5e4a1)，Apache-2.0 | 多变量、未来已知协变量、分位数预测及其独立评价 | 原生 `Chronos2Pipeline.predict_quantiles/predict_df`；再用原生 `fit` 做有界训练、保存和新进程加载 | 官方 120M 权重需单独固定；CPU/单 GPU 路径可选；协变量可见性必须逐字段核对 |
| AReaL | [3b936798](https://github.com/areal-project/AReaL/tree/3b93679888e9f4929f6f155f13c6a286a62dfd72)，2.1.0，Apache-2.0 | 多轮工具反馈、原生 tokens/logprobs/mask、策略修订、训练与采样衔接 | 原生 TIR workflow、calculator-only、本地 Qwen；真实 PPO/GRPO 后端更新、HF 检查点导出、独立新进程评价 | 首选同步短任务验证，避免首轮引入分布式恢复；当前 CUDA 栈与驱动的兼容性必须先测，未承诺可运行 |
| Data-Juicer | [abb9e498](https://github.com/datajuicer/data-juicer/tree/abb9e49897bdd0e0e2f44ce3272cc1ea5c5a6111)，v1.6.1，Apache-2.0 | 原始数据到派生训练集的成员变化、去重、合成和加工血缘 | 原生 YAML 算子管线及 `DefaultExecutor.run`；加工产物先封存，再由 EnvironmentTS 显式登记派生数据；独立质量评价 | 独立运行环境，只安装使用的算子依赖；原生抽样 tracer 不能当作全量 GymTS 轨迹 |

选型理由：这五个工作流分别检验 Agent、跨模态数据/模型、概率预测与训练、多轮 RL、数据加工血缘。TimeCopilot 和 Chronos-2 必须各自独立完成原生验收；一次嵌套调用不能替代两个项目的交付。AReaL 和 Data-Juicer 是独立基础设施接入，最终仍使用时序数据/任务检验，不能只跑与时序无关的示例后宣称领域能力完成。

### 已调研的替补与取舍

| 候选 | 有价值的挑战 | 本轮暂不首选的具体原因 |
| --- | --- | --- |
| [Cast-R1](https://github.com/ustc-time-series/Cast-R1/tree/c14fdda764cf8e111e433c8a714252f5038e72d1) | 时序诊断、选预测模型、记忆状态、多轮 GRPO | 官方未附 SFT/RL 策略权重，论文训练设置为 4 张 A800，仓库未见明确代码许可证；完整接入需要增加准备与训练范围。CPU 检查不等于真实 8B 闭环 |
| [Agent Lightning](https://github.com/microsoft/agent-lightning/tree/05c7fe133175653e48c990546a3509e52dc56512) | 原生 Agent harness、代理采集与训练 | 当前 v1 与旧版 API 完全不同；安装文档与脚本的 vLLM 版本有漂移；官方本地清理脚本包含全局进程清理，不能原样在共享机器运行 |
| [rLLM](https://github.com/rllm-org/rllm/tree/4e828c81680e5a85b638ceedeaf09d1e90109ca8) | harness 与训练 backend 分离、多轮工具训练 | 当前 verl/vLLM/torch 依赖较重，默认示例使用更多卡；可替代 AReaL，但不能仅按旧文档认定更容易部署 |
| [SkyRL](https://github.com/NovaSky-AI/SkyRL/tree/f8abdfa81a2bf4bf18eefdf081d5195ec1d9e5a4) | 自定义 Generator 接入原生 harness | 当前源码依赖比网页索引更新，已采用 CUDA 13 栈；此轮不先调整共享机器系统驱动 |
| [ChatTime](https://github.com/ForestsKing/ChatTime) | 文本序列化时序预测和分析，本地权重可用 | 代码许可证、基础权重许可与实际运行版本需分别厘清；不把模型卡许可自动套给整个源码仓库 |
| [SODA TS Agent](https://github.com/sodafoundation-ai/ts-ai-agent/tree/4475883576cbcf7018751b64d976c27ac0a5f18f) | 自然语言生成 PromQL，再消费真实查询结果 | 当前是早期原型；所读 MCP client 的总结请求未使用工具结果，DynamicPrompt 路径则有显式结果续推。若选它，需要公开列出适配修正，不把现成 MCP 文件当已完成闭环 |

另已对比 distilabel 与 Lhotse：前者有本地合成管线，但维护状态及原生 token 证据需额外核对；后者适合音频时序，不优先占用本轮数值时序名额。

## 每个项目怎样才算完整跑通

共同验收分为以下七项；只有安装、import、mock 返回、轨迹导出或上游单元测试不能算完成。

1. **交付独立**：适配包在源码目录外构建、安装和启用；发现不触发模型加载、下载或训练。锁定原生版本、模型/数据内容身份及实际使用的配置。
2. **原生工作流**：执行上游真实模型/Agent/算子/优化器。适配只改变边界，不重写一个同名算法替代上游。Agent 的实际工具、参数、返回与续推全部保存。
3. **数据与用途**：原始、派生、训练、验证和测试成员固定；测试目标不进入推理输入。未来协变量需有预测时已可获得的依据。用户五份测评附件始终 evaluation-only。
4. **完整证据**：记录输入输出、全部模型/工具尝试、原生终态、错误与预算。缺少 tokens/logprobs 的接口如实标 IO，不根据文本重分词伪造 native rollout。RL 保存实际 token mask、策略修订和奖励来源。
5. **训练确实发生**：选入的训练路径须同时有非零有效梯度和真实参数变化，以及实际 optimizer 更新计数与检查点；RL 还须有非零有效 advantage，明确 weight decay，排除仅衰减或重新初始化造成的变化。训练流程由上游承担。检查点固定基础模型、adapter/config、tokenizer/processor 与训练血缘，并在新进程加载。
6. **独立评价与重评**：通过 AutoBenchTS 原生 `evaluate/score`，领域 Scorer 位于适配包；从封存结果重评时模型/环境调用数为零，旧报告不改写。训练 reward、加工 filter 和上游自报摘要均不直接充当正式评价。
7. **可直接使用**：提供准备命令、实际运行命令、结果读取与重评命令、依赖锁和失败说明。干净环境按说明可复现工程闭环；报告明确样本数、失败率与实际质量，不把少量样本说成整篇论文复现。

移除原生执行依赖后，保留轻量适配包的 Candidate 注册元数据与领域 Scorer，可重评历史 Run。当前 core 0.5 的 AutoBench 重评仍校验 Candidate manifest，不宣称只保留 Scorer 就能移除全部其他适配代码。卸载整个适配包时验证核心及其他项目继续工作、旧证据仍可读取；不承诺缺失领域 Scorer 还能进行该领域评分。

### 各项目的重点验收

- **Chronos-2**：固定官方真实数据子集及时间切分；同时验收多变量、分位数和协变量路径；记录覆盖率/区间或分位数误差、点误差、缺失和非法输出；对一次有界原生微调做检查点回读。禁止把未来目标伪装成已知协变量。
- **ITFormer**：采用官方 HDF5 与 QA 元数据；样本键至少保留信号身份、原问题身份和视图版本。按照当前官方修复后的问答去重语义统计，不因重复信号而误删不同问题。原生 encoder、projector 和语言模型实际加载；测评解析/答案格式策略单独固定。
- **TimeCopilot**：实际调用原生分析 Agent，至少观察到真实工具决策、执行结果被下一轮使用及正常终止；回测仅使用允许历史，私有最终未来值由 AutoBench Scorer 读取。选择失败、工具异常和预算终止均进入覆盖与失败统计。
- **Data-Juicer**：以 train-only 时序合成/说明数据执行原生清理、过滤、去重及受限本地模型加工；保存每个阶段的实际成员和一对多来源映射。先生成封存产物，再通过 EnvironmentTS 登记；AutoBench 单独验证结构、时序/文本对齐、重复、来源与 holdout 交叉污染。
- **AReaL**：保留原生 TIR 与优化器；先用官方算术任务核对 token/mask/工具回合，再加入可验证的时序任务。保存工具 token 不训练、模型 token 参与训练的实际 mask 和奖励归属。训练参考与最终 heldout 分离，检查点由新的 GymTS Candidate 独立评价。

具体样本清单、训练步数及质量指标，在原生数据/API 预检后、正式模型实验前固定。若预检表明所需规模超出预算，先讨论调整，不以缩成一个 mock 或自动删失败样本来完成验收。

### 已查到的原生接口陷阱

TimeCopilot 使用当前 `TimeCopilot.analyze(...)`，而非已弃用的 `forecast(...)`。Agent 的数据解析也可能请求 LLM，必须计入调用和预算。[当前入口](https://github.com/TimeCopilot/timecopilot/blob/961aa330f71afcf53a6ecf2d4b499cb39b44da3e/timecopilot/agent.py#L1212)

ITFormer 的 `TLM.from_pretrained` 另行读取基础 Qwen，不能只记录 ITFormer checkpoint。原生代码对缺失 TS encoder 权重可能只告警后留下随机初始化，预处理也可能降级为零值样本；适配须核对必要权重并启用严格预处理，失败不能计作真实模型输出。官方数据还需约 18.8 GB HDF5 文件，不能把本地已有权重当作数据也已就绪。代码/数据许可证与模型卡声明分别记录，权重仅外部引用。[模型加载](https://github.com/OpenTSLab/ITFormer-ICML25/blob/b80142fc8b6ab2be8f148f3bb7a7534bb32f318b/models/TimeLanguageModel.py)、[数据预处理](https://github.com/OpenTSLab/ITFormer-ICML25/blob/b80142fc8b6ab2be8f148f3bb7a7534bb32f318b/dataset/dataset.py)、[模型卡](https://huggingface.co/pandalin98/ITFormer-7B/blob/a5f52d265b7303bae513e77512453d86d477c44b/README.md)

AReaL 当前 TIR 配置实际为 `tir_math_config.yaml`，README 中旧配置名不能直接照抄。原生 workflow 产生模型/工具回合和训练字段，原生训练器执行更新。真实 rollout 在对应 GymTS Run 内执行并封存，再产生固定 Snapshot/领域 Manifest，后端重新读取和校验后更新；不能另行采样一份用于留痕，或只做训练后摘要导入。事后导入标明 imported，不算本轮执行证据闭环；缺少训练必需的 token/logprob/mask 时不能降为 IO 后仍宣布 RL 验收完成。HF 推理导出与 DCP 训练恢复分别标明，不混称检查点恢复已验收。[原生 workflow](https://github.com/areal-project/AReaL/blob/3b93679888e9f4929f6f155f13c6a286a62dfd72/examples/tir/tir_workflow.py)、[训练入口](https://github.com/areal-project/AReaL/blob/3b93679888e9f4929f6f155f13c6a286a62dfd72/examples/tir/train_tir.py)

原生并发/off-policy 行为不因配方取名“同步”而消失。首轮预检必须确认一个 Run 内策略稳定、rollout 封存前不更新，并保存原生策略版本到权重身份的映射。还需区分 verifier 异常与真实零奖励，核对奖励对应实际训练 token 范围；不能把完整回答的奖励默默分配给截断训练样本。若所选配置不能保证这些条件，先讨论适配范围，不预先宣称同步闭环已成立。

Data-Juicer 的原生 QA mapper 默认解析格式与本地 Qwen 模板不一定一致。解析失败和零输出原样计数；去重不能丢掉数值或只按问题文字去重，否则会把不同序列误合并。原生 tracer 有抽样行为，适配器另保存全量阶段成员和模型请求原始返回。[QA mapper](https://github.com/datajuicer/data-juicer/blob/abb9e49897bdd0e0e2f44ce3272cc1ea5c5a6111/data_juicer/ops/mapper/generate_qa_from_text_mapper.py)、[去重算子](https://github.com/datajuicer/data-juicer/blob/abb9e49897bdd0e0e2f44ce3272cc1ea5c5a6111/data_juicer/ops/deduplicator/document_deduplicator.py)

## 冻结与递归改进

建议顺序为 Chronos-2 → ITFormer → TimeCopilot → Data-Juicer → AReaL；RL 的 CUDA/原生推理与反向预检提前进行，避免最后才发现训练栈不可用。

1. 冻结 F0 wheel、公开合同和回归基线，先接独立 Chronos-2 包。所有加载 GymTS 的主进程和 worker 均核对实际导入文件来自 F0 安装、摘要一致，在源码目录外运行且无源码 PYTHONPATH 回退。先证明运行、留轨迹、独立评价、重评全部无需修改核心。
2. 每接一个项目，新增真实负例及适配验收；先尝试现有公开合同。格式、领域维度、工具协议、原生 API 差异放适配器；需要共享领域合同也作为独立包交付。
3. 若出现核心缺口，提交最小真实失败案例，记录：哪个需求无法表达、用过哪些公开扩展点、为什么适配器不足、拟变更的通用合同、旧项目兼容方式、回归与迁移验证。只有“想接某项目”不构成修改理由。
4. 有必要改核心时产生新冻结 F1，保留 F0 的失败/成功证据，复验旧项目，再让下一个新项目仅通过独立包接入 F1。若最后一个项目才修改核心，须补一次新的独立接入验证后才能宣称 F1 通用性已验收。不得接每个项目都改核心却仍宣称完成冻结验证。
5. 每项目交付时列明核心变化数、包与依赖身份、真实 Run/Evaluation/Snapshot、失败和预算、复现命令与限制；整个阶段最后做轻量适配包共同安装、声明兼容的角色替换、非法组合拒绝和移除验证。原生运行栈继续隔离，不承诺五个异构项目的任意角色可互换。

启动时没有五项目运行证据，不预先认定需要任何核心修改。后续每个原生适配问题优先在外部包解决，并记录实际验收。

## 资源提案与需要讨论的利害

已只读看到本机有 8 张 A800 80GB，驱动 535.129.03；其中一张当时有其他任务。可用性快照不等于卡已预留。

资源提案为最多两张当时空闲的 GPU、串行实验、累计 12 GPU 小时；仅本地模型/服务，不调用付费 API，不调整系统驱动，不使用全局 `pkill`/`ray stop --force` 清理。按自己启动的 PID、实例和工作目录释放资源。达到预算保留成功/失败证据并讨论，不自动扩大。

用户已确认按该组合、工程闭环和资源上限推进；所有失败尝试继续计入同一预算。CUDA 12.x 的驱动兼容机制也不保证所有 JIT/PTX/FlashAttention 路径可运行，须以隔离环境中的真实推理与反向为准；见 [NVIDIA 兼容说明](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html)。

运行依赖按项目独立安装，通过适配层连接；不把所有上游 extras 塞进同一解释器。活动 Run store、检查点工作区和构建放本地 POSIX 路径；权重、数据、原生 checkout、缓存、大日志不提交主仓库。公开提交只保留适配器、配方、说明和不含私有原题/凭证的小型验收摘要。

用户已确认项目组合和首轮验收/资源边界。工程闭环验证可以证明接口与证据链真实可用；复现全部论文数据与指标还需要逐项目额外准备和预算，不能混为同一完成标准。
