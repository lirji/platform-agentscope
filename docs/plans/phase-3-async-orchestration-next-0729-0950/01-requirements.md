# Phase 3 异步编排下一步实施：需求分析

> 视角：requirements-analyst
> 状态：仅规划，等待实施审批
> 事实基线：`docs/delivery/phase-3-async-orchestration/DELIVERY_PLAN.md`、
> `docs/delivery/phase-3-async-orchestration/DELIVERY_STATUS.md` 与 2026-07-29 实际代码。

## 1. 问题与目标

当前 `agentscope-platform` 已有同步 ReAct、DAG、Planner、Analyst、Reflexion 和 Process
只读能力，但没有异步提交、任务查询/取消、任务 SSE 代理及 Reflexion SSE。旧
`langchain4j-platform` 已有这些 HTTP 入口，中央 `async-task-service` 已有任务记录、
租约、状态、取消、生命周期 SSE 和 webhook/outbox。

本阶段的目标不是新建第二套任务中心，而是让 `agentscope-platform` 成为五种 Agent
任务的执行者，让 `async-task-service` 继续作为唯一任务状态、生命周期/进度 SSE 与 webhook
投递权威；进程崩溃后不重放模型调用，由中央 orphan reaper 把无法恢复的任务明确终结。

## 2. 范围

### 2.1 对外 HTTP/SSE

必须新增并保持旧路径：

1. `POST /agent/run/async`
2. `POST /agent/dag/run/async`
3. `POST /agent/dag/plan-run/async`
4. `POST /agent/analyst/run/async`
5. `POST /agent/process/run/async`
6. `GET /agent/tasks`
7. `GET /agent/tasks/{taskId}`
8. `DELETE /agent/tasks/{taskId}`
9. `GET /agent/tasks/{taskId}/stream`
10. `POST /agent/reflexive/stream`

旧端点证据：

- 五个提交端点分别见
  `../langchain4j-platform/agent-service/src/main/java/com/lrj/platform/agent/async/AgentTaskController.java:36`、
  `.../dag/AgentDagController.java:56`、`:71`、
  `.../analyst/DataAnalystController.java:42`、
  `.../process/ProcessController.java:42`。
- 任务查询、取消、SSE 见
  `../langchain4j-platform/agent-service/src/main/java/com/lrj/platform/agent/async/AgentTaskController.java:44-69`。
- Reflexion SSE 见
  `../langchain4j-platform/agent-service/src/main/java/com/lrj/platform/agent/reflexion/ReflexionController.java:56-75`。

### 2.2 中央任务协作

- 创建任务：`POST /async/tasks`。
- 领取/续租：`POST /async/tasks/{taskId}/lease`；同一 `workerId` 再调用即续租。
- 状态回报：`PATCH /async/tasks/{taskId}/status`。
- 查询/列表/取消/SSE：复用中央既有端点。
- 新平台 worker 只执行自己同步创建并成功 lease 的任务，不扫描恢复历史任务。
- 中央 reaper 只处理本阶段五种新 kind，不能误杀 workflow 或旧 `agent.task`。

中央端点证据：
`../langchain4j-platform/async-task-service/src/main/java/com/lrj/platform/asynctask/AsyncTaskController.java:79-211`。

### 2.3 两仓变更

- `agentscope-platform`：兼容 DTO、中央 client、执行管理、租约心跳、取消、五端点、
  任务 SSE 代理、Reflexion SSE、契约/安全/失败映射/双跑/文档。
- `../langchain4j-platform/async-task-service`：按 kind 白名单执行的 orphan reaper；
  同时做满足终态不可变、旧 Agent SSE/webhook 契约所必需的事件日志与定点加固。
- 不切换 edge 生产 `AGENT_URI`，不部署生产。

## 3. 已确认业务规则

### 3.1 状态与权威

- 新 Agent 任务使用 `PENDING → RUNNING → SUCCEEDED|FAILED|CANCELLED`。
- 终态不可变；取消、成功、失败、reaper 竞争时，中央成功提交的第一个终态为准。
- 中央任务记录是查询、取消、生命周期 SSE 和 webhook 的唯一权威。
- lease 会把中央任务置为 `RUNNING`
  （`AsyncTaskStore.withLease`，`.../AsyncTaskStore.java:106-123`）。
- 五个提交端点只有在中央 create 和 lease 均已确认后才返回 202。
- 为兼容旧提交响应，202 返回 create 得到的 10 字段 `PENDING` 快照；随后的 GET 可以已经是
  `RUNNING`。此处是“兼容快照”而非再次写状态。

### 3.2 兼容任务视图

旧 `AgentAsyncTask` 是 10 字段：

`taskId, tenantId, userId, status, input, result, error, createdAt, updatedAt, finishedAt`
（`../langchain4j-platform/agent-service/src/main/java/com/lrj/platform/agent/async/AgentAsyncTask.java:11-20`）。

