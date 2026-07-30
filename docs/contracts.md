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
- `exp`：必需

无效或缺失 token 在认证开启时返回 401。`/health`、`/readiness`、`/info` 不要求业务身份。

Phase 1 的出站工具沿用经过验证的入口内部 token。后续如必须延长多跳调用窗口，应新增与
`platform-security` 一致的内部 token 签发端口，而不是静默使用 master secret。

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
不会进入任务 input/result/event/webhook。取消与 worker 完成由中央原子终态竞争裁决。

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

## 10. `/agent/process/run` 只读候选

请求与旧同步入口相同，响应继续使用 `AgentDagRunReply`。候选服务仅迁移
`workflow_status`、`workflow_tasks` 和 `rag_search` 查询；不会执行 `refund_start` 或
任何审批/认领/删除操作。要求写操作的目标会返回只读能力边界说明。

该收窄契约不与旧 Process 写能力等价。全量默认切换后，“发起退款”等写诉求会明确停留在
只读能力边界，不会静默回退 Java。
`/agent/process/run/async` 已迁移但仍调用相同只读 Planner/DAG 工具集。

## 11. `/agent/capabilities`

认证后的 `GET /agent/capabilities` 返回四个旧 interop 可直接消费的
`McpToolDescriptor`：run、run_async、dag.plan_run、dag.plan_run_async。字段名和 input
JSON Schema 保持旧契约，description 标明 AgentScope。该端点是 interop live discovery
全量切换的必需契约。

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

运行 `uv run python scripts/export_contracts.py --check` 可阻止生成契约与快照漂移。

后续计划：

1. 从旧平台导出 OpenAPI。
2. 增加旧服务 provider contract 和新服务 consumer/compatibility tests。
3. 每次变更比较 OpenAPI breaking changes。
4. 最终将语言中立契约发布为独立版本化制品。
