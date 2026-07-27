# 现状与迁移边界

## 1. 行为基线

旧项目：`../langchain4j-platform`

重点基线：

| 能力 | 旧实现位置 | 新项目策略 |
|---|---|---|
| ReAct | `agent-service/DeepAgentService` | 迁移到 AgentScope Agent |
| 工具注册 | `AgentAction` + Spring Bean | AgentScope Toolkit + 自有 Tool Policy |
| DAG | `agent-service/dag` | `run`、`plan-run` 已迁；critic/replan 待迁 |
| Analyst/Process | `agent-service/analyst`,`process` | Analyst 同步 Planner 已迁；Process 待迁 |
| Voting/Reflexion/Chain | `agent-service` 对应包 | 迁移为应用编排器 |
| 异步任务 | `agent-service/async` + `async-task-service` | 中央任务服务保留 |
| 对外 A2A/MCP | `interop-service` | 首期保留，代理新服务 |
| 评测 | `eval-service` | 保留并扩充双跑门禁 |

## 2. 必须保留的 Java 服务

- `edge-gateway`：外部身份交换、限流、路由。
- `auth-service`：账号、会话、RBAC。
- `knowledge-service`：多路检索、向量库、ES、GraphRAG、文档授权。
- `analytics-service`：受控 NL2SQL 与 schema 探索。
- `workflow-service`：Flowable、事务、outbox、人在环。
- `order-service`：租户隔离的订单读取。
- `async-task-service`：任务状态、租约、取消、webhook。
- `channel-service`、`interop-service`、`eval-service`、`vision-service`、`voice-service`。
- LiteLLM：模型路由、failover 和 provider 治理。

## 3. 迁移到新项目的代码类别

- Prompt 与结构化输出定义。
- Agent loop、计划、委派、路由和 handoff。
- DAG worker、synthesis、critic、replan。
- Voting、Reflexion、Prompt Chaining。
- Java `AgentAction` 的 Python HTTP/MCP 适配器。
- Agent 事件、轨迹与评测采集。

## 4. 不直接复制的代码

- Spring 配置类和 Bean 装配。
- Java `ThreadLocal` 租户上下文。
- LangChain4j `AiServices` 接口。
- Java DTO jar。
- 领域服务内部实现。

这些能力要转换为语言中立契约和 Python 适配器，而不是逐行翻译。

## 5. 第一批工具

| 工具 | 类型 | 副作用 | 首批 |
|---|---|---:|---:|
| `current_time` | 本地 | 无 | 是 |
| `rag_search` | HTTP | 无 | 是 |
| `order_query` | HTTP | 无 | Phase 1 |
| `schema_explore` | HTTP | 无 | Phase 1 |
| `analytics_sql` | HTTP | 只读数据库 | Phase 1 |
| `workflow_status/tasks` | HTTP | 无 | Phase 2 |
| `refund_start` | HTTP | 有 | Phase 4 |
| `mcp_call` | MCP | 取决于远端 | Phase 4 |
| `browser_*` | Sandbox | 外部交互 | Phase 4 |
| `code_exec` | Sandbox | 高风险 | Phase 4 |
