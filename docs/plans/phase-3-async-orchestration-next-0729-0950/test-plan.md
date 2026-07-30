# 测试方案与验收标准

## 1. 测试原则

- 先冻结旧 `langchain4j-platform/agent-service` 的 HTTP/JSON/SSE fixture，再实现新端点。
- 所有中央 client 测试使用确定性 fake/MockTransport；跨仓集成使用真实进程与数据库。
- 并发正确性不能只测顺序 happy path，必须使用 barrier/latch 制造取消、完成、reaper 竞争。
- token、租户、webhook 与错误脱敏既做行为测试，也做持久化/日志负向检查。
- 模型双跑比较结构和质量阈值，不要求非确定模型输出逐字相等。

## 2. 单元测试

### 2.1 Python 领域映射

拟新增 `tests/test_async_task_domain.py`：

- 中央十四字段到旧十字段投影精确匹配 `AgentAsyncTask`。
- `webhookUrl` 从业务 input 正确投影到旧 `input`，但 token/header 永不出现。
- 五种提交 request 的 `extra` 行为保持现有模型：run 严格、DAG run 严格、
  plan/analyst/reflexion 的现状不被意外改变。
- kind 白名单：仅 `agent.run/agent.dag/agent.dag-plan/agent.analyst/agent.process`。
- terminal/非 terminal 状态判定和稳定错误映射。

验收：所有字段、null、时间格式、枚举值与旧 fixture 一致；未知中央字段不会泄漏到旧 JSON。

### 2.2 中央 client

拟新增 `tests/test_async_task_client.py`：

- create/get/list/lease/update/cancel 的 method、path、header、body。
- `X-Internal-Token`、`X-Trace-Id` 转发；不写日志。
- create/lease/DELETE 响应丢失时的 GET 对账。
- 网络错误、超时、4xx、5xx、非法 JSON、中央稳定错误体的映射。
- heartbeat 只重试网络/5xx，且重试有上限和抖动；4xx 不重试。
- SSE read timeout 关闭，connect/write/pool timeout 有界。
- SSE parser 覆盖任意 chunk 分割、CRLF、注释、空行、多行 data、无 id、UTF-8 边界。

验收：没有对有副作用操作的无条件重试；所有失败产生稳定、脱敏的外部错误。

### 2.3 AsyncTaskManager 状态机

拟新增 `tests/test_async_task_manager.py`：

- 严格 create → lease → register/heartbeat → 202 顺序。
- create 成功/lease 失败时不启动执行。
- semaphore 排队期间仍 heartbeat。
- service 返回 DTO 后写 `SUCCEEDED`；抛异常写 `FAILED`。
- runner 吞掉 `CancelledError` 并返回 CANCELLED execution 时，stop flag 阻止写成功。
- cancel、完成、heartbeat 失败和本地 shutdown 各路径只完成一次。
- terminal update 返回已存在 `CANCELLED` 时接受中央决胜。
- token 剩余期不足时创建前拒绝；运行截止前主动失败并取消。
- registry 在完成后删除，不泄漏 task/token。

验收：每个 task 最多一个本地执行 handle；所有后台 task 均可 await 并收敛，无
“Task was destroyed but pending”。

### 2.4 DAG/Reflexion progress

扩充现有 DAG/规划/同级能力测试，并拟新增 `tests/test_progress_events.py`：

- 与旧 `AgentDagService` 一致的事件名、顺序和 data shape。
- 可选 sink 为 `None` 时现有同步返回值和调用顺序不变。
- sink 失败的策略明确：中央进度写失败不得悄悄变为业务成功；按配置重试后失败任务。
- Reflexion 事件固定为 `attempt-start/answer/critique/done`。
- 空问题在已建立 SSE 后发送兼容 error 事件；异常信息脱敏。
- 有界队列背压、客户端断开、producer 取消与资源回收。

验收：黄金事件 fixture 逐帧通过；同步端点测试零回归。

### 2.5 Java store、事件日志与 reaper

