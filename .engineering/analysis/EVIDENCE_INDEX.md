# 证据索引
- workspace: `/Users/liruijun/personal/LLM/agentscope-platform`
- generated_at: 2026-09-16
- protocol: project-deep-analysis/v1
- source_of_truth: 源码（README 仅线索）
- re_run_policy: REGENERATE_OWNED_ARTIFACT
- 能力状态标注：已实现 / 可选开关 / 规划中 / 推测

本文件是分析结论到源码的映射。可信度：`CONFIRMED` / `HIGH_CONFIDENCE` / `PARTIAL` / `UNCONFIRMED`。

---

## E-01 项目定位：绞杀者 Agent 编排服务

- 结论：本仓库是 `langchain4j-platform/agent-service` 的独立 Python 替换件，只承接推理与多 Agent 编排，不复制 Java 领域逻辑。
- 证据类型：构建元数据 + 应用描述 + 架构约束测试
- 文件路径：`pyproject.toml`；`src/agentscope_platform/api/app.py`；`AGENTS.md`；`tests/test_architecture_boundaries.py`
- 类名：`create_app`
- 方法名：N/A
- 配置项：`description = "AgentScope 2.0 orchestrator for incremental migration from langchain4j-platform."`
- 数据库表：N/A（本仓无 SQL）
- SQL：N/A
- 依赖：`agentscope==2.0.5`、`fastapi`、`httpx`
- 调用链：FastAPI 应用 → Application 用例 → Domain DTO → Infrastructure Adapter
- 可信度：CONFIRMED
- 能力状态：已实现

## E-02 AgentScope 不得越出适配器

- 结论：`agentscope` 只能出现在 `infrastructure/agentscope/`；`domain` 禁止 FastAPI/HTTPX/Redis/AgentScope。
- 证据类型：ArchUnit 风格导入扫描测试
- 文件路径：`tests/test_architecture_boundaries.py`
- 类名：N/A
- 方法名：`test_agentscope_imports_are_confined_to_adapter`、`test_framework_dependencies_do_not_cross_inward`、`test_domain_and_application_do_not_depend_on_outer_layers`
- 配置项：N/A
- 数据库表：N/A
- SQL：N/A
- 依赖：N/A
- 调用链：pytest 扫描 `src/agentscope_platform/**/*.py` 的 AST import
- 可信度：CONFIRMED
- 能力状态：已实现

## E-03 业务请求默认要求内部 JWT

- 结论：缺 token 且 `INTERNAL_AUTH_REQUIRED=true` 时返回 401；健康探针除外。`/metrics` 也要求 RunContext，因此也要 token。
- 证据类型：依赖注入 + 配置默认值 + 路由
- 文件路径：`src/agentscope_platform/api/dependencies.py`；`src/agentscope_platform/core/config.py`；`src/agentscope_platform/api/routes.py`
- 类名：N/A
- 方法名：`get_run_context`、`prometheus_metrics`、`health`、`readiness`
- 配置项：`internal_auth_required: bool = True`；`internal_jwt_header = "X-Internal-Token"`
- 数据库表：N/A
- SQL：N/A
- 依赖：`pyjwt`
- 调用链：Header `X-Internal-Token` → `InternalJwtVerifier.verify_with_expiry` → `RunContext`
- 可信度：CONFIRMED
- 能力状态：已实现（本地可关：可选开关 `INTERNAL_AUTH_REQUIRED=false`）

## E-04 JWT 校验 iss/aud/kid/token_use/jti/TTL

- 结论：内部 token 必须匹配算法、kid、typ、issuer、单一 audience、token_use、scopes、jti，且 TTL 有上限。
- 证据类型：验签实现
- 文件路径：`src/agentscope_platform/infrastructure/security/internal_jwt.py`
- 类名：`InternalJwtVerifier`
- 方法名：`verify_with_expiry`
- 配置项：`INTERNAL_JWT_MAX_TTL_SECONDS` 默认 300
- 数据库表：N/A
- SQL：N/A
- 依赖：`pyjwt`
- 调用链：`get_run_context` → `jwt_verifier.verify_with_expiry`
- 可信度：CONFIRMED
- 能力状态：已实现

