# AI Runtime Boundary Decomposition Delivery Plan

## Requirement

以“AgentScope/Python 只负责推理与编排，Java 服务继续拥有数据、事务、安全和副作用”
作为最终架构方向，编排并实施 `agentscope-platform` 与 `langchain4j-platform` 的后续拆分，
避免形成同时包含 Agent、Chat、RAG 存储、工作流、SQL 执行和媒体处理的 Python 新单体。

本交付覆盖两层内容：

1. 建立可自动验证的架构边界、语言中立契约和迁移门禁。
2. 按风险从低到高实施迁移波次；外部生产门禁未满足的删除、切流和部署动作只做到
   release-ready，不擅自执行。

## Repository Evidence

- `agentscope-platform/AGENTS.md` 已限定 AgentScope 类型只能进入
  `infrastructure/agentscope/`，领域服务通过 HTTP/MCP 复用，不复制 Java 领域逻辑。
- `langchain4j-platform/pom.xml` 是包含共享库及多个独立服务的 Maven 聚合仓；这不是待拆单体。
- `langchain4j-platform/edge-gateway/.../application.yml` 已按服务前缀路由。
- Java `agent-service` 已是整服务回滚目标，AgentScope 是 `/agent/**` 默认目标。
- `interop-service` 同时代理 AgentScope 与 conversation，属于协议边界，而非数据所有者。
- Java `eval-service` 与 Python `evaluation/` 已形成重复评测控制面。
- Knowledge 上传同步执行解析、切块、embedding 和多索引写入；长任务文档明确记录其尚未接入
  `async-task-service`。
- Knowledge 在线查询仍包含进程内 keyword mirror；直接把 query/ingest 拆成不同进程会造成
  查询结果不一致。
- 两个仓库当前都有大量未提交修改，并与 async-task、interop、knowledge、CI 和文档重叠。
  实施时必须逐文件保留既有变化，不允许 reset 或覆盖。

## Feasibility

- Verdict: conditional-go
- Constraints:
  - 不改外部 HTTP/JSON/SSE 契约，除非先增加兼容版本并获得单独批准。
  - 所有业务请求继续要求有效 `X-Internal-Token`，显式传播 tenant/user/scope/dept/trace。
  - AgentScope 不拥有 Flowable、SQL、订单、Knowledge 索引、身份或异步任务数据库。
  - 不在真实双跑与回滚门禁通过前删除 Java `agent-service` 或修改生产路由。
  - 不对有副作用工具做无条件重试。
  - 当前 dirty worktree 的既有修改全部视为用户修改。
- Dependencies:
  - `async-task-service` 作为长任务权威状态。
  - LiteLLM 继续作为唯一模型 provider 网关。
  - Knowledge 异步入库前需要确定原始文档权威存储和文档版本状态机。
  - 跨仓契约需要 OpenAPI/JSON Schema，不以 Java DTO jar 或 Python 类作为唯一事实源。
- Risks and mitigations:
  - **分布式单体**：只按数据所有权、资源隔离或发布节奏拆；不按 chain/vote/reflexion 拆服务。
  - **Knowledge 半完成索引**：引入版本化 ingestion job、逐 sink 状态、幂等写和 reconcile，
    不声称跨 Qdrant/ES/Graph/Redis 有全局事务。
  - **重复评测事实源**：先统一 case/report schema，再切 runner。
  - **协议回归**：每个切片先补契约、安全、失败映射和旧/新双跑用例。
  - **工作区覆盖**：修改前检查目标文件 diff；存在不可安全合并的重叠时停止该切片并报告。
  - **服务爆炸**：先同仓不同 entrypoint/profile/Deployment，只有独立所有权成熟后再拆仓。

## Product Design

- Actors and goals:
  - 平台调用方：现有 API、SSE、错误码和安全语义不变。
  - Agent 开发者：只在 AgentScope 中实现推理、计划、委派、工具选择和轨迹。
  - Java 领域服务开发者：继续维护数据不变量、事务、授权和副作用执行。
  - 发布/运维人员：每个迁移能力均可 shadow、灰度、观测和整服务回滚。
