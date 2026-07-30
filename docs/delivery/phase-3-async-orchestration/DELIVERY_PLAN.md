# Phase 3 Async Orchestration Delivery Plan

## Requirement

迁移 Phase 3 异步能力：异步任务状态机、SSE、`/agent/reflexive/stream`、
`/agent/process/run/async`、取消和 webhook，并复用旧平台 `async-task-service`。

## Repository Evidence

- 新服务已完成同步 ReAct、DAG/Planner/Analyst、Reflexion 和 Process 只读编排。
- 旧 `agent-service` 提供 `/agent/run/async`、DAG/Planner/Analyst/Process async、
  `/agent/tasks/**` 和 Reflexion SSE。
- `async-task-service` 已提供创建、查询、列表、租约、状态更新、取消、带
  `Last-Event-ID` 的 SSE、JDBC store 和 webhook outbox。
- 中央任务中心没有 worker 扫描/主动恢复；租约过期只允许被动重领。
- 任务恢复需要原租户身份。内部 JWT 不得写入任务 input/result 或日志，因此新服务重启后
  不能安全地自动续跑旧模型任务。

## Feasibility

- Verdict: conditional-go
- Constraints:
  - 生产耐久性要求 `async-task-service` 使用 JDBC store。
  - 新服务捕获的内部 token 仅保存在当前进程内存，绝不进入中央任务记录。
  - 进程崩溃后的任务采用“租约超时后明确失败”，本阶段不跨重启续跑。
  - Process async 继续是只读候选，不迁移 `refund_start`。
- Dependencies:
  - `async-task-service` 的现有 HTTP/SSE/lease/webhook 接口。
  - LiteLLM 和同步应用服务。
  - 对旧 `langchain4j-platform/async-task-service` 增加可配置 orphan reaper。
- Risks and mitigations:
  - 取消与成功竞争：中央终态优先，任何迟到成功不得覆盖 `CANCELLED`。
  - 双 worker：先获得 lease 才执行，并周期续租；lease 409 立即停止。
  - 重启孤儿：中央 reaper 将过期 `RUNNING` 和超时 `PENDING` 置为 `FAILED` 并触发 SSE/webhook。
  - token 泄漏：任务 input 仅保存业务参数，错误只保存稳定错误码/脱敏消息。
  - webhook SSRF：只接受 http/https、无 user-info 的 URL；生产建议通过中央 egress/allowlist
    治理，DNS rebinding 仍列为残余风险。
  - SSE 背压/断线：生命周期流直接代理中央流并保持 event id；客户端断线关闭上游连接。

## Product Design

- Actors and goals:
  - 已认证用户提交长任务并立即获得 taskId。
  - 用户按租户列举/查询/取消自己的任务。
  - 用户通过 SSE 获取生命周期，断线后用 `Last-Event-ID` 续订。
  - webhook 消费方在终态获得至少一次回调。
- Scope:
  - `POST /agent/run/async`
  - `POST /agent/dag/run/async`
  - `POST /agent/dag/plan-run/async`
  - `POST /agent/analyst/run/async`
  - `POST /agent/process/run/async`（只读）
  - `GET /agent/tasks`
  - `GET /agent/tasks/{taskId}`
  - `DELETE /agent/tasks/{taskId}`
  - `GET /agent/tasks/{taskId}/stream`
  - `POST /agent/reflexive/stream`
  - lease 续期、取消监测、中央 webhook/outbox。
- Out of scope:
  - Process 流程发起/审批。
  - 把内部 JWT 或 AgentScope 状态持久化。
  - 自动恢复并重放崩溃前的模型调用。
  - 修改 edge 生产路由或部署生产环境。
- Business rules:
  - 状态仅允许 `PENDING → RUNNING → SUCCEEDED|FAILED|CANCELLED`。
  - 终态不可变。
  - 创建、查询、取消、SSE 全部按当前内部 JWT 租户隔离。
  - 提交在中央 create + lease 成功后才返回 202。
  - webhook 由中央任务中心唯一投递，避免双发。
  - Process async 与同步 Process 使用同一只读应用服务。

## Acceptance Criteria

