# 候选方案 A：进程内执行器 + 中央任务权威状态

## 1. 方案定位

这是交付基线最接近的方案：`agentscope-platform` 在收到异步提交请求后，先在
`async-task-service` 创建任务并取得租约，再返回旧契约的 `202`；实际推理仍由当前
Python 进程执行，中央服务只负责权威状态、租约、取消、生命周期 SSE 与 webhook。

本方案不承诺进程重启后恢复执行。进程崩溃遗留的任务由仅面向新 AgentScope
任务 kind 的 orphan reaper 终结为 `FAILED`。

## 2. 架构与模块职责

### agentscope-platform

- `domain/async_task.py`（拟新增）
  - 定义语言中立的任务状态、中央任务 DTO、旧版十字段响应 DTO、提交结果与进度事件。
  - 不出现 AgentScope、FastAPI、HTTPX 类型。
- `application/async_task.py`（拟新增）
  - `AsyncTaskManager` 负责 create → lease → register → heartbeat → execute → terminal update。
  - 维护仅存于内存的 `task_id -> execution handle` 注册表；handle 含本地
    `asyncio.Task`、heartbeat task、stop flag、完成锁。
  - 负责中央状态到旧响应的投影、五种 kind 白名单与失败映射。
- `application/ports.py`
  - 增加中央任务客户端与可选进度 sink 的端口，不向应用层暴露 HTTPX。
- `infrastructure/http/async_task_client.py`（拟新增）
  - 集中实现中央 create/get/list/lease/update/cancel/SSE。
  - 普通 JSON 请求使用有界超时；SSE 使用独立流式客户端且关闭 read timeout。
- `api/routes.py`
  - 增加五个提交端点、任务查询/列表/取消/流式代理、Reflexion SSE。
- `api/app.py`
  - 组装 manager/client；通过 FastAPI lifespan 启动与关闭 HTTP client、收敛本地任务。
- 现有五个同步 service
  - 被 manager 调用；尽量不复制业务编排。
  - Reflexion 增加可选 progress sink，默认 `None` 时保持当前同步行为。

### async-task-service

- `AsyncTaskOrphanProperties`（拟新增）
  - 控制启用、扫描周期、grace、批量大小、PENDING 超时、允许回收的 kind。
- `AsyncTaskOrphanReaper`（拟新增）
  - 只处理新五种 kind。
  - PENDING 以 `CREATED_AT` 判断；RUNNING 以过期 lease 加 grace 判断。
- `AsyncTaskStore` / `JdbcAsyncTaskStore`
  - 新增条件式“仍为 orphan 才置失败”的原子操作并返回实际获胜记录。
  - 同时收紧 JDBC 状态更新与取消的竞争条件。

## 3. 核心流程

### 3.1 提交

1. 复用 `require_context()` 验证 `X-Internal-Token`，取得 tenant/user/scopes/department/trace。
2. 检查 JWT 剩余有效期能覆盖最小启动窗口；不足则返回稳定的 `503`，不创建任务。
3. 生成 UUID taskId，将业务输入与 webhook URL 发送给中央服务；不发送或持久化 token。
4. 使用同一 taskId 对 create 的网络歧义做查询式对账，避免因重试生成第二个任务。
5. 使用本实例稳定 workerId 取得租约。未取得租约则不返回 `202`，执行补偿式查询并映射错误。
6. 将执行 handle 注册入内存并立即启动 heartbeat；任务即使尚在并发 semaphore 队列中也续租。
7. 返回 create 时的旧版 `PENDING` 十字段快照；随后 GET 可以观察到 `RUNNING`。

### 3.2 执行、完成与取消

1. manager 根据 kind 调用现有 service。
2. service 正常返回 DTO 时更新 `SUCCEEDED`；抛异常时写入脱敏错误并更新 `FAILED`。
3. terminal update 的响应是权威结果。若取消先获胜，迟到的成功更新返回
   `CANCELLED`，manager 不得覆盖。
4. DELETE 先调用中央 cancel，再设置本地 stop flag 并取消本地 task。
5. 由于现有 AgentScope runner 会把 `CancelledError` 转成 `stop_reason=CANCELLED`，
   完成路径必须先检查 stop flag/中央状态，不能仅依赖异常传播。
6. DELETE 发生网络歧义时以 GET 对账；仅在中央已为 `CANCELLED` 时返回旧版成功响应。

### 3.3 心跳与 token 生命周期

- 心跳使用原请求 token，不持久化、不记录。
- 同一 task/worker 的租约续期只对网络错误与 5xx 做有界重试；4xx 不自动重试。
- 运行硬截止时间为：
  `min(配置最大运行时长, token.exp - 当前时间 - 安全余量)`。
- 到截止时间前 manager 主动尝试将任务置 `FAILED` 并取消本地执行；若最终写回也因
  token 过期失败，依赖 reaper 收敛。
- 这意味着本方案明确不支持超过调用 token 生命周期的长任务。

### 3.4 SSE

