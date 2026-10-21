# 五分钟开始

GymTS 的主线是**存储数据、接入数据、组织实验、记录实验**。先运行核心自带的小型实验，
再根据需要安装适配包。这个流程不需要 GPU、外部数据、模型服务或 API key；Python 要求
为 3.9+，本地存储后端面向 Linux / macOS。

## 1. 安装源码

```bash
git clone https://github.com/Jurmean/GymTS.git
cd GymTS
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

当前实现版本是 **0.6.0**，公共合同是 **1.4.0**。这些命令安装仓库源码，不假定此版本已发布到 PyPI。

当前 F2.1 已完成技术验收。固定数据引用、多阶段执行、失败续接和数据回库见[实验组织指南](experiment-organization.md)；已验证范围与限制见[当前验收报告](reports/experiment-organization-2026-10-21.json)。

## 2. 完成第一次实验与重评

```bash
python examples/quickstart.py --root /tmp/gymts-quickstart
```

该程序运行预测与控制示例，对两个候选评分，再追加独立标签，对同一组 Run 重评。
摘要包含以下字段（Run ID 每次生成）：

```json
{
  "counter_operations": 3,
  "initial_verdict": "insufficient_evidence",
  "rescored_verdict": "pass",
  "mae": {"last-value": 1.0, "window-mean": 2.0},
  "same_run_ids": true,
  "original_results_unchanged": true
}
```

初次缺少标签时，`insufficient_evidence` 是正确结果。执行完成、证据充分、评价达标是三个不同判断。
重评新增评价报告，保留原 Run、事件与方法输出。

## 3. 查看轨迹

```bash
gymts --store /tmp/gymts-cli run examples/forecast_experiment.json
gymts --store /tmp/gymts-cli inspect RUN_ID --events
```

把 `RUN_ID` 换成上一条命令返回的 `run_id`。Run 关联配置、组件版本、输入输出与事件；
制品按内容寻址保存在 CAS 中，评价报告另有独立身份。

## 4. 按需接入适配包

```bash
python -m pip install . ./adapters/timeseries ./adapters/chatts
```

```python
from gymts import GymTS

with GymTS("/tmp/gymts-adapter-demo") as gym:
    print(gym.available_integrations())
    gym.enable_integration("timeseries")
    gym.enable_integration("chatts")
```

发现适配包不会自动启用。具体环境、任务、方法与 Scorer 在适配包显式注册；
数据集、原生模型、仿真依赖和凭证按各包要求另行准备。

## 5. 下一步

- [使用手册](user-guide.md)：存储与接入数据、规划、执行、晚到标签和记录。
- [实验组织](experiment-organization.md)：阶段依赖、尝试记录、查询与数据回库。
- [API 与 CLI](reference.md)：方法签名、退出码与协议字段。
- [环境接入](environment-adapters.md)：合成、静态、仿真与 live 来源。
- [独立适配包](../adapters/README.md)：适配包的安装和验收矩阵。
- [最小教学适配包](../examples/adapters/minimal_demo/README.md)：独立安装、运行、卸载与重评。

活动 SQLite / CAS 必须使用本机 POSIX 文件系统，避免直接放在 S3FS 等对象存储挂载上。
`/tmp` 适合体验，但不是备份；长期实验请使用自己的持久本机目录。
