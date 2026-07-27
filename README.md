# agentscope-platform

基于 AgentScope 2.0 的独立 Agent 编排项目，用绞杀者迁移方式逐步替换
`langchain4j-platform/agent-service`。现有 Java 平台继续提供鉴权、知识检索、数据分析、
业务流程、订单、异步任务、互操作和评测能力。

当前状态：**Phase 1 只读 ReAct 与候选路由准备**。已具备分层边界、FastAPI 服务、内部 JWT
验签、LiteLLM/AgentScope Runner、兼容 `/agent/run` 契约、只读工具、执行轨迹、运行
治理日志和可选 OpenTelemetry。候选 `/agent/v2/run` 路由默认关闭，可用于后续灰度与
回滚演练。本地真实三轮双跑已通过，但语义评分、可归因货币成本和 edge 切流证据尚未
完成，因此不宣称与旧 `agent-service` 生产等价。

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

当前只注册五个只读工具：

- `current_time`
- `rag_search`
- `order_query`
- `schema_explore`
- `analytics_sql`

所有业务服务调用都从已验证的运行上下文传播内部 token 和 `X-Trace-Id`，模型参数不能
覆盖租户身份。遗留响应中的 `thought` 字段保留为空，不暴露模型隐藏推理。

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
```

`/agent/run` 默认要求来自旧平台 edge-gateway 的 `X-Internal-Token`。本地只验证路由时，
可以在 `.env` 中临时设置 `INTERNAL_AUTH_REQUIRED=false`；该设置不得用于共享或生产环境。

`/agent/v2/run` 默认不注册。只有显式设置 `AGENT_V2_ENABLED=true` 并重启后才可访问，
操作与回滚顺序见[候选路由指南](docs/candidate-route.md)。

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
uv build
docker compose -f compose.yml config
```

真实旧/新服务双跑使用 `agentscope-shadow-eval`。它默认只允许 localhost，凭据只能通过
环境变量注入，报告不保存回答、工具 observation 或 token。具体命令和门禁口径见
[Shadow 双跑指南](docs/shadow-evaluation.md)。

## 文档入口

- [目标架构](docs/architecture.md)
- [现状与迁移边界](docs/current-system-map.md)
- [重构路线图](docs/migration-plan.md)
- [兼容契约](docs/contracts.md)
- [测试与发布门禁](docs/testing-and-gates.md)
- [Shadow 双跑指南](docs/shadow-evaluation.md)
- [候选路由与回滚](docs/candidate-route.md)
- [开发指南](docs/development.md)
- [ADR-0001：采用绞杀者迁移](docs/adr/0001-strangler-agent-orchestrator.md)