- 任务 SSE：先 GET 验证任务属于当前 tenant 且 kind 属于五种 AgentScope kind，
  然后保持中央现状的 query `lastEventId` 优先、`Last-Event-ID` header 次之；逐帧转发
  `id/event/data`，客户端断开时关闭上游。
- Reflexion SSE：producer 调用现有 `ReflexionService.run()`，通过有界
  `asyncio.Queue` 推送 `attempt-start/answer/critique/done`；generator 编码 SSE；
  断开时取消并 await producer。
- 中央当前只发布任务生命周期 `status` 事件。旧服务 DAG 的
  `dag-planned`、`dag-worker-start` 等细粒度事件不会自然出现。这是本方案的已知
  兼容弱点，必须在审批时确认是否以交付基线的生命周期范围为准。

## 4. 改动范围

- Python：新增领域 DTO、manager、client；修改依赖、路由、应用组装、配置、
  JWT 验证结果、Reflexion 进度出口；增加契约、单元、集成、安全、双跑测试。
- Java：新增 reaper 配置/调度；扩充 store 原子操作；修复状态/取消并发；增加
  Agent kind 的旧 webhook 投影与别名 header。
- 数据库：不新增业务列；为 orphan 查询补 `(STATUS, CREATED_AT)` 索引。若只采用
  生命周期 SSE，不新增事件表。
- 部署：Python 增加中央地址、worker/租约/心跳/并发/截止参数；Java reaper 默认关闭，
  分环境启用。

## 5. 扩展性与实施成本

- 扩展第六种任务时，需要新增 kind/handler 注册和 DTO 映射，结构清楚。
- 可水平扩容提交实例；单个任务由租约绑定到最初执行实例，不能迁移。
- 中等实施成本；主要复杂度集中在 manager 状态机、取消竞态、token 截止和 SSE 流代理。
- 不引入第二份任务数据库，维护成本相对低。

## 6. 风险评审

### 兼容性

- JSON 十字段需由中央十四字段投影，`input` 中 webhook URL 的旧表现需显式还原。
- 列表必须过滤五种 kind；否则同租户 workflow 任务会泄漏到 `/agent/tasks`。
- 同租户但非 Agent kind 的 GET/DELETE/SSE 必须返回 404，避免跨领域误取消。
- 最大缺口是 DAG 细粒度 SSE。若其属于本期硬门禁，本方案不能原样获批。

### 事务、并发与幂等

- create 成功而 lease/响应失败会留下 PENDING；reaper 是最终补偿，不是原子提交。
- JDBC 当前普通 SELECT + UPDATE 存在取消与完成互相覆盖风险，必须改为条件更新或加锁。
- terminal update、cancel、reaper 都必须使用“当前状态仍满足条件”的 CAS 语义。
- 对同一 UUID 的 create 可对账；整个外部 POST 没有 idempotency key，客户端重发仍会
  产生新任务，这是明确非目标。

### 性能

- heartbeat 数量与运行中/排队任务线性增长；需抖动、限流与共享 HTTP client。
- SSE 是一客户端一上游连接；需配置连接池与断开清理。
- orphan 扫描必须批量、走索引，不能全表扫。

### 安全

- token 只在 request context/handle 内存中；日志、中央 input/result/error 均不得包含。
- 中央 webhook URL 需拒绝 userinfo，并保持 scheme/host 校验；不得由 Python 另发一次。
- 错误只允许稳定错误码与脱敏摘要。

### 数据迁移

- 仅新增索引，迁移风险较低；需要兼容已有表与不同 JDBC 数据库语法。
- 内存 store 同样要实现语义，但无 schema 迁移。

### 灰度与回滚

- 先部署中央兼容改动且 reaper 关闭，再部署 Python 暗流量，最后按 kind/租户开启。
- 回滚 Python 路由不会破坏同步端点；残留任务由 reaper 收敛。
- 回滚中央代码前必须先关 reaper；新增索引可保留，无需紧急回退。

## 7. 典型失败场景

- create 超时但实际上成功：用同一 taskId GET 对账。
- lease 返回丢失：GET 检查 worker/lease；不能盲目换 workerId 重租。
- heartbeat 短暂失败：有界重试；超过安全窗口主动失败/取消。
- cancel 与成功同时发生：中央 CAS 决胜，客户端接受中央返回状态。
- worker 崩溃：租约到期加 grace 后 reaper 置 `FAILED`。
- token 先于任务过期：本地截止机制提前收敛，极端情况下 reaper 兜底。
- SSE 上游半帧/CRLF/多行 data：增量解析，不按 HTTP chunk 等同 SSE frame。
- webhook post-commit enqueue 丢失：需要监控并在最终方案中保留为已知残余风险。

## 8. 验证重点

- 五端点 create-before-lease-before-202 的调用顺序与补偿。
- 同租户跨 kind 隔离、跨租户 404/空列表。
- cancel/success/reaper 三方竞争的唯一终态。
- runner 吞取消异常时仍不能写回成功。
- token 未落库/未入日志的静态与运行时断言。
- SSE 帧级透传、断线清理、Last-Event-ID 优先级。
- reaper allowlist 不碰旧 `agent.task` 与 workflow kind。
