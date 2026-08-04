# 兼容契约

## 1. 原则

迁移阶段优先保持旧客户端可用。兼容对象由本项目定义，不能直接序列化 AgentScope 类型。

## 2. `/agent/run`

请求：

```json
{
  "goal": "查询知识库中的退款规则",
  "webhookUrl": null
}
```

同步响应：

```json
{
  "goal": "查询知识库中的退款规则",
  "steps": [],
  "finalAnswer": "……",
  "stopReason": "DONE",
  "depth": 0,
  "tenantId": "acme"
}
```

Phase 1 已将 AgentScope tool call/result 事件按调用顺序映射为 `steps`，并保留并行工具的
原始调用顺序。`thought` 固定为空字符串，避免暴露隐藏推理。真实模型输出质量、延迟与
成本尚需在旧/新服务双跑环境中验收，因此仍不能宣称生产等价。

## 3. 停止原因

兼容值：

- `DONE`
- `MAX_STEPS`
- `LOOP`
- `TIMEOUT`
- `BUDGET`
- `CANCELLED`
- `ERROR`

AgentScope 的 finished reason 和异常必须在应用层映射，不把框架枚举直接暴露出去。

## 4. 认证

- Header：`X-Internal-Token`
- 算法：HS256 或 RS256
- `sub`：tenantId
- `uid`：userId
- `scopes`：字符串数组
- `dept`：可选部门
- `iss=langchain4j-platform`、`aud=[platform-internal]`：签发域和唯一内部 audience
- JOSE `kid=platform-internal-v1`、`typ=JWT`：当前内部签名 key 标识
- `token_use=internal_access`：拒绝 service callback 或其它用途令牌冒充业务身份
- `jti`、`iat`、`exp`：必需；默认最长 300 秒，只允许有界 clock skew

无效或缺失 token 在认证开启时返回 401。`/health`、`/readiness`、`/info` 不要求业务身份。

调用保留的 Java 领域服务继续沿用经过验证的内部 token，以保持 tenant/user 权威上下文。
MCP、Browser 与 Code 等外部 provider 不接收该 caller token；每次调用改发专用
`X-Agent-Service-Token`，使用独立 key，并绑定 provider audience、tenant、actor、action、
`token_use=agent_downstream`、`jti/iat/exp`。provider 必须校验完整契约，不能把它当平台内部 token。
claims JSON Schema 位于 `contracts/boundaries/downstream-service-token-claims.schema.json`。

## 5. Trace

- 接受 `X-Trace-Id`；缺失时生成。
- 响应回传 `X-Trace-Id`。
- 所有 HTTP/MCP 工具继续传播。
- 接入 OTel 后仍保留该兼容头，直至旧平台完成 W3C Trace Context 统一。

## 6. SSE 与异步契约

已实现以下兼容入口：

- 五类 `POST .../async`：run、dag/run、dag/plan-run、analyst/run、process/run。
- `GET /agent/tasks`、`GET|DELETE /agent/tasks/{taskId}`。
- `GET /agent/tasks/{taskId}/stream`，query `lastEventId` 优先于 header
  `Last-Event-ID`。
- `POST /agent/reflexive/stream`，依次产生 `attempt-start/answer/critique/done`。

任务外部视图固定为十字段，不暴露中央 `kind/webhookUrl/lease*`；同租户的非 Agent kind
也按 404/过滤处理。中央 task-scoped sequence 作为 SSE `id`，lifecycle data 投影为十字段，
`dag-*` progress data 保持 `{taskId,event,data,ts}`。内部 token 仅存在于进程内上下文，
不会进入任务 input/result/event/webhook。用户查询、列表、流和取消按 `tenant + owner user`
授权；同租户其他用户也得到 404。`lease/status/events` 是独立 worker 数据面，只接受
`X-Async-Worker-Token`：HS256 凭据绑定 service、tenant、actor、worker、task 和单一 action，
TTL 最长 120 秒，不能用普通 `X-Internal-Token` 替代。状态与进度写入还必须持有当前未过期
租约。取消与 worker 完成由中央原子终态竞争裁决。

## 7. `/agent/dag/run`

请求继续使用旧字段名：

```json
{
  "goal": "分析订单和退款趋势",
  "tasks": [
    {"id": "schema", "description": "确认表结构", "dependsOn": []},
    {"id": "trend", "description": "查询趋势", "dependsOn": ["schema"]}
  ],
  "webhookUrl": null
}
```

