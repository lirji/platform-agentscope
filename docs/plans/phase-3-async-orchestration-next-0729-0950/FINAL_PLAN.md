# Phase 3 异步编排下一步实施总计划

> 状态：**已批准并完成候选实现；生产切流门禁尚未审批**
> 依据：`docs/delivery/phase-3-async-orchestration/DELIVERY_PLAN.md`、
> `docs/delivery/phase-3-async-orchestration/DELIVERY_STATUS.md` 及两仓实际代码
> 最终架构：方案 A 的进程内执行骨架 + 方案 D 的中央持久化事件日志
> 适用仓库：`agentscope-platform` 与同级 `langchain4j-platform`

## 1. 背景

`agentscope-platform` 已实现同步 ReAct、DAG/Planner/Analyst、Reflexion 和只读 Process，
但没有异步提交、任务管理或 SSE 入口。旧 `agent-service` 已公开五个 async 提交端点、
任务 GET/list/cancel/SSE 和 Reflexion SSE；中央 `async-task-service` 已有通用任务模型、
tenant scoped CRUD、租约、生命周期 SSE、JDBC store 及 webhook/outbox。

批准后的工作是把异步执行迁到 Python，而不是复制 Java 领域服务：Python 继续调用现有
同步应用 service；中央服务成为唯一任务权威和唯一 webhook 投递方。内部 JWT 仅随当前
进程内的执行上下文存在，崩溃后不重放模型调用，中央 orphan reaper 将遗留任务明确失败。

## 2. 目标

1. 在 `agentscope-platform` 实现并保持旧路径：
   - `POST /agent/run/async`
   - `POST /agent/dag/run/async`
   - `POST /agent/dag/plan-run/async`
   - `POST /agent/analyst/run/async`
   - `POST /agent/process/run/async`
   - `GET /agent/tasks`
   - `GET /agent/tasks/{taskId}`
   - `DELETE /agent/tasks/{taskId}`
   - `GET /agent/tasks/{taskId}/stream`
   - `POST /agent/reflexive/stream`
2. 由一个中央 async-task client 统一完成 create/get/list/lease/update/cancel/event/SSE。
3. 由进程内 manager 管理执行、并发、取消、租约心跳、token 截止与 shutdown。
4. 任务 JSON 保持旧 `AgentAsyncTask` 十字段；状态终态不可逆。
5. 任务 SSE 由 Python 代理中央流，并保持旧 lifecycle 与 DAG 细粒度事件。
6. Reflexion SSE 保持 `attempt-start/answer/critique/done`。
7. 在 `async-task-service` 增加 allowlist orphan reaper 和可靠事件回放。
8. 保持租户隔离、token 不持久化、Process 只读、错误脱敏、中央 webhook 单投递。
9. 补齐契约、安全、失败映射、竞态、双跑、迁移和回滚验证。

## 3. 非目标

- 不把 AgentScope 类型或状态对象带入 domain/application/API DTO。
- 不持久化、加密保存或刷新调用者内部 JWT。
- 不在进程重启后恢复或重放模型执行。
- 不迁移 knowledge/workflow/analytics/order 领域逻辑。
- 不开放 Process 发起、审批、认领、退款等写能力。
- 不把中央通用 workflow/旧 `agent.task` 纳入 Agent orphan reaper。
- 不新增 Python 本地任务数据库，不形成双权威。
- 不在本次直接切换生产 `AGENT_URI`，也不执行生产部署。
- 不承诺外部 POST 的 exactly-once；调用者没有 idempotency key 时，重发仍是新任务。

## 4. 已确认业务规则

### 4.1 权威与状态

- `async-task-service` 是任务快照、事件和 webhook 的唯一权威。
- 合法主流程为 `PENDING → RUNNING → SUCCEEDED|FAILED|CANCELLED`。
- 终态不可变。cancel、worker 完成、reaper 同时竞争时，由中央原子条件更新决定唯一终态。
- 严格主流程只对五种新 Agent kind 强制；workflow 等现有 producer 的
  `PENDING → SUCCEEDED` 必须继续兼容。所有 kind 共同遵守终态不可变。
- 正常返回业务 DTO 即 `SUCCEEDED`；抛异常才 `FAILED`。现有 service 返回的
  `stopReason=ERROR/CANCELLED` 是否要改变该规则，须由双跑 fixture 验证；默认保持旧
  `AgentAsyncTaskService` 的“callable 正常返回即成功”语义。

### 4.2 提交与执行

- API 只有在中央 create 和 lease 都成功后才返回 `202`。
- 为兼容旧响应，`202` 返回 create 时的 `PENDING` 十字段快照；紧随其后的 GET 可为
  `RUNNING`。
- 五种中央 kind 固定为：
  `agent.run`、`agent.dag`、`agent.dag-plan`、`agent.analyst`、`agent.process`。
- taskId 由 Python 先生成 UUID；create 网络歧义时使用同一 ID 查询对账。
- workerId 在进程生命周期稳定，不能每次 heartbeat 变化。

### 4.3 租户与 kind 隔离

- 所有业务端点要求有效 `X-Internal-Token`；健康探针除外。
- 中央继续做 tenant scope；Python 再做五 kind 白名单。
- `/agent/tasks` 过滤非上述 kind；GET/DELETE/SSE 对同租户但非 Agent kind 也返回 404。
- 旧服务是 tenant 级而非 user 级查询；本期不擅自改为 user 级。
- tenant/user/scopes/department/trace 通过 `RunContext` 显式传播，不使用全局业务变量。

### 4.4 token 生命周期

- token 只存在于请求对象、`RunContext` 和进程内 execution handle，禁止进入中央
  input/result/error/event/outbox 或日志。
- `InternalJwtVerifier` 必须保留验证出的 `exp`，但不改变现有 `verify()` 调用者契约：
  推荐增加 `verify_with_expiry()`，由依赖层构造带 deadline 的 `RunContext`。
- 任务硬截止为：
  `min(异步最大运行时长, token.exp - 安全余量)`。
