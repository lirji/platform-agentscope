# Phase 3 Fallback And Terminal Semantics Review Report

## Decision

本修复切片 merge-ready；评审范围内无未解决 P0/P1/P2。该结论不批准生产切流。

## Reviewed Scope

- `AgentApplicationService` 同步/异步语义分流。
- `/agent/run/async` 路由绑定与 `AsyncTaskManager` 既有异常终态映射。
- 服务、manager 和 API 三层回归测试。
- LiteLLM fallback provider、Ollama endpoint 与回滚文档。
- 完整门禁、真实 fallback、故障注入和运行恢复证据。

## Findings

| Severity | Finding | Resolution |
| --- | --- | --- |
| P1 | LiteLLM native Ollama adapter 无法转换 AgentScope 消息内容 | 改用本机 Ollama OpenAI-compatible `/v1` |
| P1 | 异步 runner `ERROR` 被普通返回路径记录为 `SUCCEEDED` | 新增 async-only application boundary 并复用中央失败映射 |
| None open | 未发现新的正确性、安全或兼容性缺陷 | 完整门禁与黑盒验证通过 |

## Design And Boundary Review

- 异步语义判断位于 application service，不把业务规则放入 FastAPI transport。
- domain 与外部 DTO 未引入 AgentScope、FastAPI 或 LiteLLM 类型。
- 同步 `run()` 未改变；只有 async route 调用 `run_for_async()`。
- 仅处理已确认的 `ERROR`，没有擅自重分类其他 stop reason。
- 失败结果不泄露模型/provider 异常。
- fallback 逻辑名和顺序不变，非敏感 `ollama` 仅为本地 OpenAI client 占位 key。

## Residual Operational Risks

- fallback 模型能力降级仍需按生产用例单独评测。
- 本地单实例成功不能证明多实例、长时容量或告警行为。
- `chat-default` 仍指向云端主模型；当前只恢复运行状态，没有发送主模型语义请求。