- Scope:
  - 架构边界自动检查与 ADR。
  - Agent Java 回滚实现的退役门禁。
  - Agent A2A/MCP 协议面的单一归属。
  - Java/Python 评测控制面的语言中立化与离线运行。
  - Knowledge query/ingest 的安全拆分设计和实现。
  - 后续 conversation、analytics planner、workflow AI adapter 的能力级迁移骨架。
- Out of scope:
  - 生产部署、生产切流、删除生产数据、Git commit/push。
  - 把 Knowledge/Workflow/SQL/Order/Auth/AsyncTask 数据面重写成 Python。
  - 在本轮创建新的身份体系、消息队列或通用工作流引擎。
  - 为每一种 Agent 编排策略创建独立服务。
- Business rules:
  - 数据权威随领域服务，不随调用语言迁移。
  - 模型不得提供 tenantId 作为工具可信输入；租户只来自已验证上下文。
  - 写工具必须带副作用等级、幂等策略、审批要求、timeout 和 retry policy。
  - 评测服务不应成为面向普通业务流量的强依赖。
  - 删除遗留实现必须晚于契约、安全、质量、成本、故障恢复和回滚门禁。

## Acceptance Criteria

| ID | Observable behavior | Priority | Verification |
| --- | --- | --- | --- |
| AC-01 | 架构 ADR 明确 Python/Java 所有权、禁止依赖和例外审批规则 | P0 | 文档审查 + 路径证据 |
| AC-02 | CI 可自动阻止 AgentScope/框架类型进入 domain/application/API DTO | P0 | 架构测试失败/通过用例 |
| AC-03 | 跨语言契约有唯一的 OpenAPI/JSON Schema 事实源和兼容性检查 | P0 | contract export + snapshot tests |
| AC-04 | Java `agent-service` 具有可执行的退役清单，未满足门禁时不会被删除或切流 | P0 | 配置/文档/CI 检查 |
| AC-05 | Agent A2A/MCP capability 不再由 Java 静态重复维护，失败时有确定性映射 | P0 | interop/AgentScope 契约测试 |
| AC-06 | 评测 case/report 可由独立 job/CLI 执行，在线 Agent API 不依赖评测 runner | P0 | CLI、schema、双跑测试 |
| AC-07 | Knowledge query 与 ingest 可独立扩缩，query 不依赖进程内 ingest 状态 | P0 | profile/entrypoint 集成测试 |
| AC-08 | Knowledge 入库通过 durable task，重复提交幂等，逐 sink 状态可恢复/对账 | P0 | JDBC/H2、故障注入、reconcile tests |
| AC-09 | Knowledge 跨租户文档、任务和索引不可见，授权失败保持 fail-closed | P0 | 跨租户和 authz failure tests |
| AC-10 | Analytics 只有规划可迁 Python，SQL guard/只读凭据/执行仍由 Java 持有 | P1 | contract + security tests |
| AC-11 | Workflow AI 失败不回滚人工审批或破坏 Flowable/outbox 事务语义 | P1 | workflow failure tests |
| AC-12 | 若迁移 Chat，使用独立 conversation runtime，memory/cache/profile 不进入 AgentScope | P1 | 独立进程与契约测试 |
| AC-13 | 每一切片均有 rollout、监控、rollback 和未完成外部验证记录 | P0 | delivery/QA artifacts |
| AC-14 | Knowledge split 的 query/ingest-api/worker 可在可选 Compose 拓扑独立启动，S3 client 不受 Spring HTTP BOM 二进制冲突影响，且默认宿主端口不与 AgentScope 冲突 | P0 | client construction test + Compose render + MinIO smoke |
| AC-15 | 默认在线拓扑未部署 `/eval/**` 时，前端把 Eval 明确展示为离线/未部署且禁止发起网络请求；Interop 能力不受影响 | P1 | catalog/gate/interaction tests + Chrome |
| AC-16 | Vision provider 判定图片/请求无效时返回稳定 HTTP 400，而不是泄漏为 HTTP 500 | P1 | controller error mapping test + edge API smoke |
| AC-17 | RAG 静态能力不预设“降级”；实际 embedding/vector/hybrid 状态由运行时发现结果呈现 | P1 | catalog contract + live runtime + Chrome |
| AC-18 | S3-compatible 原文凭据按 ingest 写、worker 读、query 无凭据进行最小权限拆分，越权操作明确拒绝 | P0 | MinIO policy + allow/deny smoke |
| AC-19 | required sink 暂时不可用时任务进入可观测的非 READY 状态，依赖恢复后只重试幂等 sink 并最终 READY | P0 | Qdrant/ES 故障注入与 reconcile |
| AC-20 | 并发提交保持幂等、租户隔离与 job 状态一致，并记录吞吐、成功率和延迟分位数 | P0 | 本地并发负载报告 |
| AC-21 | 拆分运行面在持续读写期间无任务丢失、无非预期 PARTIAL/FAILED、无服务重启 | P0 | 有界 soak 报告和容器统计 |
| AC-22 | AgentScope/Knowledge canary 可按租户或整能力切换，观测头/健康/查询结果可确认实际 backend | P0 | canary smoke + 配置/路由证据 |
| AC-23 | 回滚先停止新流量、排空在途任务，再切回 legacy/combined backend；恢复后可重新切回且不重放旧请求 | P0 | 本地回滚与恢复演练 |

