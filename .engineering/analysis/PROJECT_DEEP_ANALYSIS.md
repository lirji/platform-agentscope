# 项目深度分析
- workspace: `/Users/liruijun/personal/LLM/agentscope-platform`
- generated_at: 2026-09-16
- protocol: project-deep-analysis/v1
- source_of_truth: 源码（README 仅线索）
- re_run_policy: REGENERATE_OWNED_ARTIFACT
- 能力状态标注：已实现 / 可选开关 / 规划中 / 推测

配套文件：`ARCHITECTURE.md`、`BUSINESS_FLOWS.md`、`EVIDENCE_INDEX.md`。

本仓库是 **Python 3.12 Agent 编排服务**，不是 Java 单体。第 20 节按技能固定标题保留，素材写的是可迁移的企业编排/一致性能力，不把本仓说成 Java 业务系统。

---

## 1. 项目一句话定位

用 AgentScope 2.0 替换旧 Java `agent-service` 的推理与多 Agent 编排，同时把身份、数据和有副作用动作继续交给原平台，避免把模型变成租户或账本权威。

## 2. 项目背景与业务目标

- 核心用户 / 调用方：经 `edge-gateway` 的内部服务与 Showcase 前端；不是匿名公网 Agent。
- 系统负责：模型调用、工具选择、DAG/投票/反思编排、轨迹与版本、受治理写工具入口、可恢复会话、把异步任务提交给中央服务。
- 系统不负责：知识索引、NL2SQL 执行与租户行级权限、订单账本、工作流审批、出站 webhook 权威存储、生产 IAM。
- 上游：edge-gateway（JWT）、LiteLLM。
- 下游：knowledge / analytics / workflow / order / async-task，以及默认关闭的 MCP 与远端 sandbox。
- 为什么不是普通 CRUD：失败形态是跨租户泄漏、重复退款、把超时当失败后瞎补、模型自带 tenantId、确认只绑工具名不绑参数、AgentScope 状态外泄。这些都不是“加一个聊天接口”能挡住的。

## 3. 系统总体架构

单进程六边形：API 兼容旧 HTTP；Application 持有端口；Domain 语言中立；Infrastructure 适配 AgentScope/HTTP/Redis/JWT。同步路径无本地业务库。异步与写工具默认关。详见 `ARCHITECTURE.md`。证据：E-01、E-02、E-19。

## 4. 模块地图

从路由与端口恢复，而不是目录宣传：

| 模块 | 入口证据 | 职责 |
|---|---|---|
| api | `routes.py` 全量 `/agent/**` | 契约、鉴权依赖、SSE 投影 |
| application.service | `AgentApplicationService` | 单次 run |
| application.dag/planning | DAG + Planner 种类 GENERAL/ANALYST/PROCESS | 图执行与安全回退 |
| application.sibling | chain/vote/reflexion | 无工具编排 |
| application.session | session CAS | 可恢复执行 |
| application.async_task | 202 worker | 中央任务的本地执行器 |
| application.confirmation | grant 生命周期 | 人在环写工具 |
| domain.tool | `ToolPolicy` | 纯策略 |
| infrastructure.agentscope | runner/tools/planner | 框架隔离 |
| infrastructure.http | `PlatformClient` | Java ACL |
| evaluation | CLI 入口 | 迁移门禁，不在热路径 |

## 5. 核心业务链路

1. 同步只读 `/agent/run`
2. 确认 grant + `refund_start`
3. DAG / plan-run / analyst
4. Process 只读与受控写
5. 会话 checkpoint 恢复
6. 异步 202 + SSE
7. chain / vote / reflexion
8. 能力发现 registry

细节与时序图见 `BUSINESS_FLOWS.md`。

## 6. 核心领域模型

不硬套完整 DDD 聚合。实际核心对象：

