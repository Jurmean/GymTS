# gymts-itformer

GymTS 0.5 的独立 ITFormer/EngineMT-QA 适配包。核心没有引入 ITFormer 格式、模型或评分。安装与插件发现不会加载模型；`plan` 只校验 JSON 声明。实际执行使用上游 `TLM.from_pretrained`、严格 `TsQaDataset`、`DataCollator` 和 `generate`，并封存真实输入/输出 token IDs。本包提供冻结推理，不提供 ITFormer 训练或 Agent 自主工具循环。

## 固定来源与许可

- 原生代码：[OpenTSLab/ITFormer-ICML25](https://github.com/OpenTSLab/ITFormer-ICML25)，固定 `b80142fc8b6ab2be8f148f3bb7a7534bb32f318b`，MIT。
- 模型：[pandalin98/ITFormer-7B](https://huggingface.co/pandalin98/ITFormer-7B)，调研快照 `a5f52d265b7303bae513e77512453d86d477c44b`。模型卡正文声明 MIT；该快照没有 LICENSE 文件，Hub license 元数据为空。还需遵守另行加载的基础 Qwen 权重许可。
- 数据：[pandalin98/EngineMT-QA](https://huggingface.co/datasets/pandalin98/EngineMT-QA)，快照 `ea2051a15512212976c22c1a075ec549c7d48eef`，数据卡 MIT。
- 本包代码 MIT。不分发上游完整模型实现、模型权重、完整 QA 或训练输出。推理仅使用 safetensors，不读取模型目录里的 optimizer、pickle 或训练状态。

严格闭集答案解析改编自固定上游 `utils/metrics.py`；原始版权和 MIT 许可见 [UPSTREAM_LICENSE](UPSTREAM_LICENSE)。

## 安装

尚无 PyPI 发布承诺。在主仓库根目录构建核心与本包后，安装生成的 wheel；运行时可以位于源码目录之外：

```bash
python3 -m venv /tmp/gymts-itformer-venv
. /tmp/gymts-itformer-venv/bin/activate
python3 -m pip wheel --no-deps . ./adapters/itformer --wheel-dir /tmp/gymts-itformer-wheels
python3 -m pip install /tmp/gymts-itformer-wheels/gymts-0.5.0-py3-none-any.whl
python3 -m pip install '/tmp/gymts-itformer-wheels/gymts_itformer-0.1.0-py3-none-any.whl[runtime]'
gymts-itformer --help
mkdir -p /tmp/gymts-itformer
gymts-itformer freeze-core \
  --wheel /tmp/gymts-itformer-wheels/gymts-0.5.0-py3-none-any.whl \
  --output /tmp/gymts-itformer/core-identity.json
```

`freeze-core` 只用 CPU 和标准库，核对实际导入的已安装 GymTS、发行版本、完整包成员及其与所提供 wheel 的逐文件原始字节；拒绝 editable/source 回退。GymTS 0.5.0 必须是完整的 39 个核心文件。生成的身份包含 wheel SHA-256 和各文件摘要，不依赖本轮临时目录或历史 Git 提交；后续 `plan/run/score` 使用该文件。已有独立可信摘要时加 `--expected-sha256 SHA256` 可拒绝错误 wheel。生成自己的身份证明当前安装与该 wheel 一致，不等于自动取得本轮 F0 的来源认证；本轮 F0 的 wheel SHA-256 为 `8883e708dbfcc46301939335f594884b40239ddd8bbe201a66e6af2f18e012cf`。兼容范围内的其他稳定 0.5.x 版本需要重新冻结其实际 wheel，不能复用 0.5.0 身份。

原生运行栈应位于独立环境，不能把它的 torch/transformers 要求加入核心依赖。本包 runtime 范围基于 torch 2.5–2.6、transformers 4.47.1；完整实际验收依赖另见验收记录。上游 checkout 不能复用有本机修改的旧目录。

```bash
git clone https://github.com/OpenTSLab/ITFormer-ICML25.git /tmp/gymts-itformer/upstream
git -C /tmp/gymts-itformer/upstream checkout --detach b80142fc8b6ab2be8f148f3bb7a7534bb32f318b
```

从固定 Hub 快照下载 `test_qa.jsonl`、约 18.8 GB 的 `time_series_data.h5`，以及模型 safetensors/config。基础 Qwen2.5-7B-Instruct 需要完整配置、权重和 tokenizer。本包不会在发现、规划或运行时自动下载文件；路径不存在就失败。

## 准备公开视图与独立答案

直接生成与本轮验收相同成员的 8 条官方 QA 小视图，可使用一个命令：

```bash
gymts-itformer prepare-official --output /tmp/gymts-itformer/prepared
```

该显式命令下载并核对固定 revision 的 17 MB QA 文件，仅范围读取所需官方 HDF5 信号，按源顺序每阶段选择 2 条，再分离为 `/tmp/gymts-itformer/prepared/view/public.json` 与 `private-targets.json`。已有官方 QA 文件可加 `--qa /data/EngineMT-QA/test_qa.jsonl`，同样逐字节核对固定 LFS 摘要。后续 `plan/run --view` 使用这个 `view` 目录。准备数据需要网络；真实推理和重评不需要网络。可设置 `GYMTS_CORE_IDENTITY=/tmp/gymts-itformer/core-identity.json`，让所有准备/预检命令也逐文件核对已安装核心。

已经下载完整 HDF5 时也可以使用：

```bash
gymts-itformer prepare \
  --h5 /data/EngineMT-QA/time_series_data.h5 \
  --qa /data/EngineMT-QA/test_qa.jsonl \
  --per-stage 1 --output /tmp/gymts-itformer/view
```

默认按源顺序选择四个阶段各一条 QA。JSONL 行内的所有 QA 都先展开；样本身份同时固定数据内容、视图版本、展开索引、源行、QA 偏移和信号身份。不会按信号/源行去重。`public.json` 只包含原问题、公开阶段/属性和原生选择后的信号；`private-targets.json` 单独保存 evaluation-only 答案，文件权限为 0600。`provenance.json` 固定文件内容摘要、原始 HDF5 维度和成员。

全 HDF5 下载过慢时，可以直接读取固定官方文件的真实 HTTPS byte ranges，生成明确标记的紧凑派生资产：

```bash
gymts-itformer project --qa /data/EngineMT-QA/test_qa.jsonl \
  --per-stage 2 --output /tmp/gymts-itformer/projected
gymts-itformer prepare --h5 /tmp/gymts-itformer/projected/selected-signals.h5 \
  --qa /data/EngineMT-QA/test_qa.jsonl --per-stage 2 \
  --projection /tmp/gymts-itformer/projected/projection.json \
  --output /tmp/gymts-itformer/view
```

`projection.json` 保存官方 repo/revision、LFS 全文件 SHA-256 与长度、每次实际读取的字节范围及 SHA-256、所选原信号行/ID、float64 原始数值及 native float32 数值摘要、原 ID→派生行映射、展开 QA 索引和派生文件内容身份。只创建已读取的行，不补零、不冒充原完整文件。固定 revision 的 HTTPS 来源和分块摘要不构成对全文件 LFS hash 的重新计算或 Merkle 包含证明；此限制明确记录。单次 projection 有 64 MiB/512 次请求的硬上限，服务器不严格返回对应的 206 range 就失败。

上游发布的 HDF5 为 `(118921, 600, 33)`，没有通道名称。字符串 ID 选择整条序列；ID 列表按原生规则拼接各序列的前十分之一。保留全部 33 个通道及其顺序，不推断物理名称。非法 ID、非有限值、配对错误和形状错误直接失败，不补零、不删样本。

## 预检、规划与真实运行

复制 [examples/candidate.json](examples/candidate.json) 并填入三个实际本地路径；`device=cuda:0` 指当前进程可见的第一张已授权 GPU。CPU 路径也允许，但 7B 计算成本很高。未实测时不能承诺显存或耗时。

```bash
gymts-itformer preflight --params /tmp/gymts-itformer/candidate.json \
  --output /tmp/gymts-itformer/preflight.json
```

预检核对官方 Git SHA/干净源码、全部 safetensors shard/index、encoder/ITFormer/projector 前缀和基础 Qwen checkpoint，并对实际权重、tokenizer、config 计算 SHA-256。完整哈希会读取几十 GB 数据；这不是模型推理。

`--core-identity` 使用前面 `freeze-core` 生成的 JSON，必须包含 `core_version`、完整 `installed_files` 和 `wheel_sha256`。命令会逐文件核对**当前实际导入的已安装核心**，不能用源码导入回退替代；不要求本机存在本轮 F0 的临时文件或 Git 历史。

```bash
cd /tmp
PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
gymts-itformer plan --view /tmp/gymts-itformer/prepared/view \
  --params /tmp/gymts-itformer/candidate.json --root /tmp/gymts-itformer/runs \
  --core-identity /tmp/gymts-itformer/core-identity.json \
  --output /tmp/gymts-itformer/plan.json

PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
CUDA_VISIBLE_DEVICES=YOUR_AUTHORIZED_GPU gymts-itformer run \
  --view /tmp/gymts-itformer/prepared/view --params /tmp/gymts-itformer/candidate.json \
  --root /tmp/gymts-itformer/runs --core-identity /tmp/gymts-itformer/core-identity.json \
  --output /tmp/gymts-itformer/evaluation.json
```

以上 `/data` 和 GPU 值是明确的本机配置模板；`candidate.json` 中的三个本地路径也需要填写。若用手工 `prepare` 生成其他目录，相应替换 `--view`。不得在已有任务占用的 GPU 上直接照抄。

一次固定视图对应一个 Run，模型只准备一次；每个 QA 是独立 Task case/input/result。运行开始时再次核对全部模型内容，原生基础模型的 missing/unexpected/mismatched keys 必须为空；非 LLM 权重必须完整且加载后逐张量一致。原生随机 encoder 回退、补新随机 placeholder embedding、预处理零样本回退和 tokenizer 静默修复均拒绝。

公开 tensor 在临时单行 HDF5 中交给原生 `TsQaDataset(strict_preprocessing=True)`；空答案只是数据接口占位，真实答案不可用。原生 chat 模板、原始问题及 25 个信号占位 token 均核对；仅允许的五个张量传入 `generate`，从不传入 labels/reference。默认 greedy、128 新 tokens；到达上限如实记录 `limit_reached`，不删掉截断或格式错误的答案。

Run/CAS、SQLite、构建和临时文件必须使用本机 POSIX 文件系统；模型/下载缓存可以另行存放。`root` 不是 HF 缓存。本包是受信任 Python 插件，访问能力依赖代码审查与进程隔离；核心资源授权接口不等于操作系统沙箱。请勿向不受信任适配包交出答案目录或凭证。

## 独立评价与零推理重评

正式评价调用原生 `gym.autobench.evaluate`。`answer_exact_match` 对 Stage 2/3 使用固定严格 A–F 选项集合解释，对 Stage 1/4 使用去除首尾空白后的全文相等；`lexical_token_f1` 是小写后按空白分词的多重集 F1，仅表示词面重叠，不是语义正确率，也不是论文 BLEU/ROUGE；`format_valid` 报告有效答案比例。选项解析移植自固定上游 MIT 代码，Scorer 不导入原生模型依赖。

分母是预先固定的全部 QA 成员。缺失结果/参考记 missing；空输出、格式不合法、错误答案不会排除，格式失败的闭集答案计为错误。工程验收 Gate 检查 Run 成功及评分覆盖率，**不表示模型达到质量门槛或论文复现**。

```bash
CUDA_VISIBLE_DEVICES='' gymts-itformer score \
  --evaluation /tmp/gymts-itformer/evaluation.json --root /tmp/gymts-itformer/runs \
  --core-identity /tmp/gymts-itformer/core-identity.json \
  --output /tmp/gymts-itformer/rescore.json
```

重评只读取旧 Run 和封存答案，创建新的 Evaluation，关联旧 Evaluation ID。命令主动禁止新 Run 和 Candidate.prepare，输出 `execution_calls` 必须均为零；可在只安装核心和本 wheel、没有 torch/transformers/原生源码的独立解释器中执行。旧报告和 Run 不覆盖。完整卸载本包后核心仍可读取 CAS/Run，但缺少领域 Scorer 时不能进行本领域评分。

## Python 接口与证据

```python
from gymts import GymTS
from gymts_itformer.workflow import build_evaluation

# public/private/params 为上面命令生成或读取的 JSON 对象。
with GymTS('/tmp/itformer-run', integrations=('itformer',)) as gym:
    spec = build_evaluation(gym, public, private, params)
    report = gym.autobench.evaluate(spec)
```

公开函数为 `prepare_view`、`flatten_questions`、`project_official`、`preflight`、`build_evaluation`、`score_spec`、`freeze_core`、`verify_frozen_core`。输入输出 schema、原生数据、模型 codec 和领域评分全部归本包管理。

每次真实生成保存一个正式 ModelCall：请求/响应、真实 native prompt/response token IDs、五个原生输入张量、参数、耗时边界、权重/基础模型/tokenizer/源码身份和异常。write-ahead intent 是独立制品，不伪造第二次采样。记录 profile 为 `io`；没有采样 logprobs，不声称可直接用于 RL。没有 Agent 工具行为，因此不伪造 ToolCall。Snapshot 引用封存 Run 事件边界，正式评价引用独立答案视图。

## 测试、错误与限制

```bash
python3 -m venv /tmp/gymts-itformer-contract-venv
/tmp/gymts-itformer-contract-venv/bin/python -m pip install --no-deps \
  /tmp/gymts-itformer-wheels/gymts-0.5.0-py3-none-any.whl \
  /tmp/gymts-itformer-wheels/gymts_itformer-0.1.0-py3-none-any.whl
/tmp/gymts-itformer-contract-venv/bin/python -I -m unittest discover -s adapters/itformer/tests -v
```

上述命令从完整 checkout 读取测试，包本身由 wheel 安装。仅有核心和本包的轻量环境仍运行 21 项合同测试，包括注册/Schema、QA 展开、固定模型身份负例、核心 wheel 身份、纯规划、真实 SDK 评分/重评及部分失败的完整分母。5 项名称含 `native_data` 的原生数据 CPU 测试需要可选 h5py/NumPy；缺失时明确报告该组 skip，不把未执行的 HDF5 准备称为通过，也不要求核心安装科学依赖。用于评分的轻量固定 JSON 视图和测试 Candidate 均明确标为 test-only，不替代真实数据准备或原生模型验收。

在独立数据环境安装本 wheel 的 `data` extra 后，运行全部 26 项，或仅运行 5 项 native-data CPU 组：

```bash
python3 -m venv /tmp/gymts-itformer-data-venv
/tmp/gymts-itformer-data-venv/bin/python -m pip install \
  /tmp/gymts-itformer-wheels/gymts-0.5.0-py3-none-any.whl \
  '/tmp/gymts-itformer-wheels/gymts_itformer-0.1.0-py3-none-any.whl[data]'
/tmp/gymts-itformer-data-venv/bin/python -I -m unittest discover -s adapters/itformer/tests -v
/tmp/gymts-itformer-data-venv/bin/python -I -m unittest discover -s adapters/itformer/tests -k native_data -v
```

数据组真实创建 HDF5 并检查全部通道、原生列表投射、私有答案隔离、非有限值/重复选择与资产成员负例。带可选数据依赖的完整 26 项零跳过验证与真实 8-QA 模型验收分别记录；轻量发行检查的 21 项执行、5 项 skip 是另一层检查。测试不调用模型或 GPU。

命令退出码：0 为准备/预检/规划完成或工程评价 Gate 通过；1 为配置、文件、依赖、身份或运行异常；2 为评价已保存但失败或证据不足。原生 prepare 失败也会保留 GymTS Run/错误；详细证据读 `evaluation.json` 和 Run store。

本轮已完成小规模工程验收，不能推断全部 42,477 条测试 QA 的质量。7B checkpoint 的 LLM 部分按上游原生实现被忽略，实际另行加载基础 Qwen，二者均记录；不把仅有一个模型目录当成完整身份。本包仅在显式 `prepare-official/project` 命令读取网络，不自动训练、不修改核心、不发布模型，也不自动部署维护决策。

## 本轮真实验收摘要

2026-10-21 在冻结 GymTS 0.5.0 wheel 上完成，39 个已安装核心文件摘要一致，核心改动为 0。每阶段 2 条、共 8 条 QA；原生模型加载验证了全部 150 个非 LLM 权重键/值，基础 Qwen missing/unexpected/mismatched keys 均为空；11 个实际模型分片与两个官方固定 Hub 快照的 LFS 摘要全部一致。Qwen 固定快照为 `a09a35458c702b33eeacc393d103063234e8bc28`。

| 检查 | 实际结果 |
| --- | --- |
| 真实生成 | 8 次成功 ModelCall；672 prompt tokens、144 completion tokens；没有到达 128 token 上限 |
| 格式有效率 | 8/8 |
| 混合任务 answer_exact_match | 2/8；开放题使用全文匹配，不能与闭集准确率混为一谈 |
| lexical_token_f1 | 0.49763887682055463；仅是词面重叠 |
| GPU | 1 张 A800，统一预算记录 415.744 秒，约 0.1155 GPU 小时；未训练 |
| 独立重评 | 没有 torch/transformers/h5py/timm 的环境中成功；新执行和模型 prepare 均为 0，分数一致 |
| 证据不变 | 62 个原 Run 事件与封存 execution snapshot 摘要一致 |
| 交付 | sdist 重建 wheel、源码外安装；data 环境 26/26 CPU 测试零跳过，轻量环境 21 项执行、5 项 native-data skip；卸载整个适配包后核心仍可读取 8 条历史结果和 CAS |

Run 为 `run_00abb98bd1a3481ca5b34f1964c36e24`，原 Evaluation 为 `evaluation_9aeab3ec4361429c9d01ef985d442517`。完整原题、答案、权重、日志和活动 CAS 保留在本机，不随源码发布。统计证明该小视图的工程闭环，不证明整体 benchmark 指标或模型改进。
