# 目标架构

## 1. 架构目标

`agentscope-platform` 只承接 Agent 推理、工具选择和多 Agent 编排。原
`langchain4j-platform` 继续承载成熟的领域能力和平台治理能力。

```text
Client / Showcase Frontend
          │
          ▼
edge-gateway
Casdoor / Session / API Key → X-Internal-Token
          │
          ├──────────────────────────────────────────┐
          ▼                                          ▼
agentscope-platform                           Java domain services
AgentScope 2.0                                knowledge / analytics
          │                                   workflow / order / vision
          ├── LiteLLM                         async-task / channel
          ├── HTTP tools ────────────────────▶
          ├── MCP tools
          └── OTel / audit / cost events
```

## 2. 分层

### Domain

保存语言中立的请求、响应、租户身份和执行结果。禁止依赖 AgentScope、FastAPI、HTTPX。

### Application

定义 `AgentRunner` 等端口以及 Agent 用例服务。应用层决定业务流程，不感知框架对象。

### Infrastructure

- `agentscope/`：创建 AgentScope Agent、模型和工具。
- `http/`：调用保留的 Java 服务。
- `security/`：兼容现有内部 JWT。
- 后续增加 `tasks/`、`observability/`、`audit/`。

### API

提供旧 `/agent/**` 兼容面和健康接口。外部 DTO 不直接返回 AgentScope Event、Msg 或 State。

## 3. 依赖规则

```text
api ───────▶ application ───────▶ domain
 │                 ▲
 └──▶ infrastructure ┘
```

`domain` 永远位于依赖方向最内层。AgentScope 升级只能影响基础设施适配器和必要的组装代码。

## 4. 请求生命周期

1. edge-gateway 验证外部凭据并签发 `X-Internal-Token`。
2. API 层验证 HS256/RS256、过期时间及 `sub/uid/scopes/dept`。
3. 生成或复用 `X-Trace-Id`。
4. 构造不可变 `RunContext`。
5. AgentScope Runner 为本次请求创建独立 Agent。
6. plan-run/analyst 请求先通过独立 Planner 端口生成语言中立 DAG；空或无效计划回退单任务。
7. 普通请求直接执行；DAG 请求先做拓扑分层，每层 worker 有界并发，层间传递直接依赖结果。
8. 工具经 HTTP/MCP 调用 Java 服务，并传播 token 与 trace。
9. DAG 在全部 worker 完成后执行 synthesis；每次 runner 调用都复用同一不可变
   `RunContext`，但创建独立 Agent。
10. AgentScope 返回结果，应用层映射成稳定 DTO。
11. API 返回兼容 JSON/SSE，同时记录评测、审计、成本与追踪数据。

每次请求创建独立 Agent 是 Phase 0 的安全选择，优先保证租户和会话隔离。引入持久会话后，
必须使用 `(tenant_id, user_id, session_id)` 复合键，并验证不同租户不能恢复彼此状态。

## 5. 运行与部署

- AgentScope 模型调用继续指向 LiteLLM，不在应用中维护 provider switch。
- 服务默认无状态，可横向扩容。
- 长期任务、取消、SSE 和 webhook 状态最终仍以 `async-task-service` 为权威。
- 会话/Agent 状态不得只存在于单进程内存。
- 探针不要求业务身份；其他业务路径默认要求内部 JWT。

## 6. 安全不变量

1. 无有效内部 JWT 的业务请求返回 401。
2. 工具不能接收模型自行生成的 tenantId；租户只来自 `RunContext`。
3. 工具结果进入模型前要限制大小并标记来源。
4. 写工具默认禁止自动并行和自动重试。
5. workflow 工具必须保留人在环，不提供自动审批能力。
6. code/browser 工具必须进入隔离 sandbox，不与 API 进程共享宿主文件系统。
7. prompt、工具输入输出和模型结果不得写入包含密钥的日志。

## 7. 后续演进

- Phase 1：只读 ReAct 工具与完整轨迹。
- Phase 2：DAG run、plan-run 与 Analyst 同步入口已迁；继续迁移 critic/replan、
  Reflexion/Voting/Chaining。
- Phase 3：统一异步任务、SSE、取消和 webhook。
- Phase 4：受治理的副作用工具、Browser、MCP、Sandbox。
- Phase 5：灰度切换并移除旧 Java 编排代码。