- `TenantIdentity`：tenant/user/scopes/dept，frozen dataclass
- `RunContext`：身份 + caller token + trace + 确认集 + 幂等键
- `ToolMetadata` / `ToolPolicyDecision`：工具安全契约
- `ToolConfirmationGrant`：一次性、参数哈希绑定
- `AgentSessionCheckpoint`：revision、lease、goalSha256、sideEffectObserved
- `AgentAsyncTask` / `CentralAsyncTask`：任务投影，含 leaseEpoch
- `DagPlan` / `AgentDagRunReply`：任务图与质量尝试
- `ExecutionVersions`：prompt/model/toolset 内容哈希
- `AgentRunReply`：对外兼容，`thought` 恒为空字符串

AgentScope `Agent`/`AgentState` 不是领域模型，禁止外发。

## 7. 核心数据库模型

本仓 **没有** 业务表、Flyway 或唯一索引。

持久化只有两类 Redis（或 memory 等价物）：

1. 确认防重放：`{namespace}:{grant_id}` → `"1"`，`SET NX EX ttl`
2. 会话：`{namespace}:{sessionId}` → checkpoint JSON，Lua 比较 `revision` 后 `SET EX`

异步任务、退款实例、订单、知识文档的表不在本 Workspace。Python 把 `Idempotency-Key` 映射为 Java `dedupeId`。Java 是否 UNIQUE：UNCONFIRMED（E-28）。

## 8. 技术栈

每项落到真实链，禁止名词堆砌。

| 技术 | 用在哪条链 | 解决什么 | 状态 |
|---|---|---|---|
| Python 3.12 + FastAPI/Uvicorn | 全部 HTTP | 兼容旧 JSON/SSE | 已实现 |
| Pydantic / pydantic-settings | 契约与 env | extra=forbid、生产条件校验 | 已实现 |
| AgentScope 2.0.5 | runner/planner/reviewer/tools | ReAct 与模型事件 | 仅 adapter |
| HTTPX | Java/MCP/sandbox/async | 共享连接池 | 已实现 |
| PyJWT | 内部/确认/downstream/worker 四套 | 身份与授权分离 | 已实现 |
| Redis | 确认 NX、会话 CAS | 多副本互斥与一次性 | 可选；生产条件强制 |
| mcp SDK Streamable HTTP | MCP 工具 | 无 stdio | 默认关 |
| OpenTelemetry | tracing/metrics | 可选导出；Prometheus 默认可刮 | OTel 默认关 |
| structlog | 观察 | 避免把密钥打进日志的约定 | 已实现 |
| pytest/ruff/mypy | CI | 边界与契约锁 | 已实现 |
| Kafka/MySQL/Celery | — | 依赖与源码均未使用 | 未使用 |

模型网关是 LiteLLM（配置 `GATEWAY_BASE_URL`），应用内无 provider switch。

## 9. 核心技术难点

评级只展开 S/A。

### 9.1 模型不能成为租户权威（S）

```text
Problem: 工具参数或 prompt 里伪造 tenantId，会打到别人的知识/订单/流程。
Why Difficult: LLM 输出不可信；工具框架回调往往没有显式 context 参数。
Current Solution: JWT 构造 RunContext；ContextVar 绑定；Java 调用只传已验证 caller token；MCP 参数禁止身份字段；RAG 二次比对 tenant_id。
Key Implementation: InternalJwtVerifier；current_run_context；PlatformClient._request；ReadonlyToolset.rag_search；McpToolBinding 禁 platform.agent.*
Trade-off: 工具函数签名“看起来”无身份，调试要找 ContextVar；假设 asyncio 任务传播。
Failure Scenario: Java 不回 tenant_id 时 Python 跳过比对；INTERNAL_AUTH_REQUIRED=false 时身份变成 anonymous。
Risk: 跨租户只读泄漏。
Possible Evolution: 强制下游响应带 tenant；禁止非生产关闭鉴权。
```

### 9.2 写工具超时既不能当成功也不能当失败（S）

