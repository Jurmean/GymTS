# 本地 RL rollout 与 TRL GRPO

本接入以独立发行包 `gymts-rl` 存放在 `adapters/rl/`，源码命名空间为 `gymts_rl`。数据、任务、模型、私有奖励、QA 导出器和 TRL 后端均由该适配包交付；核心保留接口规范 1.2.0 定义的通用 TraceCollector、训练证据合同和公开构建入口，不导入具体适配包。训练复用 [TRL 0.18.2 的 GRPOTrainer](https://github.com/huggingface/trl/blob/v0.18.2/trl/trainer/grpo_trainer.py)，包括其 clipped GRPO loss、backward、优化器与检查点。GymTS 负责原生采样、证据、私有奖励、固定快照与可追溯的数据集。

## 当前机器直接运行

已有独立运行时 `/tmp/gymts-rl-venv/bin/python`。迁移后先在该运行时安装核心与适配包，再执行示例；其他环境需安装下方 `runtime` extra。没有改动原有模型或 Python 环境。

```bash
/tmp/gymts-rl-venv/bin/python -m pip install -e . -e adapters/rl
```

在项目目录执行：

```bash
bash adapters/rl/examples/rl_grpo_local.sh
```

脚本使用 GPU 0、`/zzr/models/Qwen2.5-7B-I`、GSM8K 和真正的 ChatTS 合成器，完成数据准备、三步 LoRA GRPO、留出样本推理和 verifier 校验。每次创建新的 `/tmp/gymts-rl-时间戳`，结果入口为 `training/training-summary.json`。通过 `CUDA_VISIBLE_DEVICES`、`GYMTS_RL_OUTPUT`、`GYMTS_RL_MODEL`、`GYMTS_RL_STEPS` 和 `GYMTS_RL_PYTHON` 可修改设备、目录、模型、步数与解释器。

训练命令自动生成的 heldout eval 仍是独立于训练样本的 Run 与 verifier 诊断；`evaluation_status=succeeded` 仅表示推理 Run 完成。现在可用下面的 `score` 命令或 `score_rollout_runs` 对这些已封存 Run 形成 AutoBenchTS ScoreSpec 与正式 EvaluationReport，并再次重评分，全程不调用模型。正式 benchmark 的构建维护与报告仍归 AutoBenchTS。0.5 已支持固定 checkpoint 制品装载与执行 seed 绑定，见下方完整闭环；训练 reward 或 rollout.metrics 不能代替正式报告，Gate 需要显式指定。职责见 [AutoBenchTS 基准管理设计](dataset-benchmark-catalog-design.md)。

`/zzr/models/Qwen2.5-7B-Instruct` 的第一分片实际缺少 82,746 字节；使用经过分片检查的 `Qwen2.5-7B-I`。`Qwen3-4B-Instruct-2507` 没有完整检查点。加载器先检查 safetensors header、shape、dtype、offset、文件长度与 index 引用，再计算实际权重和自定义代码 SHA256。

SQLite WAL、CAS 与训练输出应放本机 POSIX 文件系统，例如 `/tmp`。当前项目目录位于 S3FS，适合保存源码与封存后的实验归档，不适合运行 SQLite。`/tmp` 是运行目录，长期证据需要另外归档。

## 分步命令与原生 ChatTS

下列命令均在主仓库源码目录执行。`--store` 放子命令前；准备数据时指定的 CAS 必须与后续命令相同。

```bash
RL_PY=/tmp/gymts-rl-venv/bin/python
RL_OUT=/tmp/my-gymts-rl-experiment

"$RL_PY" -B -m gymts_rl.cli --store "$RL_OUT/records" prepare \
  --output "$RL_OUT/data" --gsm8k-train 128 --gsm8k-eval 32 \
  --chatts-train 32 --chatts-eval 8 --sequence-length 64

CUDA_VISIBLE_DEVICES=2 "$RL_PY" -B -m gymts_rl.cli --store "$RL_OUT/records" train \
  --data "$RL_OUT/data" --model /zzr/models/ChatTS-3-8B --family chatts \
  --trust-remote-code --device cuda:0 --dtype bfloat16 \
  --output "$RL_OUT/chatts-grpo" --steps 3 --generations 4 --groups-per-step 2 \
  --max-new-tokens 768
```

`chatts` family 使用检查点自己的 processor 与时序 patch encoder，捕获真正送入模型的时序张量。`text` family 使用完整精度的 JSON 数值序列替换提示中的时序占位符，并记录该变换。二者共用同一公开题目和私有 verifier。

只采样、不训练，或在新进程中消费训练后的 adapter：

```bash
CUDA_VISIBLE_DEVICES=2 "$RL_PY" -B -m gymts_rl.cli --store "$RL_OUT/records" rollout \
  --data "$RL_OUT/data" --model /zzr/models/ChatTS-3-8B --family chatts \
  --trust-remote-code --adapter "$RL_OUT/chatts-grpo/final-adapter" \
  --split eval --per-source 1 --generations 2 --max-new-tokens 768 \
  --output "$RL_OUT/reloaded-eval"
```

训练只支持一个进程、一张可见 GPU。CLI 未指定 `CUDA_VISIBLE_DEVICES` 时，会在导入 torch 前把 `--device` 选定的物理卡设为唯一可见卡，避免 Trainer 自动启用 DataParallel。自行使用 Python API 时需预先设置此环境变量。

新环境可用 Python 3.11 安装 `pip install -e . -e 'adapters/rl[runtime]'`。TRL、Transformers、PEFT、Accelerate、datasets、NumPy、Arrow 与 pandas 采用固定版本；默认 GymTS 安装及 `--help` 不导入这些科学库。现成运行时复用已有 torch 2.11.0+cu126 的只读包，其余依赖独立安装；没有复用存在 flash-attn ABI 问题的 vllm 环境。模型推理为本地 HF+SDPA，不需要服务凭证。

## 包边界与迁移

核心发行版从 0.4 起不再提供 `gymts.integrations.rl.*`；改用 `gymts_rl.*`。0.4.1 的公共构建入口为 `gymts.training.build_dataset(spec, records, artifacts)`，按固定 builder_ref 选择外部 provider。具体 `native_rollout_build_spec` 和 native row reader 留在 `gymts_rl.exporter`；其旧 `build_dataset(gym, spec)` 两参数 helper 继续兼容，内部委托公开入口，不要求整个 GymTS 对象成为 provider 的合同。核心不向 RL 反向导入。

适配包 0.2.0 依赖 `gymts>=0.5,<0.6`；原核心 `[rl]` extra 移到适配包 `[runtime]`。ChatTS 数值生成器来自显式选择的上游源码目录，不要求安装另一个 GymTS ChatTS 适配器。源数据及模型身份、组件/Schema/builder ID、历史快照和训练算法均保持原语义；变更的是 Python 导入与发行边界。

## 三侧与实验边界

| 侧 | 组件 | 行为 |
| --- | --- | --- |
| 数据 | `rl-qa-snapshot` | 不可变公开 prompt/array 快照；私有参考答案另存 CAS |
| 任务 | `rl-verifiable-qa` | 一个 sample 对应一个 case；解析格式，保留原始文本与 evidence |
| 模型 | `rl-local-hf` | 制品装载或旧常驻 HF/ChatTS 模型；每个 Run 冻结策略修订，更新由外部 TRL 控制 |

安装适配包后，`rl = gymts_rl:register_rl_plugins` 通过 `gymts.integrations` entry point 被发现；显式启用方式为 `GymTS(root=..., integrations=("rl",))`。默认核心安装不包含本包及其 CLI、科学库或具体导出器。**一次 Run 是一个样本 × 一个固定策略 × 一个 seed 的实际调用**；同一题目 G 次生成有 G 个独立 Run。一次训练是父记录，串联这些 Run、batch、快照、奖励、数据集和权重修订。训练的 optimizer 更新发生在这些 Run 之间，不伪装成 Candidate 的在线 update。

每个 batch 先生成并封存 Run，再由受信任 reward 端追加 Outcome。训练 Outcome 仅允许 `training_export`，评测 Outcome 仅允许 `evaluation`。候选的数据能力只包含该题的公开快照，TaskInput 和训练 sampler 均不含答案、标签或 reward_spec。

## 数据与奖励

GSM8K 来自 [OpenAI 官方仓库](https://github.com/openai/grade-school-math)，固定提交 `3101c7d5072418e28b9008a6636bde82a006892c`，下载后校验两个文件的 SHA256。官方 train 7,473 条、test 1,319 条；test 只作 eval。同一问题保持相同 group，重复 rollout 不去重。奖励验证末行唯一的 `#### number`，用 Decimal 比较正确性，正确为 1，否则为 0。

ChatTS 从 `/zzr/scripts/ChatTS` 的官方数值生成函数直接生成，记录源码提交、实际文件 hash、配置、依赖、种子与 attributes；不调用 AskGPT 或外部模型。数据明确命名为 **`chatts-native-generated/v1`**，新增任务为 `chatts.numeric_summary`，不声称复现 ChatTS-Bench 的七任务基准。

时序目标 `mean/min/max/last` 由真正生成的数组计算。模型需输出恰好四个键的有限数值 JSON；格式错误为 0，正确为 1，其余为 `1 / (1 + MAE / scale)`。同时独立报告 format_valid、correct、MAE 与 reward。train/eval 使用独立种子并按曲线内容 hash 检查隔离。两来源的指标分开报告。

## 原生轨迹与训练消费

每次真实调用保存：

- 正式 ModelCallArtifact 及 run/input/output/call/attempt ID。
- 真实 prompt/response token IDs，包含实际 EOS；原始模型和实际采样两类 logprob。
- 实际 generation config、seed、采样分布、结束原因、usage、错误和采集完整性。
- 精确 tokenizer 文件和 chat template；processor 版本与真正输入模型的 tensor/mask。
- 时序 tensor 的 NPY 原始字节、shape 和 dtype；bfloat16 以 uint16 位表示无损保存。
- 实际基础权重/代码内容 hash、每次冻结的 LoRA adapter 文件、策略修订。

核心采集器在调用前绑定预分配 output_id，立即提交正式调用事件。采集失败按配置停止或标记；存储失败始终停止。失败调用与无效输出也保留已有原始证据。默认 `model_calls=none` 保持原有行为。

训练路径为：

```text
sealed Run → authorized Outcome → RewardRecord → fixed RecordSnapshot
           → DatasetBuildSpec → native JSONL/CAS shards + lineage → DatasetManifest
           → TRL GRPO loss/backward/optimizer → saved adapter → new policy revision
```

`gymts.training.build_dataset(spec, records, artifacts)` 通过外部 `NativeRolloutBuilder` 只读取固定的已封存快照，核对调用身份、token hash、策略、logprob、标签授权与来源。Manifest 最后发布，记录接受/排除计数。每行保留原生 IDs、旧采样 logprob、attention/action/loss mask、标量 reward 与血缘引用。EOS 即使与 pad ID 相同也保留 action=1；prompt/padding 的 loss=0。


公开入口只负责协议、provider 能力与 Manifest 身份校验：`gymts.dataset_builders` entry point 的名称对应 `builder_ref.name`，仅加载选中的固定 provider；缺失、冲突、版本或目标 schema 不适配明确报错。具体 profile 负责选择、授权、分段、奖励与 mask。核心还核对返回 Manifest、CAS 中保存的完整 BuildSpec、输入快照和输出 schema 一致，并确认输出制品已提交。

```python
from gymts.training import build_dataset
from gymts_rl.exporter import native_rollout_build_spec

spec = native_rollout_build_spec(snapshot_refs, reward_refs, mapper_ref)
manifest = build_dataset(spec, gym.records, gym.artifacts)
```

`GymTSGRPOTrainer` 继续复用 TRL 的 loss/backward/optimizer，不新增训练引擎。现在可传 `artifacts` 和 `rollout_provider(inputs, policy, *, generation, seed_start)`，无需传 GymTS 或 QA 数据配置。provider 负责在新策略修订上采样并发布固定 native DatasetManifest，返回 `manifest_ref` 与 `batch_ref`；Trainer 从校验过的已发布 shard 读取 rows，拒绝与 provider 内存 rows 不同的内容。它按标准 `sample_id/source_sample_id`、policy_revision、原生 token/mask/logprob 和 reward 消费数据，不读取 GSM8K/ChatTS 配置。旧 `gym=..., prepared_dataset=...` 参数继续通过 QA provider 闭包兼容。

```python
trainer = GymTSGRPOTrainer(
    policy=policy, args=grpo_args, train_dataset=public_prompts,
    artifacts=artifact_services, rollout_provider=collect_native_batch,
    peft_config=lora_config)
```

目前仍只消费该 native one-call/one-case profile。新增来源可提供相同合同；多轮工具 episode 或不同动作空间需自己的 exporter/backend 适配，不伪装成这个 QA profile。

TRL 从已发布的 shard 读回训练输入，不从解码文本重新分词。`row_indices` 与 TRL shuffle 一同移动，确保原生张量、logprob 和 reward 对应同一条生成。ChatTS 的 forward 会展开时序 patch，当前策略 logprob 通过模型返回的 `new_token_positions` 对齐。

本轮支持 one-call/one-case、原生 capture、call 级标量 reward。截断、缺失、失败均明确排除并保留原因；GRPO 若因此缺少某个组成员就停止，保存完整 batch，不填假样本、假 logprob 或缺失奖励 0。

训练固定 T=1、top_p=1、top_k=0、beta=0、单次 iteration，拒绝额外概率 processor；实际 raw/sampling 概率也核对。HF 的 `use_model_defaults=False` 显式防止检查点默认温度覆盖配置。beta=0 表示本流程没有 reference KL 项。组内 reward 完全相同时 advantage 为 0；短训练验证可运行性，不代表模型质量提升，也不保证每步都有非零更新。

`training-summary.json` 从初始化前开始记录，每个 batch 更新并用 `previous_summary_ref` 串联 CAS 修订。构造失败、取消或训练异常保留父链接；非有限诊断明确标记。最终检查点保存后经 PEFT 重新加载并比对实际字节，结果记录 `weights_changed`、`checkpoint_reload_equal`；留出样本使用独立 eval Run，该自动诊断本身仍不等于正式报告；固定 checkpoint 可另走下面的 AutoBenchTS.evaluate。


## 固定制品到新实验的完整闭环

`run_training` 在 PEFT 磁盘字节与实际训练参数逐张量一致后，默认发布 `checkpoint_bundle_ref`、`deployment_policy_revision` 和 `training_provenance_ref`。单一 CAS ZIP 包含 adapter 权重与配置、tokenizer/processor 字节，以及指向训练父记录、实际 DatasetManifest、RecordSnapshot、采样 Run 的血缘；发布时重新校验这些引用和最终权重，并将基础目录与训练加载时的固定身份比对，拒绝训练期间被替换的基础文件。部署修订同时固定基础权重身份、adapter 字节/配置和输入资产，不依赖常驻 `active_policy`。

大型基础模型保持外部，只接受与完整文件 hash 一致的显式本地路径。小模型可传 `include_base_in_bundle=True` 嵌入基础权重，上限 128 MiB。可用 `load.base_model_path` 重定位外部模型，但新路径仍须匹配原内容身份；自定义模型代码需显式 `trust_remote_code=True`。加载时核对 ZIP 路径、逐文件长度与 hash、策略身份和实际 PEFT tensor hash；内嵌 provenance 的规范 JSON hash、长度、schema 必须匹配其原 ArtifactRef，搬迁后重新保存仍保持相同内容身份。候选只有整个 archive 的授权，不需递归扩大 CAS 权限。

```python
from gymts_rl.evaluation import checkpoint_evaluation_spec, rescore_checkpoint_evaluation

spec = checkpoint_evaluation_spec(
    gym, prepared, summary['checkpoint_bundle_ref'], heldout_sample_ids,
    seeds=[7, 11], generation={'max_new_tokens': 512},
    load={'device': 'cpu', 'dtype': 'float32'}, gates=explicit_gates)
report = gym.autobench.evaluate(spec)
rescored = rescore_checkpoint_evaluation(gym, report)
```

该 helper 只构造原生 EvaluationSpec：公开题目、私有 evaluation-only 参考分开提交，计划封存、执行、比较、Gate 与 EvaluationReport 仍由 AutoBenchTS 管理。每个 Run 从 `CandidateContext.execution_seed` 采样并记录实际 seed，多个 repetition 共用一个候选及权重身份。旧显式 `params.seed` 仅为历史常驻采样兼容保留；新 artifact 候选拒绝它。`gym.validate` 使用纯 describe/compatibility，不构造三侧实例、不读模型或数据，资源内容校验推迟到实际运行。

本机可直接执行完整 CPU 工程验收：

```bash
CUDA_VISIBLE_DEVICES= /tmp/gymts-rl-venv/bin/python -B \
  adapters/rl/examples/checkpoint_loop.py --output /tmp/new-gymts-checkpoint-loop
```

示例明确构造 1 层、hidden=16 的 Qwen2 工程模型，使用真实缓存 GSM8K 与原生 ChatTS 生成数据。为让受控词表得到有效组内 reward 差异，只从官方 GSM8K train 子集中显式选择答案为 1 的训练题，复用实际 TRL GRPO 训练入口、loss 和 optimizer，检查非零梯度、无 weight decay 的真实权重变化及 checkpoint reload 一致。ChatTS 数值摘要数据真实准备并进入独立留出测评，本微型模型不声称对该任务产生有效训练提升。

训练与测评为不同进程；测评前移走原基础模型和 final-adapter 路径，强制从 CAS archive 装配。正式评价使用 GSM8K、ChatTS 各一题 × 三个执行 seeds；技术 Gate 检查执行失败率为 0 与评分覆盖率为 1，任务准确率原样报告，不以技术通过声称模型质量达标。再以相同 seeds 重新执行一次完整评价并核对采样 token hash 可复现；随后屏蔽模型装载和生成，对封存 Runs 再评分，核对结果与事件未变。五份用户上传 benchmark 不参与该训练或 fixture 数据选择。

最终独立安装验收见 [JSON 证据](reports/rl-checkpoint-loop-2026-10-20.json)：核心 0.5.0 固定 wheel、适配包 0.2.0 从独立 sdist 重建并安装后，87/87 项通过，包含真实来源检查。两个真实 GRPO 更新的 grad_norm 为 0.5753、0.6844，weight_decay 为 0，权重 hash 改变且重载一致；完整记录共 28 个封存 Run（16 训练采样 + 6 新评价 + 6 相同 seed 重复评价）。三份正式评价/重复/重评分报告均保存于 CAS；重评分没有增加模型调用或修改原 Run。

本地原始日志为 `docs/reports/rl-checkpoint-loop-2026-10-20.log`，不随源码分发。
JSON 中的本地日志路径或摘要标识原验证证据，不代表仓库提供原始日志下载。

本轮正式评测的 accuracy 为 **0.0**，format_valid 为 **0.5**，评分覆盖率为 **1.0**；技术 Gate 通过仅证明闭环可执行与证据完整，模型质量没有达标声明。完整验收覆盖内嵌微型基础模型；外部大型基座和原生 ChatTS processor 没有在这轮重新训练验收。完整 SQLite/CAS、输入与检查点、固定 wheel/sdist 及日志另存于仓库 `output/rl-checkpoint-loop-resource-final-2026-10-20/full-evidence.tar.gz`，其 SHA256 记录在 JSON；此前候选轮单独保留，不替代最终轮。

## 对旧 Run 形成独立评价

```bash
gymts-rl --store /tmp/my-gymts-rl-experiment/records score \
  --run-id <已有eval-run-id> --min-accuracy 0.8 \
  --output /tmp/my-gymts-rl-experiment/autobench-report.json
```

可重复 `--run-id`。命令只读取已封存的 eval Run、固定输出与获准 evaluation Outcome，返回原生 AutoBenchTS EvaluationReport 和 CAS 引用；不加载模型、不训练。省略 `--min-accuracy` 不设验收 Gate，报告保留 `no_acceptance_gate`，不自动给通过结论。Python 入口为 `gymts_rl.evaluation.score_rollout_runs(gym, run_ids, gates=...)`；`previous_evaluation_id` 可关联重评分；新增参考修订时通过 `outcome_refs=[{"outcome_id": ..., "revision": ...}]` 显式选择，不默认覆盖或混合旧参考。

独立 `rl-qa-scorer` 提供 accuracy 与 format_valid。合法参考下的格式错误测为 0；缺参考保留 missing 分母，非法参考保留 invalid，均不补奖励零。format_valid 不需要标签。训练-only Outcome 和 train Run 不可改称独立评测。旧 seed 位于 CandidateSpec.params，所以按其真实配置和捕获的模型修订保留不同候选身份，不把多个 seed 伪合并成同一候选的 repetitions。新配置把 seed 放在 execution，固定 checkpoint 用 CandidateSpec.artifact 装载；旧 Run 的 ScoreSpec 仍只评价实际已执行的组合。

verl 当前没有训练器适配；保留正式 JSONL 和原生输入引用供后续后端接入。分布式、vLLM、混合 temperature 的 importance correction、复杂多轮工具 episode、恢复 optimizer 训练和 Pi 自动 Research 循环尚未实现。