- create 前若剩余 token 时间不足以完成 create+lease+最小 heartbeat 窗口，返回脱敏
  `503` 且不建任务。
- 接近截止时先尝试中央 `FAILED`，再取消本地 work；写回失败由 reaper 兜底。
- 本期明确不支持运行时间超过原 token 有效期的任务。

### 4.5 取消与 shutdown

- DELETE 先请求中央 cancel，成功后设置 stop flag 并取消本地 work。
- DELETE 响应丢失时 GET 对账；仅中央已 `CANCELLED` 才返回旧
  `{"taskId": "...", "cancelled": true}`。
- 现有 `AgentScopeRunner.run()` 会吞 `CancelledError` 并返回 CANCELLED execution，
  manager 必须独立检查 stop flag/中央状态，阻止迟到成功。
- 进程 shutdown 取消本地 work/heartbeat，不伪造成功；无法写回的任务交 reaper。

### 4.6 SSE 与 webhook

- 任务 SSE 连接前先 GET，确保错误发生在 `StreamingResponse` 建立之前并可返回 404。
- 保持中央当前参数优先级：非空 query `lastEventId` 优先于 `Last-Event-ID` header。
- Python 按 SSE frame 增量解析，不把 HTTP chunk 当 frame；支持 CRLF、多行 data 和任意
  UTF-8/chunk 边界。
- status 事件 data 从中央十四字段投影为旧十字段；DAG progress data 保持旧
  `{taskId,event,data,ts}`。
- Reflexion SSE 不创建持久任务；客户端断开即取消 producer。
- webhookUrl 仅随中央 create 发送；Python 不投 webhook。
- 五种 Agent kind 的中央 webhook 使用旧十字段 payload，同时发
  `X-Agent-Task-Id`、`X-Agent-Task-Status`、`X-Tenant-Id`；可并存中央
  `X-Async-Task-*` header。
- webhook URL 仅允许 http/https、有 host、无 user-info；DNS rebinding 仍是残余风险，
  生产需 egress/allowlist。

### 4.7 Process

- async Process 必须调用现有 `AgentDagPlanningService.plan_and_run(..., DagPlanKind.PROCESS)`。
- 保持 `application/planning.py` 的写 marker 拒绝与只读 fallback。
- Runner 继续只装配 `ReadonlyToolset`；不得引入 workflow 写工具。

## 5. 当前代码与调用链结论

### 5.1 Python

- `api/app.py:create_app()` 组装同步 service，`Container` 尚无 manager/client，且没有 lifespan。
- `api/dependencies.py:get_run_context()` 验 token 并建 `RunContext`。
- `infrastructure/security/internal_jwt.py:InternalJwtVerifier.verify()` 已校验 `exp`，但返回时丢弃。
- `api/routes.py` 已有五类同步入口和 `/agent/reflexive`，无 async/task/SSE。
- `AgentDagApplicationService.run/_execute/_run_level/_run_one` 是 DAG 执行主链。
- `AgentDagPlanningService.plan_and_run` 是 plan/analyst/process 复用入口。
- `ReflexionService.run` 有完整循环但无 progress sink。
- `PlatformClient._request` 每次创建临时 client，且不能承载长 SSE；只能复用其 header/
  脱敏思想，不能直接作为 task client。
- `AgentScopeRunner.run` 的取消返回行为已被 `tests/test_runner.py` 固定。

### 5.2 旧 agent-service

- 路径和行为来源分别为 `AgentTaskController`、`AgentDagController`、
  `DataAnalystController`、`ProcessController`、`ReflexionController`。
- `AgentAsyncTask` 是十字段外部任务视图。
- `AgentTaskSseService` 的 lifecycle event data 是十字段任务；progress data 是
  `AgentTaskProgress`。
- `AgentDagService` 实际发布 `dag-planned/dag-levels/dag-worker-*/dag-synthesis-*`
  等事件；因此仅代理中央生命周期事件不足以满足“旧 SSE 契约”的严格解释。

### 5.3 async-task-service

- `AsyncTaskController` 已有 create/list/get/updateStatus/lease/cancel/stream。
- `AsyncTaskStore.update()` 的内存实现按 key 原子。
- `JdbcAsyncTaskStore.update()` 当前是事务内普通 SELECT + UPDATE，无 row lock/CAS；
  cancel 与完成可能互相覆盖。
- `JdbcAsyncTaskStore.lease()` 使用条件 UPDATE，租约竞争相对安全。
- `AsyncTaskSseService` 历史仅在内存，容量 64；全局 `AtomicLong` 在重启后归零。
- JDBC terminal 与 Kafka lifecycle outbox 可同事务，但 HTTP webhook outbox 由
  `AsyncTaskWebhookOutboxEnqueuer.onTaskEvent()` 在提交后入队，存在崩溃窗口。
- workflow producer 可直接把 PENDING 更新为 SUCCEEDED；因此不能全局强制
  PENDING 必须先 RUNNING，也不能让 reaper 扫描所有 kind。
- 默认 application/Compose 使用 JDBC；Helm values 当前默认 in-memory，生产灰度前必须
  显式校验/改为 JDBC。

## 6. 候选方案裁决

| 方案 | 核心 | 加权分 | 裁决 |
|---|---|---:|---|
| A | 进程内执行 + 中央状态 | 3.80 | 采用执行骨架；单独使用会缺旧 DAG progress |
| B | 中央拉取 + 可恢复 worker | 2.20 | 不采用；缺安全委托身份且有双执行 |
| C | Python 本地账本 + 中央镜像 | 1.60 | 不采用；双权威且不能解决 token 恢复 |
| D | 中央持久事件 + 进程内执行 | 3.35 | 吸收事件日志、幂等 append 与可靠回放 |

统一评分细节见 `comparison.md`。最终选择不是按总分机械取 A：旧代码证据证明 DAG 有
细粒度 SSE，因此选择 A+D 的组合。

## 7. 最终架构