## E-05 租户身份来自 JWT，不来自模型参数

- 结论：`RunContext.identity` 只从验签 claims 构造；工具通过 `current_run_context()` 取身份，Java 调用传播已验证 caller token。
- 证据类型：领域对象 + 工具适配 + HTTP 客户端
- 文件路径：`src/agentscope_platform/domain/agent.py`；`src/agentscope_platform/core/context.py`；`src/agentscope_platform/infrastructure/http/platform_client.py`；`src/agentscope_platform/infrastructure/agentscope/readonly_tools.py`
- 类名：`TenantIdentity`、`RunContext`、`PlatformClient`、`ReadonlyToolset`
- 方法名：`_request`、`rag_search`
- 配置项：N/A
- 数据库表：N/A
- SQL：N/A
- 依赖：N/A
- 调用链：JWT `sub/uid/scopes` → `RunContext` → ContextVar → 工具 → `X-Internal-Token` 出站
- 可信度：CONFIRMED
- 能力状态：已实现

## E-06 知识检索二次校验租户

- 结论：RAG 结果若带 `tenant_id` 且与当前身份不一致，工具返回错误，不把跨租户片段喂给模型。
- 证据类型：只读工具实现
- 文件路径：`src/agentscope_platform/infrastructure/agentscope/readonly_tools.py`
- 类名：`ReadonlyToolset`
- 方法名：`rag_search`
- 配置项：`AGENT_RAG_TOP_K` 等
- 数据库表：N/A（权威在 Java knowledge-service）
- SQL：N/A
- 依赖：HTTP → `KNOWLEDGE_BASE_URL/rag/query`
- 调用链：`rag_search` → `PlatformClient.query_knowledge` → `reply.tenant_id != context.identity.tenant_id` → error
- 可信度：CONFIRMED
- 能力状态：已实现。Java 侧是否始终返回 tenant_id：PARTIAL（本仓只看到 Python 校验）

## E-07 工具安全契约：副作用 / 幂等 / 确认 / 禁止无条件重试

- 结论：只读工具禁止副作用、幂等和确认；写工具必须声明 side-effect；`IDEMPOTENT_TRANSIENT` 重试要求已有幂等策略。
- 证据类型：领域不变量
- 文件路径：`src/agentscope_platform/domain/tool.py`
- 类名：`ToolMetadata`、`ToolPolicy`
- 方法名：`validate_safety_invariants`、`evaluate`
- 配置项：N/A
- 数据库表：N/A
- SQL：N/A
- 依赖：N/A
- 调用链：`GovernedFunctionTool.check_permissions/call` → `ToolPolicy.evaluate`
- 可信度：CONFIRMED
- 能力状态：已实现

## E-08 写工具默认关闭；refund_start 需确认 grant + 幂等键

- 结论：`AGENT_REFUND_START_ENABLED` 默认 false。开启后工具 `refund_start` 要求 `agent` scope、参数绑定确认、`Idempotency-Key`，且 `retryPolicy=NONE`。
- 证据类型：配置默认值 + 工具元数据 + 适配器
- 文件路径：`src/agentscope_platform/core/config.py`；`src/agentscope_platform/infrastructure/agentscope/governed_tools.py`；`.env.example`
- 类名：`GovernedToolset`
- 方法名：`__init__`、`refund_start`
- 配置项：`agent_refund_start_enabled: bool = False`
- 数据库表：N/A（退款账本在 Java workflow）
- SQL：N/A
- 依赖：`WORKFLOW_BASE_URL/workflow/refund/start`
- 调用链：确认 grant 消费 → `PlatformClient.start_refund(dedupeId=idempotency_key)`
- 可信度：CONFIRMED
- 能力状态：可选开关（默认关）

