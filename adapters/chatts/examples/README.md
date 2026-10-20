# ChatTS 连接配置

本目录属于独立的 `gymts-chatts` 适配包。主仓库根目录安装 `python3 -m pip install . ./adapters/timeseries ./adapters/chatts` 后运行：

```bash
gymts-chatts \
  --profile-dir /path/to/profiles/native \
  --profile-dir /path/to/profiles/classical \
  --candidate-config adapters/chatts/examples/chatts_http_candidate.json \
  --output /tmp/chatts-model-001
```

`chatts_http_candidate.json` 使用 `timeseries-chatts-http`，接收中立数值 TaskInput，再在模型 codec 内生成原生时序 HTTP dialect。运行前修改服务地址、模型和部署版本；本配置不证明该服务可用或权重已固定。

`deepseek_candidate.json` 使用普通文本 LLM，公开序列完整序列化为 `named_numeric_json/v1` 文本。先通过本地密钥管理设置 `DEEPSEEK_API_KEY`，再以此文件替换上面的 `--candidate-config`，可加 `--no-baseline --max-per-task 1` 进行小规模连接验收。配置仅保存环境变量名。`deepseek-flash-api-alias` 是服务身份，证据记录 `weights_pinned=false`。

输出目录必须是新目录。若从本包解压目录运行，配置路径改为 `examples/chatts_http_candidate.json`。更多数据边界、评价、重评分及保存轨迹说明见主仓库的[接入指南](../../../docs/chatts-integration.md)。

历史 `/1` pipeline 使用 `--legacy`，连接配置相应选 `chatts_http_candidate.legacy.json` 或 `deepseek_candidate.legacy.json`。默认新路径和旧路径的输入协议、Candidate ID 有意分开，不能混用。
