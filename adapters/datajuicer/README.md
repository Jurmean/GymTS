# GymTS Data-Juicer adapter

独立接入 [Data-Juicer v1.6.1](https://github.com/datajuicer/data-juicer/tree/abb9e49897bdd0e0e2f44ce3272cc1ea5c5a6111)。本包只依赖 `gymts>=0.5,<0.6`；核心不导入 Data-Juicer、Transformers 或 torch。Data-Juicer 和本地模型使用另一解释器。代码许可为 [MIT](LICENSE)，Data-Juicer 源码为 Apache-2.0，ChatTS 来源及模型、数据仍保留其原始许可。

一次实验的边界为一个固定 train-only 数据视图和一份原生加工 recipe。EnvironmentTS 管执行、读权限和封存证据；AutoBenchTS 通过本包独立质量 Scorer 评价。Candidate 仅产生加工结果，不负责发布数据或自行批准训练用途。

## 安装

在主仓库中构建本包，随后离开源码目录安装 wheel。核心 0.5.0 与原生依赖分离：

```bash
python -m build adapters/datajuicer --outdir /tmp/datajuicer-wheels
python -m pip install /tmp/datajuicer-wheels/gymts_datajuicer-0.1.0-py3-none-any.whl
gymts-datajuicer --help
```

为原生 worker 建立独立 Python 3.11 环境，固定上游 SHA；模型权重需提前下载到本地，不使用付费服务。只准备本配方使用的依赖，不安装 `[all]` 或整个 `[generic]`：

```bash
git clone https://github.com/datajuicer/data-juicer /tmp/datajuicer-native
git -C /tmp/datajuicer-native checkout abb9e49897bdd0e0e2f44ce3272cc1ea5c5a6111
python3.11 -m venv /tmp/datajuicer-worker
/tmp/datajuicer-worker/bin/python -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cu124
/tmp/datajuicer-worker/bin/python -m pip install /tmp/datajuicer-native transformers==4.57.1 accelerate einops 'ray>=2.51,<3'
/tmp/datajuicer-worker/bin/python -m pip install --no-deps /tmp/datajuicer-wheels/gymts_datajuicer-0.1.0-py3-none-any.whl
```

CUDA wheel 必须匹配实际驱动能力，不能仅凭安装成功判定 GPU 路径可用。原生最低依赖包括 `datasets>=4.7.0`、`fsspec>=2026.1.0`、固定 multiprocess/dill；不要将它们直接装入旧 RL 环境。正式验收记录实际依赖锁、源码树、模型/tokenizer 文件 SHA256 和导入路径。worker 自己不导入 GymTS，且禁止 LazyLoader 临时下载安装依赖。

固定版本的 executor 包初始化会导入 `RayTracer` 并执行 `ray.remote` 装饰，因此即使选择 default executor，也需要安装 Ray 包；本配方不调用 `ray.init` 或启动分布式集群。这个上游依赖限制留在独立 worker，不进入 GymTS 核心。`model-identity` 除哈希外还检查实际 safetensors header、tensor offsets/shape 与分片 index，截断文件不能仅因名字存在而通过。

## 准备数据与运行

`prepare-source` 调用 ChatTS 自身的 `generate_random_attributes` 和 `generate_time_series`，记录实际源码身份。按完整生成 family 先分 train/holdout，再加入明确标记的两条重复训练输入和一条过短输入以验证去重/过滤；holdout 不交给 Candidate。它不是用户 benchmark 的训练拆分。

```bash
gymts-datajuicer prepare-source --output /tmp/dj-source --chatts /path/to/ChatTS --python /path/to/chatts-env/bin/python --train-count 12 --holdout-count 4 --length 32 --seed 21
gymts-datajuicer model-identity --model /path/to/Qwen2.5-7B-Instruct --output /tmp/dj-model.json
gymts-datajuicer preflight --output /tmp/dj-native-cpu-check --source /tmp/dj-source --native-python /tmp/datajuicer-worker/bin/python --upstream /tmp/datajuicer-native --model /path/to/Qwen2.5-7B-Instruct --model-identity /tmp/dj-model.json
CUDA_VISIBLE_DEVICES=0 gymts-datajuicer run --root /tmp/dj-proof --source /tmp/dj-source --native-python /tmp/datajuicer-worker/bin/python --upstream /tmp/datajuicer-native --model /path/to/Qwen2.5-7B-Instruct --model-identity /tmp/dj-model.json --work /tmp/dj-worker-runs
```

`preflight` 是显式的原生 CPU 预检，需已准备原生依赖，和默认轻量合同测试分开运行。它强制隐藏 CUDA，解析完整含 QA 的 recipe、实例化真正的原生算子，并在初始化原生日志后通过真实 spawn Pool 检查 QA 对象序列化；再实际运行过滤/去重管线。预检不调用模型，不是 GPU 验收。日志、完整配置和 `summary.json` 都保存在指定的新目录；失败不会触发自动依赖安装。

真实执行 `init_configs` 和 `DefaultExecutor.run`：原生长度过滤 → 原生 exact document dedup → 原生本地 HF QA mapper → 原生 JSONL 导出。本包审计子类调用 QA mapper 的原始实现；仅包装实际 pipeline 请求/返回，不代写模型答案。输入要求严格 `Human: JSON Assistant: JSON`，失败、零输出或不正确数值均原样保留。`max_new_tokens` 默认 192、worker 超时默认 1200 秒；可用 CLI 参数显式设定。

本配方保留生成的全部 QA，不用评分答案回流过滤。固定上游的 post-instantiation preflight 会将后续算子的字段与最初输入 schema 比较，不能据此识别 QA mapper 后产生的 `query/response` 字段；因此不添加依赖这些新字段的后置长度 filter，保持原生严格 preflight。输出结构由独立质量 Scorer 检查，不因格式错误删除正式评价分母。

完整阶段 before/after 数据、每个成员的哈希、丢弃 ID、一对多数量、全部真实模型 IO、配方与导出字节保存到 Run CAS。固定原生 mapper 实际指定 `return_full_text=False`；逐次请求/有效参数与 raw `generated_text` 共同证明解析对象仅为新增生成文本，不会把输入中的格式模板当成生成 QA。原生抽样 tracer 不作为全量轨迹。IO 证据不宣称原生 token IDs、logprobs 或模型隐藏推理。

## 显式登记派生数据

模型加工完毕且 Run 成功封存后，由调用者明确执行登记。必须提供同一成功 Run 的正式 `datajuicer-quality/1.0.0` 不可变评价报告，且血缘与用途隔离指标覆盖完整、对应 Gate 均通过；报告缺失、跨 Run、holdout 污染或血缘失败均拒绝发布训练数据：

```bash
gymts-datajuicer register-derived --root /tmp/dj-proof --report /tmp/dj-proof/evaluation.json --dataset-id example/chatts-datajuicer-qa --output /tmp/dj-derived-manifest.json
```

`run` 自动保存 `evaluation.ref.json`，`rescore` 保存与报告同名的 `.ref.json`；登记默认读取该引用，也可显式传 `--report-ref`。原始 JSON 必须与 CAS 中的正式报告相同。该命令通过 `EnvironmentTS.datasets.publish_asset/register_dataset` 保存不可变派生资产与来源链，定义仅含 train split、训练用途明确允许。每条派生行保留父 `sample_id`，新 `sample_id` 固定到实际 Run 和输出行。固定的 `timeseries-operation-chat/1` 投影提供可读取的对话 `prompt` 与原模型 `completion`，同时保留原生 `query/response`、序列和血缘。答案标记为 `model_generated_unverified`；原模型错误不会被悄悄修正或筛成验证正确的标签。使用方必须自行决定是否采用、怎样清洗这些训练标签。

```python
import json
from gymts import GymTS
manifest = json.load(open('/tmp/dj-derived-manifest.json'))
with GymTS('/tmp/dj-proof/records', integrations=('datajuicer',),
           data_home='/tmp/dj-proof/data', cache_home='/tmp/dj-proof/cache') as gym:
    data = gym.environment_ts.datasets.load_dataset(manifest['dataset_id'],
        revision=manifest['revision'], split='train', purpose='training')
    print(len(data), data[0]['parent_sample_id'], data[0]['label_status'])
```

## 独立评价与重评

本包 `QualityScorer` 不导入 Data-Juicer 或任何模型。它从封存输出和独立参考重新计算 JSON/数值正确率、源覆盖、重复残留、全阶段血缘、holdout 交叉污染。没有输出的合法源在 source-level accuracy 中计零；加工 filter 不等于正式评分。

```bash
gymts-datajuicer rescore --root /tmp/dj-proof --report /tmp/dj-proof/evaluation.json --output /tmp/dj-proof/rescore.json
```

重评不启动模型、原生 worker 或环境。原评价和 Run 不改写。`pass` 的门槛为运行成功、血缘完整和 holdout 未污染；数值质量仍须查看独立指标，不意味着达到训练效果或复现论文指标。仅加工数据、验证读取不等于训练更新或模型效果提升。

## 合同验证与限制

```bash
python -m unittest discover -s adapters/datajuicer/tests -v
```

测试覆盖来源用途拒绝、隐私字段拒绝、格式/数字不正确、源缺失、阶段篡改、holdout 污染及纯注册/计划。原生 CPU 预检与真实 GPU 验收另行记录，不能由 mock 或测试替代。`run` 或 `rescore` 会先保存失败报告，再以非零退出码结束。CLI 不负责下载模型、GPU 调度、远程发布或分布式恢复；信任适配代码，并不将 Python 子进程当作安全沙箱。超时仅停止本次自己启动的进程组。Linux worker 还会登记父进程死亡信号；父进程被 SIGKILL/OOM 结束后，worker 只清理其自己建立的独立会话进程组。

源码审计针对固定 SHA 的内部包装点；升级原生版本需重新核对并改变版本身份。worker 独立检查完整阶段终态，缺少任何配置阶段或出现失败阶段均明确拒绝验收并保留原始证据；这属于适配器完备性防护，不声称固定上游存在异常吞没问题。核心无项目专用补丁。

## 真实验收记录

2026-10-21 已通过源码目录外安装的独立 wheel，使用固定 GymTS 0.5.0 F0 wheel、Data-Juicer v1.6.1 和本地 `/zzr/models/Qwen2.5-7B-I` 完成模型执行、封存、独立评价、零模型重评和训练用途数据读取。原生 worker 使用独立环境，复用已存在的 torch 2.6.0+cu124 二进制文件；不是重新解析安装整个 generic 依赖。实际 Transformers 为 4.57.1、datasets 为 5.0.1。完整身份及结果见[机器可读摘要](examples/native-validation-2026-10-21.json)。

| 项目 | 实测结果 |
| --- | --- |
| 数据边界 | 12 个训练 family、4 个隔离 holdout family，另有 2 条训练重复输入和 1 条短输入 |
| 原生管线 | 15 输入 → 长度过滤 14 → 去重 12 → 原生 QA 输出 9 |
| 正式轨迹 | 1 个成功 Run、3 个算子 ToolCall、12 个真实 ModelCall，全部 `return_full_text=False` |
| 独立质量 | 源级正确率 0.50；结构率和源覆盖率 0.75；唯一率、血缘完整度、holdout 隔离均为 1 |
| 质量分母 | 6 源正确、3 源数值错误、3 源没有原生 QA；缺失和错误均保留 |
| 正式评价与重评 | 均 completed/pass；6 个指标全部 ready，逐指标 counts 为 eligible=1、scored=1、missing=0、invalid=0 |
| 发布与调用 | 9 行全部按 `model_generated_unverified` 显式登记；新进程以 training 用途读取 9 行，不导入原生依赖 |
| 核心兼容 | F0 安装的全部 39 个文件逐 SHA256 相同，核心 Python 和公共合同零修改 |

`pass` 表示执行、血缘与用途隔离门槛通过，不能将 0.50 正确率解释为全部答案正确。三条错误答案仍是未验证训练标签，未用独立评分进行 oracle 筛选。三条无 QA 的源仍在原始评价分母内。

此前四次失败证据保留在本机原始 Run/worker 目录，包括旧提示下 12 次真实调用均只生成 `Assistant:`、导致原生解析零 QA 的实验。最终只加强公共格式指引并建立新 source revision；没有给当前输入附加答案或修改原生生成结果。空导出现在也可正式封存和评价为零，但不能登记为空训练数据。验收不宣称执行训练更新、提升下游模型质量或复现论文结果。
