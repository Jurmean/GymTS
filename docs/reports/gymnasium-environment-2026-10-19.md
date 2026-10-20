# Gymnasium 仿真环境接入验收

本轮新增两个独立适配包，核心保持 GymTS 0.5.0 冻结。`gymts-interaction`
提供可复用的控制任务、动作合同和独立评分器；`gymts-gymnasium` 实现真实
Gymnasium 的 reset、step、close。前者不导入 Gymnasium、OpenEnv 或模型项目，
后者不修改 EnvironmentTS 或 AutoBenchTS。

验收使用冻结核心 wheel `cea1ab0bdccf479820d9e9cf20cfc4a82c733978e7c722151601067e8925d226`，
核心代码树为 `8990de5a08378498c47853f238f7ae27c6f0072c1ea61bd29328294c6b8b9e20`。
实际从 `/tmp` 中调用源码目录外安装的 wheel，并逐文件核对安装核心与冻结清单。
精确适配包 wheel、版本、Run ID、测试数量和制品 SHA 见同名 JSON 报告。

## 职责与调用位置

Candidate 接收公开状态并输出 JSON 动作。Task 解释该动作并请求绑定的 `act`；
Runner 执行授权检查、调用 Environment 并保存调用证据。Environment 才持有原生
Gymnasium 实例。生产 Agent 可以替换当前序列策略，继续使用相同的任务合同；
本轮策略是验收工具，没有模型训练或 Agent 能力提升的结论。

每个 Run 创建一个环境实例，只 reset 一次，使用 execution.seed，并核对实际
`np_random_seed`。act 仅 step 一次，observe 只消费缓存的状态，不推进后端。
终止后不自动重置，重复操作与未消费前再次操作均拒绝，只关闭自有实例。
原生 terminated/truncated 保持区别。scope 最后一次动作产生的状态和奖励完整保存，
但该边界不再产生新决策。若取消发生在 act 与 observe 之间，未消费状态保存在
封存清理摘要 artifact_refs 引用的状态制品，不能冒充完整 episode。

独立 Scorer 从 AutoBenchTS 授权的 sealed result/event snapshots 核对决策、
operation、receipt 与每一步 transition，再计算回报和步数。重评不访问原生环境。
已有 ResultsView.event_snapshot_ref 和 TaskRequest.command 足以表达需求，因此
没有理由修改核心，也没有增加项目专用的 Runner 分支。

## 真实 CPU 结果

以下每种配置均使用 seeds 19、29，运行和原 Run 重评均通过，共 6 个成功 Run。

| 环境与边界 | 平均回报 | 平均步数 | 终止解释 |
|---|---:|---:|---|
| FrozenLake-v1，非滑动，6 步成功路径 | 1 | 6 | 原生 terminated，最后奖励为 1 |
| CartPole-v1，固定向右，至原生终止 | 9 | 9 | 原生 terminated |
| CartPole-v1，2 步 scope | 2 | 2 | scope 截断；最后奖励为 1，原生两个标志均为 false |

验收将 `gymnasium.make` 替换为必定失败的函数后执行原 Run 重评，仍全部通过。
重评前后完整 Run 记录哈希一致。纯计划阶段把 Gymnasium 从可导入模块中移除，
仍能成功生成 AssemblyPlan，证明计划不打开原生后端。

## 异构接口对合同的修正

与 OpenEnv 接入一起检验共享适配域时，发现两个真实差异，均在外部适配包解决：

- 有的环境不提供数值 reward。保留 null，只有 episode_return 缺少证据；有完整
  transition 时，步数和终止信息仍可独立评价，不能用 0 冒充未知奖励。
- 有的环境只提供 done，未说明 terminated 还是 truncated。通过可选 backend_done
  和 end_cause="unclassified" 保存原信号；EndInfo.reason 为
  source_exhausted，detail.reason 为 native_done_unclassified，相应分类指标报告 missing。
  scope_limited 独立表示决策范围结束，不改写原生 truncated。Gymnasium 继续保留原生分类。

中立包测试覆盖这两个差异、未知远端操作结果、防重发、权限、缓存和清理边界；
Gymnasium 测试覆盖真实 reset/step/close、末奖励、原生动作空间、种子、版本漂移和重评。

## 复现与范围

安装核心及两个适配包，并安装 `gymnasium==1.2.1`。其原生运行时要求 Python 3.10+。
运行：

```bash
python adapters/gymnasium/examples/native_cpu.py --output /tmp/gymts-gymnasium-proof-new
```

输出必须是尚不存在的本机目录。运行中的 CAS 和 SQLite 保持在 `/tmp`，归档位置是
`output/environment-adapters-2026-10-19/gymnasium/evidence.tar.gz`，包含完整 CAS、
封存 Run、评价与重评报告、精确 wheel 和测试日志。该目录为忽略的运行制品，不随包发布。

本轮支持 Discrete、Box、MultiDiscrete、MultiBinary、Tuple、Dict 的 JSON/NumPy
投射；不支持的自定义空间、不可有限表示的 observation、非字符串 JSON 对象键明确拒绝。
Info 默认不公开，必须配置 public_info_keys。vector、auto-reset wrapper、附着已有
episode 和外部可变注册项没有被本轮验收覆盖。记录安装版本、注册 entry point 与配置，
不宣称这等价于对全部原生依赖的密码学证明。

原生接口依据：[Gymnasium Env API](https://gymnasium.farama.org/api/env/)。
