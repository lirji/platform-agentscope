# 异步编排运行手册

## 架构与安全边界

Python 只负责进程内执行；`async-task-service` 是任务快照、事件、终态和 webhook 的唯一
权威。提交顺序固定为 create → lease → 返回 202，之后 manager 执行现有同步 service，
周期续租并写回唯一终态。内部 JWT 不持久化，任务硬截止不晚于
`min(ASYNC_TASK_MAX_RUNTIME_SECONDS, token.exp - safety)`。

中央 API 分为两个授权面：任务列表、查询、SSE 和取消按 `tenant + owner user` 隔离；
`lease/status/events` 只接受 `X-Async-Worker-Token`。worker token 与普通内部 JWT 使用不同
密钥，绑定 service/tenant/actor/worker/task/action，单次请求短时签发；Python 发送 worker
请求时不会同时转发 caller `X-Internal-Token`。状态和进度写入必须持有当前未过期租约。

五个中央 kind 固定为 `agent.run`、`agent.dag`、`agent.dag-plan`、`agent.analyst` 和
`agent.process`。任务 API 会隐藏同租户的其他 kind。Process 仍只装配只读 workflow/RAG
能力。

## 启用

1. 先部署兼容版 `async-task-service`，生产必须使用 JDBC。
2. 保持 `ASYNC_TASK_ORPHAN_ENABLED=false`，确认事件表和 outbox 初始化成功。
3. 配置 Python `ASYNC_TASK_BASE_URL`，先以 `ASYNC_TASK_ENABLED=false` 验证 readiness。
   启用前还必须配置稳定的 `ASYNC_TASK_WORKER_ID` 和至少 32 字节、且不复用 internal、
   confirmation 或 downstream key 的 `ASYNC_TASK_WORKER_JWT_SECRET`。
4. 对内部租户开启 async，再按 run → DAG → plan → analyst → process 扩大。
5. 验证 heartbeat 后，才以长 grace、小 batch 开启中央 orphan reaper。

关键默认值见 `.env.example`。`heartbeat * 3 <= lease`、`max_inflight >= max_concurrent`、
`token_safety > request_timeout` 由配置启动校验强制执行。

多副本部署时，`ASYNC_TASK_WORKER_ID` 是允许签发 worker token 的稳定服务身份；每个进程会在它后面
追加随机实例后缀作为实际 lease owner。首次 claim 会递增中央 `leaseEpoch`，续租必须同时匹配 owner
和 epoch。租约到期被其它副本接管后，旧副本的 heartbeat、status 和 progress 写入都会被 fencing。
四条 Java outbox/relay 链同样使用实例级 claim owner 和 TTL，只有仍持有未过期 claim 的实例可以
提交 delivered/retry/dead，进程退出后由其它副本重领。

## SSE 与恢复

任务流入口为 `GET /agent/tasks/{taskId}/stream`。query `lastEventId` 优先于
`Last-Event-ID` header。中央事件 ID 是 task-scoped 单调 sequence；重连时按该 ID 回放。
lifecycle data 是旧十字段任务，DAG progress 是 `{taskId,event,data,ts}`。

所有任务 lifecycle/progress 和 Reflexion SSE 在写出前都会递归遮蔽邮箱、中国手机号和身份证号；
上游坏帧或底层异常只返回稳定的 `AGENT_TASK_STREAM_FAILED` 或
`AGENT_REFLEXION_STREAM_FAILED`，不会带 provider body、异常文本或密钥。

任务 SSE 是持久任务的观察通道：客户端断开只关闭 Python→中央的上游 HTTP 流，不取消权威任务；
需要停止任务必须显式调用 `DELETE /agent/tasks/{taskId}`。Reflexion 流使用
`POST /agent/reflexive/stream`，不创建持久任务；客户端断开会取消 producer 协程并等待收敛。
中央 SSE 读取同时受 `ASYNC_TASK_STREAM_IDLE_TIMEOUT_SECONDS`（默认 30 秒无数据）和
`ASYNC_TASK_MAX_RUNTIME_SECONDS`（总时限）限制；连接在整个消费期间占用 async-task 专属
bulkhead 槽，超时、5xx 和传输失败会计入该依赖熔断，4xx 不会污染熔断状态。

## 故障处理