```text
Problem: refund_start 在确认已消费后 Java 超时，重试可能双开流程，当失败可能漏开。
Why Difficult: 确认消费与 Java 调用无共享事务；本仓无 Outbox。
Current Solution: 写工具 retryPolicy=NONE；grant 一次性 NX；同一 Idempotency-Key 传 Java；工具文案强调未批准。
Key Implementation: GovernedFunctionTool.call consume-then-invoke；GovernedToolset.refund_start；Settings 禁止写工具无 32-byte confirmation secret。
Trade-off: 用户可能看到失败但 Java 已创建；要靠下游去重或人工查实例。
Failure Scenario: Java 无 unique(dedupeId)；memory replay 多副本；新 grant + 同 key 的语义完全依赖 Java。
Risk: 重复发起审批（不一定自动打款，但仍是工单事故）。
Possible Evolution: 先 Java 再消费 grant，或把 consume 纳入 Java 事务/Outbox（需跨仓）。
```

### 9.3 确认必须绑参数而不是绑工具名（S）

```text
Problem: “用户确认了 refund_start”后模型把金额/订单改掉。
Why Difficult: 确认与执行时间分离；参数是 JSON。
Current Solution: canonical JSON sha256 进 JWT；执行时再哈希比对；旧头 X-Agent-Confirmed-Tools 直接 400。
Key Implementation: canonical_tool_arguments_hash；RunContext.confirmation_for；_confirmation_tokens
Trade-off: 参数键序/空格必须 canonical；过大参数拒绝。
Failure Scenario: 非 JSON 可序列化参数；时钟 skew 过大仍受 TTL 上限约束。
Risk: 确认覆盖错误业务对象。
Possible Evolution: 把业务主键单独进 grant claims。
```

### 9.4 可恢复会话 vs 框架状态泄漏（A）

```text
Problem: 把 AgentScope state 或原始 goal/token 存 Redis，会变成密钥库和第二身份源。
Why Difficult: 框架状态不可语言中立，也难跨版本。
Current Solution: checkpoint schema 固定；只存 steps 截断与 goalSha256；CAS+lease；副作用恢复要新确认。
Key Implementation: AgentSessionCheckpoint；Redis Lua CAS；AgentSessionService._validate_resume
Trade-off: 不能完美热恢复模型 KV cache；lease 过期才能抢。
Failure Scenario: 默认 memory 多副本丢互斥；progress CAS 失败中断。
Risk: 双 worker 同时跑同一 session。
Possible Evolution: 生产启动即拒绝 memory（已有 env=production 校验）。
```

### 9.5 异步任务租约 fencing（A）

```text
Problem: 双副本都以为自己在跑同一 taskId，后写覆盖先写。
Why Difficult: 至少一次 + 进程崩溃 + 时钟。
Current Solution: 中央 lease_epoch；心跳校验 owner+epoch；update_status 带 fencing；token 寿命不足拒绝提交。
Key Implementation: AsyncTaskManager._heartbeat/_complete_once/_validate_deadline
Trade-off: 执行仍在抢到 lease 的 API 进程里，不是独立 worker pool。
Failure Scenario: 中央服务不校验 epoch（本仓客户端会传，服务端 UNCONFIRMED）；inflight 只在本进程计数。
Risk: 双跑模型费用；错误终态。
Possible Evolution: 真正的独立 worker 部署单元。
```

### 9.6 DAG 环、扇出与质量闭环（A）

```text
Problem: 坏图死循环；同层打爆模型；低质量综合答案直接返回。
Why Difficult: 计划来自模型。
Current Solution: 任务数上限、环检测、semaphore、critic/replan 有界；Process 更严且关 replan。
Key Implementation: _topological_levels；_worker_slots；DagReviewPolicy
Trade-off: 同步延迟和费用上升；replan 默认开。
Failure Scenario: critic 自身幻觉；阈值被“空话”凑过。
Risk: 成本事故多于资损。
Possible Evolution: 按租户费用熔断。
```

## 10. 核心架构亮点

同时满足：真实问题 + 方案 + 代码 + 复杂度。

1. **绞杀者边界**：AgentScope 被 ArchUnit 式测试关在 adapter 里，对外仍是旧 JSON。这不是“换个框架重写”。
2. **工具政策对象化**：只读/写、确认、幂等、重试四元组互相约束，写工具默认关。
3. **确认 grant 作为能力票据**：与内部 JWT、downstream JWT、worker JWT 密钥分离。
4. **语言中立 checkpoint**：可恢复但不持久化框架对象。
5. **出站韧性按依赖隔离**：一个 Java 服务熔断不会抽干全部 httpx 槽位。
6. **评测作为迁移闸门**：只读 Shadow、localhost 默认、内容寻址版本；生产 GO 另走证据 JSON fail-closed。