```text
Client
  │ X-Internal-Token / X-Trace-Id
  ▼
FastAPI async routes
  │ validate + build RunContext(deadline)
  ▼
AsyncTaskManager ── registry / semaphore / stop flag
  │
  ├─ AsyncTaskGateway ─HTTP/SSE─> async-task-service
  │     create → lease → heartbeat → append progress → terminal
  │                                └→ JDBC task + event journal + outbox
  │
  └─ existing application services
        ReAct / DAG / planning / analyst / read-only process

Task GET/list/cancel/SSE ──> central authority
Reflexion SSE ──> bounded in-process queue ──> existing ReflexionService
OrphanReaper ──CAS only allowed kinds─> FAILED + event + audit + webhook outbox
```

### 7.1 Python manager

拟新增 `AsyncTaskManager`：

- `submit(kind, input, context, execute)`：create、lease、注册并启动执行，返回 create snapshot。
- `_run(handle, execute)`：在 semaphore 内调用现有 service，提交唯一终态。
- `_heartbeat(handle)`：立即启动、周期续租、检查中央取消/owner 冲突。
- `cancel(task_id, context)`：中央 cancel + 本地 stop/cancel + 歧义对账。
- `shutdown()`：停止接收、取消并 await 全部后台 task，清空含 token 的 handle。
- `_complete_once(...)`：以 per-task lock 防止本地重复 terminal 请求。

`ExecutionHandle` 为 application 内部 dataclass，只存内存，不序列化。

### 7.2 中央事件日志

拟增加 event append API 与持久日志。每个任务事件包含：

- `taskId`
- task-scoped `sequence`（作为 SSE `id`）
- `eventKey`（task 内唯一，供 producer 重试去重）
- `event`
- `data`
- `createdAt`
- `workerId`（系统 lifecycle 可空）

progress append 必须验证 tenant、Agent kind、非终态、worker 是未过期 lease owner、
event name 白名单和 payload 大小。生命周期事件由中央内部生成，不能由 worker 冒充。

JDBC 用 `SELECT ASYNC_TASK ... FOR UPDATE` 锁定已存在的 task row，再计算该 task 的下一
sequence 并插入事件，避免空集合 `MAX+1` 竞争。状态变更与对应 lifecycle event 必须在同一
事务。SSE 以数据库水位完成历史回放，再接 live subscriber，并二次追平水位以消除切换空窗。

首次 lease 的 `PENDING → RUNNING` 生成一条 RUNNING lifecycle event；同一 owner 的后续
heartbeat 只更新 lease expiry，不生成重复 RUNNING 事件。store mutation 结果必须显式区分
“记录已更新”和“对外状态已变化”，避免心跳造成事件表与 SSE 写放大。

内存 store 实现相同语义，但只用于开发/测试；生产门禁要求 JDBC。

### 7.3 orphan reaper

拟新增 `AsyncTaskOrphanReaper.reap()`：

- 默认 disabled。
- allowlist 只含五个新 kind。
- stale PENDING：`createdAt < now - pendingTimeout`。
- stale RUNNING：`leaseExpiresAt < now - grace`。
- 每周期 batch 处理。
- store 原子条件更新为 `FAILED`，固定稳定错误码/文案；只对真正更新获胜者发布
  lifecycle event、audit 和 webhook。
- 多副本可同时扫描，不依赖单实例 leader。
- scheduler 线程没有请求期 `TenantContext`。对每个实际获胜任务，reaper 必须用记录中的
  tenant/user 构造显式上下文，在 try/finally 中绑定、发布事件/审计后恢复或清理；不得让
  audit/webhook executor 捕获 `anonymous`，也不得把上一任务上下文串到下一任务。

旧 `agent.task` 没有 heartbeat，workflow 也不遵循统一 lease 状态机，二者永久排除。

### 7.4 webhook 事务边界

JDBC 模式下将 HTTP webhook outbox enqueue 移入 `JdbcAsyncTaskStore` 的非终态→终态事务；
`AsyncTaskWebhookOutboxEnqueuer` 不再为 JDBC 重复入队。Kafka lifecycle outbox 保持现有
同事务机制。内存模式仍使用事件监听 notifier，但不得用于生产。

五种 Agent kind 使用兼容 payload factory；其他 kind 保持现有中央十四字段，避免改变
workflow 消费者。现有 outbox 已以 `OUTBOX_ID=taskId` 主键实现每任务单行幂等，实施时保留
该事实并测试 `ON DUPLICATE KEY` 不会让迟到/重复通知重置已投递记录；无需再添加第二个唯一键。

## 8. 精确修改清单

以下“新增/拟新增”名称是实施约定，不声称当前已存在。

### 8.1 agentscope-platform