- 中央 create/lease 不成功：Python 不启动模型执行。
- heartbeat 失败或租约丢失：停止本地 work，不提交迟到成功。
- 用户取消：中央 CANCELLED 先获胜，再停止本地 work。
- `agent.run` 的 runner 返回 `stopReason=ERROR`：同步 `/agent/run` 为兼容旧契约仍返回
  该业务响应；异步入口必须写中央 `FAILED`、`result=null` 和
  `ASYNC_TASK_EXECUTION_FAILED`，禁止记录为伪成功。
- Python 崩溃：token 随进程消失；中央 reaper 只把五种 Agent kind 的 stale
  PENDING/RUNNING 标记为 `FAILED/ASYNC_TASK_ORPHANED`。
- Python 收到正常停止信号：先停止接收新任务，并在 `ASYNC_TASK_DRAIN_TIMEOUT_SECONDS`（默认 30 秒）
  内保持 heartbeat、等待在途任务完成；超时后只取消本地 work，不伪造终态。容器停止宽限必须大于
  drain（Compose/Helm 默认 45 秒）。当前执行闭包只存在于内存，进程崩溃后不会自动重放；租约到期
  fencing 后由 orphan reaper 明确失败。可跨进程续跑的语言中立 checkpoint 留待 AC-14。
- webhook 失败：由中央 outbox 重试/死信；Python 禁止直接投递。
- 依赖 bulkhead 满或 circuit open：立即返回稳定 unavailable，不排队扩大拥塞；读取能力由调用方
  明确显示暂不可用，副作用能力绝不自动重试或构造成功结果。

检查中央 dead outbox、过期 lease、orphan 数量和事件 append 错误。日志和指标不得以
taskId、prompt、result 或 token 作为高基数标签。

## 指标抓取与告警

两侧 scrape endpoint 都沿用内部 JWT 认证：

```bash
curl -H "X-Internal-Token: ${INTERNAL_TOKEN}" \
  http://localhost:8085/metrics
curl -H "X-Internal-Token: ${INTERNAL_TOKEN}" \
  http://localhost:8086/actuator/prometheus
```

Python 暴露：

- `agent_async_task_submissions_total{kind}`
- `agent_async_task_completions_total{kind,status}`
- `agent_async_task_heartbeat_failures_total`
- `agent_async_task_running{kind}`
- `agent_async_task_inflight{kind}`
- `agent_async_task_backlog{kind}`
- `agent_run_duration_ms_bucket{model,le}` / `_count` / `_sum`
- `agent_run_inflight{model}`
- `agent_run_terminations_total{model,reason}`
- `agent_run_tokens_total{model,direction}`
- `agent_run_cost_usd_total{model}`（按部署配置的每百万 token 费率估算）

中央服务暴露：

- `async_task_event_append_total{event,duplicate}`
- `async_task_orphan_failed_total{kind}`
- `async_task_backlog`（数据库中 `PENDING` 数量）
- `async_task_inflight`（数据库中 `RUNNING` 数量）

部署验收必须同时验证无 token 返回 401、带 token 返回 200，且至少执行一次任务后能看到
对应 counter/gauge。告警至少覆盖 heartbeat failure 增长、orphan failure 增长、backlog 持续增长、
inflight 长时间不归零、错误/超时终止率和 webhook dead outbox；延迟告警使用 histogram quantile，
token/cost 使用 rate 或窗口增量。上述自定义指标的标签中禁止出现 taskId、tenant、user、prompt、
result、webhook URL 或 token。Python 的 cost 是配置费率估算值，费率为 0 时不能当成真实零成本。

Python reader 按进程保存指标；多 worker 或多 pod 部署必须逐实例抓取，再由 Prometheus
聚合。不要只抓负载均衡地址中的任意一个实例。

## 回滚

1. 关闭 `ASYNC_TASK_ENABLED`，同步端点不受影响。
2. 关闭 `ASYNC_TASK_ORPHAN_ENABLED`，保留任务与事件表。
3. 将 edge 异步流量切回旧 `agent-service`；不要删除新表或重置 Git/数据库历史。
4. 等待已提交的新任务进入唯一终态或由人工按 taskId 处置 webhook dead letter。

不得通过恢复普通内部 JWT 访问 worker API 来回滚；若 worker JWT 配置异常，应停止新异步流量、
排空或明确失败在途任务，再回滚所有 signer/verifier 到上一组仍相互兼容的镜像和密钥。

本阶段不修改生产 `AGENT_URI`；正式切流仍需真实双跑、故障注入和独立审批。
指标修复的回滚只需恢复上一服务镜像，不涉及任务表、事件表或 API 契约迁移。