Spring/FastAPI/Redis 本身不算亮点。

## 11. 设计模式分析

真实变化点才写：

- **Adapter / ACL**：`PlatformClient`、`HttpRemoteSandboxGateway`、`StreamableHttpMcpGateway`、`AgentScopeRunner`
- **Strategy**：`DagPlanKind`（general/analyst/process）换 Planner 提示与回退；`VotingStrategy`
- **Policy**：`ToolPolicy` 纯函数，与 I/O 分离
- **Ports & Adapters**：`application/ports.py`
- **Template Method 弱形式**：DAG `_execute` 固定 levels→workers→synthesis，质量策略可关
- **Fence/Lease**：session 与 async-task
- **未观察到**：空 `BaseXxxImpl` 接口充数；也没有 Drools/工作流引擎在本仓

## 12. 性能与稳定性分析

仓库 **没有** 正式 QPS/TP99 NFR，不得编造达标数字。

已实现的稳定手段：

- 每请求 wall-clock `asyncio.timeout(AGENT_TIMEOUT_SECONDS)`
- 有限 `AGENT_MAX_TOKENS` / `AGENT_MAX_STEPS` / 单次 output tokens
- 模型重试默认 0
- HTTP 连接池、每依赖并发、熔断、绝对 `X-Request-Deadline-Ms`
- readiness 单依赖 2s，领域服务 DOWN 不挡只依赖模型的流量
- DAG/sibling 并行上限
- async inflight/concurrent/runtime/drain
- Compose 只读根盘 + 非 root

压力点（10× 流量）：LiteLLM 与 Java RAG/SQL；DAG 同步扇出；单 Redis key（sessionId/grant_id，离散，不像全局热点库存）；API 进程内 async worker 会先打满 inflight。

## 13. 数据一致性设计

最弱且对当前范围足够的模型：

- **身份与授权**：请求级强校验，无最终一致身份缓存
- **只读查询**：允许短暂陈旧（Java/缓存如何做不在本仓）
- **写工具**：一次性票据 + 下游业务幂等键；**无** 本仓 Outbox/Inbox
- **会话**：乐观 revision + lease；冲突失败，不静默覆盖
- **异步任务**：中央权威 + epoch fencing
- **确认 replay**：NX 成功即“已用”，与 Java 成功解耦

选择最终一致而不是 2PC 的原因：编排器与 Java 无共享 DB。代价是 UNKNOWN 窗口。对账不在本仓。

## 14. 并发与异步设计

- 同 session：CAS + 未过期 lease 拒绝第二请求
- 同 grant：Redis NX / 内存锁
- 同 async task：lease owner+epoch；心跳失败停跑
- DAG 同层 gather + 全局 semaphore；异常取消兄弟 task
- 写工具 `is_concurrency_safe` 对只读为 True，写工具默认跟 metadata.read_only
- 无超卖库存问题；“超卖”类比是重复退款工单与双跑 session
- ContextVar 不是跨进程锁

## 15. 可扩展性分析

有：

- 工具 allowlist（MCP JSON、GovernedToolset 开关）
- Planner kind
- Session store / replay store 工厂
- Capability registry 内容哈希
- 评测数据集 schema

没有：通用插件 SPI、规则引擎、工作流引擎、用户可上传工具。扩展靠改配置与加 adapter，这是刻意收窄。

## 16. 工程质量分析

- 53 个测试模块，覆盖 JWT、确认、会话、DAG、韧性、契约导出、架构边界、Shadow
- CI：ruff、mypy strict、pytest cov≥80、contract export --check、shadow-smoke、SBOM、Trivy HIGH/CRITICAL、tag 发布签名
- 错误：未知失败映射稳定码，避免把上游正文回给客户端（readiness/async/SSE）
- 开关默认值与代码一致：写工具/MCP/browser/code/async/v2/OTel 默认关
- 本分析 **未执行** pytest/ruff；测试结果标 UNVERIFIED
- `CODEX_PROGRESS.md` 记录过 470 tests / 89.60% coverage，属历史证据，非本次运行