在 sibling 仓库增加对应 store/reaper/event 测试，具体测试类名以该仓库现有命名惯例
落地，计划目标包括：

- event append 的 tenant/kind/worker/lease/event-name 校验。
- 同一 event key 重试只产生一条记录。
- 并发 append 的 task sequence 严格递增且无重复。
- terminal 状态和 lifecycle event 同事务提交/回滚。
- JDBC cancel 与 success 并发只保留一个终态。
- reaper 仅命中：
  - 超过 PENDING timeout 的五类任务；
  - lease 过期且超过 grace 的 RUNNING 五类任务。
- reaper 不命中：
  - 旧 `agent.task`；
  - workflow kind；
  - 有效租约；
  - terminal；
  - 刚创建 PENDING。
- 两个 reaper 实例并发扫描只由条件更新获胜者发事件/webhook/audit。
- reaper batch、禁用开关和异常后下一周期继续。

验收：内存 store 与 JDBC store 语义一致；并发测试循环运行无偶发状态覆盖。

## 3. API 契约测试

拟新增/扩充 `tests/test_api_contract.py`、`tests/test_api_async_tasks.py`、
`tests/test_sse_proxy.py`：

### 五个提交端点

- `POST /agent/run/async`
- `POST /agent/dag/run/async`
- `POST /agent/dag/plan-run/async`
- `POST /agent/analyst/run/async`
- `POST /agent/process/run/async`

逐项验证：

- 状态码、content-type、十字段 JSON、字段 null 语义。
- 无 token/坏 token/过期 token。
- request extra 字段行为与同步端点一致。
- 中央 create 或 lease 失败时绝不返回 202。
- Process 输入通过现有只读 planning/runner 链路；写工具拒绝测试继续通过。

### 任务管理

- `GET /agent/tasks`
- `GET /agent/tasks/{taskId}`
- `DELETE /agent/tasks/{taskId}`
- `GET /agent/tasks/{taskId}/stream`

逐项验证：

- tenant scope 与旧“无分页参数、按创建时间倒序返回全部租户任务”的语义；Python 再过滤
  五种 Agent kind。若容量测试证明不可接受，另立中央分页契约，不在本期暗加参数。
- 同租户非 Agent kind 返回 404/不出现在列表。
- 另一租户 taskId 不可枚举：GET/DELETE/SSE 行为与旧服务一致。
- DELETE 的 PENDING/RUNNING/terminal/not-found 行为。
- SSE `text/event-stream`、`Last-Event-ID` 优先级、事件 id/name/data、断开清理。

### Reflexion

- `POST /agent/reflexive/stream`
- 正常多轮、提前通过、最大轮次、空问题、模型失败、客户端中断。

验收：导出 OpenAPI/JSON Schema 与受审 fixture 的语义差异为零；任何批准的非实质差异
必须记录原因，而非更新 fixture 掩盖回归。

## 4. 安全测试

- tenant A 无法 GET/DELETE/stream tenant B 的任务。
- 同 tenant 用户 A/B 的行为保持旧服务“tenant 级可见”现状，不擅自收紧为 user 级。
- 同 tenant 的 Agent API 无法访问 workflow 或旧 `agent.task`。
- scopes/department/trace 显式传递；并发请求不会串上下文。
- 数据库 `INPUT_JSON/RESULT_JSON/ERROR`、事件 `DATA_JSON`、webhook outbox payload 中
  搜索原 token 片段均为零。
- caplog/访问日志/HTTP client debug 日志中搜索 token 与 provider 原始异常均为零。
- webhook 拒绝非 HTTP(S)、空 host、userinfo；保留现有允许策略的其余部分。
- event append 不能伪造另一 worker、过期 lease、终态任务或非法 event name。
- Process 只读测试覆盖直接请求、异步请求和 DAG worker。

验收：上述任一负向测试失败即阻断发布。

## 5. 跨仓集成与故障注入

建立本地双仓测试拓扑：`agentscope-platform` + `async-task-service` + 测试数据库。

场景：