| 文件 | 类/方法 | 修改 |
|---|---|---|
| `src/agentscope_platform/domain/async_task.py`（新增） | `AsyncTaskStatus`、`CentralAsyncTask`、`LegacyAgentAsyncTask`、`AsyncTaskEventAppend` | 建中央十四字段、旧十字段、状态与事件 DTO；提供纯映射函数 |
| `src/agentscope_platform/domain/agent.py` | `RunContext` | 增加可空 `token_expires_at`/deadline；保持不可变与显式上下文 |
| `src/agentscope_platform/application/ports.py` | `AsyncTaskGateway`、`ProgressSink`（新增 protocol） | 定义 create/get/list/lease/update/cancel/append_event/stream/close |
| `src/agentscope_platform/application/async_task.py`（新增） | `AsyncTaskManager.submit/_run/_heartbeat/cancel/shutdown/_complete_once`、`ExecutionHandle` | 实现状态机、registry、semaphore、stop flag、token 截止、失败映射 |
| `src/agentscope_platform/application/dag.py` | `AgentDagApplicationService.run/_execute/_run_level/_run_one/_critique/_revise` | 增加默认 `None` 的 progress sink；按旧事件名和 payload 发进度，不改变无 sink 的同步路径 |
| `src/agentscope_platform/application/planning.py` | `AgentDagPlanningService.plan_and_run` | 透传 progress sink；plan/replan 事件与旧 `AgentDagService` fixture 对齐；Process 规则不变 |
| `src/agentscope_platform/application/sibling.py` | `ReflexionService.run` | 增加默认 `None` 的 progress sink；每轮发四类旧事件 |
| `src/agentscope_platform/infrastructure/security/internal_jwt.py` | `InternalJwtVerifier.verify_with_expiry`（新增），`verify`（保留） | 一次验签返回 identity+exp；旧 `verify` 保持现有返回类型 |
| `src/agentscope_platform/infrastructure/http/async_task_client.py`（新增） | `HttpAsyncTaskClient` 及 REST/SSE 方法 | 共享 AsyncClient、稳定 header/timeout、歧义对账、增量 SSE parser、关闭上游 |
| `src/agentscope_platform/infrastructure/observability/async_task_metrics.py`（新增） | `AsyncTaskMetrics` | 定义无 taskId/prompt 标签的计数、时延与 gauge |
| `src/agentscope_platform/infrastructure/observability/setup.py` | `configure_tracing` 及新增 metrics 组装 | 复用现有 OTel SDK/OTLP 依赖；若部署端未收 metrics，保留 no-op 注入 |
| `src/agentscope_platform/api/dependencies.py` | `get_run_context` | 使用 expiry 构造 deadline；仍由当前 request 明确取 token/trace |
| `src/agentscope_platform/api/routes.py` | 五个 async handler、`list/get/cancel/stream_task`、`stream_reflexion` | 复用同步 DTO/service，返回旧 JSON/状态；stream 使用 `StreamingResponse` |
| `src/agentscope_platform/api/app.py` | `Container`、`create_app`、lifespan、异常 handler | 组装/inject client+manager；启动/关闭资源；增加稳定 async-task 错误映射 |
| `src/agentscope_platform/core/config.py` | `Settings` | 增加并校验 async 配置，约束 heartbeat < lease、安全余量与并发 |
| `.env.example` | 新环境变量示例 | 只放非敏感默认值 |
| `compose.yml` | service env/dependency | 配中央 URL 与开关；不放生产地址/密钥 |
| `scripts/export_contracts.py` | `main` 中 schema 列表 | 导出旧任务、中央 client/event 与 SSE payload schema |
| `contracts/openapi.json`、`contracts/legacy/agent-async-task.schema.json`、`contracts/legacy/agent-task-progress.schema.json`、`contracts/legacy/async-task-stream-event.schema.json` | 生成物/新增 schema | 由 exporter 更新，不手改语义 |
| `src/agentscope_platform/evaluation/async_shadow.py`（新增） | submit/poll/SSE/cancel runner | 支持旧/新异步双跑和脱敏报告 |
| `src/agentscope_platform/evaluation/cli.py` | async suite 注册 | 复用 target allowlist，禁止误打生产 |
| `eval/baseline/async-orchestration-cases.jsonl`（新增） | 双跑 case | 覆盖五类、取消、SSE、Process 只读 |
| `tests/test_async_task_domain.py`（新增） | 映射测试 | 十/十四字段、kind 与 token 负向 |
| `tests/test_async_task_client.py`（新增） | client 测试 | REST、timeout、失败、重试、SSE parser |
| `tests/test_async_task_manager.py`（新增） | manager 测试 | 状态机、心跳、截止、取消、shutdown、竞态 |
| `tests/test_api_async_tasks.py`（新增） | API 测试 | 五 submit + GET/list/DELETE |
| `tests/test_sse_proxy.py`（新增） | SSE 测试 | status/progress 映射、重连、断开 |
| `tests/test_api.py`、`tests/test_dag_service.py`、`tests/test_planning_service.py`、`tests/test_sibling_services.py`、`tests/test_runner.py` | 现有回归 | 同步零回归、progress optional、Process 只读、取消吞异常 |
| `docs/contracts.md`、`docs/migration-plan.md`、`docs/testing-and-gates.md`、`README.md` | 现有文档 | 同步契约、门禁与迁移状态 |
| `docs/async-orchestration.md`（新增） | runbook | 配置、监控、灰度、回滚与故障处理 |

### 8.2 langchain4j-platform / async-task-service

根路径均为 `../langchain4j-platform/async-task-service/`。

