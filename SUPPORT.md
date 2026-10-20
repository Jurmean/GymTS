# 获取帮助

先从 [README](README.md)和[文档导航](docs/README.md)选择使用路径。
常见问题见 [FAQ](docs/faq.md)；第三方数据/服务接入见[环境指南](docs/environment-adapters.md)，
新项目开发见[适配包指南](adapters/README.md)。

| 问题 | 入口 |
| --- | --- |
| 可复现的错误 | [Bug 报告](https://github.com/Jurmean/GymTS/issues/new?template=bug_report.yml) |
| 功能或公共接口建议 | [功能建议](https://github.com/Jurmean/GymTS/issues/new?template=feature_request.yml) |
| 新数据、任务、模型、工具集或服务接入 | [适配请求](https://github.com/Jurmean/GymTS/issues/new?template=adapter_request.yml) |
| 使用问题或现有文档不清楚 | [普通 Issue](https://github.com/Jurmean/GymTS/issues/new) |
| 疑似安全漏洞或敏感数据泄漏 | [安全策略](SECURITY.md)，不要公开详情 |
| 社区行为问题 | [行为准则](CODE_OF_CONDUCT.md) |

报告问题时请提供准确的 GymTS/适配包版本、Python/操作系统、显式启用的集成、最小配置、执行命令、
预期和实际行为，以及脱敏后的错误码/日志。涉及运行结果时，保留原存储，在公开 Issue 中只附必要的
Run ID、事件片段和制品哈希。Run ID 只是本地记录标识，维护者无法仅凭该 ID 访问你的磁盘。

不要上传整个生产 CAS、参考答案、访问令牌、完整服务连接串或含个人数据的样本。
可先运行 `python3 -B examples/quickstart.py --root /tmp/gymts-support-demo`，确认基础链路是否正常，
再把问题缩小到具体适配器。原生后端的安装、账号和版本问题，必要时同时向相应上游项目报告；
请在两边附上关联链接，避免重复调查。

当前支持方式是仓库内的异步公开协作。本项目没有声明商业支持、工单系统、固定响应时限或可用性保证，
也未确认启用了 GitHub Discussions。请勿将研究验收报告中的本机真实服务验证视为生产部署承诺。