## E-09 确认 grant：参数哈希 + 一次性 Redis NX

- 结论：确认令牌绑定 tenant/user/tool/`args_sha256`/idempotency_key；执行时 `SET key NX EX ttl`，重放返回 false。生产开启写工具时强制 redis。
- 证据类型：签发/验签 + 防重放存储 + Settings 校验
- 文件路径：`src/agentscope_platform/domain/confirmation.py`；`src/agentscope_platform/application/confirmation.py`；`src/agentscope_platform/infrastructure/security/tool_confirmation.py`；`src/agentscope_platform/core/config.py`；`src/agentscope_platform/infrastructure/agentscope/tools.py`
- 类名：`ToolConfirmationService`、`JwtToolConfirmationCodec`、`RedisConfirmationReplayStore`、`GovernedFunctionTool`
- 方法名：`issue`、`verify_tokens`、`consume`、`call`
- 配置项：`AGENT_CONFIRMATION_REPLAY_STORE`；生产校验 `must be redis`
- 数据库表：N/A
- SQL：N/A（Redis Lua 不在此；confirmation 用 SET NX）
- 依赖：`redis`
- 调用链：`POST /agent/tool-confirmations` → JWT grant → 请求头携带 → `ToolPolicy` 匹配参数哈希 → `consume` NX
- 可信度：CONFIRMED
- 能力状态：已实现；生产 redis 为条件强制

## E-10 拒绝旧的仅工具名确认头

- 结论：`X-Agent-Confirmed-Tools` 一律 400，不允许“只确认工具名、不绑定参数”。
- 证据类型：API 依赖
- 文件路径：`src/agentscope_platform/api/dependencies.py`
- 类名：N/A
- 方法名：`_confirmation_tokens`
- 配置项：`CONFIRMED_TOOLS_HEADER = "X-Agent-Confirmed-Tools"`
- 数据库表：N/A
- SQL：N/A
- 依赖：N/A
- 调用链：任意业务路由 → `get_run_context`
- 可信度：CONFIRMED
- 能力状态：已实现

## E-11 外部 MCP/Browser/Code 不转发 caller JWT

- 结论：MCP/sandbox 客户端不得读取 `context.internal_token`；改发独立 `X-Agent-Service-Token`，audience/action 分离。
- 证据类型：边界测试 + token 签发 + MCP 客户端
- 文件路径：`tests/test_architecture_boundaries.py`；`src/agentscope_platform/infrastructure/security/downstream_jwt.py`；`src/agentscope_platform/infrastructure/mcp/client.py`
- 类名：`DownstreamServiceTokenIssuer`、`StreamableHttpMcpGateway`
- 方法名：`test_external_tool_adapters_cannot_forward_the_caller_internal_token`、`issue`、`call`
- 配置项：`AGENT_DOWNSTREAM_JWT_SECRET` 不得复用 internal/confirmation secret
- 数据库表：N/A
- SQL：N/A
- 依赖：`mcp`、`pyjwt`
- 调用链：工具调用 → `issue(audience, action)` → HTTP header
- 可信度：CONFIRMED
- 能力状态：MCP/Browser/Code 均为可选开关，默认关

## E-12 MCP 禁止递归 Agent 工具与 stdio

- 结论：远程名以 `platform.agent.` 开头被拒绝；MCP 适配器禁止 subprocess/stdio。
- 证据类型：领域校验 + 架构测试
- 文件路径：`src/agentscope_platform/domain/mcp.py`；`tests/test_architecture_boundaries.py`
- 类名：`McpToolBinding`
- 方法名：`reject_recursive_agent_tools`、`test_mcp_adapter_is_remote_http_only`
- 配置项：`AGENT_MCP_TOOLS_JSON` allowlist
- 数据库表：N/A
- SQL：N/A
- 依赖：`mcp` Streamable HTTP
- 调用链：Settings 解析 JSON → `McpToolBinding`
- 可信度：CONFIRMED
- 能力状态：可选开关，默认关

