# Fallback And Terminal Semantics QA Plan

## Scope

验证两个完整拓扑 P1 修复：

1. AgentScope 经 LiteLLM `chat-default-fallback` 调用本机 Ollama。
2. Agent runner 返回 `ERROR` 时，异步任务中心记录失败终态。

## Environment

- Java Compose: `../langchain4j-platform/deploy/docker-compose.yml`
- AgentScope candidate: `http://127.0.0.1:18085`
- LiteLLM: `http://127.0.0.1:4000`
- Ollama: `http://127.0.0.1:11434`
- Central async-task service: `http://127.0.0.1:8086`
- Authentication: 本地生成、短时 HS256 internal JWT；不保存原始 token

## Safety And Cost Boundary

- 只访问 localhost。
- fallback 用已安装的本地 `llama3.1`，不调用付费模型。
- 故障注入使用不存在的逻辑模型名，不访问第三方 provider。
- 不修改生产 `AGENT_URI`、数据库 schema 或 feature flag 默认值。
- 完成后恢复候选服务为 `GATEWAY_MODEL=chat-default`。

## Acceptance Checks

1. Python 完整 CI 等价门禁通过。
2. Java Compose 配置可解析，25/25 服务运行且无 unhealthy/restart。
3. fallback 请求达到中央 `SUCCEEDED` 与业务 `DONE`。
4. 受控坏模型请求达到中央 `FAILED`、空 result 与稳定错误码。
5. 同步兼容行为由自动化测试证明仍返回 `stopReason=ERROR`。
6. 关键健康端点与认证 metrics 端点符合契约。
