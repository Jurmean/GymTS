# RL 接入本地验收：2026-10-19

主仓库为 `/zzr/zmx/GymTS/Jurmean-GymTS`，基线 `cffa38f223e64a75874936ad58ce53d9391e63a9`。本轮所有实现保留在工作区，没有 stage、commit、push 或 PR。原有 TimeSigma 接入保留。

能力口径澄清：下文验收针对 RL 采样、真实优化、原生轨迹、adapter 消费及留出推理。heldout verifier 分数尚未接 AutoBenchTS Scorer/EvaluationReport，不代表正式 benchmark 或验收 Gate 通过；正式评价组织仍应由 AutoBenchTS 完成。

## 真实训练与检查点

数据采用官方固定版本 GSM8K train/test 各 4/2 题，ChatTS 原生生成的 train/eval 各 4/2 条、每条 32 点。正式训练只使用 train；eval 从未进入 optimizer。小样本用于接口验收，不能据此判断泛化效果。

| 模型 | 实际训练 | 原生 rollout | 非零梯度步 | 训练参数 | 权重变化 | 检查点字节重载 |
| --- | --- | --- | --- | --- | --- | --- |
| `/zzr/models/Qwen2.5-7B-I` | TRL GRPO 4 步，86.97 s | 32 | 2 | LoRA q_proj/v_proj，rank 8 | 是 | 一致 |
| `/zzr/models/ChatTS-3-8B` | TRL GRPO 2 步，103.01 s | 16 | 1 | 3,833,856 个 LoRA 参数 | 是 | 一致 |

Qwen 的非零 gradient norm 为 0.03963 和 2.59266；ChatTS 为 0.35639。均为 BF16 本地基础模型、FP32 可训练 adapter，独立使用 GPU 0 和 GPU 2。其他训练步的组内奖励相同，按原生 GRPO 得到零 advantage；没有修改奖励制造梯度。

48 行正式训练数据逐一通过以下独立审计：原生 input tensor 与 prompt token 制品一致，单样本 attention mask 全 1，真实 EOS 的 completion mask 为 1，logprob 与 completion 等长，实际采样与原始模型概率一致，batch 内只有一个策略修订，train/eval sample 不重叠。ChatTS 时序张量按 BF16 位表示完整保存并恢复。

两模型都在新进程重新读取基础权重、加载 `final-adapter`，各执行两条独立 eval Run，全部 `succeeded` 且 EOS 完整；这验证检查点可被消费。严格任务格式仍会导致奖励 0：部分回答使用 fenced JSON 或未将 `####` 答案置于独立末行。未放宽 verifier 或重标结果。

训练后即时 eval：Qwen 为 1/2 正确，ChatTS 为 0/2。新进程使用另一固定采样 seed 的 eval 均为 1/2；这些不是成对对照，不代表性能提升。ChatTS processor 自带基础统计元数据，numeric_summary 本身也较简单，仅用于验证真实原生输入、采样和训练接口。

## 修复与失败保留

- `Qwen2.5-7B-Instruct` 第一 safetensors 分片缺 82,746 字节。增加 header/dtype/shape/offset/文件长度校验；改用完整的 `Qwen2.5-7B-I`，没有修改源权重。
- 真实 tokenizer 的 AddedToken 不能直接编码为核心 JSON。以实际 token 字符串保存选定配置，同时保留完整 tokenizer 文件。
- Transformers 会以模型专用默认值替换传入的 global-default 温度。显式传入 generation kwargs 与 `use_model_defaults=False`，并保存、核对实际 raw/sampling 概率。
- Trainer 在多张可见 GPU 下自动扩大 batch 并可能启用 DataParallel。CLI 在导入 torch 前固定唯一设备，训练器额外检查单 GPU。
- 初次单步 Qwen 训练组内奖励完全相同，`weights_changed=false` 如实记录；后续覆盖更多题目后完成真实非零更新。
- 所有已执行的失败/取消 Run、旧采样不一致的 smoke、截断或格式错误、零梯度试验均保留。加载器预检阶段尚未分配 Run 的失败保留初始化日志，不伪造执行记录。

## 自动验证

| 验证 | 结果 |
| --- | --- |
| 固定 RL 环境，`GYMTS_RL_NATIVE=1`，全部 `test_rl*.py` | 51 通过，0 跳过，0 失败；包含真实数据生成及 tiny HF/TRL backward |
| 通用 capture / builder / 既有 core 针对性验证 | 20 / 17 / 28 项通过；最终输出计数修复另有 36 项相关回归通过 |
| 默认 host 全套旧快照 | 330 项：317 通过，13 可选依赖/原生检查跳过，0 失败 |
| 最新源码发行包，在源码目录外独立安装 | 334 项：305 通过，29 可选依赖/原生检查跳过，0 失败 |
| wheel、sdist、源包重建安装，第三方 integration 装卸 | 通过；四个 CLI help 通过；sdist 包含运行脚本 |

完整套件也曾在大型 RL 环境运行；TimeSigma 子进程冷启动超过其短 deadline，出现 4 fail、1 error。保留该日志，没有调整超时测试迁就环境。默认 host 和独立安装的同一 TimeSigma 进程/截止/强制终止测试通过；RL 专用完整套件则在固定 RL 环境全部通过。

发行物检查排除本地 output、数据库、模型和凭证模式。直建 wheel 与源包重建 wheel 因 ZIP 时间戳 hash 不同，不声称二进制相同；两者分别通过独立安装验证。

## 证据位置与重用

当前运行目录：`/tmp/gymts-rl-acceptance-20261019/`。两个主入口为 `qwen-grpo-v5/training-summary.json` 与 `chatts-grpo-v1/training-summary.json`，最终 adapter 位于各自 `final-adapter/`。

长期归档位于本仓忽略目录 `output/rl-acceptance-20261019/`。`evidence-manifest.json` 提供归档 SHA256、大小和内容索引，`evidence.tar.gz` 包含备份后的 SQLite、全部 CAS、Run/快照/奖励/数据集、实际 LoRA 权重、源码副本、数据、日志及失败 smoke。解压后用归档内 `experiment/records` 打开 GymTS；adapter 用解压后的实际路径传给 CLI。引用中的原运行路径保留原貌，基础 7B/8B 权重继续使用 `/zzr/models` 中的已核对文件。

运行方法和支持边界见 [RL 接入指南](rl-integration.md)。当前交付单进程、单 GPU、单调用 QA 的 native GRPO；verl、多轮工具 episode 和分布式训练尚未适配。
