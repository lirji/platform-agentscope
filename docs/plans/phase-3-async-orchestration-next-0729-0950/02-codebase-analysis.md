# Phase 3 异步编排：代码库分析

> 视角：codebase-explorer
> 原则：本文件只描述已读取代码的事实；拟新增内容均明确标注“计划新增”。

## 1. 一句话结构

`agentscope-platform` 是 FastAPI + 分层应用服务的无状态 Agent 编排候选；旧仓的
`async-task-service` 是 Spring MVC + 可选 JDBC 的通用任务权威，当前具备租约、生命周期
SSE 和 webhook/outbox，但没有主动 orphan 扫描。

## 2. 新仓现状

### 2.1 启动与组装

- `src/agentscope_platform/main.py:6` 在 import 时调用 `create_app()`。
- `src/agentscope_platform/api/app.py:56-67` 的 `Container` 保存 settings、JWT verifier 和
  七个同步应用服务；没有 task client/manager。
- `create_app` 在 `api/app.py:69-75` 支持 runner/planner/reviewer/text generator 测试注入。
- `api/app.py:76-143` 构造单一 `PlatformClient`、AgentScope adapters 和同步服务。
- `api/app.py:146-154` 创建 FastAPI；当前没有 lifespan/shutdown 清理。
- `api/app.py:156-162` 生成或透传 `X-Trace-Id`。

可复用点：

- `Container` 的显式依赖组装适合加入 task gateway/manager。
- `create_app` 已有 test-double 注入方式。
- trace middleware 已保证所有新响应有 trace header。

### 2.2 HTTP 路由

`src/agentscope_platform/api/routes.py` 当前只有同步路径：

- ReAct：`run_agent/_run_agent`，`:68-91,215-224`。
- DAG：`:94-108`。
- plan-run：`:111-126`。
- Analyst：`:129-144`。
- Reflexion：`:175-186`。
- Process 只读：`:189-212`。

当前没有 `StreamingResponse`、task 路由、async submit 路由或 SSE parser。

现有错误映射：

- `AgentNotConfiguredError → 503`，`api/app.py:164-175`。
- `DagValidationError → 400`，`:177-185`。
- `DagQualityError → 502`，`:187-198`。
- sibling validation → 400，`:200-206`。
- text generation → 脱敏 502，`:208-220`。

可复用点：

- 同步路由里的 service 选择可由异步 submit use case 复用。
- 现有异常 handler 的稳定文案可用于 worker 失败分类，但后台任务不能直接依赖 FastAPI
  exception handler。

### 2.3 认证与上下文

- `api/dependencies.py:11-39` 从配置的 header 取原 token，验签并构造 `RunContext`。
- `domain/agent.py:6-18` 的 `TenantIdentity`/`RunContext` 是不可变 dataclass，显式含
  tenant/user/scopes/department/token/trace，但没有 token expiry。
- `infrastructure/security/internal_jwt.py:20-58` 验证 `sub/uid/scopes/dept/exp`，但返回时丢弃
  `exp`。
- `core/context.py:5-19` 用 `ContextVar` 绑定 Runner 工具上下文。

影响：

- 异步 work coroutine 可以持有 `RunContext`，但必须增加 expiry 才能在原 token 失效前终结。
- 不能把 `RunContext` 序列化成中央 input。

### 2.4 同步应用服务与取消传播

- `AgentApplicationService.run` 调用 runner 并映射回复：
  `application/service.py:10-30`。
- `AgentDagApplicationService.run` 做校验、执行、critic/replan：
  `application/dag.py:64-106`。
- DAG 同层用 `asyncio.create_task` + `gather`，异常时取消同层 children：
  `application/dag.py:207-224`。
- Planner/Analyst/Process 复用 `AgentDagPlanningService.plan_and_run`：
  `application/planning.py:37-116`。
- Process 写 marker 拒绝和只读 fallback 在
  `application/planning.py:18-34,66-108`。
