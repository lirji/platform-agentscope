# agentscope-platform

基于 AgentScope 2.0 的独立 Agent 编排项目，用绞杀者迁移方式逐步替换
`langchain4j-platform/agent-service`。现有 Java 平台继续提供鉴权、知识检索、数据分析、
业务流程、订单、异步任务、互操作和评测能力。

当前状态：**Phase 5 全量默认切换**。除 Phase 1/2 同步能力外，已提供兼容
`/agent/dag/run`、`/agent/dag/plan-run`、`/agent/analyst/run` 契约，具备拓扑分层、
同层有界并行 worker、直接上游结果传播、通用/分析专用规划、synthesis 以及
critic/replan 质量闭环；五类异步提交、任务查询/取消/可恢复 SSE、Reflexion SSE 也已接入
中央 `async-task-service`。Process 始终只读；异步总开关与中央 orphan reaper 默认关闭，
旧平台 edge 与 interop 的默认目标已切到 `agentscope-orchestrator`，能力发现
`GET /agent/capabilities` 也已兼容。旧 Java 服务仅保留为显式整服务回滚目标；当前只读
工具面不宣称覆盖 Java-only 高风险/写能力，也未执行生产部署。

## 技术基线

- Python 3.12
- AgentScope 2.0.5
- FastAPI + Uvicorn
- uv
- HTTPX
- Pydantic Settings
- PyJWT

独立的 `agentscope-runtime` 已进入归档路线，新项目直接采用 AgentScope 2.0，并用自有
API/领域边界包装框架。

## 目录

```text
src/agentscope_platform/
├── api/                    # FastAPI 路由、依赖和异常映射
├── application/            # 用例服务与端口
├── domain/                 # 框架无关的 DTO、租户和运行语义
├── evaluation/             # 旧/新 Agent Shadow 对比与迁移门禁
├── infrastructure/
│   ├── agentscope/         # AgentScope 2.0 适配器
│   ├── http/               # 旧 Java 平台工具客户端
│   ├── observability/      # 安全结构化日志与可选 OTel
│   └── security/           # 内部 JWT 兼容实现
└── main.py
```

默认只注册七个只读工具：

- `current_time`
- `rag_search`
- `order_query`
- `schema_explore`
- `analytics_sql`
- `workflow_status`
- `workflow_tasks`

所有 Java 领域服务调用都从已验证的运行上下文传播内部 token 和 `X-Trace-Id`，模型参数不能
覆盖租户身份。入站 token 严格校验 issuer、唯一 audience、kid、token-use、jti、时间窗和最大
TTL。MCP/Browser/Code 外部 provider 不接收 caller token，只接收独立 key 签发且按 audience/action
限权的短时 `X-Agent-Service-Token`。遗留响应中的 `thought` 字段保留为空，不暴露模型隐藏推理。

Phase 4 已加入默认关闭的受治理 `refund_start`。它需要 `agent` scope、`Idempotency-Key`
以及由 `/agent/tool-confirmations` 对精确工具参数签发的一次性短时 grant；旧的仅工具名确认头
会被拒绝。工具只调用 Java workflow 发起流程，绝不自动审批。配置、安全语义、灰度和回滚见
[受治理工具运行手册](docs/governed-tools.md)。

标准 Streamable HTTP MCP 客户端也已迁移，但默认关闭。服务只注册
`AGENT_MCP_TOOLS_JSON` 中逐项声明策略的工具，不支持 stdio、不自动发现并暴露远端工具，
也拒绝 `platform.agent.*` 递归调用。MCP 写工具复用相同的确认和幂等策略。

`browser_*`、`browser_see` 与 `code_exec` 已迁移为默认关闭的远端 sandbox adapter。
orchestrator 不安装 Playwright、不启动 shell/JVM/container，也没有本地 fallback。Browser 同时
要求目标 host allowlist；Code 请求固定禁网、临时 workspace，并携带超时、输出、内存和进程上限。

## 本地启动

```bash
cp .env.example .env
uv sync --dev
./scripts/dev.sh
```

健康检查：

```bash
curl http://localhost:8085/health
curl http://localhost:8085/readiness
curl -H "X-Internal-Token: ${INTERNAL_TOKEN}" http://localhost:8085/metrics
```

`/agent/run` 默认要求来自旧平台 edge-gateway 的 `X-Internal-Token`。本地只验证路由时，
可以在 `.env` 中临时设置 `INTERNAL_AUTH_REQUIRED=false`；该设置不得用于共享或生产环境。
`/metrics` 同样要求有效内部 token，避免匿名暴露运行时与容量信息。
`/readiness` 会并发探测模型网关，以及所有已启用的 async-task、MCP、Browser、Code
和 Redis confirmation replay 依赖；任一必要依赖不可用时返回 503。Knowledge、Analytics、
Workflow、Order 会显示状态，但降级不阻止只依赖模型的请求进入。响应只包含稳定的
`UP`/`DOWN`/`DISABLED`，不会泄露地址或上游错误正文。