## 17. 当前架构问题

1. 确认消费与 Java 调用非原子，存在 UNKNOWN
2. 默认 memory 存储与 Compose 默认值偏开发
3. 异步执行粘在 API 进程
4. Process 计划过滤是字符串包含，纵深依赖工具策略
5. RAG 租户二次校验可被空 tenant_id 绕过比对
6. PII 脱敏只覆盖邮箱/国内手机/身份证模式
7. 本仓无 Helm，文档/进度里的 K8s 能力不能算本仓已实现
8. README “Phase 5 全量默认切换” 与生产 NO-GO 并存，对外叙述容易混

## 18. 潜在技术风险

事故形态，不写空泛“有风险”：

- 跨租户只读泄漏（鉴权关、Java 漏 tenant）
- 重复退款工单（Java 去重缺失 + 换 grant 重试）
- 确认重放（生产误用 memory）
- 双 session runner（memory 或多副本 CAS 失败被忽略——当前失败会抛 409，忽略发生在调用方）
- DAG/投票把 LiteLLM 打满，同步请求堆积
- Shadow 未在真实模型上跑却声称行为等价
- 供应链：依赖审计在 CI，但本分析未验证最新 Action 运行结果

## 19. 架构改进方向

短期（不视为已批准设计）：

- 生产环境拒绝 `INTERNAL_AUTH_REQUIRED=false`
- 写工具路径明确文档化 UNKNOWN 与查询 workflow 的操作手册
- RAG 在 Java 缺失 tenant_id 时 fail closed

中期：

- 独立 async worker 部署
- 确认与 Java 的补偿/对账表（应落在 Java Owner）
- 租户级费用熔断

长期：

- 生产证据 GO 后再谈删除 Java agent-service
- 统一 W3C Trace，替换长期兼容的 `X-Trace-Id`

## 20. 高级Java简历价值点

说明：本仓实现语言是 Python。下列条目写的是 **平台编排与一致性**，面试时可迁到 Java 等价设计；不要写成“负责 Java 库存中心”。

项目描述（约 160 字）：

负责企业平台 Agent 编排替换件，覆盖内部 JWT 入站、只读工具调用、受治理写工具、DAG 编排到可恢复会话与异步任务投影的完整链路，设计工具安全契约、参数绑定一次性确认、会话 revision/租约和中央任务 fencing，基于语言中立 HTTP/JSON 契约与 AgentScope 适配器落地旧接口兼容能力。

贡献候选：

1. 负责 Agent 运行身份链路，覆盖验签、RunContext 传播到 Java 工具调用，设计禁止模型参数覆盖租户，基于 JWT claims 与出站透传实现租户绑定执行。
2. 负责写工具治理链路，覆盖确认签发、参数哈希校验、一次性消费到 workflow 发起，设计确认与内部令牌密钥分离，基于 Redis NX 与幂等键传递实现可追责发起而非自动审批。
3. 负责可恢复执行链路，覆盖 session 创建、进度 CAS、lease 互斥到终态写回，设计语言中立 checkpoint，基于 Redis Lua 比较 revision 实现多请求恢复且不持久化框架状态。
4. 负责异步任务投影链路，覆盖 202 提交、租约心跳、epoch 写回到可恢复 SSE，设计 token 剩余寿命门禁与进程 drain，基于中央任务服务权威实现取消与事件顺序。
5. 负责 DAG 编排链路，覆盖计划校验、分层并行、综合与有界 replan，设计环检测与 Process 只读回退，基于同一 RunContext 多 Agent 执行实现兼容旧 `/agent/dag/**`。
6. 负责迁移评测链路，覆盖只读双跑、内容寻址版本与生产证据 fail-closed，设计远程目标显式 opt-in，基于独立 CLI 实现工程 PASS 与生产 GO 分离。
7. 负责出站隔离链路，覆盖共享连接池、每依赖 bulkhead/熔断与绝对 deadline，设计写路径不做无条件重试，基于 HTTPX 与依赖注册表实现故障域隔离。