- Reflexion 的完整循环在 `application/sibling.py:236-298`，当前没有 progress sink。
- text generator、planner、reviewer 都显式重抛 `asyncio.CancelledError`：
  `infrastructure/agentscope/text_generator.py:73-74`、
  `planner.py:140-141`、`reviewer.py:148-149`。
- 但 `AgentScopeRunner.run` 会捕获取消并返回 `stop_reason="CANCELLED"`，不会重抛：
  `infrastructure/agentscope/runner.py:77-88`；现有测试固定了该行为
  `tests/test_runner.py:191-215`。

影响：

- task manager 不能只依赖 `execution_task.cancel()`；supervisor 必须维护独立 stop reason，
  work 返回后先检查 stop flag/中央状态再决定是否提交成功。
- 不建议为本阶段修改 Runner 的同步取消契约；在 manager 层隔离解决。

### 2.5 领域 DTO

- `AgentRunRequest` 禁止额外字段，含 `goal` 和 alias `webhookUrl`：
  `domain/agent.py:21-25`。
- `AgentDagRunRequest` 禁止额外字段；plan request 忽略额外字段：
  `domain/dag.py:44-56`。
- `ReflexionRequest` 忽略额外字段：
  `domain/sibling.py:65-68`。
- 所有 reply 都是 camelCase alias 的 Pydantic 模型，适合安全 `model_dump(by_alias=True)`。

影响：

- 五个 async 端点不能用一个宽松通用 request；应复用各自同步 DTO 和同步业务校验。
- 中央 task DTO 与旧 Agent task view 需单独建模，不能混用同步 reply。

### 2.6 HTTP client

`infrastructure/http/platform_client.py`：

- `PlatformServiceError` 只保留 service/status/稳定 message，`:21-25`。
- `_request` 每次创建 `httpx.AsyncClient`，`:181-204`。
- 出站传播 `X-Trace-Id` 和原 `X-Internal-Token`，`:190-203`。
- 网络错误和错误响应被转成稳定 `PlatformServiceError`，`:205-220`。

可复用点：

- header 构造与稳定失败模式。

不能直接复用的点：

- task SSE 需要持久 streaming client、`read=None`、上游 context manager 的完整生命周期。
- create/lease/status 需要细分 404/409/终态响应，不能把所有错误折叠。

### 2.7 配置、部署、契约和 CI

- `core/config.py:34-99` 无 async-task 配置。
- `.env.example:1-64`、`compose.yml:9-39` 无 async-task base URL、worker、lease/heartbeat。
- `scripts/export_contracts.py:29-71` 生成现有 DTO schema 和 `contracts/openapi.json`。
- CI 已运行 contract check、Ruff、format、mypy、pytest+80% coverage、shadow smoke、build、
  Compose：
  `.github/workflows/ci.yml:28-57`。
- 当前 `docs/contracts.md:71-80` 把 SSE/async 标成未实现。
- 当前 `docs/migration-plan.md:79-93` 要求取消竞态、重复 lease、webhook 与重启明确失败。

影响：

- 新测试会自动进入 pytest，但新增 schema 必须加入 exporter，否则 CI snapshot 不覆盖。
- 无需为普通单测改 CI；若要求跨仓集成，需文档化双仓命令，不能假设单仓 CI checkout 到 sibling。

### 2.8 评测框架

- `evaluation/shadow.py` 提供 target URL 防误打远端、脱敏报告、旧/新双跑。
- `evaluation/dag_shadow.py:19-38` 已支持 DAG/plan/analyst 同步端点。
- `evaluation/sibling_cases.py:9-27` 覆盖同步 sibling。
- `eval/baseline/process-readonly-cases.jsonl` 已有 Process 写请求安全拒绝用例。

可复用点：

- `Target`、URL allowlist、报告只保存状态/指标不保存答案。

计划扩展：

- 异步双跑需要 submit→poll/SSE→terminal→cancel 的专用 runner，不能把现有同步 evaluator
  直接改成等待 HTTP 200。

## 3. 旧 Agent 服务兼容基线