中央 `AsyncTask` 多出 `kind, webhookUrl, leaseOwnerId, leaseExpiresAt`
（`../langchain4j-platform/platform-protocol/src/main/java/com/lrj/platform/protocol/asynctask/AsyncTask.java:11-24`）。

因此：

- 对外不能直接透传中央 14 字段对象。
- 对外不能暴露 lease owner/expiry。
- `kind` 只用于内部过滤，不注入旧响应 `input`。
- 旧实现会把非空、trim 后的 `webhookUrl` 放进任务 `input`
  （`AgentAsyncTaskService.input`，`.../AgentAsyncTaskService.java:266-272`）。中央存储应把
  webhook 保存在专用字段，兼容映射对当前租户返回时再补入 `input.webhookUrl`。
- `GET /agent/tasks` 只返回五种新 Agent kind；不能返回同租户的 workflow 等通用任务。
- 对同租户但非 Agent kind 的 taskId，GET/DELETE/SSE 也必须返回 404。

### 3.3 kind 与输入

本阶段固定内部 kind：

| 外部端点 | 中央 kind | 中央 `input` |
|---|---|---|
| `/agent/run/async` | `agent.run` | `goal` |
| `/agent/dag/run/async` | `agent.dag` | `goal`, `tasks` |
| `/agent/dag/plan-run/async` | `agent.dag-plan` | `goal` |
| `/agent/analyst/run/async` | `agent.analyst` | `goal` |
| `/agent/process/run/async` | `agent.process` | `goal` |

`webhookUrl` 只进入中央 create 的专用字段，不进入中央 `input`；内部 token、完整
`RunContext`、AgentScope 对象、模型/provider 配置均不得进入中央 input/result/error。

### 3.4 租户和身份

- 除健康探针外，全部新业务入口必须使用有效 `X-Internal-Token`。
- 认证得到的 tenant/user/scopes/department/trace 必须通过不可变 `RunContext` 显式传递。
- 中央调用使用同一请求的原始 token 与 `X-Trace-Id`；不得用客户端提供的 tenantId。
- 跨租户 GET/DELETE/SSE 必须表现为 404，不能泄露 taskId 是否存在。
- 旧行为按 tenant 过滤，不按 user 过滤：
  `AgentAsyncTaskService.listMine/get` 只比较 tenant
  （`.../AgentAsyncTaskService.java:177-190`）。本阶段不擅自收紧成用户级隔离。

### 3.5 token 生命周期

这是基线计划未明确但代码已证明的硬约束：

- Java 内部 JWT 默认 TTL 为 5 分钟
  （`../langchain4j-platform/platform-security/src/main/java/com/lrj/platform/security/InternalSecurityProperties.java:32-33`）。
- Python 当前出站只转发原 token
  （`src/agentscope_platform/infrastructure/http/platform_client.py:190-203`），不能像 Java
  `OutboundTenantForwarder` 一样每跳重新签发
  （`../langchain4j-platform/platform-security/src/main/java/com/lrj/platform/security/OutboundTenantForwarder.java:26-33`）。

批准本计划即批准以下阶段性规则：

- token 只在当前 Python 进程的 work registry 中持有，绝不落中央任务、日志、评测报告或磁盘。
- `RunContext` 必须携带已验签 token 的到期时间。
- worker 的硬截止时间取“配置的任务最大时长”和“token 到期时间减安全余量”的较早者。
- 截止前由仍有效 token 把任务置为稳定失败码，然后取消本地工作；若中央不可达，则由
  orphan reaper 在 lease 过期后终结。
- 剩余 token 时长短到无法完成一次 create/lease/首个 heartbeat 时，提交失败并返回脱敏 503，
  不创建不可控任务。
- 本阶段不让 Python 持有新的签发私钥，不引入 token refresh，不宣称支持超过内部 token
  生命周期的模型任务。

具体默认秒数是部署参数，实施前须与实际 edge `platform.security.jwt-ttl` 联调；计划中的建议值
必须在配置文档标为建议而非现存事实。

### 3.6 取消、租约与幂等

- 每个提交尝试先生成稳定 UUID taskId；同一次 create 在网络结果不确定时只用同一 taskId
  做有限重试/GET 对账。
- 用户重发整个外部 POST 没有旧契约中的幂等键，因此仍可能产生新任务；本阶段不新增外部
  idempotency header。
- heartbeat 只允许同一 taskId/workerId 续租；409、404、401/403 或已确认终态立即停止本地工作。
- heartbeat 的网络/5xx 重试必须有界且只复用同一幂等参数；不得重试业务 4xx。
- DELETE 结果不确定时 GET 对账；若已是 `CANCELLED`，仍向旧 API 返回
  `{"taskId": "...", "cancelled": true}`。