运行指标包含 Agent 延迟直方图、inflight、token、估算成本和终止原因。生产环境应按模型价格配置
`AGENT_INPUT_COST_USD_PER_MILLION_TOKENS` 与
`AGENT_OUTPUT_COST_USD_PER_MILLION_TOKENS`；默认 0 只保留 token 事实，不产生非零成本估算。

`/agent/v2/run` 默认不注册。只有显式设置 `AGENT_V2_ENABLED=true` 并重启后才可访问，
操作与回滚顺序见[候选路由指南](docs/candidate-route.md)。

同步 DAG 入口为 `/agent/dag/run`，与 `/agent/run` 一样强制校验内部 JWT。请求格式、
兼容行为与限制见 [DAG 编排指南](docs/dag-orchestration.md)。

`/agent/dag/plan-run` 会先生成通用 DAG；`/agent/analyst/run` 使用“先探表后取数”的
只读数据分析 Planner。两者都复用相同 DAG 引擎。

同步 sibling 入口为 `/agent/chain`、`/agent/vote` 和 `/agent/reflexive`。服务端步骤、
并发/阈值配置、安全边界与未迁范围见
[Sibling Orchestrators 指南](docs/sibling-orchestrators.md)。

`/agent/process/run` 是安全收窄的只读候选：可查询实例状态和待审批任务，但不会发起或
审批退款。迁移决策见
[Process 只读切片](docs/delivery/phase-2-process-readonly-slice.md)。

异步入口、中央依赖、token 截止、SSE 恢复、灰度和回滚见
[异步编排运行手册](docs/async-orchestration.md)。本地需先启动中央服务，再显式设置
`ASYNC_TASK_ENABLED=true`；默认关闭不会改变既有同步路径。

所有 Java、MCP、Browser、Code 与 async-task 出站调用按进程复用同一个异步连接池，并传播
绝对 `X-Request-Deadline-Ms`。每个依赖有独立的非阻塞 bulkhead 与 circuit breaker；超过并发、
父请求剩余时限或熔断窗口时立即返回稳定的 unavailable 错误。写操作不会在这一层自动重试，
也不会把下游失败降级成伪成功。池大小、keep-alive、并发和熔断阈值见 `.env.example`。

CI、CycloneDX SBOM、镜像扫描、OIDC 签名、发布后验证与 digest 回滚见
[软件供应链与可信发布](docs/software-supply-chain.md)。

语言中立的可恢复执行入口为 `POST /agent/sessions/{sessionId}/run` 与对应 GET；生产以 Redis
revision CAS/租约持久化，每个完整工具边界 checkpoint，且不保存 caller token、原始 goal 或
AgentScope state。版本化能力发现使用 `GET /agent/capabilities/registry`；旧四项 discovery
响应保持不变。契约、安全恢复与回滚见
[Agent 会话检查点与能力注册](docs/agent-sessions-and-capabilities.md)。

## Docker 启动

```bash
cp .env.example .env
docker compose up --build
docker compose logs -f orchestrator
docker compose down
```

容器内默认通过 `host.docker.internal` 访问宿主机上的 LiteLLM 和旧 Java 服务，相关地址可在
`.env` 中覆盖。Compose 不创建或清理旧平台的数据卷。

## 验证

```bash
uv run python scripts/export_contracts.py --check
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest --cov=agentscope_platform --cov-report=term-missing --cov-fail-under=80
uv run python scripts/shadow-smoke.py
uv run python scripts/test_supply_chain_config.py
uv build
docker compose -f compose.yml config
```

真实旧/新服务双跑使用 `agentscope-shadow-eval`。它默认只允许 localhost，凭据只能通过
环境变量注入，报告不保存回答、工具 observation 或 token。具体命令和门禁口径见
[Shadow 双跑指南](docs/shadow-evaluation.md)。`agentscope-shadow-cost` 可将报告 trace
与脱敏 LiteLLM/OTel 账本关联，执行 token/估算成本门禁。

DAG 结构兼容双跑使用 `agentscope-dag-shadow-eval`，只在报告中保存 case、目标标签、
状态码、延迟和稳定错误码，不保存任务结果或综合答案。

## 文档入口

- [目标架构](docs/architecture.md)
- [现状与迁移边界](docs/current-system-map.md)
- [重构路线图](docs/migration-plan.md)
- [兼容契约](docs/contracts.md)
- [测试与发布门禁](docs/testing-and-gates.md)
- [Shadow 双跑指南](docs/shadow-evaluation.md)
- [候选路由与回滚](docs/candidate-route.md)
- [DAG 编排指南](docs/dag-orchestration.md)
- [Sibling Orchestrators 指南](docs/sibling-orchestrators.md)
- [异步编排运行手册](docs/async-orchestration.md)
- [开发指南](docs/development.md)
- [受治理工具运行手册](docs/governed-tools.md)
- [Agent 会话检查点与能力注册](docs/agent-sessions-and-capabilities.md)
- [运行版本与评测数据闭环](docs/evaluation-versioning.md)
- [生产发布、RPO/RTO 与恢复手册](docs/operations/production-release-runbook.md)
- [ADR-0001：采用绞杀者迁移](docs/adr/0001-strangler-agent-orchestrator.md)
