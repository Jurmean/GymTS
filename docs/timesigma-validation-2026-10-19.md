# TimeSigma 本地接入验证（2026-10-19）

本次以 Jurmean/GymTS 的 `cffa38f223e64a75874936ad58ce53d9391e63a9` 为起点，只在此主仓库新增可选 integration。没有提交、暂存或推送 Git；未调用收费 Provider。当前范围按用户确定的边界交付 GymTS 实验、工具调用和 Research 父轨迹，Pi 自动循环及原生 Memory 发布另行适配。

## 回归与独立安装

| 检查 | 结果 |
| --- | --- |
| 接入前原有测试 | 175 项通过 |
| 最终完整回归 | 246 项通过；5 项需显式科学环境，默认跳过 |
| `GYMTS_TIMESIGMA_NATIVE_TESTS=1` 定向验证 | 71 项全部通过，含真实原生 CPU 训练、重放及八指标一致性 |
| wheel / sdist 重建 wheel，干净环境安装 | 均通过；3 个 console entrypoint 可运行 |
| 干净安装中的完整回归 | 246 项通过，缺 NumPy 与原生环境的用例按合同跳过 |
| 基础安装与显式 registration | 不加载 NumPy、SciPy、Torch、EasyTSAD 或 TimeSigma 科学模块 |
| Git diff whitespace 检查 | 通过 |

真实科学环境使用 Python 3.12.3、TimeSigma `5a953c1a84d0a442d1c41b17b4e8aba8c013be10`、EasyTSAD `e7be92374a4543d7c52d6e34ef7047f4d6776be0`，CPU执行。18 组 float32/float64 × raw/min-max/z-score × diff0/1/2 的分阶段预处理与原生完整 loader 逐字节相同。原生训练入口、scaler.fit 在 score/replay 阶段均被禁止，独立进程重放核对真实分数字节。

## 真实数据上的六个 PlanningUnit

数据为固定 TODS，源 revision `0c6dfa195a5af8ef75938bc1ca6b870e49c7b14a`。每条曲线原 train/test 均为5000点，原生 split 为4000/1000。IsolationForest 使用原生配置；AR 仅将 epochs 显式设为2，其余使用原生默认值，作为 CPU 接口验收，不作为方法排名或泛化性结论。

| 方法 | Schema | 独立评价曲线数 | Run 状态 | 评价 Gate |
| --- | --- | --- | --- | --- |
| IsolationForest | naive | 1 | succeeded | pass |
| IsolationForest | all_in_one | 15 | succeeded | pass |
| IsolationForest | zero_shot | 7 | succeeded | pass |
| AR | naive | 1 | succeeded | pass |
| AR | all_in_one | 15 | succeeded | pass |
| AR | zero_shot | 7 | succeeded | pass |

naive 固定曲线0；all_in_one 使用15条成员；zero_shot 使用原冻结的8条 weight-training成员和7条 held-out成员。ZERO_SHOT 的归一化可见15条曲线自己的 train，权重训练只使用8条成员；原生语义与权限分开记录。AR每条测试曲线输出4984个分数、offset=16，IsolationForest输出5000个分数、offset=0。每个 PlanningUnit 只有一个 TaskInput/TaskResult容器，成员曲线始终分列、不拼接。

八个官方指标均由原生 evaluator 计算，原生 add/avg 聚合、margin/delay及全正常标签排除规则保留。Gate检查执行失败率和完整覆盖率；pass不代表方法优于其他方法。无标签首报保留计划分母，标签在封存后附加，重评分保持原 Run ID、执行结果与分数不变。

多方法验收实际发现并修复了同一 gold revision 的重复 attach 时间字段冲突；新增回归覆盖重复挂载和封存不变。受影响的已完成 AR/naive Run直接重评分，没有重复训练。安装检查还发现测试夹具的包路径依赖，已修复并在干净 wheel 安装中验证。截止时间测试给独立进程启动留出明确余量，继续验证真实超时、SIGTERM清理、强制进程组终止及真实未封存前缀保留。

## 父轨迹、预算与迁移

真实 ResearchEpisode 通过 model.catalog、data.import、experiment.run关联一个 AR/zero_shot 子Run。请求、结果、失败、预算及子RecordSnapshot均使用CAS哈希链；预算恢复不重置、重复call_id不重做实验，模型用量未知时保留预留额。该实际episode执行1次科学训练，Provider请求0次、token计费0；它没有模拟成一次LLM自主研究。

执行工具和独立重评分均使用进程组硬截止时间；真实Run分配后先持久保存receipt，失败、超时或后置评价异常也保留子Run关联。SIGKILL所留下的running前缀不被伪造为已封存结果。记录失败阻止后续副作用，关闭writer后不能分叉原journal。

六个Run的固定快照导出为 `six-planning-units.zip`，包含351个CAS制品，归档SHA256为 `47b725f8475cab6b1d8536093e8e1bf3c4b0a6d7e18c0b6eecab4ca94d9bca05`。校验涵盖原始ArtifactRef、bytes、metadata引用、记录快照边界、事件与结果一致性及标签版本。

在全新原生存储中导入后，历史Run没有被插入执行索引。加载原 AR/zero_shot 模型产生明确的新 replay Run，模型版本不变，7条曲线与原输出分数字节完全相同，prepare/infer/replay未重新训练。新Run状态succeeded，八指标覆盖Gate通过。

## 本地证据

证据保存在主仓库忽略目录 [output/timesigma-acceptance-20261019](../output/timesigma-acceptance-20261019/)，活动SQLite/CAS位于 `/tmp/gymts-jurmean-acceptance-state` 与 `/tmp/gymts-jurmean-restored-state`，避免在S3FS上运行WAL。

- `matrix.json` 与六个方法/Schema JSON：真实Run、模型版本、初报、补标签评分与快照引用。
- `research-parent.json`：父轨迹及真实预算状态。
- `six-planning-units.zip` / `portable-replay.zip`：完整原始实验与离线恢复证据。
- `portable-replay.json`：全新存储中的load_only结果。
- `tests.log` / `native-tests.log` / `release-check.json`：最终回归与独立安装结果。
- `source-files-sha256.json` / `evidence-files.json`：源码及归档文件校验清单。

这些是本地未发布产物，不进入源码发行包，也没有上传GitHub。原生Pi、其完整Memory发布目录、其余Core12方法、operators/ensemble和GPU仍未验收；接口与限制详见 [接入指南](timesigma-integration.md)。