## UI/UX Design

- Applicability: 主要拆分不改变交互；真实 QA 后的状态诚实性修复适用。
- Eval：默认在线拓扑下显示“离线评测控制面未部署”，运行按钮禁用并说明需通过独立
  CLI/CI Job 执行，不能让用户点击后才得到网络错误。
- RAG：静态目录保持中性“就绪”，检索台继续以 live discovery 展示实际 embedding、
  vector、hybrid、Graph 和 rerank 状态。
- Compatibility requirement: 现有 API 路径、SSE event、错误响应和鉴权行为保持兼容。

## Technical Solution

### Chosen approach

采用“窄 AgentScope + Java 领域数据面 + 独立协议/评测控制面”的渐进式绞杀：

```text
Client
  |
  v
edge-gateway                         LiteLLM
  |                                    ^
  +--> agent-protocol-gateway          |
  |          |                         |
  |          v                         |
  |     agentscope-orchestrator -------+
  |          |
  |          +--> knowledge-query-service
  |          +--> analytics-executor
  |          +--> workflow-service
  |          +--> order-service
  |          +--> async-task-service
  |
  +--> conversation-service/runtime
  +--> knowledge-ingest-api --> async-task --> knowledge-ingest-worker
  +--> channel / vision / voice / auth

CI/Nightly --> ai-evaluation-runner --> edge/agent/knowledge targets
```

边界规则：

- `agentscope-orchestrator`：ReAct、DAG、planner、critic/replan、handoff、tool policy、轨迹。
- `agent-protocol-gateway`：A2A/MCP/Agent Card/外部 push 协议；不拥有模型或业务数据。
- `knowledge-*`：原文、文档版本、索引、检索、ReBAC；不进入 AgentScope。
- `analytics-executor`：schema allowlist、SQL guard、只读连接和执行。
- `workflow-service`：Flowable、审批任务、事务、outbox。
- `async-task-service`：任务、租约、SSE journal、取消、webhook。
- `ai-evaluation-runner`：离线/CI 控制面，不是在线请求依赖。

### Alternatives rejected

1. **把 Chat/RAG/Workflow/SQL/Media 全并入 AgentScope**：形成 Python 新单体，扩大故障域并丢失
   数据/事务边界。
2. **每个 Agent 策略一个服务**：无独立数据、团队或扩缩容证据，会形成高延迟分布式单体。
3. **立即每模块拆独立 Git 仓库**：当前共享库和 dirty worktree 很重，先拆部署生命周期更可逆。
4. **Knowledge 直接用消息最终一致且不记录 sink 状态**：无法识别或修复半完成索引。
5. **Python 直接连接业务数据库**：扩大凭据和租户隔离风险，绕过 Java guard。

### Modules and anticipated file map

Wave 0（边界与门禁）：