| ID | Observable behavior | Priority | Verification |
| --- | --- | --- | --- |
| AC-01 | 五个 async 提交端点返回 202 和旧 `AgentAsyncTask` 字段 | P0 | API contract tests |
| AC-02 | 中央 create/lease/update 传播 token、trace，input 不含 token | P0 | HTTP client tests |
| AC-03 | 任务状态合法流转且终态不会被迟到结果覆盖 | P0 | race/state tests |
| AC-04 | GET/list/cancel 对跨租户任务返回 404，合法取消返回旧响应 | P0 | security/API tests |
| AC-05 | worker 周期续租；lease 冲突或中央取消会停止本地工作 | P0 | deterministic async tests |
| AC-06 | task SSE 保留 event、id、Last-Event-ID 和兼容任务 JSON | P0 | proxy parser/route tests |
| AC-07 | Reflexion stream 依次发送 attempt-start/answer/critique/done；错误脱敏 | P0 | SSE tests |
| AC-08 | webhookUrl 仅交给中央任务中心且终态只触发一次投递路径 | P0 | request/central tests |
| AC-09 | Process async 不能规划或调用流程写工具 | P0 | safety regression |
| AC-10 | 崩溃孤儿在租约/PENDING 超时后明确 FAILED 并发布事件 | P0 | Java store/controller tests |
| AC-11 | 取消、失败、webhook 和 SSE 日志不泄漏 token/model/provider details | P0 | adversarial tests |
| AC-12 | 契约、文档、CI 和离线双跑数据同步 | P1 | snapshot/docs/CI gates |

## UI/UX Design

- Applicability: Not applicable。
- Evidence: 当前仓库仅为后端服务，用户未要求修改独立 Vue 前端。
- Existing frontend 可继续使用旧任务面板：202 task 快照、轮询、DELETE 和 SSE 字段保持兼容。

## Technical Solution

- Chosen approach:
  - `async-task-service` 作为唯一权威 store、SSE history 和 webhook/outbox owner。
  - 新服务实现语言中立 `AsyncTaskGateway` 端口与 HTTP/SSE 适配器。
  - `AsyncExecutionManager` 保留当前进程工作协程，执行前 lease，后台 heartbeat 续租并检测取消。
  - API 对中央 `AsyncTask` 做兼容映射，不暴露 lease/framework 内部字段。
  - task SSE 流式解析中央 SSE frame，保留 id/event，并把 data 映射为旧 Agent task 视图。
  - Reflexion service 增加 progress sink；直连 SSE 不创建持久任务，断线时取消当前执行。
  - 旧平台新增 orphan reaper，将 stale PENDING/expired RUNNING 明确失败。
- Alternatives rejected:
  - 仅用进程内 store：重启丢状态，webhook/SSE 不耐久。
  - 把内部 JWT 存到任务 input：凭据泄漏和重放风险不可接受。
  - 重启后自动重跑：现有中央 API 无安全 delegated identity/claim feed。
  - 新服务自行投 webhook：与中央 outbox 双重投递且缺少事务耐久性。
- Modules and file map:
  - 新项目：
    - `domain/async_task.py`：中央/兼容 DTO、状态。
    - `application/async_task.py`：manager、状态/取消规则、work registry。
    - `application/ports.py`：gateway/progress 协议。
    - `infrastructure/http/async_task_client.py`：REST、lease、SSE。
    - `api/routes.py`、`api/app.py`：async/task/SSE 入口和生命周期。
    - `application/sibling.py`：Reflexion progress sink。
    - `core/config.py`、`.env.example`、`compose.yml`：base URL、worker、lease/heartbeat。
    - `contracts/**`、`eval/baseline/**`、`tests/**`、相关文档。
  - 旧项目：
    - `async-task-service` store/scheduler/config/tests：orphan reaper。
    - webhook header 兼容仅在测试证明现有中央载荷不足时增加。
- Contracts and data:
  - 对外保持 `AgentAsyncTask` 十字段和旧状态名。
  - 中央记录使用 `kind=agent.run|agent.dag|agent.dag-plan|agent.analyst|agent.process`。
  - result 仅保存语言中立 `model_dump(by_alias=True)`。
  - error 仅保存 `cancelled by user` 或稳定脱敏错误。