| 文件 | 类/方法 | 修改 |
|---|---|---|
| `src/main/java/com/lrj/platform/asynctask/AsyncTaskStreamEvent.java`（新增） | record | 中央事件响应/持久化模型 |
| `.../AsyncTaskEventAppendRequest.java`（新增） | record | append 请求 DTO 与字段校验输入 |
| `.../AsyncTaskEventJournal.java`（新增） | append/eventsAfter/latest/cleanup | 事件日志端口，task-scoped sequence/eventKey 幂等 |
| `.../InMemoryAsyncTaskEventJournal.java`（新增） | 接口实现 | 开发/测试用有界内存 journal |
| `.../JdbcAsyncTaskEventJournal.java`（新增） | init/append/eventsAfter/cleanup | `ASYNC_TASK_EVENT` DDL/JDBC 实现；参与 async-task 事务 |
| `.../AsyncTaskStore.java` | `put/update/lease`；新增 `transition/failOrphans/findOrphans` | 保留内存语义，加入条件终态与 reaper API |
| `.../JdbcAsyncTaskStore.java` | `init/update/lease/cleanup`；覆写新增方法 | 加索引；用 row lock/CAS 保证终态；状态+事件+outbox 同事务 |
| `.../AsyncTaskController.java` | `create/updateStatus/lease/cancel/stream`；新增 `appendEvent` | 改用原子 store 结果；只对真实状态变化发审计/live event；暴露 append API |
| `.../AsyncTaskEvent.java` | record | 携带已持久化的 stream event，避免 SSE 层重新分配 id |
| `.../AsyncTaskSseService.java` | `subscribe/onTaskEvent/eventsAfter/send` | DB 回放 + live 水位衔接；发送通用 event name/data |
| `.../AsyncTaskOrphanProperties.java`（新增） | properties | `app.async-task.orphan.*` 绑定与 allowlist 校验 |
| `.../AsyncTaskOrphanReaper.java`（新增） | `reap` | 批量扫描、CAS 失败、逐任务绑定并清理 tenant/audit 上下文、事件/通知 |
| `.../AsyncTaskMetrics.java`（新增） | Micrometer counters/timers/gauges | reaper、CAS、event、SSE、outbox 指标；禁止 taskId 高基数 tag |
| `.../AsyncTaskWebConfig.java` | properties beans | 注册 orphan/event/webhook compatibility 配置 |
| `.../AsyncTaskWebhookPayloadFactory.java`（新增） | `payload/headers` | 五 Agent kind 映射旧十字段与 alias headers，其它 kind 保持现状 |
| `.../AsyncTaskWebhookNotifier.java` | `onTaskEvent/deliver/headers/webhookUri` | 内存模式兼容 payload；拒绝 URI user-info |
| `.../AsyncTaskWebhookOutbox.java` | `init/enqueue/payload` | terminal 唯一约束、使用 payload factory；支持同事务调用 |
| `.../AsyncTaskWebhookOutboxEnqueuer.java` | `onTaskEvent` | JDBC 事务入队后禁用重复监听入队；是否保留类由现有条件装配测试决定 |
| `.../AsyncTaskWebhookOutboxDispatcher.java` | `send/headers` | 发兼容 header；保持现有 retry/dead 语义 |
| `src/main/resources/application.yml` | `app.async-task.orphan/event` | 默认 orphan disabled，配置 timeout/grace/batch/retention/payload limit |
| `src/test/java/com/lrj/platform/asynctask/AsyncTaskControllerTest.java` | API/竞态 | append、kind/tenant/lease、终态 |
| `.../JdbcAsyncTaskStoreTest.java` | JDBC 事务 | cancel/complete/reaper CAS、事件/outbox 原子 |
| `.../AsyncTaskSseServiceTest.java` | SSE | 持久回放、live 衔接、重启 |
| `.../AsyncTaskOrphanReaperTest.java`（新增） | reaper | allowlist、grace、batch、多实例 |
| `.../AsyncTaskEventJournalTest.java`（新增） | event | 幂等、sequence、retention |
| `.../AsyncTaskWebhookNotifierTest.java`、`.../AsyncTaskWebhookOutboxTest.java` | webhook | 十字段、双 header、URL、唯一入队 |

### 8.3 sibling 仓部署/文档

实施时按实际文件存在性修改：

- `../langchain4j-platform/deploy/docker-compose.yml`：JDBC/reaper/event 参数。
- `../langchain4j-platform/deploy/helm/platform/values.yaml`：把承载新 Agent 流量的中央
  服务明确设为 JDBC。
- `../langchain4j-platform/README.md` 及 async-task 文档：append API、事件保留、reaper、
  webhook 兼容、监控/回滚。
- 不修改 `agent-service` 业务实现；它只作为契约与双跑基线。

## 9. 数据库、接口、配置与消息变更

### 9.1 数据库

现有 `ASYNC_TASK` 不新增业务列，新增索引：

```sql
INDEX IDX_ASYNC_TASK_STATUS_CREATED (STATUS, CREATED_AT)
```

拟新增表：

```sql
CREATE TABLE ASYNC_TASK_EVENT (
  TASK_ID VARCHAR(128) NOT NULL,
  SEQUENCE BIGINT NOT NULL,
  EVENT_KEY VARCHAR(128) NOT NULL,
  EVENT_NAME VARCHAR(128) NOT NULL,
  DATA_JSON MEDIUMTEXT,
  CREATED_AT BIGINT NOT NULL,
  WORKER_ID VARCHAR(128),
  PRIMARY KEY (TASK_ID, SEQUENCE),
  UNIQUE KEY UK_ASYNC_TASK_EVENT_KEY (TASK_ID, EVENT_KEY),
  INDEX IDX_ASYNC_TASK_EVENT_CREATED (CREATED_AT)
);
```

不回填旧历史；升级时为已有任务在首次订阅时合成当前 status snapshot。事件 retention 不得
早于任务 TTL；cleanup 先删事件后删终态 task，或使用显式顺序避免孤立数据。当前 schema
由 Java `init()` 字面量演进，不假设项目存在 Flyway/Liquibase。

HTTP webhook outbox 当前以 taskId 作为 `OUTBOX_ID` 主键，已经提供每任务单行幂等；
不新增 `(TASK_ID, TASK_STATUS)` 唯一键。实施需验证事务内 enqueue 与重复 terminal 回调
不会把 `DELIVERED/DEAD` 意外重置为 `PENDING`。

### 9.2 中央接口

保留现有 `/async/tasks/**`，新增：

```http
POST /async/tasks/{taskId}/events
{
  "eventKey": "worker-id:logical-step-id",
  "event": "dag-worker-start",
  "data": { "...": "旧 AgentTaskProgress data" },
  "workerId": "stable-worker-id"
}
```

成功返回带 `taskId/sequence/eventKey/event/data/createdAt/workerId` 的事件；同 eventKey
重复请求返回原事件。错误：

- 400：字段/event name/payload 非法；
- 404：跨 tenant、不存在或非允许 kind；
- 409：终态、租约 owner 不符或租约过期；
- 413：payload 超限（若 Spring 全局先拦截，最终错误体需契约测试固定）。

现有中央 SSE 的 event id 改为 task-scoped sequence；event name/data 支持 lifecycle 与
progress。query/header 优先级保持当前行为。

### 9.3 Python 外部接口

- 五 submit 返回旧十字段：
  `taskId, tenantId, userId, status, input, result, error, createdAt, updatedAt, finishedAt`。
- GET/list 同一 schema。
- DELETE 保持旧 `{taskId,cancelled:true}`。
- SSE lifecycle data 同一十字段；progress data 同旧 `AgentTaskProgress`。
- Reflexion stream 保持旧四种 event，不增加持久 taskId。

### 9.4 配置

Python 拟新增并在 `Settings` 校验：