### 3.1 五种提交

| 端点 | 旧 kind | 执行入口 |
|---|---|---|
| `/agent/run/async` | `DEEP_AGENT` | `DeepAgentService.run` |
| `/agent/dag/run/async` | `AGENT_DAG` | `AgentDagService.run(request, progress)` |
| `/agent/dag/plan-run/async` | `AGENT_DAG_PLAN` | `AgentDagService.planAndRun` |
| `/agent/analyst/run/async` | `AGENT_ANALYST` | `DataAnalystService.analyze` |
| `/agent/process/run/async` | `AGENT_PROCESS` | `ProcessService.run` |

证据：

- `AgentAsyncTaskService.submit/submitWithProgress`：
  `../langchain4j-platform/agent-service/src/main/java/com/lrj/platform/agent/async/AgentAsyncTaskService.java:80-175`。
- 各 controller 路径见 `01-requirements.md`。

旧实现创建本地 `PENDING` 任务后立刻返回，后台线程再 RUNNING。当前交付基线收紧为
create+lease 后才 202，属于可靠性增强；返回体仍使用 create 的 PENDING 兼容快照。

### 3.2 查询/取消

- 旧本地模式 tenant scoped，非本租户任务为 empty/404：
  `AgentAsyncTaskService.java:177-195`。
- cancel 先终结权威任务，再取消 future，并用 cancellation token 阻止迟到成功：
  `AgentAsyncTaskService.java:192-223`。
- authoritative 模式的 Java client 会吞掉所有 REST 异常并返回 false/empty：
  `ExternalAsyncTaskClient.java:47-124`。新 Python client 不应复制这种信息丢失，应保持稳定分类。

### 3.3 旧 SSE

- lifecycle event 名为状态名，data 为 `AgentAsyncTask`：
  `AgentTaskSseService.java:87-94`。
- progress event 名为业务 event，data 为
  `{taskId,event,data,ts}`：
  `AgentTaskSseService.java:97-105`、
  `AgentTaskProgress.java:11-18`。
- DAG 真实 event 包含 `dag-planned`、`dag-levels`、`dag-worker-start/result`、
  `dag-synthesis-*`、`dag-critique`、`dag-replan/replanned`
  （`../langchain4j-platform/agent-service/src/main/java/com/lrj/platform/agent/dag/AgentDagService.java:85-197`）。
- 旧 agent SSE 本身没有 event id/replay；Last-Event-ID 是中央任务中心新增能力。

### 3.4 旧 Reflexion SSE

- controller 在后台 executor 运行并桥接 progress：
  `ReflexionController.java:56-89`。
- service 的事件及 payload：
  `ReflexionService.java:51-83`。
- 旧异常分支会泄漏 `e.getMessage()`：
  `ReflexionController.java:70-73`。新实现按当前安全基线脱敏，这是有意安全修复。

### 3.5 旧 webhook

- 旧 headers 为 `X-Agent-Task-*`，payload 为 10 字段：
  `AgentTaskWebhookNotifier.java:74-102`、
  `AgentTaskWebhookPayload.java:11-33`。
- 旧 URL 校验 http/https+host，但未拒绝 user-info：
  `AgentTaskWebhookNotifier.java:113-127`。
- 旧 README 也公开承诺这组 headers：
  `../langchain4j-platform/README.md:322`。

## 4. 中央 async-task-service 现状

### 4.1 中央 API 与模型

- `AsyncTask` 为 14 字段通用模型：
  `platform-protocol/.../AsyncTask.java:11-24`。
- create 支持 caller taskId，重复全局 taskId 返回 409：
  `AsyncTaskController.java:79-109`。
- list/get 仅按 tenant：
  `AsyncTaskController.java:112-120,222-225`。
- updateStatus 对终态返回原值；校验 lease owner：
  `AsyncTaskController.java:122-153,227-232`。
- lease TTL clamp 1..3600 秒，同 owner 可续租：
  `AsyncTaskController.java:156-184,234-249`。