- worker 回报终态后必须采用中央响应作为最终值；不能因本地计算成功就假定中央为
  `SUCCEEDED`。
- shutdown 取消本机任务和 heartbeat，不伪造成功，也不持久化 token；由 lease 超时与 reaper
  明确失败。

### 3.7 Process 只读

- `/agent/process/run/async` 必须调用当前同步 Process 使用的同一个
  `process_planning_service`。
- 现有 `AgentDagPlanningService.plan_and_run` 对 Process 拒绝写 marker，并使用只读 fallback
  （`src/agentscope_platform/application/planning.py:66-108`）。
- 当前 AgentScope runner 只装配 `ReadonlyToolset`
  （`src/agentscope_platform/infrastructure/agentscope/runner.py:181-200`）。
- 本阶段不加入 `refund_start`、审批、认领、完成或任何 workflow 写工具。

### 3.8 webhook

- webhook 只由中央任务中心投递，Python 不建立第二条投递路径。
- 旧 Agent webhook 使用 10 字段载荷与
  `X-Agent-Task-Id`、`X-Agent-Task-Status`、`X-Tenant-Id`
  （`.../AgentTaskWebhookNotifier.java:74-102`、
  `.../AgentTaskWebhookPayload.java:11-33`）。
- 中央当前使用 14 字段载荷与 `X-Async-Task-*`
  （`.../asynctask/AsyncTaskWebhookNotifier.java:59-87`、
  `.../asynctask/AsyncTaskWebhookOutboxDispatcher.java:122-139`）。
- 因而五种新 kind 必须由中央输出旧 Agent 兼容载荷，并同时至少带旧 `X-Agent-Task-*`
  头；通用任务继续使用现有中央契约。
- URL 只接受绝对 http/https、存在 host、无 user-info。DNS rebinding/私网 egress 仍需平台
  allowlist 或网络策略，本阶段不宣称彻底解决 SSRF。
- webhook 是至少一次；消费者必须按 taskId + terminal status 幂等。

### 3.9 SSE

任务 SSE：

- 代理中央 `id` 与 `event`，`data` 转为旧 10 字段任务 JSON。
- 透传 `Last-Event-ID` header；同时兼容中央已有 `lastEventId` query，query 优先级与中央一致
  （`AsyncTaskController.stream`，`.../AsyncTaskController.java:203-210`）。
- 上游分片、CRLF、多行 data、空行分帧必须正确解析。
- 客户端断线必须关闭中央上游流。
- 中央 SSE 历史当前只在进程内保存 64 条，sequence 重启会重置
  （`.../AsyncTaskSseService.java:28-33,82-128`）。这只是现状，不满足最终严格兼容与可靠代理
  方案；实施需增加 task-scoped 持久事件日志，使已保留窗口内的 `Last-Event-ID` 跨中央重启
  可续订。
- 旧 DAG 的 `dag-*` event name 和 `AgentTaskProgress` data 均属于严格兼容范围；中央新增
  append API 时必须校验 tenant/kind/lease owner/event 白名单和 payload 大小。

Reflexion SSE：

- 空问题在已建立的 SSE 中发送 `event: error` 和
  `{"error":"question is required"}` 后结束，与旧 controller 一致
  （`.../ReflexionController.java:56-64`）。
- 每轮顺序严格为 `attempt-start → answer → critique`，最后只发一次 `done`
  （`.../ReflexionService.java:55-83`）。
- `done` data 为完整 `ReflexionReply`。
- 模型/评审错误只发送稳定脱敏错误及 traceId，不返回 provider message。
- 使用有界队列产生背压；客户端断线取消 producer 并等待协程收敛。

旧 task SSE 还可发 `dag-*` 细粒度进度，而中央 SSE 只存状态快照：
`../langchain4j-platform/docs/平台工程/长任务处理指南.md:63-68`。这与交付基线的“直接代理中央
生命周期流”存在范围冲突。requirements 视角按用户明确的“保持旧 SSE 契约”采用严格解释：
最终方案必须吸收候选方案 D 的中央持久进度协议，不能用单机内存假装兼容；这项范围扩大仍
需要在实施审批中明确接受。

## 4. 边界条件与失败映射