## E-13 会话检查点：语言中立 JSON + Redis CAS + 租约

- 结论：持久化格式是 `agent-session-checkpoint.v1`，不含 caller token、原始 goal、AgentScope state；Redis Lua 按 `revision` CAS；RUNNING 期间持有 lease。
- 证据类型：领域模型 + 应用服务 + Redis Lua
- 文件路径：`src/agentscope_platform/domain/session.py`；`src/agentscope_platform/application/session.py`；`src/agentscope_platform/infrastructure/persistence/agent_session.py`
- 类名：`AgentSessionCheckpoint`、`AgentSessionService`、`RedisAgentSessionStore`
- 方法名：`run`、`compare_and_set`、`_validate_resume`
- 配置项：`AGENT_SESSION_STORE` 默认 `memory`；生产强制 redis
- 数据库表：N/A
- SQL：Redis Lua `_CAS_SCRIPT`
- 依赖：`redis`
- 调用链：`POST /agent/sessions/{sessionId}/run` → CAS create/resume → checkpointed runner → CAS complete
- 可信度：CONFIRMED
- 能力状态：已实现；默认 memory，生产 redis

## E-14 副作用会话恢复要求原幂等键 + 新确认

- 结论：checkpoint `side_effect_observed=true` 且未终态时，恢复必须匹配原 idempotency digest 且携带未过期确认，否则 412。
- 证据类型：应用服务 + API 异常映射
- 文件路径：`src/agentscope_platform/application/session.py`；`src/agentscope_platform/api/app.py`
- 类名：`AgentSessionService`
- 方法名：`_validate_resume`、`agent_session_confirmation_required`
- 配置项：N/A
- 数据库表：N/A
- SQL：N/A
- 依赖：N/A
- 调用链：resume → 412 `fresh side-effect confirmation required`
- 可信度：CONFIRMED
- 能力状态：已实现

## E-15 异步任务权威在中央服务；本进程只做 worker

- 结论：`ASYNC_TASK_ENABLED` 默认 false。提交走中央 create/lease；心跳续租校验 `lease_owner_id` + `lease_epoch`；写回带 fencing。
- 证据类型：应用编排 + 配置
- 文件路径：`src/agentscope_platform/application/async_task.py`；`src/agentscope_platform/domain/async_task.py`；`src/agentscope_platform/core/config.py`
- 类名：`AsyncTaskManager`
- 方法名：`submit`、`_heartbeat`、`_complete_once`、`_validate_deadline`
- 配置项：`async_task_enabled: bool = False`
- 数据库表：N/A（权威在 Java async-task-service）
- SQL：N/A
- 依赖：`ASYNC_TASK_BASE_URL`
- 调用链：`POST /agent/*/async` → gateway.create → lease → in-process execute → update_status
- 可信度：CONFIRMED
- 能力状态：可选开关，默认关

## E-16 DAG：拓扑分层、有界并行、环检测、critic/replan

- 结论：任务图分层后同层 `asyncio.gather`，全局 semaphore 限并行；环返回 400；replan 默认开、最多 1 次。Process 路径关闭 replan 且任务上限更紧。
- 证据类型：DAG 应用服务 + 组装
- 文件路径：`src/agentscope_platform/application/dag.py`；`src/agentscope_platform/api/app.py`
- 类名：`AgentDagApplicationService`
- 方法名：`run`、`_topological_levels`、`_run_level`
- 配置项：`AGENT_DAG_MAX_TASKS=6`；`AGENT_DAG_REPLAN_ENABLED=true`；Process `max_tasks=min(..., 4)` 且 `review_policy.enabled=False`
- 数据库表：N/A
- SQL：N/A
- 依赖：AgentRunner / DagQualityReviewer
- 调用链：`/agent/dag/run` 或 plan-run → levels → workers → synthesis → critique → optional replan
- 可信度：CONFIRMED
- 能力状态：已实现

