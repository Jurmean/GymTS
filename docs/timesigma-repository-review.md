# 接入前的仓库核对

> 迁移说明（2026-10-19）：以下为接入时 GymTS 0.3.1 的历史核对。当前核心 0.4.0 已将 TimeSigma 移至独立发行包 `gymts-timesigma` 0.1.0（`adapters/timesigma/src/gymts_timesigma`），改用安装元数据 entry point 发现，组件 ID 和 `/1` 合同保持不变。当前安装与调用方式见 [接入指南](timesigma-integration.md)；本历史表不作为新包边界的验收证据。

主仓库为 [Jurmean/GymTS](https://github.com/Jurmean/GymTS)，本地 checkout 起点为 `cffa38f223e64a75874936ad58ce53d9391e63a9`（main，GymTS 0.3.1）。改动在这个 checkout 内完成。以下判断来自实际代码、正式文档及现有测试，不沿用先前工作区的同名接口假设。

| 核对对象 | 现行事实 | 本次接入决定 |
| --- | --- | --- |
| docs/feishu/GymTS接口规范 与 contracts/schema | 规范 1.1.0；公共消息 /1；Payload 是严格 inline/artifact union | 为 TimeSigma 单独登记版本化 schema |
| docs/framework 与 integration discovery | 第三方/内置可选集成均显式注册；发现阶段不导入代码 | 增加 timesigma 元数据，默认核心不加载科学包 |
| pluggability-design / contract-v2 | 尚未实施的 2-draft.1 | 不依赖 SourceProvider、RuntimeProvider 或 v2 消息 |
| ChatTS integration | 已有 Environment、Task、Candidate、Scorer 与封存后补标签范例 | 复用其公开扩展模式，不复制业务数据结构 |
| environment_ts/runner | prepare 在观察前执行；fit 必须返回实际训练版本和 provenance | 真正拆开 TimeSigma fit/score，禁止延迟到 infer 再训 |
| environment_ts/services | 精确 ArtifactRef/View capability；不递归授权嵌套 ref | train View、test snapshot、private labels 分开；native/context 使用 inline |
| registries / validation | Manifest 声明的 protocol、schema、learning 能力参与验证 | 只声明已实现的 AR/IF fit/frozen 能力，无 online update |
| storage/artifacts | POSIX CAS、不可变 metadata identity、裸 hex content_hash | 复用 ArtifactStore 保存数据、checkpoint、native-call 与父轨迹 |
| storage/records | SQLite WAL，前驱先提交，Run 封存后不能补执行事件 | 复用 Run/RecordSnapshot；标签用 attach_outcomes 独立追加 |
| autobench_ts | 先固定计划单位，再执行；独立 score 不重新调用 Candidate | 缺标签保留分母，封存后评价，固定输出重评分 |
| recording validation | model_calls 目前仅 none；traces 为 None；无 extra event collector | 记录真实 CAS 制品，不虚构 token/collector 能力 |
| CLI / setup / CI | --store、显式 --integration；Python3.9+，离线 wheel/sdist 安装检查 | 增加专用 pipeline；保持纯 host 安装与现有检查 |

接入前原有 175 项测试全部通过。对比上游 TimeSigma 时另核查了原生 Catalog、Schema membership、label-free loader、TSData 预处理、AR/IsolationForest、checkpoint、官方八指标、Pi bridge、Research experiment 与严格 Evidence parser。完整 native Research job 和本次 GymTS 模型 bundle 是两个合同；本轮按用户确定的范围交付 GymTS 实验和父轨迹，Pi 自动循环与原生 Memory 发布另行适配。

代码没有给核心 Runner 添加 TimeSigma 名称分支，没有搬入旧工作区的 Runner、轨迹 SQLite 或消息层，也没有将旧测试数量视作新仓库的验证。具体使用及限制见 [TimeSigma 接入指南](timesigma-integration.md)。