响应保留 `levels`、`taskResults`、`synthesis`、`tenantId`、`attempts` 和
`acceptedByThreshold`。critic/replan 默认开启：每次执行写入一个 attempt，低于阈值时
有限次修订并重跑；关闭 `AGENT_DAG_REPLAN_ENABLED` 后 `attempts=[]` 且
`acceptedByThreshold=true`。任务上限默认 6；空任务、重复 ID 和循环图返回
`400 {"error": "..."}`。为兼容旧实现，未知依赖会从拓扑计算中忽略，但仍在
`dependsOn` 回显。Critic/Replanner 模型或结构失败返回脱敏 502，不把未评审结果标为达标。

对应 async 端点复用相同 service；DAG 进度写入中央持久事件 journal。

## 8. `/agent/dag/plan-run` 与 `/agent/analyst/run`

两个端点接受：

```json
{"goal": "分析上月退款趋势", "webhookUrl": null}
```

并返回相同的 `AgentDagRunReply`。`plan-run` 使用通用拆解规则；`analyst/run` 只规划当前
已迁的 `schema_explore` 和 `analytics_sql`，强调先探表后取数。空计划、无效结构化输出
或可恢复的 Planner 调用失败回退到单任务 `t1`；缺少模型配置仍返回 503。

同步端点仅为兼容接受 `webhookUrl`，不会发送 webhook；async 端点只把 URL 交给中央
任务中心，由中央以至少一次 outbox 语义投递。

## 9. Sibling orchestrators

- `/agent/chain` 接受 `{"input":"..."}`，返回步骤、`finalOutput`、`completed` 和
  `tenantId`。步骤配置仅来自服务端；请求中的额外字段保持旧宽松 DTO 行为但不能改变步骤。
- `/agent/vote` 接受 `question` 和可选 `n`，返回 `votes`、`strategy`、`decision`、
  `agreement`、`confident` 和 `tenantId`。synthesis 的 `agreement` 为 JSON `null`。
- `/agent/reflexive` 接受 `question`，返回 `finalAnswer`、逐轮评分、阈值结果和 `tenantId`。

空文本和非法候选数返回 `400 {"error":"..."}`；纯文本生成失败返回脱敏 502。Reflexion
Critic 失败沿用质量评审脱敏 502。流式 Reflexion 不创建持久任务，断开连接会取消 producer。
流式 answer/critique/done 和任务 lifecycle/progress 的任意嵌套字符串都会遮蔽邮箱、中国手机号与
身份证号。Reflexion 失败事件固定为
`{"error":"agent reflexion failed","code":"AGENT_REFLEXION_STREAM_FAILED"}`；任务代理解析或
上游失败固定为 `AGENT_TASK_STREAM_FAILED`，不得透传 provider/HTTP 异常文本。

## 10. `/agent/process/run` 受治理候选

请求与旧同步入口相同，响应继续使用 `AgentDagRunReply`。默认仍只使用
`workflow_status`、`workflow_tasks` 和 `rag_search`。当 `AGENT_REFUND_START_ENABLED=true` 时，
调用方须先以相同的身份和 `Idempotency-Key` 调用 `POST /agent/tool-confirmations`，提交
`toolName=refund_start` 与精确工具参数。执行请求再通过 `X-Agent-Confirmation-Grants` 携带
返回的一次性短时签名 grant，Planner 才能规划 `refund_start`，并由 Java workflow-service
以该键发起流程。grant 绑定 tenant、user、工具、参数摘要、幂等键和有效期，且在 provider
调用前原子消费；旧 `X-Agent-Confirmed-Tools` 头明确返回 400。

模型参数不能提供确认、幂等键、tenantId 或 userId。候选始终禁止审批、认领、取消认领、
完成审批和删除；`WAITING_APPROVAL` 也不得表述为已批准。异步入口复用相同策略和工具集。

## 10.1 MCP 工具绑定

`contracts/boundaries/mcp-tool-binding.schema.json` 定义运维配置中的远端 server/tool 到本地
Agent 工具的显式绑定。每项必须包含 `serverId`、`remoteName`、`description` 和完整
`ToolMetadata`；本地名以 `mcp_<serverId>_` 开头。运行时只有配置项能成为工具，远端 discovery
不会扩大能力面，`platform.agent.*` 递归工具被禁止。