## E-17 Process 规划 fail-closed：字符串标记 + 工具策略双保险

- 结论：Process planner 若提出审批/认领等写描述则丢弃计划并回退只读单任务；真正写仍被 `ToolPolicy` 挡住。refund 仅在开关+确认+幂等同时满足时放行。
- 证据类型：规划服务 + Planner prompt
- 文件路径：`src/agentscope_platform/application/planning.py`；`src/agentscope_platform/infrastructure/agentscope/planner.py`
- 类名：`AgentDagPlanningService`
- 方法名：`plan_and_run`
- 配置项：`process_write_tools` 仅当 refund 开启时为 `{refund_start}`
- 数据库表：N/A
- SQL：N/A
- 依赖：N/A
- 调用链：`POST /agent/process/run` → planner → marker filter → DAG
- 可信度：CONFIRMED
- 能力状态：已实现（写能力仍为可选开关）

## E-18 HTTP 每依赖 bulkhead + circuit + 绝对 deadline

- 结论：出站调用按依赖名隔离并发和熔断；超时/5xx 计失败；写路径这一层不自动重试。
- 证据类型：韧性实现 + 客户端
- 文件路径：`src/agentscope_platform/infrastructure/http/resilience.py`；`src/agentscope_platform/infrastructure/http/platform_client.py`；`src/agentscope_platform/core/deadline.py`
- 类名：`HttpDependencyGuard`、`DependencyGuardRegistry`、`PlatformClient`
- 方法名：`execute`、`_enter`、`_request`、`bind_deadline`
- 配置项：`HTTP_DEPENDENCY_MAX_CONCURRENT=32`；`HTTP_CIRCUIT_FAILURE_THRESHOLD=5`
- 数据库表：N/A
- SQL：N/A
- 依赖：`httpx`
- 调用链：工具 → PlatformClient → guard.lease → httpx
- 可信度：CONFIRMED
- 能力状态：已实现

## E-19 本仓无业务数据库 / 无 MQ

- 结论：仓库内无 `.sql` / Flyway / Kafka / Celery / SQLAlchemy。业务写权威在 Java；本仓 Redis 只用于确认防重放和会话 checkpoint。
- 证据类型：仓库扫描 + 依赖
- 文件路径：`pyproject.toml`；`src/agentscope_platform/infrastructure/persistence/agent_session.py`；`src/agentscope_platform/infrastructure/security/tool_confirmation.py`
- 类名：N/A
- 方法名：N/A
- 配置项：`AGENT_SESSION_STORE`、`AGENT_CONFIRMATION_REPLAY_STORE`
- 数据库表：无
- SQL：无
- 依赖：`redis` 存在且被 session/confirmation 调用；无 kafka
- 调用链：N/A
- 可信度：CONFIRMED
- 能力状态：已实现（Redis 用途有限）

## E-20 Shadow 双跑默认只允许 localhost，且用例必须只读

- 结论：评测拒绝非只读 case；远程 URL 必须 `--allow-remote-targets`；报告不保存回答/observation/token 的口径见文档，代码侧有体积上限和脱敏约束。
- 证据类型：评测实现
- 文件路径：`src/agentscope_platform/evaluation/shadow.py`
- 类名：N/A
- 方法名：`load_cases`、`validate_target_url`、`evaluate_shadow`
- 配置项：CLI `agentscope-shadow-eval`
- 数据库表：N/A
- SQL：N/A
- 依赖：`httpx`
- 调用链：dataset JSONL → dual HTTP `/agent/run` → judge/gates
- 可信度：CONFIRMED
- 能力状态：已实现（真实生产双跑：规划中 / 外部证据未过）

## E-21 生产发布 fail-closed：证据模板默认 NO-GO

