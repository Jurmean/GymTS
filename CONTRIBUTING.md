# 参与 GymTS 开发

欢迎通过问题报告、使用反馈、文档和独立适配包改进 GymTS。开始前请阅读
[项目说明](README.md)、[行为准则](CODE_OF_CONDUCT.md)和[支持方式](SUPPORT.md)。
疑似安全漏洞按[安全策略](SECURITY.md)私下报告，不在公开 Issue 中附上利用方法或敏感数据。

## 先确定改动放在哪里

GymTS 的主线是存储数据、接入数据、组织实验、记录实验。EnvironmentTS 管通用数据、运行和证据，核心组织协议关联阶段与 attempt，AutoBenchTS 管独立评价；具体项目的
数据格式、模型后端、任务语义、训练算法和领域评分放在独立适配包中。同仓库维护不意味着
项目实现可以进入 `gymts` 核心发行包。

| 需求 | 优先位置 |
| --- | --- |
| 新数据格式、HF 视图、仿真或 testbed | 独立 Environment、DatasetReader 或连接适配器 |
| 新任务、模型、评分器或 benchmark 解析器 | 独立领域适配包及其 schema |
| 新工具集或 Agent SDK | 外部工具/Agent 适配器；由 Agent 决定工具调用 |
| TRL、LibraryTS 等训练能力 | 独立训练或工具适配包，优先复用上游实现 |
| 所有项目都需要的执行、访问边界、封存或评价机制 | 提供复现证据后讨论核心协议 |

现行接口见[框架指南](docs/framework.md)和[接口规范 1.4.0](docs/feishu/GymTS接口规范/GymTS接口规范.md)。
[下一版可插拔协议](docs/pluggability-contract-v2.md)是草案，不应当作已实施合同。
新增适配包按[适配包指南](adapters/README.md)和[环境接入指南](docs/environment-adapters.md)操作。固定数据/产物输入、阶段依赖、attempt 和失败续接见[实验组织指南](docs/experiment-organization.md)。

当前 0.6.0 / 规范 1.4.0 以 F2.1 为冻结验证基线；[当前验收](docs/reports/experiment-organization-2026-10-21.json)验证独立接入与卸载后重评，旧 23 个 schema 摘要保持不变。历史 F0/F1 的版本与证据保留。提出核心修改时，在 Issue 或 PR 中写清楚：

1. 哪个真实项目的哪个需求无法用现有接口表达，附最小配置和实际失败证据。
2. 为什么独立适配器或已有扩展点不能解决，而不是只因实现方便。
3. 拟修改的公共合同、能力声明、证据结构和失败语义。
4. 旧配置、旧适配包、旧 Run/CAS 的兼容方式；不能兼容时明确迁移和版本边界。
5. 一个冻结核心后的外部接入验证：运行、留轨迹、独立评价、原 Run 重评。

## 本地开发