- cancel 对不存在或终态返回 404：
  `AsyncTaskController.java:187-201`。

### 4.2 已发现的并发事实

- 内存 `AsyncTaskStore.update` 用 `ConcurrentHashMap.computeIfPresent`，单 key 原子：
  `AsyncTaskStore.java:49-50`。
- JDBC `JdbcAsyncTaskStore.update` 是事务内“普通 SELECT → UPDATE”，没有
  `SELECT ... FOR UPDATE`、version 或状态 CAS：
  `JdbcAsyncTaskStore.java:129-156`。
- controller 的 lease owner 检查发生在 store update 之前；JDBC 竞态下可能检查后被另一操作改变。
- cancel 的 store updater 没有在原子区内重查 terminal：
  `AsyncTaskController.java:187-195`。它可与成功竞争覆盖终态。
- JDBC lease 本身是带条件的单条 UPDATE，竞争安全：
  `JdbcAsyncTaskStore.java:170-189`。

结论：reaper 不能建立在现有通用 `update` 的读改写语义上；必须新增原子条件终态变更，并让
cancel/status 共用终态不可变保护，否则 AC-03/R-04 无法成立。

### 4.3 表结构与数据

`ASYNC_TASK` 现有字段和索引见 `JdbcAsyncTaskStore.java:66-89`：

- 已有 `STATUS`、`CREATED_AT`、`UPDATED_AT`、`FINISHED_AT`、
  `LEASE_OWNER_ID`、`LEASE_EXPIRES_AT`。
- 已有 `(STATUS, LEASE_EXPIRES_AT)` 索引，适合 expired RUNNING。
- 没有 `(STATUS, CREATED_AT)`，stale PENDING 扫描需要补一个加法索引。
- orphan reaper 本身无需新增任务列，也无需重写已有行；最终 A+D 方案为严格 SSE 兼容
  另增事件表，但不改现有任务记录字段。

### 4.4 SSE

- 中央 SSE 每次发送 `id`、状态名 event、14 字段 task data：
  `AsyncTaskSseService.java:130-135`。
- history 是每 task 内存 deque，最多 64；sequence 是进程级 AtomicLong：
  `AsyncTaskSseService.java:28-33,104-128`。
- JDBC 只持久任务，不持久 SSE history。

结论：Python 必须流式解析/映射，不能 byte-for-byte 盲转；中央当前只能提供近期内存窗口。
最终方案若要满足严格旧 DAG SSE 与可靠重连，必须增加持久事件日志，这是拟新增能力而非
对现状的描述。

### 4.5 webhook/outbox

- 内存模式直接异步 webhook：
  `AsyncTaskWebhookNotifier.java:28-79`。
- JDBC 模式由 event listener 入 `ASYNC_TASK_WEBHOOK_OUTBOX`：
  `AsyncTaskWebhookOutboxEnqueuer.java:16-37`。
- dispatcher 有 claim TTL、多实例 claim、4xx dead、5xx/network retry：
  `AsyncTaskWebhookOutboxDispatcher.java:24-147`。
- JDBC 终态与 Kafka lifecycle outbox 可同事务：
  `JdbcAsyncTaskStore.java:129-167`。
- HTTP webhook outbox 入队仍是提交后的 Spring event listener，不与任务终态同事务。该现有限制应
  作为残余风险，不在计划中误称为严格原子。
- 中央 URL 校验未拒绝 user-info：
  `AsyncTaskWebhookNotifier.java:98-112`。

### 4.6 orphan 与跨模块影响

- 当前只有终态 TTL cleanup，没有非终态扫描：
  `AsyncTaskStore.java:70-85`、`JdbcAsyncTaskStore.java:201-209`。
- workflow-service 会创建 `PENDING` 后直接 PATCH `SUCCEEDED`，不 lease：
  `../langchain4j-platform/workflow-service/src/main/java/com/lrj/platform/workflow/WorkflowAsyncTaskNotifier.java:45-86`。