- 结论：进度与运行手册把工程 PASS 和生产 GO 分开；默认证据 `--require-go` 必须失败。
- 证据类型：进度文档 + 测试脚本存在
- 文件路径：`CODEX_PROGRESS.md`；`docs/operations/production-release-runbook.md`；`scripts/test_production_runbook.py`；`.github/workflows/ci.yml`
- 类名：N/A
- 方法名：N/A
- 配置项：CI 步骤 `Verify production runbook and pending evidence template`
- 数据库表：N/A
- SQL：N/A
- 依赖：N/A
- 调用链：CI quality job → `test_production_runbook.py`
- 可信度：HIGH_CONFIDENCE（本仓代码与文档一致；目标环境外部证据本分析未重新执行）
- 能力状态：已实现门禁；生产切流为规划中

## E-22 候选路由 `/agent/v2` 默认不注册

- 结论：只有 `AGENT_V2_ENABLED=true` 才 `include_router(candidate_router)`。
- 证据类型：应用组装 + 配置
- 文件路径：`src/agentscope_platform/api/app.py`；`.env.example`
- 类名：N/A
- 方法名：`create_app`
- 配置项：`agent_v2_enabled: bool = False`
- 数据库表：N/A
- SQL：N/A
- 依赖：N/A
- 调用链：settings → FastAPI include_router
- 可信度：CONFIRMED
- 能力状态：可选开关，默认关

## E-23 Readiness：启用依赖并发探测，Java 领域服务降级不阻塞

- 结论：模型网关、已启用的 async/MCP/sandbox、确认 replay、session store 为必要依赖；Knowledge/Analytics/Workflow/Order 状态可见但非 required。
- 证据类型：探针实现 + API
- 文件路径：`src/agentscope_platform/infrastructure/http/readiness.py`；`src/agentscope_platform/api/routes.py`
- 类名：`HttpDependencyReadinessProbe`
- 方法名：`check`、`readiness`
- 配置项：`READINESS_PROBE_TIMEOUT_SECONDS=2`
- 数据库表：N/A
- SQL：N/A
- 依赖：httpx 探测各 origin `/health`
- 调用链：`GET /readiness` → 503 if required DOWN
- 可信度：CONFIRMED
- 能力状态：已实现

## E-24 轨迹与执行版本内容寻址，不落密钥

- 结论：`ExecutionVersions` 对 prompt/model 参数/工具契约做 sha256；HTTP 响应头回传三个版本；checkpoint 存 goalSha256 而非原文。
- 证据类型：领域 + runner 组装
- 文件路径：`src/agentscope_platform/domain/versioning.py`；`src/agentscope_platform/domain/agent.py`；`src/agentscope_platform/api/routes.py`
- 类名：`ExecutionVersions`
- 方法名：`build_execution_versions`、`_run_agent`
- 配置项：N/A
- 数据库表：N/A
- SQL：N/A
- 依赖：N/A
- 调用链：Container 启动计算 versions → `/agent/run` 响应头
- 可信度：CONFIRMED
- 能力状态：已实现

## E-25 SSE 隐私脱敏

- 结论：异步任务流与 Reflexion SSE 在出站前 `redact_pii`（邮箱/手机/身份证模式）。
- 证据类型：应用隐私 + 路由投影
- 文件路径：`src/agentscope_platform/application/privacy.py`；`src/agentscope_platform/api/routes.py`
- 类名：N/A
- 方法名：`redact_pii`、`_project_task_frame`、`_reflexion_events`
- 配置项：N/A
- 数据库表：N/A
- SQL：N/A
- 依赖：N/A
- 调用链：上游 SSE → JSON parse → redact → yield
- 可信度：CONFIRMED
- 能力状态：已实现（模式覆盖有限，见风险）

## E-26 模型重试默认 0，由 LiteLLM 负责 failover