以下命令从仓库根目录执行。核心要求 Python 3.9+；当前本地存储实现面向 Linux/macOS。
创建独立虚拟环境，避免把模型训练环境中的依赖当成核心运行要求：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install "setuptools>=64" wheel packaging
python -m pip install --no-build-isolation -e .
python -B examples/quickstart.py --root /tmp/gymts-contribution-demo
```

上述可编辑安装使用支持该模式的 setuptools 64+；发行构建声明的最低版本仍是 58。
核心 JSON 工作流没有第三方运行依赖。YAML、Arrow 和各项目原生运行依赖按需要安装；
它们不应成为发现插件元数据或使用无关项目的前提。离线开发时，先从自己的 wheelhouse
安装声明的构建工具，再执行检查；下面两个检查脚本本身不会访问包索引。

活动 SQLite/CAS、虚拟环境和构建工作目录应放在支持本地文件锁和原子文件操作的磁盘。
对象存储或类似挂载目录可保存关闭后的不可变证据归档，不应默认用作活动数据库目录。

## 实现约定

- 使用公共 SDK、注册表、Manifest 和 schema；不要导入核心私有实现或给 Runner 添加项目名分支。
- 规划和校验保持声明式，不打开数据、连接服务、加载模型、创建会话或写 CAS。实际 I/O 在 Run 建立后执行。
- 真实调用和失败都留证据。未知结果或可能发生的副作用要明确记录，不自动重试有副作用的操作。
- 用明确的组件、协议、数据和模型修订标识。记录源文件/上游提交的校验值、原生参数和工具调用血缘。
- 不把不存在的奖励、缺失标签或未知终止原因填成零或成功。领域适配器解释上游语义，框架保存其声明和证据。
- 公共输入、私有参考和训练数据分开授权。benchmark 默认只用于评价；训练必须具有明确的数据用途许可和来源政策。
- 插件发现不能导入重型运行时；安装与显式启用分开。可选依赖缺失应给出可操作错误。
- 外部进程使用参数数组而非拼接 shell 命令；设置有界超时、工作目录和环境，只清理自己创建的进程/会话。不要记录凭证值。
- 实验结果、日志、模型权重、下载数据和本机路径不要混入发行包。不能分享的数据用小型可公开复现夹具替代。

## 验证改动

运行与改动相关的检查。纯文档或模板修改检查链接、命令、格式和事实即可，无需为文档另造单元测试。
逻辑修复应增加能重现实际错误的回归用例，不写仅重复实现的断言。

```bash
# 核心源码回归
python -B -m unittest discover -s tests -v

# 核心 sdist、wheel、sdist 重建、隔离安装和公共 API 外部插件
python -B scripts/check_release.py --output /tmp/gymts-release-check.json

# 全部独立适配包的构建、安装、发现/启用、回归、移除和共同启用
python -B scripts/check_adapters.py --output /tmp/gymts-adapter-check.json
```

两个打包脚本需要当前解释器已有 `setuptools>=58`、`wheel`，并能用 `venv` 创建带 pip 的环境；`check_adapters.py` 另需 `packaging`。
它们在临时目录构建，并通过 `--no-index` 从本地制品安装。报告写到指定路径；临时发行包会在结束时删除。
GitHub Actions 的[工作流](.github/workflows/ci.yml)配置了 Python 3.9、3.12 和 3.13；配置存在不等于本次分支已通过远端 CI。

已有 0.5.0 [核心隔离安装报告](docs/reports/core-package-check-2026-10-20.json)记录 160 项通过；
[十一包报告](docs/reports/environment-adapter-package-check-2026-10-19.json)记录 319 项运行、54 项条件跳过。
这些是具体快照的基线，不是未来改动固定的测试数量。缺少原生依赖时的跳过不能替代实际运行验证：
例如 HF、Gymnasium、OpenEnv、Prometheus 的[原生验收](docs/reports/environment-acceptance-2026-10-19.json)
单独记录了来源、版本、成功和失败轨迹。新增原生后端应附相应的可重复命令与依赖说明。

## 提交可审阅的贡献

从当前基线建立主题分支，保持改动聚焦。一般文档或修复可直接开 PR；协议变化、新外部副作用、
新科学运行时或较大重构，先用 Issue 讨论接口和验收边界。没有要求贡献者先创建形式上的空 Issue。

PR 应说明问题、修改后的行为、适配器/核心边界、实际验证命令及结果、条件跳过和已知限制。
重评分或兼容性变动应附旧 Run ID/结果哈希保留的验证。不要提交密钥、用户数据、私有参考答案或完整生产服务地址。
使用 [PR 模板](.github/PULL_REQUEST_TEMPLATE.md)提供审阅材料；本项目目前没有声明 CLA 或 DCO 流程。

GymTS 代码和文档采用 [MIT License](LICENSE)；提交贡献时，请确认有权按该许可提供相应内容。
新增或引用第三方代码、模型、数据时，记录来源和其独立许可要求，并保留需要的声明；
项目的 MIT 许可不能替这些资产授予使用或分发权。发布准备见[维护指南](docs/maintainer-guide.md)。