- 旧 agent authoritative worker 只 lease 一次，没有 heartbeat：
  `ExternalAsyncTaskClient.java:101-113`、
  `AgentAsyncTaskService.java:119-140`。

结论：

- 不能全 kind reaper。
- 不能把全局状态机强制成“所有 kind 必须 RUNNING 才可 terminal”，否则破坏 workflow。
- reaper allowlist 默认只含五种新 kind；旧 `agent.task` 必须排除。

### 4.7 部署事实

- async-task `application.yml` 默认 JDBC：
  `../langchain4j-platform/async-task-service/src/main/resources/application.yml:22-43`。
- Docker Compose 默认 JDBC：
  `../langchain4j-platform/deploy/docker-compose.yml:395-415`。
- Helm values 目前默认 in-memory：
  `../langchain4j-platform/deploy/helm/platform/values.yaml:185-194`。
- 多副本文档已要求 JDBC：
  `../langchain4j-platform/deploy/helm/README.md:168-174`。

## 5. 精确调用链

### 5.1 计划中的 async submit

```text
FastAPI async route
  -> RunContextDependency（验 token + trace + token expiry）
  -> AsyncAgentApplicationService.submit_*（计划新增）
  -> AsyncExecutionManager.submit（计划新增）
  -> AsyncTaskGateway.create(taskId, kind, sanitized input, webhook, context)
  -> AsyncTaskGateway.lease(taskId, workerId, leaseSeconds, context)
  -> registry[taskId] = WorkControl（只在内存，含 context/callable/stop state）
  -> asyncio supervisor（heartbeat + deadline + bounded worker slot）
  -> 既有同步 application service
  -> DAG/planning 可选 progress sink
  -> AsyncTaskGateway.append_event（幂等 eventKey）
  -> result.model_dump(by_alias=True)
  -> AsyncTaskGateway.update_status(SUCCEEDED/FAILED)
  -> 中央 event -> SSE + webhook/outbox
```

### 5.2 计划中的 cancel

```text
DELETE /agent/tasks/{taskId}
  -> gateway.get（tenant + Agent kind 预检）
  -> gateway.cancel
  -> manager.cancel_local(taskId)（有则设置 USER_CANCELLED + cancel work）
  -> 中央最终快照对账
  -> 旧兼容 cancel JSON；跨租户/非 Agent kind/终态为 404
```

### 5.3 计划中的 task SSE

```text
GET /agent/tasks/{taskId}/stream
  -> gateway.get 预检（404/非 Agent kind）
  -> gateway.stream（传播 token/trace/Last-Event-ID）
  -> 增量 SSE parser
  -> lifecycle AsyncTask data -> AgentAsyncTaskView
  -> progress AgentTaskProgress data -> 原事件透传
  -> StreamingResponse 逐帧 yield
  -> client disconnect/finally -> close upstream response
```

### 5.4 计划中的 Reflexion SSE

```text
POST /agent/reflexive/stream
  -> bounded QueueProgressSink
  -> producer task: ReflexionService.run(request, context, sink)
  -> sink emit attempt-start/answer/critique/done
  -> StreamingResponse consumer
  -> disconnect -> cancel producer -> await gather(return_exceptions=True)
```

### 5.5 计划中的 orphan reaper

```text
@Scheduled AsyncTaskOrphanReaper.reap
  -> store.findOrphanCandidates(allowlisted kinds, pending cutoff, lease cutoff, batch)
  -> 对每条 store.failIfStillOrphan（内存 compute / JDBC row lock+recheck）
  -> 只有本实例成功变更者 publish AsyncTaskEvent + audit
  -> SSE 终态帧 + HTTP webhook outbox 或 Kafka lifecycle outbox
```

## 6. 受影响文件

以下是可直接执行的预计清单；“新增”表示仓库当前不存在。

### 6.1 `agentscope-platform`

核心：

- `src/agentscope_platform/domain/async_task.py`（新增）：中央 DTO、旧 task view、状态、
  SSE frame、kind allowlist。