| 场景 | 对外/中央预期 |
|---|---|
| 空/blank goal 或 question | 旧兼容 `400 {"error":"... is required"}`；Reflexion stream 为 SSE error |
| 缺失/伪造/过期 token | 401，不访问中央 |
| 中央任务不存在、跨租户、非 Agent kind | agent task API 404 |
| 中央 create 重复 taskId | GET 对账；内容一致才继续，否则 503/冲突审计 |
| 中央 lease 冲突 | 不执行，清理/终结自己创建的孤儿；提交不返回 202 |
| 中央网络/5xx | 脱敏 503；无原始响应体泄漏 |
| 中央 JSON 不合法 | 脱敏 502 |
| 本地业务抛异常 | 中央 `FAILED` + 稳定错误码，不存异常堆栈/provider 文本 |
| 用户取消与成功竞争 | 中央首个终态胜出；迟到成功不得覆盖 CANCELLED |
| heartbeat 409/404 | 停止本地任务，不再写成功 |
| token 临近到期 | 截止前失败并取消；无法回报则等 reaper |
| shutdown/崩溃 | 不续跑；lease 到期后 reaper → FAILED |
| webhook 4xx | 现有中央行为进入 DEAD，不改变任务终态 |
| SSE 上游 404 | 本地先做 kind/租户预检并返回 404 |
| SSE 数据不合法 | 关闭流并记录稳定错误，不透传原始中央 body |

## 5. 非目标

- 不恢复或重放进程崩溃前的模型调用。
- 不持久化内部 JWT、刷新令牌、AgentScope state 或 Python callable。
- 不实现任务级自动业务重试。
- 不把 Process 写能力迁入候选服务。
- 不修改 edge 生产路由，不切换生产 `AGENT_URI`。
- 不为所有通用 kind 启用 orphan reaper。
- 不解决公网 webhook 的 DNS rebinding、签名与全局 egress 治理。
- 不把 Phase 4 的副作用工具治理带入本阶段。

## 6. 歧义、易遗漏点与审批项

### P0：审批必须明确

1. **任务 SSE 的“旧契约”范围**：交付基线选择中央生命周期代理，但旧 Java 还会发
   `dag-*` 进度。需求分析识别出该冲突；`FINAL_PLAN.md` 已按严格兼容选择 A+D，实施审批
   必须明确接受新增中央事件表/API 的成本。
2. **5 分钟 token 上限**：默认选择“凭据到期前明确失败”，不签发/刷新 token。若业务要求
   超 5 分钟，当前方案不能批准，必须先设计委派身份。
3. **Webhook 兼容**：代码已证明中央现状与旧 Agent headers/payload 不一致，必须批准中央
   的按 kind 兼容映射；否则不能声称保持旧 webhook 契约。
4. **Reaper 白名单**：只包含五个新 kind，不能默认包含 `workflow.*` 或旧 `agent.task`。

### P1：实施前验证

- 运行中的旧服务/OpenAPI 是否对缺 body、非法 JSON、额外字段返回与源码/当前快照一致。
- edge 实际部署的 `platform.security.jwt-ttl` 是否仍为默认 5 分钟。
- 当前生产 webhook 消费者是否严格拒绝额外 JSON 字段（兼容映射仍按严格旧载荷实现）。
- 实际 async-task 部署是 JDBC；Helm 当前默认仍是 in-memory
  （`../langchain4j-platform/deploy/helm/platform/values.yaml:185-194`）。
- MySQL 版本与运行期 `ALTER TABLE ADD INDEX` 的锁/在线 DDL行为。

## 7. 验收标准

| ID | 可观察验收 |
|---|---|
| R-01 | 五个 async POST 对合法请求返回 202 和旧 10 字段任务快照；空值错误形状兼容 |
| R-02 | create/lease/status/heartbeat 传播 token 与 trace；中央 input/result/log 无 token |
| R-03 | 仅成功 create+lease 的任务执行；每个 taskId 同进程最多一个 work coroutine |
| R-04 | 取消/成功/失败/reaper 竞态后只有一个不可变终态 |
| R-05 | heartbeat 续租；409/404/终态/token deadline 会停止本地执行 |
| R-06 | `/agent/tasks` 只展示五种 kind；跨租户或非 Agent kind 的 GET/DELETE/SSE 为 404 |
| R-07 | task SSE 保留 lifecycle 与旧 `dag-*` event、兼容 data、task-scoped id、跨中央重启续订，并在断线时关闭上游 |
| R-08 | Reflexion SSE 精确按阶段排序，done 一次，错误脱敏，断线取消 |
| R-09 | 中央对五种 kind 使用旧 Agent webhook headers 与 10 字段载荷，且只有中央投递 |
| R-10 | Process async 沿用现有只读服务，所有评测无写工具 |
| R-11 | reaper 仅扫描 allowlist；stale PENDING/expired RUNNING → FAILED 并发事件/webhook |
| R-12 | reaper 多副本竞争、worker 心跳、用户取消之间无双终态或重复终态事件 |
| R-13 | Python 契约/安全/client/manager/SSE/双跑测试及 Java controller/store/reaper/webhook 测试通过 |
| R-14 | 两仓静态检查、构建、测试、契约快照、Compose/Helm 配置验证通过 |
| R-15 | 在不切生产流量前完成测试租户灰度、监控看板核对和一次回滚演练 |