禁止把“为了避免超卖引入 Redis”这类分析腔写进简历。无压测数字，不写高性能。

## 21. 面试官深挖问题

### 故事 A：超时后的退款发起（S）

1. 场景：已消费 confirmation 后 workflow HTTP 超时。
2. 风险：当失败会漏单；立刻重试可能双开。
3. 设计：不重试；grant 一次性；同一幂等键给 Java；用户可见失败但可查实例。
4. 取舍：体验差于 2PC，换来编排器无业务库。
5. 验证：工具与确认单测；Java unique 需跨仓证明。
6. 锚点：`governed_tools.py` `refund_start`；`GovernedFunctionTool.call`

口头：这里最危险的不是接口慢，而是超时后既不能当成功也不能当失败。

### 故事 B：确认绑参数（S）

追问：键相同 payload 不同怎么办？答：哈希不匹配走 `CONFIRMATION_INVALID`，不是 ALLOW。

### 故事 C：会话 lease（A）

追问：lease 过期但进程还在跑？答：对方 CAS 会失败抛 409；需要看 progress 是否还持有旧 revision。仍有窗口，靠 TTL 与单写者。

### 故事 D：为什么 ContextVar 不算全局租户变量（L3）

答：请求进入绑定、finally 复位；未绑定直接崩。是适配器约束，不是 ThreadLocal 缓存当前登录用户跨请求复用。

### 分层题库

- Level 1 项目理解：为什么不重写 Java 知识/订单？默认工具为什么只有七个只读？
- Level 2 实现细节：JWT 要校验哪些 claims？MCP 为什么不能拿 `X-Internal-Token`？checkpoint 为什么存 goalSha256？
- Level 3 架构设计：为什么确认先 NX 再调 Java？反过来呢？为什么异步权威不放本进程 Redis？
- Level 4 故障场景：memory replay 多副本；critic 一直低于阈值；SSE 客户端断开而 bounded queue 已满。
- Level 5 规模扩大：DAG 同步扇出 10×；LiteLLM 成为单点；API 进程兼 worker 时 inflight 先满。

## 22. 项目学习地图

1. `api/dependencies.py` + `domain/agent.py`：身份怎么进请求
2. `api/routes.py`：有哪些真实入口
3. `infrastructure/agentscope/runner.py` + `readonly_tools.py`：一次 run 怎么打 Java
4. `domain/tool.py` + `infrastructure/agentscope/tools.py` + `application/confirmation.py`：写工具怎么被拦住
5. `application/dag.py` + `application/planning.py`：图与 Process fail-closed
6. `application/session.py` + `infrastructure/persistence/agent_session.py`：CAS/lease
7. `application/async_task.py`：fencing 与 drain
8. `tests/test_architecture_boundaries.py` + `evaluation/shadow.py`：边界与迁移闸
9. 最后读 `CODEX_PROGRESS.md` 区分工程 PASS 与生产 NO-GO

## 23. 未确认事项

- 本分析未运行 pytest/mypy/ruff；覆盖率与 470 tests 为历史记录
- Java workflow `dedupeId` 唯一约束、事务账本、Flyway、Helm HPA/PDB
- 生产 `AGENT_URI` 是否已指向本服务
- Redis 多副本 CAS/failover 是否演练过
- 真实模型 Shadow v4 是否在目标环境跑过
- edge-gateway 限流与 Casdoor 细节
- async-task-service 服务端是否强制校验 leaseEpoch（客户端已传）
- `HOST.docker.internal` 本地全栈是否仍在跑（进度文档时间点 2026-08-03）
- 组织架构/个人职级：无证据，简历不得写“主导团队”

## 24. 证据索引摘要

完整条目见 `EVIDENCE_INDEX.md`。主证据：E-01 定位、E-02 分层锁、E-03/E-04 JWT、E-07/E-09 工具与确认、E-13/E-14 会话、E-15 异步 fencing、E-16/E-17 DAG 与 Process、E-18 韧性、E-19 无业务库、E-20/E-21 评测与生产门禁、E-28 跨仓 UNCONFIRMED。