- `src/agentscope_platform/domain/agent.py`：`RunContext` 增 token expiry。
- `src/agentscope_platform/application/ports.py`：`AsyncTaskGateway`、`ProgressSink` 协议。
- `src/agentscope_platform/application/async_task.py`（新增）：
  `AsyncExecutionManager`、`AsyncAgentApplicationService`、registry/supervisor/失败码。
- `src/agentscope_platform/application/dag.py`：
  `AgentDagApplicationService.run/_execute/_run_level/_run_one` 增可选 progress sink。
- `src/agentscope_platform/application/planning.py`：
  `AgentDagPlanningService.plan_and_run` 透传 plan/replan/DAG progress。
- `src/agentscope_platform/application/sibling.py`：
  `ReflexionService.run` 支持可选 progress sink。
- `src/agentscope_platform/infrastructure/http/async_task_client.py`（新增）：
  中央 REST/SSE client、SSE parser、错误分类。
- `src/agentscope_platform/infrastructure/observability/async_task_metrics.py`（新增）及
  `infrastructure/observability/setup.py`：无高基数标签的 OTel 指标与组装。
- `src/agentscope_platform/infrastructure/security/internal_jwt.py`：
  在保留 `verify` 兼容的前提下暴露 verified expiry。
- `src/agentscope_platform/api/dependencies.py`：构造带 expiry 的 `RunContext`。
- `src/agentscope_platform/api/routes.py`：五提交、task CRUD/SSE、Reflexion SSE。
- `src/agentscope_platform/api/app.py`：组装 gateway/manager/service、lifespan shutdown、错误映射。
- `src/agentscope_platform/core/config.py`：async-task base URL、worker、lease/heartbeat、并发、
  最大运行、token margin、stream timeout 等。

配置/契约/评测：

- `.env.example`
- `compose.yml`
- `scripts/export_contracts.py`
- `contracts/openapi.json`（生成）
- `contracts/legacy/agent-async-task.schema.json`（新增）
- `contracts/legacy/agent-task-cancel-reply.schema.json`（新增）
- `contracts/legacy/reflexion-sse-event.schema.json`（新增；若 exporter 采用 per-event schema）
- `src/agentscope_platform/evaluation/async_shadow.py`（新增）
- `src/agentscope_platform/evaluation/cli.py`
- `eval/baseline/async-cases.jsonl`（新增）

测试：

- `tests/test_async_task_client.py`（新增）
- `tests/test_async_task_manager.py`（新增）
- `tests/test_async_api.py`（新增）
- `tests/test_async_sse.py`（新增）
- `tests/test_async_shadow.py`（新增）
- `tests/test_sibling_services.py`
- `tests/test_api.py`
- `tests/test_internal_jwt.py`
- `tests/test_contracts.py`
- `tests/test_planning_service.py`（仅增加 async Process 共用服务的断言时）

文档：

- `README.md`
- `contracts/legacy/README.md`
- `docs/contracts.md`
- `docs/architecture.md`
- `docs/migration-plan.md`
- `docs/testing-and-gates.md`
- `docs/async-orchestration.md`（新增）

当前 CI 已自动覆盖上述 Python 源码/测试/契约/构建，原则上不改
`.github/workflows/ci.yml`；只有审批要求把新的离线 async shadow smoke 设为独立门禁时才改，
该项标为“待验证后条件变更”。

### 6.2 `../langchain4j-platform`

async-task 核心：

- `async-task-service/src/main/java/com/lrj/platform/asynctask/AsyncTaskOrphanProperties.java`
  （新增）。
- `async-task-service/src/main/java/com/lrj/platform/asynctask/AsyncTaskOrphanReaper.java`
  （新增）。
- `async-task-service/src/main/java/com/lrj/platform/asynctask/AsyncTaskStreamEvent.java`
  （新增）。
- `async-task-service/src/main/java/com/lrj/platform/asynctask/AsyncTaskEventAppendRequest.java`
  （新增）。
- `async-task-service/src/main/java/com/lrj/platform/asynctask/AsyncTaskEventJournal.java`
  （新增，事件日志端口）。