- Security and reliability:
  - token 仅通过 `RunContext` 请求头传播。
  - 每个 taskId 使用 UUID，中央 409 失败关闭。
  - `asyncio.Task` 取消后等待收敛；finally 停止 heartbeat。
  - 中央返回终态时停止本地任务；状态更新响应是最终权威。
  - shutdown 取消本机工作，但不伪造成功；orphan reaper 后续明确失败。
- Observability:
  - 结构化记录 taskId、kind、tenantId、traceId、状态和稳定错误码。
  - 不记录 input/result/token/webhook query。
- Compatibility and migration:
  - 新 endpoint 尚不接 edge；旧 Java `agent-service` 保持回滚基线。
  - 中央任务中心需先部署 orphan reaper，再启用候选 async 路由。

## Implementation Sequence

1. 契约与中央 client（AC-01/02/04/06/08）。
2. Manager、lease/heartbeat/cancel/shutdown（AC-03/05/11）。
3. async 提交与 task API（AC-01/04/09）。
4. task SSE proxy 与 Reflexion stream（AC-06/07）。
5. Java orphan reaper 与 webhook 兼容核验（AC-08/10）。
6. 评测、评审修复、QA、文档、CI 和双仓提交（AC-12）。

## Verification Plan

| AC/Risk | Test level | Case or command | Required evidence |
| --- | --- | --- | --- |
| AC-01/04/09 | FastAPI | authenticated/blank/cross-tenant/process cases | exact status/body |
| AC-02/08 | HTTP adapter | MockTransport requests | headers and sanitized body |
| AC-03/05 | application | barriers/fake gateway/forced races | terminal state assertions |
| AC-06/07 | stream | fragmented SSE, replay header, disconnect/error | exact event frames |
| AC-10 | Java unit/integration | Maven async-task tests | stale tasks become FAILED |
| AC-11 | adversarial | provider errors/token markers | no secret in state/log/API |
| AC-12 | repository gates | Ruff/mypy/pytest/contracts/build/compose/Maven | all pass |

## Documentation Plan

- README、contracts、architecture、migration plan。
- 新增 async orchestration 运维指南：配置、状态机、SSE、取消、webhook、恢复与回滚。
- 同步旧平台长任务指南的 orphan 行为。

## CI Plan

- 新项目现有 GitHub Actions 已覆盖 contracts、Ruff、mypy、pytest、shadow、build、Compose；
  新测试自动进入现有 pipeline，无需扩大权限。
- 旧项目沿用 Maven CI；仅运行受影响模块及上游测试，再按仓库门禁运行聚合测试。

## Rollout And Rollback

1. 先部署带 JDBC 与 orphan reaper 的 `async-task-service`。
2. 部署新服务但不切 edge，使用测试租户验证 create→lease→terminal、取消、SSE 和 webhook。
3. 按 endpoint/测试租户灰度 async 路由。
4. 监控 lease conflict、orphan failed、cancel latency、webhook dead outbox 和任务 P95。
5. 回滚时停止新 async 路由并回到旧 `agent-service`；中央任务记录继续可查询。

## Assumptions And Open Decisions

- 假设 Phase 3 包含旧平台所有五个 async 提交端点，而不只显式点名的 Process async。
- 假设允许同时修改 `langchain4j-platform/async-task-service`，用于 orphan 明确失败。
- 本阶段选择“重启后明确失败”，不实现跨重启自动恢复。
- 生产 webhook egress/DNS 防护仍由平台网络策略补强，本实现不宣称解决 DNS rebinding。

## Approval

- Status: approved
- Approved scope: `docs/plans/phase-3-async-orchestration-next-0729-0950/FINAL_PLAN.md`
  中的 A+D 组合方案，包括跨仓修改 `async-task-service`、中央持久事件日志、五种
  Agent kind 的 orphan reaper、JWT TTL 截止和崩溃后明确失败语义。
- Evidence: 用户于 2026-07-29 明确回复“批准按 FINAL_PLAN 实施”。