1. 正常提交到成功，检查任务、事件、SSE、webhook 各一次。
2. 中央 create 成功后断连接，Python 以同 taskId 对账，不产生第二任务。
3. lease 成功后断连接，Python 查询 owner/lease 决定是否执行。
4. heartbeat 连续失败，任务在截止前失败；若写回失败则 reaper 最终失败。
5. Python 进程 `SIGKILL`，租约到期后 reaper 收敛，且没有第二次推理。
6. cancel 与模型返回使用 barrier 同时触发，最终状态唯一且不回退。
7. 中央重启后用旧 Last-Event-ID 重连，事件日志继续回放。
8. webhook endpoint 先失败后成功，验证重试、幂等 header 和不重复终态。
9. 数据库暂时不可用，验证 API 不虚假返回 202、reaper 不误判。
10. 两个 Python 实例与两个 Java reaper 实例并发。

验收：

- 所有任务最终处于唯一 terminal 状态；
- 无跨租户/跨 kind 数据；
- SSE 无漏事件，按 task sequence 单调；允许网络重连导致客户端收到同一幂等事件时，
  consumer 可凭 id 去重；
- webhook 最终一次逻辑交付，物理重试可由任务/状态 header 幂等。

## 6. 双跑回归

### 用例

- 复用现有 shadow/evaluation 基础设施，增加五类 async case：
  - 简单 ReAct；
  - 多层 DAG；
  - DAG replan；
  - analyst；
  - process 正常只读与写意图拒绝；
  - Reflexion 早停/满轮。
- 同一业务输入分别调用旧 Java agent-service 与新 Python 路径。

### 比较项

- HTTP 状态、字段集合、状态迁移、错误类别。
- SSE event name/order/data schema。
- 工具调用种类、租户上下文和只读策略。
- 结果结构、stop reason、评测分数与时延。

### 门禁

- 契约/安全：100% 通过，零容忍。
- Process 写工具调用：0。
- 任务终态收敛：100%。
- 质量阈值：沿用仓库现有 evaluation gate；若当前没有某类已批准数值，标记为
  “待产品/评测负责人确认”，不得临时发明。
- 性能：在同等模型依赖下报告 p50/p95 与 heartbeat/event 写放大；阈值在基线采样后批准。

## 7. 数据库迁移测试

- 空库建表/索引。
- 从当前 schema 原地升级，已有任务可查询，旧中央 producer 可继续 create/update。
- 重复执行迁移幂等。
- 大表索引创建时间与锁影响评估。
- 事件表 retention 分批清理；正在回放的任务不发生 SQL 错误。
- 回滚应用版本但保留新表/索引，旧版本仍可启动。

## 8. 灰度与回滚演练

- reaper 默认关闭；dry-run 指标先观测命中集合。
- 事件 append 双写但 SSE 仍读旧 live 路径，对比事件数量/顺序。
- 先内部租户、单 kind，再扩大五类。
- 关闭新异步路由后同步端点继续服务。
- 停止提交、等待/取消在途任务、启动 allowlist reaper 收敛残留。
- 恢复旧 `AGENT_URI`，验证旧任务查询策略与客户端路由无混淆。

验收：演练步骤、责任人、观测指标和最长等待时间在上线单中可执行；数据库新表无需紧急删除。

## 9. 最终命令与证据

agentscope-platform：

```bash
uv sync --dev
uv run ruff check .
uv run mypy src
uv run pytest
```

langchain4j-platform：

- 先读取该仓库构建说明与模块结构；
- 执行 async-task-service 的单模块测试；
- 再执行受影响协议/服务的聚合测试。
- 精确 Maven/Gradle 命令须在实施时从该仓库 wrapper/pom 事实确认，当前标记“待验证”。

最终证据包应包含：

- 两仓 commit SHA 与 dirty-state；
- OpenAPI/JSON Schema diff；
- 测试命令和完整结果；
- 并发/故障注入报告；
- 双跑矩阵；
- 数据库迁移与回滚演练记录；
- 未解决风险及批准人。