- `docs/adr/0002-ai-runtime-domain-boundaries.md`（新）
- `docs/service-decomposition.md`（新）
- `tests/test_architecture_boundaries.py`（新）
- `scripts/check_architecture_boundaries.py`（新，若测试内实现不足）
- `contracts/boundaries/*.schema.json`（新）
- `docs/delivery/ai-runtime-boundary-decomposition/*`
- `../langchain4j-platform/docs/架构边界/ai-runtime-boundaries.md`（新）
- Java Maven/CI 文件仅在可安全合并既有修改时更新。

Wave 1（Agent/协议/评测收敛）：

- AgentScope `domain/interop.py`、`api/routes.py`、application ports/services（按最终差异最小修改）
- AgentScope `evaluation/` 与 `eval/baseline/` 的统一 schema/runner
- Java `interop-service/**`：移除静态 Agent capability 重复源，保留 protocol gateway
- Java `eval-service/**`：先兼容统一 schema，再从默认在线部署/路由中退出
- edge/Compose/Helm：只准备 feature flag 和 rollback target，不执行生产切流

Wave 2（Knowledge 运行面拆分）：

- Java `knowledge-service` 新增 role/profile：`query`、`ingest-api`、`ingest-worker`
- 新增 ingestion job/domain/store/reconcile 类及测试
- `platform-protocol` 增加语言中立的 ingestion task/event schema 映射
- `async-task-service` 只增加通用 kind/事件契约所需能力，不接收 Knowledge 业务逻辑
- Compose/Helm 增加独立 Deployment 和资源/探针配置
- 原 `knowledge-service` 名称在兼容期保留为 façade/rollback

Wave 3（能力级去 LangChain4j）：

- Analytics：Python planner contract；Java guard/executor contract
- Workflow：HTTP AI adapter；保留本地确定性 fallback，不迁 Flowable
- Conversation：先独立 shadow runtime；稳定后按 `/chat` 能力灰度
- Vision/voice/channel/auth 只有出现资源、安全或团队边界信号才进入后续独立计划

### Contracts and data

- 对外和跨语言契约：OpenAPI/JSON Schema。
- Java 内部可继续使用版本化 `platform-protocol` artifact，但不能成为 Python 唯一契约源。
- Knowledge 建议的数据模型：
  - `DocumentSource`：原始对象 URI、hash、tenant、owner、contentType、size、version。
  - `IngestionJob`：jobId/idempotencyKey/documentVersion/status/attempt。
  - `IngestionSinkStatus`：vector/es/graph/registry/authz 的独立状态和错误。
  - `DocumentVersionStatus`：RECEIVED/PROCESSING/READY/PARTIAL/FAILED/DELETING/DELETED。
- 权威原文存储建议使用 S3-compatible object storage；在未批准/提供该依赖前，Wave 2 只允许
  对有界文本 payload 做开发验证，不宣称支持大文件生产迁移。

### Security and reliability

- 所有新 API 默认验证内部 JWT；健康/就绪探针例外。
- worker 从任务记录恢复不可变租户上下文，不从模型输出恢复身份。
- ingestion 幂等键建议为 `(tenantId, sourceHash, requestedVersion)`。
- 每个 sink 写入使用稳定 documentVersion，允许重复执行但不得交叉租户覆盖。
- 失败重试只针对声明幂等的 sink；authz/删除等副作用按策略处理。
- READY 只在所有 required sinks 成功后发布；PARTIAL 不进入默认检索。
- reconcile 扫描 PARTIAL/超时 PROCESSING 并重试或明确 FAILED。
- interop push 配置最终进入 Redis/async-task 权威状态，不能只放单进程 map。

### Observability

- 指标：任务等待/运行时间、每 sink 成功率、PARTIAL 数、reconcile 次数、query P95、
  Agent tool failure、protocol mapping failure、eval gate pass rate。
- 日志和 trace 包含 traceId、tenant 的脱敏标识、jobId/documentVersion；不记录 token、原文或密钥。
- 成本按 tenant/trace/model/capability 归因。

### Compatibility and migration

