# OpenEnv 外部环境接入验收

实现位于独立发行包 `gymts-openenv`；控制任务与封存事件评分位于独立
`gymts-interaction`。GymTS 核心保持 0.5.0 冻结，代码树
`8990de5a08378498c47853f238f7ae27c6f0072c1ea61bd29328294c6b8b9e20`
未改。EnvironmentTS 仍负责执行、动作授权和证据，AutoBenchTS 仍负责评价与重评。

原生验收使用未修改的官方 `huggingface/OpenEnv` 固定提交
`f2b00027b63242df33fbbf3af693bbc7cbfa9955`，启动其 Echo 和 Connect4
真实服务器，用官方 `GenericEnvClient(mode="simulation")` 通过持久 WebSocket
连接。此 SDK 与服务器的已安装 Python 文件逐项核对原始源码，不使用自制 HTTP
服务替代上游。完整依赖装在独立虚拟环境，`pip check` 通过。

| 真实需求 | 适配器处理 | 验证 |
| --- | --- | --- |
| 一个实验内保留远端状态 | 每 Run 新建一个专属 `/ws` 会话，reset 一次；observe 只消费缓存，act 执行一次 native step | Echo 连续三次工具调用返回各自原始消息 |
| HTTP 与 MCP 接口语义不同 | 不用无状态 HTTP reset/step；不把 Echo 的生产 MCP 客户端当 simulation 客户端 | 记录实际 WS reset/state/step 请求与响应 CAS |
| Echo 的 reward 是 null | 保留 null；不为求分数补零 | length=3、scope_limited=1；原生 truncated=false，return 不列为验收指标 |
| OpenEnv 只有 done，无法推断结束原因 | 外部领域协议的可选 `backend_done/end_cause` 关闭 episode；未知原因不填成 terminated/truncated 分数 | Connect4 七步真实 done，return=1、length=7；原因指标独立重评为 missing |
| 网络超时可能已产生副作用 | unknown receipt、side_effect=possible；保留未确认 operation，禁止重发和重连 | 真实 SDK 接收超时只产生一次 step 请求；真实 WS 断开后不会新开 session |
| 服务由外部所有 | Run 只拥有新 WS session，结束时 `backend_disposition=closed`；host 仍为 attached | 每轮释放 adapter 后原服务器健康检查仍成功 |
| 评价必须独立于服务可用性 | Scorer 读取封存 ResultsView/event snapshot；重评时禁止创建 SDK session | 两种环境均完成原 Run 重评；另在没有 SDK、服务器已停止的独立环境重评通过，全部 Run 记录逐项不变 |

上述差异均可在独立适配包表达，没有修改核心的必要。`backend_done/end_cause`
是外部交互领域协议的可选字段，已有 Gymnasium 的原生 terminated/truncated
及无这些可选字段的消息保持兼容。未消费的实际 transition 通过既有
`EnvironmentSummary.artifact_refs` 保存，不扩展核心摘要字段。

复现入口和安装方法见 [适配包 README](../../adapters/openenv/README.md)。
[机器可读报告](openenv-environment-2026-10-19.json) 记录最终 wheel、固定核心、
原生 Run、评价及重评 ID、测试数量和证据归档 SHA。归档包含原始 CAS/记录数据库、
真实成功和预期失败的轨迹、早期探针、上游及适配器 wheel、完整依赖清单和日志。

本轮验证对象是本机启动的真实上游服务。用户生产 testbed 的 endpoint、认证、
部署身份与权限尚未验证；配置里的远端部署身份明确是调用方声明，不冒充远程证明。
通用 seed 强制保证、已有 WS 会话附着/恢复、认证提供方和 terminal 初始 reset
暂不支持并显式拒绝。本轮 Candidate 使用固定动作序列验收接口，未声明已完成
自主 LLM Agent 的工具选择闭环。