- `async-task-service/src/main/java/com/lrj/platform/asynctask/InMemoryAsyncTaskEventJournal.java`
  （新增，开发/测试实现）。
- `async-task-service/src/main/java/com/lrj/platform/asynctask/JdbcAsyncTaskEventJournal.java`
  （新增，`ASYNC_TASK_EVENT` DDL、幂等 append、回放/清理）。
- `async-task-service/src/main/java/com/lrj/platform/asynctask/AsyncTaskMetrics.java`
  （新增，复用已有 Actuator/Micrometer，禁止 taskId 高基数标签）。
- `async-task-service/src/main/java/com/lrj/platform/asynctask/AsyncTaskStore.java`：
  原子条件终态 API、内存 orphan candidate。
- `async-task-service/src/main/java/com/lrj/platform/asynctask/JdbcAsyncTaskStore.java`：
  row-lock/CAS 终态、candidate query、`(STATUS, CREATED_AT)` 索引、同事务 lifecycle outbox。
- `async-task-service/src/main/java/com/lrj/platform/asynctask/AsyncTaskController.java`：
  cancel/status 使用原子 mutation，新增进度 append API，保留现有 HTTP 语义。
- `async-task-service/src/main/java/com/lrj/platform/asynctask/AsyncTaskEvent.java`：
  携带已分配 sequence 的持久 stream event。
- `async-task-service/src/main/java/com/lrj/platform/asynctask/AsyncTaskSseService.java`：
  数据库回放与 live 水位衔接，发送 lifecycle/progress 通用事件。
- `async-task-service/src/main/java/com/lrj/platform/asynctask/AsyncTaskWebConfig.java`：
  绑定 orphan properties（或若 properties 用 `@ConfigurationProperties` component 则不改，
  实施时二选一，不能双注册）。
- `async-task-service/src/main/java/com/lrj/platform/asynctask/AgentTaskWebhookPayload.java`
  （计划新增的本地兼容 record；若实现采用 Map mapper，则此文件可省，需在实施 diff 说明）。
- `async-task-service/src/main/java/com/lrj/platform/asynctask/AsyncTaskWebhookNotifier.java`：
  Agent kind payload/header 兼容、拒绝 user-info。
- `async-task-service/src/main/java/com/lrj/platform/asynctask/AsyncTaskWebhookOutbox.java`：
  Agent kind 的兼容 payload 入队。
- `async-task-service/src/main/java/com/lrj/platform/asynctask/AsyncTaskWebhookOutboxDispatcher.java`：
  Agent header aliases。
- `async-task-service/src/main/resources/application.yml`：reaper 配置，默认 disabled。

Java 测试：

- `async-task-service/src/test/java/com/lrj/platform/asynctask/AsyncTaskOrphanReaperTest.java`
  （新增）。
- `.../AsyncTaskControllerTest.java`
- `.../JdbcAsyncTaskStoreTest.java`
- `.../AsyncTaskSseServiceTest.java`
- `.../AsyncTaskEventJournalTest.java`（新增）
- `.../AsyncTaskWebhookNotifierTest.java`
- `.../AsyncTaskWebhookOutboxTest.java`

部署与文档：

- `deploy/docker-compose.yml`
- `deploy/helm/platform/values.yaml`
- `deploy/helm/README.md`
- `README.md`
- `docs/平台工程/长任务处理指南.md`
- `docs/参考/api-reference.md`（若其当前章节继续作为公开端点参考）
- `docs/迁移/migration-roadmap.md`

不计划改：

- `platform-protocol` 的 `AsyncTask`/request records：现有中央 API 已足够；兼容 task/webhook
  DTO留在边界适配器，避免污染通用协议。
- `agent-service` 业务代码：它是回滚基线。
- `workflow-service`：reaper allowlist 和兼容状态 mutation 必须保证其现有 direct
  PENDING→SUCCEEDED 继续工作。
- `edge-gateway`：本阶段不切路由。