- 结论：`AGENT_MODEL_MAX_RETRIES` 默认 0，注释明确禁止编排层再乘一次重试。
- 证据类型：配置
- 文件路径：`src/agentscope_platform/core/config.py`；`.env.example`
- 类名：`Settings`
- 方法名：N/A
- 配置项：`agent_model_max_retries: int = 0`
- 数据库表：N/A
- SQL：N/A
- 依赖：LiteLLM 在进程外 `GATEWAY_BASE_URL`
- 调用链：AgentScope model factory → OpenAI-compatible gateway
- 可信度：CONFIRMED
- 能力状态：已实现

## E-27 测试与 CI 门禁存在，本分析未重跑

- 结论：53 个测试模块覆盖契约、JWT、确认、会话 CAS、DAG、韧性、Shadow、架构边界；CI 含 ruff/mypy/pytest cov>=80、SBOM、Trivy、tag-only 签名发布。
- 证据类型：测试目录 + workflow
- 文件路径：`tests/`；`.github/workflows/ci.yml`；`pyproject.toml`
- 类名：N/A
- 方法名：N/A
- 配置项：`--cov-fail-under=80`
- 数据库表：N/A
- SQL：N/A
- 依赖：pytest、ruff、mypy
- 调用链：GitHub Actions quality job
- 可信度：CONFIRMED（文件存在）；测试最新结果 UNCONFIRMED（本技能禁止执行命令，未跑 pytest）
- 能力状态：已实现

## E-28 Java 幂等账本 / Flyway / Helm 不在本 Workspace

- 结论：`CODEX_PROGRESS.md` 声称 Java workflow 唯一账本、Flyway、Helm HPA 等已完成；这些文件不在本仓库。不得把进度文档当本仓实现证据。
- 证据类型：缺失扫描 + 进度文档
- 文件路径：`CODEX_PROGRESS.md`（线索）；本仓无 `*.sql`、无 `helm/`
- 类名：N/A
- 方法名：N/A
- 配置项：N/A
- 数据库表：【需人工确认】Java 侧表
- SQL：【需人工确认】
- 依赖：N/A
- 调用链：Python `start_refund` 把 `dedupeId` 交给 Java
- 可信度：UNCONFIRMED（相对本仓）；HIGH_CONFIDENCE 仅限“Python 把幂等键传给 Java”
- 能力状态：推测（对 Java 仓）/ 已实现（对本仓 HTTP 调用）

## E-29 部署形态：单 Compose 服务，只读根文件系统

- 结论：`compose.yml` 只有 `orchestrator`；非 root、drop ALL caps、read_only + tmpfs；健康检查打 `/health`。
- 证据类型：Compose + Dockerfile
- 文件路径：`compose.yml`；`Dockerfile`
- 类名：N/A
- 方法名：N/A
- 配置项：`user: "10001:10001"`；`read_only: true`
- 数据库表：N/A
- SQL：N/A
- 依赖：镜像 `python:3.12.13-slim-bookworm`；uv 0.11.3
- 调用链：docker compose up → uvicorn 8085
- 可信度：CONFIRMED
- 能力状态：已实现（本地/CI 镜像）；K8s 清单不在本仓

## E-30 ContextVar 传播 RunContext（非进程级租户全局变量）

- 结论：工具函数签名拿不到 `RunContext`，runner 用 ContextVar 绑定本次请求；未绑定则 `RuntimeError`。这是框架适配取舍，不是多租户全局可变状态。
- 证据类型：核心上下文 + runner
- 文件路径：`src/agentscope_platform/core/context.py`；`src/agentscope_platform/infrastructure/agentscope/runner.py`
- 类名：`AgentScopeRunner`
- 方法名：`bind_run_context`、`current_run_context`、`_run`
- 配置项：N/A
- 数据库表：N/A
- SQL：N/A
- 依赖：N/A
- 调用链：`_run` try/finally 绑定与复位
- 可信度：CONFIRMED
- 能力状态：已实现