- 采用 shadow → capability canary → tenant canary → default switch → rollback retention。
- Java agent、legacy knowledge façade 和旧 eval runner 在一个完整回滚周期内保留。
- 不进行单请求静默 fallback；回滚以显式整服务路由为单位。
- 所有旧/新结果进入相同评测 schema。

## Implementation Sequence

1. **Slice 0 — Architecture guardrails**：ADR、责任矩阵、架构测试、契约所有权；覆盖
   AC-01/02/03/13。
2. **Slice 1 — Retirement and protocol readiness**：Agent Java 退役门禁、interop 单一
   capability source、push 状态方案；覆盖 AC-04/05/13。
3. **Slice 2 — Evaluation control plane**：统一 case/report schema 和独立 CLI/job，Java runner
   兼容后退出默认在线路由；覆盖 AC-06/13。
4. **Slice 3 — Knowledge prerequisites**：原文权威存储接口、document version/job/sink 状态机、
   幂等与 reconcile 单测；覆盖 AC-08/09。
5. **Slice 4 — Knowledge process split**：query/ingest-api/worker entrypoint、async-task 接入、
   Compose/Helm 和兼容 façade；覆盖 AC-07/08/09/13。
6. **Slice 5 — Selective AI migration**：Analytics planner、Workflow AI adapter，分别 shadow；
   覆盖 AC-10/11/13。
7. **Slice 6 — Conversation decision gate**：只有独立状态契约和 shadow 基线通过后创建独立
   conversation runtime；覆盖 AC-12/13。
8. 每个切片后执行差异审查、QA、文档同步和 CI 验证；外部生产动作保持 blocked。
9. **Slice 7 — Production cutover gates**：S3 最小权限、故障注入、并发/容量、有界 soak、
   AgentScope/Knowledge canary、任务排空和整服务回滚；覆盖 AC-18 至 AC-23。当前本地
   可弃环境执行等价演练，真实云 IAM 与生产流量仍需目标环境再次验证。

## Verification Plan

| AC/Risk | Test level | Case or command | Required evidence |
| --- | --- | --- | --- |
| AC-01/02 | architecture | `uv run pytest tests/test_architecture_boundaries.py` | 非法 import fixture 被拒 |
| AC-03 | contract | export + snapshot/breaking comparison | schema diff |
| AC-04 | release gate | Compose/Helm/route assertions | 未批准时 legacy 仍可回滚 |
| AC-05 | unit/contract | Python + Maven interop tests | capability/错误/SSE 映射 |
| AC-06 | CLI/integration | baseline + shadow runner | 独立进程报告 |
| AC-07/08 | unit/integration | Maven knowledge/H2/async-task tests | lease/idempotency/recovery |
| AC-09 | security | 跨 tenant job/document/query | 404/拒绝且无泄漏 |
| AC-10 | security/integration | malicious SQL/tenant predicate/timeout | Java guard 拒绝 |
| AC-11 | transaction/failure | AI timeout during approval completion | Flowable 决定不回滚 |
| AC-12 | contract/shadow | old/new chat JSON/SSE comparison | quality/latency gate |
| AC-14 | deployment/integration | S3 client build、Compose render、MinIO put/get、三角色启动 | 无 linkage error、无端口冲突 |
| AC-15 | frontend contract/interaction | Eval 离线状态与 0-fetch | 默认不误报 ready |
| AC-16 | unit/integration | provider `InvalidRequestException` | HTTP 400 + 稳定错误体 |
| AC-17 | frontend/live discovery | manifest + `/rag/runtime` | 静态不误报降级、运行态准确 |
| AC-18 | security/integration | role-specific MinIO credentials | ingest 仅写、worker 仅读、query 无凭据 |
| AC-19 | resilience/integration | stop/start Qdrant or ES during ingestion | PARTIAL/FAILED 可恢复到 READY |
| AC-20 | load/integration | bounded concurrent submit/query runner | 成功率、P50/P95/P99、幂等与租户隔离 |
| AC-21 | soak/integration | bounded repeated ingest/query + container stats | 无丢失、泄漏、重启或状态堆积 |
| AC-22 | canary/integration | Agent backend and Knowledge route switch smoke | backend 可识别、非灰度流量不漂移 |
| AC-23 | operational drill | drain → switch → verify → restore | 无在途任务被双 worker 领取 |
| Python broad | static/test | `uv run ruff check .`; `uv run mypy src`; `uv run pytest` | exit 0 |
| Java broad | build/test | targeted `mvn -pl ... -am test`, then `mvn test` when feasible | exit 0 |
| Deploy syntax | config | Compose config + Helm lint/template | exit 0 |