- `ASYNC_TASK_BASE_URL`
- `ASYNC_TASK_ENABLED`（总开关，默认 false 直到灰度）
- `ASYNC_TASK_WORKER_ID`（空时启动时生成并保持）
- `ASYNC_TASK_LEASE_SECONDS`
- `ASYNC_TASK_HEARTBEAT_SECONDS`
- `ASYNC_TASK_MAX_CONCURRENT`
- `ASYNC_TASK_MAX_INFLIGHT`
- `ASYNC_TASK_MAX_RUNTIME_SECONDS`
- `ASYNC_TASK_TOKEN_SAFETY_SECONDS`
- `ASYNC_TASK_CONNECT_TIMEOUT_SECONDS`
- `ASYNC_TASK_REQUEST_TIMEOUT_SECONDS`
- `ASYNC_TASK_EVENT_MAX_BYTES`
- `ASYNC_TASK_PROGRESS_ENABLED`

约束：heartbeat 必须显著小于 lease（建议不超过 1/3）；最大 inflight ≥ 最大 concurrent；
安全余量 > 一次 request timeout。具体默认数值需结合 token TTL 和压测结果批准，当前不臆造。

Java 拟新增：

- `ASYNC_TASK_ORPHAN_ENABLED=false`
- `ASYNC_TASK_ORPHAN_SCAN_DELAY_MS`
- `ASYNC_TASK_ORPHAN_INITIAL_DELAY_MS`
- `ASYNC_TASK_ORPHAN_PENDING_TIMEOUT`
- `ASYNC_TASK_ORPHAN_LEASE_GRACE`
- `ASYNC_TASK_ORPHAN_BATCH_SIZE`
- `ASYNC_TASK_ORPHAN_KINDS`（生产必须固定五 kind）
- `ASYNC_TASK_EVENT_RETENTION`
- `ASYNC_TASK_EVENT_MAX_BYTES`

### 9.5 消息与 webhook

- 中央内部 live event 使用持久化后的 `AsyncTaskStreamEvent`，不再由 SSE listener 自增 ID。
- Kafka `AsyncTaskLifecycleMessage` 现有结构保持，避免影响消费者。
- HTTP webhook：
  - Agent kind：旧十字段 payload + `X-Agent-*` aliases；
  - 非 Agent kind：保持中央现有十四字段 payload；
  - 所有 outbox retry 至少一次，接收方按 taskId+status 幂等。
- error/event 不保存原 provider exception；只保存稳定 code/摘要。

## 10. 分阶段实施步骤与依赖

### 阶段 1：数据结构与领域模型

依赖：实施审批、旧契约 fixture 冻结、中央生产 JDBC 确认。

步骤：

1. 先在 Python 增加任务/事件 DTO、纯映射与 `RunContext` expiry。
2. 在 Java 增加事件 DTO/journal 端口、JDBC 事件表和 orphan properties。
3. 为 `ASYNC_TASK` 增 orphan 查询索引；核验并加固 webhook outbox 现有
   `OUTBOX_ID=taskId` 幂等，确保重复 enqueue 不会把 `DELIVERED/DEAD` 重置为 `PENDING`。
4. 定义中央 append OpenAPI 与旧十字段/进度 JSON schema。
5. 先写 schema/迁移/映射测试，再进入业务逻辑。

完成标准：

- 空库、原地升级、重复 init 均成功；
- 旧中央任务可继续查询；
- 十/十四字段映射黄金测试通过；
- token 负向序列化断言通过；
- schema diff 已人工审核。

### 阶段 2：核心业务逻辑

依赖：阶段 1 完成。

步骤：

1. Java 先实现原子 `transition`、`failOrphans`，修复 cancel/complete/reaper 竞态。
2. 实现状态+event+Kafka/HTTP outbox 的 JDBC 事务边界。
3. 实现 event append 幂等、sequence、水位回放与 retention。
4. 实现 reaper allowlist/batch/grace，默认关闭。
5. Python 实现 `AsyncTaskGateway`、HTTP client 和 `AsyncTaskManager`。
6. 加入 heartbeat、stop flag、deadline、semaphore、shutdown。
7. 为 DAG/planning 增 optional progress sink；保持同步默认路径。

完成标准：

- 内存/JDBC store 语义一致；
- barrier 并发测试证明终态唯一；
- create+lease 前不执行；
- heartbeat 只延长租约，不追加重复 RUNNING 事件；
- runner 吞取消时仍不会提交成功；
- event 重试不重复、sequence 单调；
- reaper 绝不命中非五 kind；
- token 未出现在任何持久数据/日志。

### 阶段 3：接口与适配层

依赖：阶段 2 状态机与 journal 稳定。

步骤：

1. 增五 submit、GET/list/DELETE。
2. 实现 task SSE preflight、流代理、status 映射、progress 透传。
3. 实现 Reflexion bounded queue SSE 与断连取消。
4. 在 `create_app` lifespan 组装/关闭 client、manager。
5. 接入 webhook 兼容 payload/header 与 URL user-info 拒绝。
6. 加总开关、progress 开关、reaper 开关和 metrics。

完成标准：

- 旧 API fixture 全过；
- 跨租户及跨 kind 全部拒绝；
- SSE chunk/CRLF/multiline/reconnect/断开测试全过；
- Reflexion 四事件顺序一致且错误脱敏；
- Process async 的写工具调用为零；
- Python 不产生 webhook 请求。

### 阶段 4：测试

依赖：阶段 3 完成、双仓可本地启动。

步骤：

1. 运行 Python 单元/契约/安全/静态检查。
2. 运行 Java async-task-service 单元/JDBC/并发测试。
3. 启动双仓拓扑做 create 响应丢失、lease 响应丢失、中央重启、Python SIGKILL、
   双 reaper、取消/完成竞态、webhook 重试等故障注入。
4. 运行旧/新五类 async + Reflexion SSE 双跑。
5. 做事件写放大、SSE 慢消费者、heartbeat 并发的容量测试。
6. 做迁移与应用版本回滚演练。

