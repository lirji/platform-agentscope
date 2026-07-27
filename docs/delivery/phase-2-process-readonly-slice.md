# Phase 2 Process 只读迁移切片

## 决策

旧 `/agent/process/run` 会规划并调用 `refund_start`，可能真实创建退款审批流程，不能作为
普通 Phase 2 代码迁移直接启用。本切片保留同步路径和 `AgentDagRunReply`，但将能力收窄为：

- `workflow_status`：GET 查询当前租户流程实例。
- `workflow_tasks`：GET 列出当前租户待审批任务，继续由 workflow-service 校验 approve scope。
- `rag_search`：查询退款政策依据。

不注册 `refund_start`、claim、unclaim、complete 或 purge。用户请求写操作时，候选服务只
能说明当前只读边界，不得声称操作成功；旧平台继续承担现有的人在环发起流程。

## 安全措施

1. Process Planner 使用独立只读 prompt。
2. 应用层检查规划结果；出现 `refund_start`、审批、认领等写操作标记时丢弃整个计划。
3. 安全 fallback 明确只允许三个只读工具。
4. Process 使用关闭 Critic/Replan 的独立 DAG 执行器，避免通用 Replanner 重新引入写任务。
5. AgentScope Toolkit 仅注册声明为 read-only 的 GET 查询工具。
6. 所有 workflow 调用传播已验证内部 token 和 trace，租户隔离仍由 workflow-service 兜底。
7. `/agent/process/run/async` 未迁移，避免绕开后续 async-task 治理。

## 兼容与回滚

同步请求仍为 `{"goal":"...","webhookUrl":null}`，响应复用 `AgentDagRunReply`。这是安全收窄，
不是旧有写能力的生产等价实现，因此 edge 不应把“发起退款”流量切到候选服务。

新端点尚未接 edge，停止候选路由即可回滚；旧 Java 服务和 workflow-service 无需修改。

## 验收

- 状态和待办查询只发送 GET。
- 请求身份、租户和 trace 原样传播。
- 403 转为不泄露底层细节的 approve scope 提示。
- 写操作规划被安全 fallback 替换。
- OpenAPI、测试、只读 baseline 和部署文档同步。

## 验证证据

- Ruff lint/format 与 strict mypy 通过。
- 182 个测试通过，总代码覆盖率 92.25%。
- JSON Schema/OpenAPI `--check` 通过。
- Shadow smoke、wheel/sdist 构建与 `docker compose config` 通过。
