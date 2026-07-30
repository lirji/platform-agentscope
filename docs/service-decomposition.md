# 服务拆分与责任矩阵

## 目标拓扑

```text
                         ┌──────────── LiteLLM ────────────┐
                         │ provider routing / failover     │
                         └──────────────▲───────────────────┘
                                        │
Client -> edge-gateway -> agent-protocol-gateway -> agentscope-orchestrator
              │                                  │
              │                                  ├─ knowledge-query-service
              │                                  ├─ analytics-executor
              │                                  ├─ workflow-service
              │                                  ├─ order-service
              │                                  └─ async-task-service
              │
              ├─ conversation-service/runtime
              ├─ knowledge-ingest-api -> async-task -> knowledge-ingest-worker
              └─ auth / channel / vision / voice

CI / Nightly -> ai-evaluation-runner -> edge / agent / knowledge targets
```

## 责任矩阵

| 能力 | 权威组件 | AgentScope 的角色 | 禁止进入 AgentScope |
| --- | --- | --- | --- |
| Agent 推理和 DAG | agentscope-orchestrator | 所有者 | 领域数据库 |
| A2A/MCP/Agent Card | agent-protocol-gateway | 被代理能力提供方 | push 状态、外部协议状态 |
| RAG 查询 | knowledge-query-service | 只读工具调用方 | 索引 client、授权关系 |
| 文档入库 | knowledge-ingest-api/worker | 可发起受治理任务 | 原文、解析器、sink 写入 |
| NL2SQL | Python planner + Java executor | 可生成查询计划 | DB 凭据、SQL 执行 |
| 审批流程 | workflow-service | 意图/文案辅助或工具调用 | Flowable、审批、outbox |
| 订单 | order-service | 只读或受治理工具调用 | 订单库 |
| 异步任务 | async-task-service | worker | 任务权威状态 |
| 普通 Chat | conversation runtime | 可选 handoff | memory/profile/cache |
| 视觉/语音 | vision/voice service | 工具调用 | 二进制媒体处理状态 |
| 身份授权 | edge/auth/auth-platform | 消费显式上下文 | 登录会话、角色关系 |
| 评测 | ai-evaluation-runner | 被测对象 | 在线请求强依赖 |

## 拆分顺序

1. 自动化架构与契约门禁。
2. 退役 Java Agent 的 release gate，收敛 Agent 协议面。
3. 统一评测 schema 和离线 runner。
4. 建立 Knowledge 原文与 ingestion job 权威状态。
5. 拆 Knowledge query/ingest 部署面。
6. 逐能力迁移 Analytics planner 和 Workflow AI adapter。
7. Conversation 先保持 Java state plane + 默认关闭的无状态 shadow；只有 history/SSE/质量门禁
   全部通过后才建立独立 runtime，且不得复用 AgentScope orchestrator 进程。

## 跨服务不变量

- 除探针外，业务调用必须验证内部 JWT。
- tenant/user/scope/department/trace 显式逐跳传播。
- 工具不能信任模型产生的身份字段。
- 副作用必须声明等级、幂等、审批、timeout 和 retry。
- 回滚以 capability/service 为单位，不做单请求静默 fallback。
- 新旧实现必须共同通过契约、跨租户、失败映射、双跑和成本质量门禁。

## Knowledge 一致性模型

S3-compatible object storage 保存不可变原文版本，是重建所有派生索引的事实源。每个 ingestion
job 使用 `(tenantId, sourceHash, requestedVersion)` 幂等键，并分别记录 vector、ES、graph、
registry 和 authz sink 状态。只有 required sinks 全部成功的版本才进入 `READY` 并对默认查询
可见；`PARTIAL`/超时 `PROCESSING` 由 reconcile 修复或明确标记 `FAILED`。

这是一套可恢复的最终一致模型，不宣称跨异构存储存在全局事务。
