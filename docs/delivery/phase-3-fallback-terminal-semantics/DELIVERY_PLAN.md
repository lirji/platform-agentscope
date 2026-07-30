# Phase 3 Fallback And Terminal Semantics Delivery Plan

## Requirement

关闭完整拓扑联调发现的两个 P1：

1. `chat-default-fallback` 经 LiteLLM 转发 AgentScope 消息时返回 500。
2. Agent 执行返回业务 `stopReason=ERROR` 时，异步任务中心错误地记录为 `SUCCEEDED`。

修复必须保持同步 `/agent/run` 的既有 HTTP/JSON 语义，不修改生产 `AGENT_URI`。

## Repository Evidence

- LiteLLM 的 `ollama/llama3.1` provider 在处理 AgentScope 消息内容时触发
  `AttributeError: 'str' object has no attribute 'get'`。
- 同一 AgentScope 请求直连 Ollama OpenAI-compatible `/v1` 端点能够成功完成。
- `AgentApplicationService.run()` 将 runner 的 `ERROR` 原样转换为同步响应；该行为属于旧契约。
- `AsyncTaskManager` 只把抛出的异常映射为 `FAILED`，因此普通返回的 `ERROR` 被当作成功结果。

## Feasibility

- Verdict: go
- Constraints:
  - AgentScope 类型仍只存在于 infrastructure adapter。
  - 同步 `/agent/run` 继续返回 200 与 `stopReason=ERROR`。
  - 仅异步 `agent.run` 将执行错误映射为中央任务 `FAILED`。
  - 不扩展到 `TIMEOUT`、`MAX_STEPS` 等未确认语义。
  - 不修改生产路由、密钥或 `AGENT_URI`。
- Risks and mitigations:
  - Ollama 与主模型能力不等价：继续标记为降级兜底，并用真实 AgentScope 工具消息冒烟。
  - 异步异常信息泄露：复用稳定错误码 `ASYNC_TASK_EXECUTION_FAILED`，不写入模型原始异常。
  - 同步契约回归：增加同步与异步分流测试。

## Product Design

- Actors and goals:
  - 调用方通过同步接口仍能读取兼容的 `ERROR` 业务响应。
  - 异步调用方通过中央任务状态可靠识别执行失败。
  - 运维在主 provider 不可用时可通过本地 Ollama fallback 完成代表性请求。
- Scope:
  - Python application service 的异步执行边界与回归测试。
  - LiteLLM 正式 fallback provider 配置与运维说明。
  - 完整拓扑重建、健康检查与真实模型冒烟。
- Out of scope:
  - 生产灰度切流。
  - 所有 stop reason 的重新分类。
  - 主备模型能力等价承诺。

## Acceptance Criteria

| ID | Observable behavior | Priority | Verification |
| --- | --- | --- | --- |
| FT-01 | AgentScope 经 LiteLLM `chat-default-fallback` 执行成功 | P0 | localhost end-to-end smoke |
| FT-02 | 异步 agent 返回 `ERROR` 时中央任务为 `FAILED` | P0 | Python application/manager test |
| FT-03 | 失败任务 `result=null`，错误码为 `ASYNC_TASK_EXECUTION_FAILED` | P0 | Python contract assertion |
| FT-04 | 同步 `/agent/run` 仍保留 `stopReason=ERROR` 响应 | P0 | Python service/API regression |
| FT-05 | 正常异步任务仍为 `SUCCEEDED` | P0 | existing async contract suite |
| FT-06 | 配置、回滚与能力降级说明同步 | P1 | docs review |
| FT-07 | 两仓相关质量门禁与完整拓扑健康检查通过 | P1 | CI-equivalent and black-box checks |

## UI/UX Design

- Applicability: Not applicable.
- Evidence: 只修复服务端任务语义、网关配置与运维文档，不修改用户界面。

## Technical Solution

- Python:
  - 保留 `AgentApplicationService.run()` 的同步兼容行为。
  - 新增只供异步入口调用的 `run_for_async()`；当 reply 的 `stopReason` 为 `ERROR`
    时抛出 application-level exception。
  - `/agent/run/async` 改用 `run_for_async()`，由现有 `AsyncTaskManager` 统一落为
    `FAILED`、空结果和稳定错误码。
- LiteLLM:
  - 将 fallback 从 LiteLLM native Ollama adapter 改为 OpenAI provider，
    `api_base=http://host.docker.internal:11434/v1`。
  - 使用非敏感占位 key `ollama` 满足 OpenAI client 参数要求；Ollama 本地端点忽略该值。
- Compatibility:
  - 外部 DTO、OpenAPI schema、同步状态码均不变。
  - fallback 逻辑模型名与主模型 fallback 顺序不变。

## Implementation Sequence

1. 增加同步兼容和异步失败终态测试，记录红灯。
2. 实现 application service 分流并修改异步路由。
3. 修改 LiteLLM fallback 配置和运维文档。
4. 运行 Python 完整门禁与 Java Compose 配置验证。
5. 重建 LiteLLM/AgentScope 相关运行组件并执行完整拓扑复测。
6. 完成 diff review、QA 报告和交付状态。

## Verification Plan

| AC/Risk | Test level | Command/case | Required evidence |
| --- | --- | --- | --- |
| FT-02/03/04/05 | Python unit/integration | focused + full pytest | terminal status and sync compatibility |
| FT-01 | black-box | AgentScope async request through LiteLLM fallback | central `SUCCEEDED`, business `DONE` |
| FT-06 | docs/config | Compose config and diff review | exact provider path and rollback |
| FT-07 | repository/runtime | Ruff, mypy, pytest, health probes | all pass |

## Documentation And CI Plan

- 更新 LiteLLM gateway guide、QA profile、QA report 与本交付状态。
- Python 新测试由既有 CI 自动执行。
- fallback 依赖本地 Ollama，保留为 localhost 黑盒门禁，不向 CI 引入模型下载和外部费用。

## Rollout And Rollback

1. 先在本地/测试环境重启 LiteLLM，验证 fallback 代表性请求。
2. 部署 AgentScope 修复并验证同步/异步分流。
3. 生产切流仍需独立双跑门禁与审批。
4. 回滚 Python 服务镜像即可恢复旧异步语义；回滚 fallback 时恢复原 provider 配置并重启
   LiteLLM。回滚不会修改任务表 schema。

## Assumptions And Approval

- 本轮只使用已运行的本地 Ollama，不调用付费云模型。
- Status: approved
- Evidence: 用户在收到“修复 fallback provider 与异步 ERROR 终态后重跑整体联调”的建议后
  明确回复“继续”。