## Slice 7 Execution Outcome

- Status: local production-equivalent **PASS**; actual production **conditional NO-GO**.
- AC-18: passed with real MinIO allow/deny checks and role-specific Compose/Helm secrets.
- AC-19: passed with Qdrant outage, PARTIAL observation, tenant isolation and reconcile to READY.
- AC-20: passed locally with 24 concurrent submissions, idempotency fan-in and 100 queries at
  concurrency 10; target-environment thresholds remain open.
- AC-21: passed as a bounded 120-second soak; a complete target business peak cycle remains open.
- AC-22/23: Knowledge and Agent whole-service switch/restore, task drain and paid-model verification
  passed locally; production tenant canary and change approval remain open.
- A post-recovery readiness defect was fixed by including Qdrant/embedding in the readiness group.
  Traffic resumption also requires three successful business warm-ups.

## Documentation Plan

- 新增跨仓架构 ADR、责任矩阵、服务拓扑和迁移门禁。
- 更新两个仓库 README/architecture/migration 文档中与实际实现相关的段落。
- 为 Knowledge ingestion、eval runner、interop rollback 分别提供运维与故障恢复说明。
- 每个能力提供回滚步骤，不提前宣称生产已切换。

## CI Plan

- 复用 GitHub Actions。
- Python CI 增加架构边界与契约快照检查；底层仍运行 ruff/mypy/pytest。
- Java CI 按切片增加 targeted Maven tests、contract compatibility、Compose 和 Helm 静态验证。
- 不新增部署权限、生产 smoke 或 secret 值。
- 增加无生产凭据的静态门禁，以及可显式触发的 localhost production-gate runner；远端
  runner 只引用 secret 名，不保存值。
- 当前 CI 文件已有未提交修改；只有确认可安全合并后才编辑，否则先让新增测试进入现有
  `pytest`/`mvn test` 自动发现路径。

## Rollout And Rollback

1. 本地/CI contract 与安全测试。
2. Shadow 调用，不返回候选结果。
3. 测试租户 capability canary。
4. 逐租户扩量，观察质量、P95、成本、错误、PARTIAL 和安全事件。
5. 默认路由切换需要单独的生产批准。
6. 回滚只切整个 capability/service backend，不在单请求内混用旧新状态。
7. 旧镜像、schema reader 和数据回填工具保留一个完整回滚周期。

## Assumptions And Open Decisions

- 推荐 `interop-service` 演进为独立 `agent-protocol-gateway`，不直接塞入 AgentScope。
- 推荐评测 runner 归 Python，但作为独立 CLI/job/镜像，不随在线 Agent API 一起扩缩。
- 推荐 Knowledge 原文使用 S3-compatible object storage；这是 Wave 2 生产化的新增依赖，
  需要在批准本计划时一并确认。若不批准，将只实现存储端口与本地测试适配器，不宣称生产 ready。
- `conversation-service` 暂不整体迁移；后续只迁纯 AI 编排并使用独立 runtime。
- Java `agent-service` 的实际删除和生产路由切换均不包含在无生产授权的自动执行中。
- 当前 dirty worktree 中修改的归属未知；计划默认全部保留并在每个切片前做重叠审计。

## Approval

- Status: approved
- Approved scope: 全部实施切片；包括 S3-compatible 原文权威存储、interop 独立协议网关、
  独立评测 job，以及 IAM、故障注入、并发/容量、soak、canary、任务排空和回滚演练。
  当前环境只执行 localhost/可弃集成环境；不猜测生产地址或凭据，不删除生产资源。
- Evidence: 2026-07-30 用户明确批准原计划与 S3-compatible 方案；随后明确授权执行上述
  生产切流门禁。