完成标准：

- Python `ruff/mypy/pytest` 全绿且不降低既有覆盖门禁；
- Java 受影响模块全绿；
- 契约/安全/Process 只读 100%；
- 所有任务最终唯一终态；
- SSE 无漏序，重连可去重；
- 双跑达到现有评测阈值；未定义阈值必须由负责人批准，不能自行放宽。

### 阶段 5：文档与最终检查

依赖：阶段 4 证据齐全。

步骤：

1. 更新两仓 README、契约、配置、runbook、迁移状态和 rollback。
2. 导出 OpenAPI/JSON Schema 并检查 diff。
3. 记录两仓 commit SHA、测试命令、结果、容量与故障注入报告。
4. 先中央兼容部署且所有新开关关闭；再做内部租户/单 kind 灰度。
5. 只有双跑、监控与回滚演练通过后，另行申请生产路由切换。

完成标准：

- 文档与代码无漂移；
- 中央 JDBC 配置得到部署证据；
- dashboard/alert/runbook/rollback 均可执行；
- 未解决残余风险有明确 owner 与批准记录；
- 本阶段仍不自动修改生产 `AGENT_URI`。

## 11. 测试方案

完整矩阵见 `test-plan.md`，发布阻断项摘要如下：

- 契约：五 submit、task CRUD/SSE、Reflexion SSE 的路径、状态、字段、null、event 顺序。
- 安全：坏/过期 token、跨租户、跨 kind、上下文串线、token/异常泄漏、webhook SSRF。
- 失败映射：中央网络/timeout/4xx/5xx/坏 JSON、create/lease/cancel 响应丢失。
- 并发：cancel vs success、reaper vs heartbeat、双 reaper、重复 append、shutdown。
- 调度上下文：reaper audit/webhook 使用任务 tenant/user，循环与异常后不残留 ThreadLocal/MDC。
- SSE：任意 chunk、CRLF、多行 data、Last-Event-ID、中央重启、慢消费者、断开清理。
- 业务：五种 service 复用、DAG progress、Reflexion 四事件、Process 只读。
- 双跑：状态迁移、十字段 JSON、事件名/data、工具类别、结果结构和评测分。
- 迁移/回滚：空库、原地升级、幂等 init、新表保留时旧应用启动。

Python 最终命令：

```bash
uv sync --dev
uv run ruff check .
uv run mypy src
uv run pytest
```

Java 精确构建命令须实施时从 sibling 仓 wrapper/pom 读取后记录，当前标记“待验证”，不在
规划中臆造。

## 12. 监控与告警

### Python 指标

- submit 总数/失败数，按 endpoint/kind/reason；
- create/lease/update/cancel/append latency 与错误；
- inflight/running/queued，registry 大小；
- heartbeat 成功/重试/lease conflict；
- token deadline 拒绝/运行超时；
- SSE active/disconnect/upstream error；
- progress queue depth/drop（设计上 drop 应为 0）；
- shutdown 未收敛 handle。

### Java 指标

- orphan scan 候选/成功 CAS/跳过/失败，按 kind/status；
- PENDING/RUNNING age 与 lease overdue；
- event append/duplicate/size reject；
- SSE replay count/live subscribers/slow disconnect；
- webhook outbox pending/retry/dead/oldest age；
- DB transition/CAS conflict/scan latency。

告警至少覆盖：orphan 激增、heartbeat 失败率、lease conflict、token deadline、outbox oldest
age/dead、事件 append 失败、SSE 5xx、任务终态率下降。标签不得包含 token、完整 prompt、
结果文本或任意高基数 taskId（taskId 只进入受控日志/trace）。

## 13. 灰度方案

1. 中央先上线 schema、CAS、event journal、webhook 兼容；reaper/progress 新读路径均关闭。
2. 事件双写 shadow：仍用旧 live SSE，对比数据库事件数、顺序和 payload。
3. reaper dry-run 只发 metrics，不改状态；核对命中集合不含旧/其他 kind。
4. Python 上线但 `ASYNC_TASK_ENABLED=false`，验证 readiness 与中央连通。
5. 对内部测试租户开启单一 `agent.run`，再依次 DAG、plan、analyst、process。
6. 开 progress append，随后按租户切换持久事件 SSE。
7. 开 reaper 小 batch、长 grace，观察至少两个扫描周期后逐步收紧至批准值。
8. 双跑和监控通过后才扩大；生产 `AGENT_URI` 切换是独立审批动作。

## 14. 回滚方案

### 应用回滚

1. 关闭新 async submit 开关，保留 GET/cancel/SSE 处理在途任务。
2. 停止扩大流量，记录在途 taskId/kind/lease owner。
3. 等待安全窗口；必要时逐任务 cancel，不执行批量无条件终结。
4. 关闭 progress append/持久 SSE 读取，回退中央旧 live 路径。
5. 关闭 reaper 后回滚 Java 应用。
6. 恢复旧 `AGENT_URI` 前验证旧 agent-service 的任务查询与中央任务不会混路由。

### 数据回滚

- 新事件表、索引和兼容列采用 additive migration，紧急回滚不删除。
- 旧应用必须能忽略新表/索引并启动。
- 只有观察期结束并有独立变更审批后才清理废弃结构。

### 在途任务

- Python 进程已崩溃：保留中央记录，等 allowlist reaper 在 grace 后失败。
- terminal 已写、webhook 未投：保留/恢复 outbox dispatcher，不能回滚时删 outbox。
- event append 已写但客户端未见：重连按 sequence 回放。
- token 即将过期：不尝试持久化或换发，按 deadline 失败。

## 15. 主要风险与控制

