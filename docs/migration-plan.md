# AgentScope 重构路线图

## 总体策略

采用绞杀者模式，旧 `agent-service` 始终作为可回滚基线。迁移单位是“能力”，不是 Java 类。

## Phase 0：项目骨架

状态：已完成（2026-07-27，提交 `64bb738`）。

范围：

- Python/uv/AgentScope 2.0 项目。
- 分层与依赖规则。
- FastAPI、健康探针和 `/agent/run` 基本契约。
- 内部 JWT HS256/RS256 验签。
- LiteLLM 模型连接。
- `current_time`、`rag_search` 工具样板。
- Docker、Compose、测试和文档。

退出条件：

- 静态检查和单测通过。
- 无 API key 时服务可启动，readiness 明确降级。
- 无 token/伪造 token 被拒绝。
- 合法 token 的 tenantId 正确回写响应。

## Phase 1：只读 ReAct 垂直切片

状态：代码切片、离线门禁和 Shadow 双跑工具已完成；本地真实协议三轮双跑已通过。
订单事实证据和 trace 归因估算成本门禁已通过；开放式答案质量和 edge 灰度发布仍待
批准。候选 `/agent/v2/run` 默认关闭入口已准备。

范围：

- `current_time`
- `rag_search`
- `order_query`
- `schema_explore`
- `analytics_sql`
- AgentScope Event → `AgentStep` 轨迹映射
- timeout、budget、max steps、cancel、loop 策略
- token/cost/audit/OTel

发布方式：

- edge 新增 `/agent/v2/**`，或由旧 agent-service 做 façade。
- 同一评测集调用旧/新服务。
- 禁止写工具。

退出条件：

- 契约测试 100%。
- 跨租户安全用例 100%。
- 只读工具选择准确率不低于旧实现。
- P95 延迟和成本在批准阈值内。

## Phase 2：多 Agent 编排

范围：

- DAG plan/run。
- 分层并行 worker。
- synthesis、critic、replan。
- Analyst Planner。
- Voting、Reflexion、Prompt Chaining。
- Process 仅迁移只读查询部分。

退出条件：

- 循环 DAG、未知依赖、任务上限行为兼容。
- 同层并发不丢失租户/trace。
- critic/replan 达到旧评测基线。

## Phase 3：异步任务

范围：

- 复用 `async-task-service`。
- lease、心跳、取消、状态机。
- SSE、断点恢复、webhook。
- worker 重启恢复。

退出条件：

- 取消竞态测试通过。
- 重复 lease 不产生双执行副作用。
- webhook 重试不改变任务最终状态。
- 服务重启后任务可恢复或明确失败。

## Phase 4：受治理工具

范围：

- `workflow_status/tasks`
- `refund_start`
- MCP
- Browser
- Code Sandbox

必要前置：

- Tool Metadata：`read_only/side_effect/idempotency/approval/timeout/retry`。
- refund 使用业务幂等键。
- 不提供自动审批工具。
- Browser/Code 使用独立 sandbox。
- MCP 工具按远端能力和 scope 做 allowlist。

## Phase 5：灰度切换

1. Shadow：新服务运行但结果不返回用户。
2. 按能力灰度：只读 Agent 先切。
3. 按租户灰度：内部/测试租户先切。
4. 扩大流量，持续比较完成率、工具错误率、延迟、成本和安全事件。
5. 将 `AGENT_URI` 切换到新服务。
6. 保留旧镜像和配置一个完整回滚周期。
7. 稳定后移除旧 Java 编排代码，保留契约与回归用例。

## 工作清单

- [x] 生成新服务兼容 OpenAPI 和遗留 DTO JSON Schema 快照。
- [ ] 从运行中的旧服务导出 `/agent/**` OpenAPI 并做 breaking-change 比较。
- [x] 建立只读离线评测数据集。
- [x] 建立安全的旧/新 Shadow 双跑 CLI、相对/绝对指标门禁和脱敏报告。
- [x] 完成本地真实模型/服务单轮双跑，并修复 AgentScope iteration 与遗留 action step
  预算语义不一致。
- [x] 使用有效种子租户完成每案例三轮本地真实双跑和质量/P95 门禁。
- [x] 建立答案事实证据、W3C trace、脱敏成本账本 Join，并完成三轮本地门禁。
- [ ] 使用 Java eval-service/模型 grader 覆盖 RAG 与分析等开放式答案。
- [x] 完成 AgentScope Event 轨迹映射。
- [x] 迁移只读工具。
- [x] 接入安全运行日志、token 计量和可选 OTel。
- [ ] 实现 DAG 与 sibling orchestrators。
- [ ] 对接 async-task。
- [ ] 建立副作用 Tool Policy。
- [x] 完成候选服务侧 `/agent/v2/run` 开关与本地启停回滚演练。
- [ ] 完成 edge 按测试租户切流与回滚演练。
