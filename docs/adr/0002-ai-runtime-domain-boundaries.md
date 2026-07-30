# ADR-0002：保持窄 AgentScope 与 Java 领域数据面

## 状态

Accepted（2026-07-30）

## 背景

`agentscope-platform` 已替换 Java `agent-service` 的推理与多 Agent 编排。继续迁移时，如果把
Chat、RAG 存储、SQL 执行、Flowable、身份、任务状态和媒体处理一并搬入 Python，会形成新的
技术单体，并把数据、事务、安全和副作用责任耦合到模型运行时。

旧平台已经按限界上下文部署为多个服务；后续目标是收敛运行面和框架职责，而不是按语言重写
所有领域服务。

## 决策

1. `agentscope-orchestrator` 只拥有推理、计划、委派、工具选择、多 Agent 编排、质量闭环和轨迹。
2. AgentScope 类型只能出现在 `infrastructure/agentscope/` 适配器内。
3. Java 服务继续拥有：
   - Knowledge 原文、文档版本、索引、检索和 ReBAC；
   - Analytics schema allowlist、SQL guard、只读凭据和 SQL 执行；
   - Workflow Flowable 状态、人工审批、事务和 outbox；
   - Order、Auth、AsyncTask 和 Channel 的领域状态及副作用。
4. A2A/MCP/Agent Card 由独立的 Agent Protocol Gateway 负责；它不拥有模型或领域数据。
5. 评测作为独立 CLI/CI/Nightly Job 运行，不成为在线 Agent API 的请求依赖。
6. 若迁移普通 Chat，使用独立 `conversation-runtime`；会话、画像和缓存状态不得进入
   AgentScope 编排进程。
7. 跨语言边界以 OpenAPI/JSON Schema 为事实源，不共享框架状态对象。
8. Knowledge 入库拆分使用 S3-compatible 对象存储作为原文权威源，以异步任务、稳定版本号、
   逐 sink 状态和 reconcile 实现可恢复的最终一致。

## 依赖规则

```text
api -> application -> domain
 |          ^
 +-> infrastructure adapters

agentscope adapter -> AgentScope
http adapter       -> Java domain services
domain/application -X-> AgentScope, FastAPI, HTTPX, database or message broker
```

模型输出不能提供可信 tenant、user、department 或 scope；这些字段只来自已验证且显式传播的
请求/任务上下文。

## 后果

收益：

- 模型框架升级不会改变领域数据格式或事务语义。
- SQL、流程和索引凭据不会扩散到 Agent 运行时。
- Agent、Knowledge ingestion、query serving 和评测可按不同资源模型独立扩缩。
- Java/Python 双栈通过稳定契约协作，可逐能力 shadow、灰度和回滚。

代价：

- 需要维护跨服务契约和故障映射。
- Knowledge 多索引只能做到可观测、可补偿的最终一致，不能假设全局事务。
- 普通 Chat 若迁移会产生独立运行时，而不是复用一个“大而全”Python 服务。

## 禁止事项

- 不把 Flowable、SQL connection、Qdrant/ES/Graph/Redis store 或业务数据库 repository 放入
  `agentscope-platform`。
- 不按 chain、vote、reflexion、planner 等策略拆独立微服务。
- 不让 AgentScope Msg/Event/State 成为外部任务或持久化协议。
- 不在双跑和回滚门禁通过前删除 Java 回滚实现或直接修改生产路由。