| 风险 | 控制 | 残余 |
|---|---|---|
| JWT 默认 TTL 短 | expiry-aware deadline、创建前拒绝、提前终结 | 无法支持超 TTL 长任务 |
| cancel/complete/reaper 覆盖 | JDBC row lock/CAS、终态 no-op、竞态测试 | 网络对账增加延迟 |
| worker 崩溃 | lease + kind allowlist reaper | 任务失败而非恢复 |
| 双执行 | create+lease、稳定 workerId、owner 校验 | lease 过期前旧进程无法被强杀证明 |
| SSE 漏/重 | 持久 eventKey/sequence、二次追平、客户端按 id 去重 | retention 外不能完整回放 |
| 事件写放大 | payload/事件白名单、batch cleanup、容量门禁 | DAG 高并发增加 DB I/O |
| webhook 丢/双发 | terminal 同事务 outbox、唯一键、接收方幂等 | HTTP 本质至少一次 |
| SSRF | scheme/host/user-info 校验、生产 egress | DNS rebinding 需基础设施控制 |
| 跨领域误操作 | Python kind allowlist + 中央 tenant scope | 同 tenant 仍按旧语义共享 |
| Process 越权 | 复用只读 service/toolset、写意图双跑 | LLM 文本不能替代工具审计 |
| 中央影响其他 producer | 新 API/kind/reaper 默认隔离、旧消息不改 | store CAS 修复需全回归 |

## 16. 最终验收清单

### 契约与功能

- [ ] 五个 async POST 路径精确，均在 create+lease 后返回 202。
- [ ] 返回/GET/list 为旧十字段，时间/null/input/webhook 表现一致。
- [ ] DELETE 与 404 行为一致，网络歧义可对账。
- [ ] task SSE 保持 lifecycle、旧 DAG progress、id 与续订。
- [ ] Reflexion SSE 依次发四类事件，异常脱敏。

### 状态与并发

- [ ] PENDING/RUNNING/三终态合法，终态永不回退。
- [ ] cancel、complete、reaper 并发只有一个获胜者。
- [ ] queued task 也 heartbeat；lease 冲突停止本地执行。
- [ ] shutdown 无悬挂协程；崩溃任务由 reaper 失败。

### 安全

- [ ] 所有业务端点验证 token；跨租户不可见。
- [ ] 同租户非 Agent kind 不可从 Agent API 访问/取消。
- [ ] token 不在 DB/event/outbox/result/error/log。
- [ ] tenant/user/scopes/department/trace 显式传播且并发不串。
- [ ] Process 异步路径写工具调用为零。
- [ ] webhook URL 校验、兼容 payload/header 和中央单投递通过。

### 数据与运维

- [ ] 生产中央使用 JDBC；Helm/Compose 值有证据。
- [ ] schema 原地升级、幂等 init、旧应用回滚均通过。
- [ ] event retention、task TTL、outbox retention 顺序合理。
- [ ] reaper 默认关闭、allowlist 固定、dry-run 命中正确。
- [ ] 指标、告警、runbook、灰度和回滚演练完成。

### 质量门禁

- [ ] Python Ruff、mypy、pytest 全绿。
- [ ] Java async-task-service 受影响测试全绿。
- [ ] API/安全/并发/SSE/故障注入 100% 通过。
- [ ] 旧/新双跑达到批准阈值，无 Process 安全回归。
- [ ] 两仓 commit、契约 diff、测试报告和残余风险已归档。
- [ ] 未在门禁前切换生产 `AGENT_URI`。

## 17. 待验证与审批项

以下不阻止形成计划，但在编码前必须以事实关闭：

1. 部署环境实际 JWT TTL 与典型任务 p95/p99；据此批准最大运行时长和安全余量。
2. sibling 仓精确 Maven wrapper/聚合模块命令。
3. 生产 Helm values 的实际路径及中央 store 当前值。
4. 旧前端是否依赖 SSE event id 的具体数值；当前只看到 event name/data 契约。
5. 现有评测框架对 async 的质量/延迟阈值；没有的阈值由负责人批准。
6. HTTP webhook outbox 的 `OUTBOX_ID=taskId` 幂等行在迁入 terminal 事务后，是否会被重复
   enqueue 错误重置；用现有数据与并发测试确认。
7. 数据库产品/版本对 `SELECT ... FOR UPDATE`、在线建索引的具体能力。

## 18. 资深架构师复审结论

本计划在最终复审中已做以下一致性修正：

- 以实际旧路径统一为 `/agent/dag/plan-run/async` 和 `/agent/reflexive/stream`。
- 保持中央现有 query `lastEventId` 优先于 header 的行为，没有按常见习惯臆改。
- 将旧 DAG 细粒度 SSE 从“可选增强”提升为最终方案范围，避免与“保持旧 SSE”矛盾。
- 明确中央十四字段与旧十字段是投影关系，不把租约字段暴露给旧客户端。
- 将 runner 吞取消、JWT 五分钟默认值、JDBC 读改写竞态、旧 kind 无 heartbeat、
  workflow 可跳过 RUNNING 等代码事实纳入设计。
- 将 HTTP webhook post-commit 入队窗口收口为 JDBC terminal 同事务 outbox，避免一边声称
  中央唯一投递、一边留下无恢复丢失窗口。
- 发现 scheduler 无请求期 TenantContext，补入逐任务 try/finally 上下文绑定与串租户测试。
- 避免把每次 heartbeat 当生命周期事件持久化，并按现有 `OUTBOX_ID=taskId` 主键设计幂等，
  删除了不基于实际 DDL 的额外唯一键假设。
- 明确事件日志是 additive schema、reaper 默认关闭、生产必须 JDBC，保证灰度/回滚闭环。

复审后仍有两个有意接受的弱点：**任务不能跨进程恢复**，且**最大执行时间受原 token
TTL 限制**。解决二者需要独立的委托身份和可恢复 worker 项目，不应在本期以持久化 token
或不受控重试规避。

## 19. 实施审批关卡

本计划至此停止。批准实施即表示接受：

- A+D 组合带来的中央事件表/API/事务改造；
- token TTL 和崩溃后失败、不恢复的运行语义；
- orphan 只允许五个新 kind；
- additive migration、分开关灰度和“未通过双跑不得切生产路由”的门禁。

在明确批准前，不修改任一业务代码、配置、schema 或 CI。
