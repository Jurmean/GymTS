# GymTS 0.3.1 修复与 GitHub 发布准备报告

日期：2026-10-18。实现版本：0.3.1。接口规范：1.1.0，现有消息主版本保持 `/1`。本文发布状态截至该日期；后续仓库状态以 GitHub 提交和 CI 结果为准。

结论：现有同步本地框架中本轮确认的正确性、可选集成装配和打包问题已修复。175 项源码测试与175 项安装后测试通过，独立第三方插件安装、启用和卸载验证通过。本版本可以作为同步本地 SDK 的源码预览版本提交评审；企业多租户平台、v2 语义合同和真实模型效果仍属于后续工作。仓库尚未指定许可证，也尚未初始化 Git 或上传 GitHub。

## 修复范围

| 问题 | 修复结果 | 回归依据 |
| --- | --- | --- |
| 默认装配直接加载 ChatTS | `GymTS()` 只注册基础参考插件，ChatTS 改为显式启用 | 新进程阻断所有 ChatTS 导入，核心预测仍成功 |
| TextLLM 继承 ChatTS 具体实现 | 二者分别使用公共 FrozenJSONHTTPCandidate，QA 校验放在共享合同模块 | 单独导入文本适配器时阻断 native candidate 导入仍成功；原 HTTP 测试保留 |
| 集成依赖私有 `plugins._common` | 新增公共 plugin_support，原私有路径保留转发 | 集成中已无该私有依赖 |
| 独立插件缺少标准发现入口 | 支持 `gymts.integrations` entry point，发现仅读取元数据，启用才加载 | 真实独立 OLS 插件 wheel 安装、发现、启用、运行、卸载 |
| 插件登记失败残留半注册状态 | schema 和四类 registry 登记事务回滚；保留原 factory identity | 四角色部分登记后失败、回滚、重试与无关实验验证 |
| 无关重名插件阻断发现 | 报告冲突元数据，只拒绝启用冲突名称 | 重名入口与无关名称启用回归 |
| 组合 Candidate 的内部引用覆盖适配器身份 | 登记键始终取 component_ref | 独立适配器名创建、内部组件名不误登记、冲突拒绝 |
| 畸形 Manifest/schema 延迟到运行时崩溃 | 提前校验组件列表、metric 定义、schema items、JSON、重复枚举/字段及引用类型 | 合同拒绝回归；超大整数不再触发浮点 OverflowError |
| 非 JSON 返回被误判为存储损坏 | 封存 failed Run，标明 evidence_status=incomplete，记录合同错误 | NaN/对象输出后仍可读 Run，同一 store 后续正常运行 |
| 非 JSON 清理摘要阻断最终封存 | 转为明确 cleanup failure 并保留失败记录 | 清理故障回归；真实持久化故障仍返回 recording_failure |
| 观测可携带尚不可用反馈 | 交给 Task 前检查 available_at 与本批可见前沿 | Task/Candidate 均未收到未来反馈；合法动作回执未误拒绝 |
| 制品发布跟随目录符号链接 | 通过 POSIX 目录描述符和 O_NOFOLLOW 发布 | blob/ref 目录符号链接写出拒绝；外部目录保持空 |
| JSON 完整性检查后重新打开文件 | 解码同一次摘要校验的字节 | 校验后替换文件，不会返回替换后的未校验 JSON |
| 未提交或改标 schema 的 Payload 可进入持久记录 | Event/Outcome 提交前解析制品并核对 schema；失败回滚整个批次 | 无悬空提交、无批次部分成功；重启可读合法引用 |
| 畸形制品元数据产生原始异常 | 明确检查 ArtifactRef、manifest 与有限 JSON metadata | 返回结构化错误；不支持 POSIX 操作的平台明确拒绝 |
| 评分用途及来源检查不完整 | allowed_uses 检查类型、唯一性和支持用途，来源制品必须可解析 | 字符串授权、重复用途和未提交来源拒绝 |
| 评分结果重复或未满足 alignment 合同 | 拒绝重复 result_id、缺失对齐键和畸形对齐值 | 自定义记录后端不能靠重复结果扩大计数 |
| 零计分项却声明 ready；需要真值却无依据 | 拒绝不满足证据条件的 Scorer 返回 | 报告 scorer_failure，不能误判 pass；无须真值的合法指标仍支持 |
| 重评分丢失 tags 分组 | RunSelection 增加可选 tags，默认空并冻结到新计划 | 原分组可恢复、调用后修改入参不改计划、无模型重跑 |
| 发布目录可能夹带本地产物 | .gitignore 与 MANIFEST.in 明确排除实验输出、缓存、数据库及凭证 | wheel/sdist 成员和已知凭证模式检查通过 |
| 只能在源码目录验证安装 | 离线构建、源包重建、源码目录外隔离安装测试 | 两次安装、两个命令入口、完整回归与独立插件验证 |

