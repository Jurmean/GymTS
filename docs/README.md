# GymTS 文档入口

当前模块名称为 EnvironmentTS 和 AutoBenchTS。框架搭建与任务接入以正式接口规范为基线。

本地框架 0.3.1 已搭建，代码入口见[项目 README](../README.md)，具体实现、接入方式及尚未支持的能力见[框架指南](framework.md)。[可运行示例](../examples/README.md)可验证执行、持久化、评价与旧 Run 重评分；[ChatTS 接入指南](chatts-integration.md)说明真实合成数据、七类 Task、原生与文本 HTTP Candidate 及完整实验流水线。历史 DeepSeek 实验产物位于本地 output/，不随源码分发；本次离线回归不重新调用该服务。

- [2026-10-18 修复与发布准备报告](release-readiness-2026-10-18.md)：本次代码修复、独立安装验证、迁移方式与未验收能力。
- [GymTS 接口规范 1.1.0](feishu/GymTS接口规范/GymTS接口规范.md)：服务入口、字段、状态、调用顺序、记录、评价、轨迹与训练导出、接入验收。
- [数据任务与执行端可插拔设计草案](pluggability-design.md)：下一版插件边界、装配、消息与替换验收提案，尚未实施，不替代现行规范。
- [三端公共消息与调用协议草案](pluggability-contract-v2.md)：字段级 schema、接口、调用顺序，以及 ChatTS 与独立 OLS 方法的消息推演；不代表已完成插件实现或真实模型推理。
- [企业内部多团队平台研发路线评审](enterprise-platform-roadmap.md)：2026-10-16 调研与架构建议，包含复用决策、共享执行边界、十二周试点规划及停止条件；尚未实施。
- [实验配置示例](examples/experiment_kpi_replay.yaml)与[旧 Run 评分示例](examples/score_existing_runs.yaml)：示例适配器和资源需登记后使用。
- [运行机制](feishu/GymTS%20运行机制/GymTS%20运行机制.md)、[场景接入](feishu/场景接入/场景接入.md)与[项目理解](项目理解.md)：说明与实践映射。
- [总体设计](feishu/GymTS总体设计/GymTS总体设计.md)：模块与周边系统分工。
- [修改前历史快照](archive/2026-10-12-before-api-v1/)：保存旧版文本与原校验清单。

原始 PDF、PPT 和架构图片保留为来源资料，可能包含旧命名。现行文本文档与接口规范冲突时，以接口规范为准。接口规范描述目标合同；实际支持范围以框架指南和已登记组件为准。