MCP 模型参数不包含可信 tenant/user/token/trace/confirmation/idempotency 字段。签名身份与 trace
从已验证请求上下文以 HTTP header 传播；幂等键只注入实际 `tools/call` 的 `_meta`，不会污染
`initialize` 握手；确认结果不发送给 provider。协议只支持 Streamable HTTP，结果文本有界，
错误脱敏。

## 10.2 远端 Sandbox 契约

Browser 使用 `POST /v1/browser/actions` 和 `DELETE /v1/browser/sessions/{sessionId}`。请求包含
不透明 `sessionId/operationId`、固定动作、参数和运维 host allowlist；不包含 tenant/user/token。
Code 使用 `POST /v1/code/execute`，请求固定 Java、禁网、临时 workspace，并明确 timeout、输出、
内存、进程上限。对应 JSON Schema 位于 `contracts/boundaries/browser-action-*.schema.json` 与
`code-execution-*.schema.json`。可信身份、trace 和 operation id 只通过 HTTP header 传播。

## 11. `/agent/capabilities`

认证后的 `GET /agent/capabilities` 返回四个旧 interop 可直接消费的
`McpToolDescriptor`：run、run_async、dag.plan_run、dag.plan_run_async。字段名和 input
JSON Schema 保持旧契约，description 标明 AgentScope。该端点是 interop live discovery
全量切换的必需契约。

### 11.1 版本化 registry 与可恢复 session

`GET /agent/capabilities/registry` 返回 `agent-capability-registry.v1`、64 位 SHA-256 revision
和完整能力列表，并设置同值 ETag。它包含旧四项以及 `platform.agent.session.run/get`。
旧 `/agent/capabilities` 仍只投影前四项，保持既有 JSON 不变。

`POST /agent/sessions/{sessionId}/run` 与 `GET /agent/sessions/{sessionId}` 使用
`agent-session-checkpoint.v1`。记录按 tenant/user owner 隔离，只保存 goal 摘要、脱敏步骤、
revision/租约/TTL 和稳定结果；禁止持久化原始 goal、内部 token、grant 或 AgentScope 对象。
副作用恢复要求相同幂等键与新 confirmation grant。

详细运行语义见 [Agent 会话检查点与能力注册](agent-sessions-and-capabilities.md)。

### 11.2 运行版本与评测数据

内部 `agent-trajectory.v1` 通过 `agent-execution-versions.v1` 绑定 prompt、model、toolset 和逐工具
SHA-256；旧 `/agent/run` JSON 不增加字段，只通过响应头公开三个集合级版本。Shadow report v4
绑定 `agent-evaluation-dataset.v1` 内容版本与可选 replay report 摘要。线上反馈只接受
`agent-online-feedback.v1` 的 consented/read-only 最小字段并在导入时脱敏。

详细命令和数据边界见 [运行版本与评测数据闭环](evaluation-versioning.md)。

## 12. 契约资产

当前已提交：

- `contracts/legacy/agent-run-request.schema.json`
- `contracts/legacy/agent-step.schema.json`
- `contracts/legacy/agent-run-reply.schema.json`
- `contracts/legacy/agent-dag-task.schema.json`
- `contracts/legacy/agent-dag-run-request.schema.json`
- `contracts/legacy/agent-dag-run-reply.schema.json`
- `contracts/legacy/agent-plan-run-request.schema.json`
- `contracts/legacy/chain-run-{request,reply}.schema.json`
- `contracts/legacy/vote-{request,reply}.schema.json`
- `contracts/legacy/reflexion-{request,reply}.schema.json`
- `contracts/legacy/agent-async-task.schema.json`
- `contracts/legacy/agent-task-progress.schema.json`
- `contracts/legacy/async-task-stream-event.schema.json`
- `contracts/openapi.json`
- `contracts/boundaries/agent-session-checkpoint.schema.json`
- `contracts/boundaries/agent-execution-versions.schema.json`
- `contracts/boundaries/agent-trajectory.schema.json`
- `contracts/evaluation/evaluation-dataset.schema.json`
- `contracts/evaluation/online-feedback.schema.json`
- `contracts/evaluation/shadow-report.schema.json`
- `contracts/capabilities/agent-capabilities.v1.json`

运行 `uv run python scripts/export_contracts.py --check` 可阻止生成契约与快照漂移。

后续计划：

1. 从旧平台导出 OpenAPI。
2. 增加旧服务 provider contract 和新服务 consumer/compatibility tests。
3. 每次变更比较 OpenAPI breaking changes。
4. 最终将语言中立契约发布为独立版本化制品。