主要代码入口：[注册器](../gymts/registries/__init__.py)、[schema](../gymts/contracts/schema.py)、[Runner](../gymts/environment_ts/runner.py)、[可选集成](../gymts/integrations/__init__.py)、[HTTP 支持](../gymts/http_candidate.py)、[制品](../gymts/storage/artifacts.py)、[记录](../gymts/storage/records.py)、[评分](../gymts/autobench_ts/service.py)。

## 最终验证

| 验证 | 结果 |
| --- | --- |
| 本机 Python | 3.9.6；实际验证声明的支持下限 |
| `python3 -B -m unittest discover -s tests -q` | 175 项通过；修前基线为125 项，新增50 项 |
| 隔离安装后的完整回归 | 175 项通过；从 sdist 重建 wheel，安装在新 venv，测试目录无源码包 |
| wheel / sdist | 构建成功；wheel 45 个文件，sdist 81 个文件；未含运行产物和常见凭证文件 |
| 两种 wheel 来源 | 直接构建及 sdist 重建均通过；本次两份 wheel 的 SHA-256 相同 |
| 命令入口 | `gymts`、`gymts-chatts` 的 help 及合成 Counter 运行通过 |
| 独立第三方插件 | 真实构建并离线安装临时 OLS 插件，8 条预测逐值正确；发现不加载，卸载后核心正常；全程无 ChatTS 导入 |
| quickstart | 动作3 次；初始 insufficient_evidence；重评分 pass；MAE 1/2；Run ID 和原始结果不变 |
| 编译检查 | gymts/examples/tests/scripts 全部通过；缓存写入临时目录 |
| 待提交候选文件 | 按本地 .gitignore 枚举并检查已知凭证模式；见源文件审计 JSON |
| GitHub CI | 已配置 Linux 上 Python 3.9/3.12/3.13；尚未在 GitHub 执行，不声称跨版本已通过 |

机器报告：[发行物与隔离安装](reports/release-check-2026-10-18.json)、[源文件候选审计](reports/source-audit-2026-10-18.json)。发行物检查的临时 wheel/sdist 会清理，报告中的摘要对应本次实际构建，不是已上传资产。已知模式检查不构成全面安全审计。

复核命令：

```bash
python3 -B -m unittest discover -s tests -q
python3 -B scripts/check_release.py --output output/release-check.json
python3 examples/quickstart.py --root .gymts/demo
```

## 迁移方式

0.3.0 调用 `GymTS()` 会自动装配 ChatTS；0.3.1 需显式选择：

```python
from gymts import GymTS

with GymTS(root=".gymts", integrations=("chatts",)) as gym:
    result = gym.run(chatts_experiment)
```

也可在现有实例调用 `gym.enable_integration("chatts")`。通用 CLI 在子命令前加 `--integration chatts`；`gymts-chatts` 和专用 pipeline 自动启用。未选择或无法加载某集成，不应影响无关基础实验。

独立分发包通过 `gymts.integrations` entry point 声明 `register(registries, schemas)`。插件仍为可信进程内代码；登记事务只回滚注册表，无法撤销插件自行执行的外部操作。

接口规范升为1.1.0，新增可选 RunSelection.tags；消息 `/1` 不变。沿用原标签分组时，评分调用方从原 EvaluationPlan 复制 tags，新计划固定这些标签；不据此改写原 Run 或声称它们是执行事实。

当前 allowed_uses 支持 evaluation、training_export、online_feedback，必须为无重复字符串列表。修复后畸形引用、缺失来源和无效评分声明会被拒绝，不再默许通过。

## 发布范围与未验收能力

本轮修复的是现有同步本地框架，不包含企业控制服务、租户授权、分布式 worker、强制超时或故障恢复。Source/Task/Method/Runtime 的 v2 字段级草案仍未实施；现有 ChatTS 与文本适配器继续共享 v1 QA 合同，不能宣称已完成全部语义拆分。

本地存储当前支持 Linux/macOS 所需的 POSIX 文件操作；没有 Windows 验收结果。不可信插件需要外部隔离；当前受限 Python 服务不是沙箱。

本轮没有连接真实 ChatTS/DeepSeek 服务、下载模型、调用源生成器或执行训练。测试中的 HTTP 与生成器使用 fixture/mock；历史真实实验不能替代本版本模型效果验证。

上传准备已经包含 README 迁移说明、文档入口、忽略规则、包内容清单和只测试不发布的 CI。原有 output/outputs、本地数据库、缓存和实验文件未删除。

项目所有者仍需决定公开或私有及许可证；没有代选 LICENSE、编造作者或仓库地址，也没有创建远程仓库、提交或推送。
