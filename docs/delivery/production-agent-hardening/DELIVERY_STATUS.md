# Delivery Status

## Goal

按已批准的生产审查建议加固 AgentScope 与 langchain4j-platform，并在每个实现切片后运行测试。

## State

- Phase: Phase 6 - verification and handoff
- Status: engineering-complete / production-NO-GO
- Last updated: 2026-08-03

## Completed

- Phase 1～4：基于两仓代码、部署、QA 与当前招聘能力要求完成可行性、产品和技术设计。
- Gate A：用户已明确批准按推荐实施，并要求每项修改后测试。
- Slice 1 / AC-01：Agent 整次运行默认限制为 24,000 tokens / 120 秒，配置不再接受 0；
  单次模型输出限制为 4,096 tokens，并将应用层模型重试默认设为 0，由 LiteLLM 统一负责
  provider retry/failover。runner 对所有执行无条件应用 wall-clock timeout，并将单次输出上限
  收敛到 `min(run budget, model output limit)`。
- Slice 2 / AC-02：所有受治理写工具改用一次性短时签名 grant。grant 绑定 tenant、user、tool、
  规范化参数 SHA-256、幂等键、`iat/exp/jti`，使用与内部 JWT 分离的 HS256 key；provider 调用前
  通过 Redis `SET NX EX` 原子消费，篡改、跨租户/用户、错参数、错幂等键、过期、重复 grant、
  重放和 Redis 故障全部 fail-closed。生产启用写工具时强制 Redis replay store；旧的仅工具名
  确认头明确拒绝。新增 `POST /agent/tool-confirmations` 语言中立契约及部署密钥隔离门禁。
- Slice 3 / AC-03：MCP、browser sandbox 与 code sandbox 不再接收 caller `X-Internal-Token`，
  改用独立 key 签发的 60 秒、单 audience、单 action、请求级下游凭据；凭据只允许
  `agent.tool.invoke` 且分别绑定 MCP tool 或 sandbox operation。Python 与 Java 内部 JWT 统一
  严格校验 `alg/typ/kid/iss/aud/token_use/jti/iat/exp`、唯一 audience、最大 TTL、身份与 scope
  边界；普通访问令牌和 service callback 令牌用途互斥。部署门禁强制三类签名 key 分离，并固定
  issuer/audience/key-id 跨语言一致。全量回归额外发现并修复 JJWT 会按长 key 自动把 HS256
  升级为 HS384 的问题，签发端现显式固定所配置算法。
- Slice 4 / AC-04：async-task 用户控制面改为 `tenant + owner user` 授权，同租户其他用户对
  list/get/stream/cancel 也不可见；lease/status/events 改为独立 worker 数据面，只接受与普通
  internal JWT 分离的短时 HS256 凭据。worker token 绑定 service/tenant/actor/worker/task/action，
  caller JWT 不再进入 worker 请求；workerId 冒充、错 action、跨 owner、无租约和过期租约均被
  拒绝。状态迁移在内存/JDBC store 内再次原子校验当前租约，消除 controller 检查后的到期竞态。
  AgentScope、workflow、knowledge 与 legacy agent 客户端均先 lease 再写状态；worker forwarder
  先于普通租户 forwarder，纯 RS256 验签节点不会误签普通内部令牌。Compose/Helm 只向中央
  verifier 和实际 worker 挂载独立 key，并显式统一 header/issuer/audience/kid/TTL/skew。
- Slice 5 / AC-05：async-task、workflow 与 A2A push 统一使用 `OutboundCallbackPolicy`，在注册和
  每次投递前校验精确 HTTPS origin、重新解析 DNS 并拒绝任一 IPv4/IPv6 私网/保留地址；3xx 不跟随
  且按策略错误终止。A2A 栈内中继是只注入 async-task-service 的完整 URL 例外，同 origin 其它路径
  仍拒绝。三条链路统一使用绑定 timestamp/delivery/event/exact-body 的 `v1` HMAC，密钥至少 32 字节、
  分服务隔离且不复用；持久 outbox 的 delivery id 跨重启/重试稳定。Compose/Helm 生产门禁检查
  allowlist、精确内网例外和三把 key 的最小挂载；文档明确 DNS TOCTOU 仍须 egress 网络策略兜底。
- Slice 6 / AC-06：AgentScope 任务/Reflexion 与 Java Conversation、Reflexion、任务中心、Voice、
  A2A 的所有 SSE 出站都在写出前遮蔽邮箱、中国手机号和身份证号；跨 token 的 Conversation
  输出使用有界尾缓冲，避免拆 token 绕过。provider、HTTP、ASR/TTS 和任务失败只映射为稳定错误码/
  固定消息，日志只保留异常类型。下游断开会关闭活动 HTTP 响应；A2A research 还会显式取消任务，
  AgentScope Reflexion 会取消并等待 producer。持久任务订阅断开只释放观察连接，必须显式 DELETE
  才取消任务；langchain4j 当前 `TokenStream`/同步模型调用没有 provider 取消句柄，此边界已在代码、
  日志和运维文档明确记录。
- Slice 7 / AC-07：Java 退款启动新增 `WF_IDEMPOTENCY` 权威账本，复合主键按 tenant、operation 与
  chat-scoped 幂等键摘要唯一；请求摘要同时绑定 user、message 和安全化 webhook。数据库 claim、
  Flowable 实例创建和 instance 绑定经同一个 `workflowTransactionManager` 原子提交，相同键同请求
  复用原实例、参数冲突返回 409、失败回滚后可重试、跨租户独立。滚动升级时只收编参数完全一致的
  旧 businessKey 实例；历史清理与 PII purge 同事务删除对应幂等绑定，避免账本悬挂或删除后泄露关联。
- Slice 8 / AC-08：AgentScope 的 Java/MCP/sandbox/async-task 客户端改为进程级共享
  `httpx.AsyncClient`，统一连接池上限、keep-alive、请求/父 deadline 传播，以及按依赖隔离的
  非阻塞 bulkhead、circuit breaker 和单 half-open probe；SSE 在完整消费期间持有隔离槽，并同时
  受空闲/总时限约束。Java `platform-security` 让 Boot `RestTemplateBuilder` 统一选择 Apache
  HttpClient 5 连接池，自动装配按 origin 的 deadline/bulkhead/circuit 拦截器和入站 deadline filter；
  百炼 rerank 也移除无连接池的 Simple request factory。4xx 不污染熔断，传输异常/5xx 计入；
  读取能力只做明确安全降级，副作用调用不在该层重试或伪造成功。
- Slice 9 / AC-09：中央任务租约新增单调 `leaseEpoch`；每个 AgentScope/Java worker 进程使用
  `serviceId.<instance>` 作为唯一 lease owner，首次 claim 递增 epoch，续租、status 和 progress
  必须同时匹配未过期 owner + epoch。JDBC/内存状态迁移和 progress journal append 都在任务级锁/
  同一事务内完成，接管后的旧副本无法提交迟到终态或事件，重复 eventKey 也不会重复推送 SSE。
  async webhook/lifecycle、workflow HTTP/terminal-event 四条 outbox relay 全部改为唯一实例 claim owner、
  TTL 过期恢复和条件 delivered/retry/dead，旧 claimant 不能覆盖新副本。AgentScope shutdown 先停止
  新提交并保持 heartbeat 等待 drain，超时只停止本地 work、保留中央 RUNNING 供租约到期/reaper
  安全收口；Compose/Helm 停止宽限大于 drain。
- Slice 10 / AC-10：AgentScope readiness 使用共享短时连接池并发检查模型网关，以及所有启用的
  async-task、MCP、Browser、Code 和 Redis confirmation replay 必要依赖；必要依赖 DOWN 时返回 503，
  可降级 Java 业务服务仅显示状态。响应只暴露 `UP/DOWN/DISABLED`，404/429/5xx 和传输失败不再误报
  可用。Python Prometheus 新增 Agent 延迟 histogram、run/async inflight、backlog、token、可配置费率
  成本估算和终止原因；Java 中央服务按权威数据库状态导出 async backlog/inflight，跨副本计数一致。
- Slice 11 / AC-11：Helm 为每个 workload 创建专用、禁用 token 自动挂载的 ServiceAccount，
  容器统一使用非 root UID/GID 10001、只读根文件系统、丢弃全部 capabilities、RuntimeDefault
  seccomp 和有界 `/tmp` emptyDir；Compose 同步强制等价运行约束。全局整包 secret 注入已移除，
  各服务只通过 `secretKeyRef` 获取实际所需 key。新增默认拒绝与必要通信 NetworkPolicy，
  默认阻断私网、metadata 和保留地址出站；edge、AgentScope 和 async-task 增加 HPA、PDB、
  RollingUpdate 及 hostname/zone 拓扑分散。静态门禁对完整 Helm 渲染和全 Compose profile 逐服务断言。
- Slice 12 / AC-12：新增独立 `database-migrations` 可执行模块，以 Flyway 版本统一管理 auth、
  async-task、workflow/Flowable、Knowledge ingestion/graph、order、channel 和 analytics demo 八个
  schema；支持旧库 version 0 baseline、additive expand/backfill 和幂等重跑，禁用 clean。业务
  JDBC store 全部移除建表/改表，Flowable 固定 `schemaUpdate=false`，启动只读验证 schema，缺表
  fail-fast 且不会创建对象。Compose 新增健康 MySQL、最小权限 app/migrator 用户与 8 个一次性迁移
  服务，业务容器等待对应迁移成功；Helm 使用 pre-install/pre-upgrade Hook Job、独立迁移凭据、
  有界 deadline 和 AC-11 安全上下文。旧 analytics 破坏性 seed SQL 已退役，demo 数据进入幂等
  migration；CI、静态门禁和 expand-contract/回滚 runbook 同步完成。最终审查进一步将所有运行时
  默认账号收紧为独立 app 身份，移除 analytics 未使用的 admin 凭据接口；Helm 迁移凭据改为
  预发布独立 `platform-migration-secrets`，避免首次安装的 pre-install Hook 与同 release ESO 资源竞态。
- Slice 13 / AC-13：两仓新增真实供应链流水线。AgentScope 运行锁定依赖审计、完整质量门禁、
  Python package/CycloneDX 和单镜像扫描；Java 运行完整 Reactor、422-component aggregate
  CycloneDX 依赖图和与仓库 17 个 Dockerfile 精确一致的镜像矩阵。所有第三方 Action 固定完整
  commit SHA，普通 CI 只有只读权限；仅 `v*` tag release 使用 GitHub OIDC 向 GHCR 推送并对实际
  digest 重新扫描、生成 SBOM、Cosign 签名和 GitHub SLSA/SBOM attestation。静态自举门禁会拒绝
  浮动 Action、`pull_request_target`、提前授予写权限及扫描/签名/证明缺失；Dependabot、发布后
  验证、失败制品 deny、可信 digest 回滚和 Action 安全事件 runbook 已同步。全量 Java Reactor
  暴露并修复了 AC-09 后遗留的 worker UUID/lease-first 测试预期，随后全绿。
- Slice 14 / AC-14：新增 `agent-session-checkpoint.v1` 语言中立 checkpoint，以及 owner 隔离、
  goal/副作用摘要绑定、revision CAS、lease、TTL 和终态幂等的持久会话服务；生产只允许 Redis
  权威 store。恢复只从稳定、脱敏步骤重建 AgentScope 运行态，框架对象不越过 adapter 或进入存储；
  副作用恢复要求原幂等摘要和新 confirmation grant。新增 session run/get API 与版本化 capability
  registry，旧 `/agent/capabilities` 保持原始 JSON 契约。Java A2A 改为持久 `a2a-task-context.v1`，
  context 跨 send/get/cancel/stream/push 保持，push token 使用独立 AES-256-GCM key 加密；能力发现
  消费新 registry，并用 Redis last-known-good 支撑进程重启，拒绝静态 Agent capability fallback。
- Slice 15 / AC-15：Agent 内部 `agent-trajectory.v1` 现在绑定内容寻址的 prompt、model、toolset
  与逐工具版本；旧 `/agent/run` JSON 不变，三个集合级 SHA-256 通过响应头提供给评测 runner。
  Shadow report 升级 v4，绑定 `agent-evaluation-dataset.v1` 内容版本、可选原报告 digest 和每次运行
  版本；缺版本元数据或批内版本漂移可 fail closed。新增 `agentscope-eval-dataset` CLI，支持旧 JSONL
  迁移/校验、强制 forbidden behavior 的 adversarial 集，以及只接受 consented/read-only 最小字段、
  遮蔽常见 PII 且不保存原 feedback ID 的线上反馈导入。回放必须使用与原报告完全一致的 dataset
  ID/version。Java eval-service 只读 parser 同步只接受带合法 dataset digest 的 v4 报告，不复制
  Python 评测执行逻辑。
- Slice 16 / AC-16：新增统一生产发布运行手册与 `agent-production-evidence.v1` 机器可读证据门禁，
  固定发布角色、RPO/RTO、供应链/IAM/迁移/恢复/容量/高峰 soak/Shadow 对抗集/租户 canary/
  告警与整服务回滚共 19 项必选证据。默认模板明确为 NO-GO；只有真实 release/digest、逐项 owner、
  RFC3339 时间和 HTTPS 证据全部 PASS 时，`--require-go` 才返回 GO。CI 同步校验运行手册、对抗数据集
  和最终 REVIEW/QA/DELIVERY 报告中的工程通过/生产 NO-GO 边界；两仓最终静态门禁与本地质量回归完成。

## Changed Files

- `docs/delivery/production-agent-hardening/DELIVERY_PLAN.md` - 交付、验收、验证与回滚基线。
- `docs/delivery/production-agent-hardening/DELIVERY_STATUS.md` - 持续状态和逐项测试记录。
- `.env.example` - 有界执行配置示例与重试责任说明。
- `compose.yml` - 显式传递 Agent 执行预算。
- `src/agentscope_platform/core/config.py` - 非零预算、单次输出和重试配置。
- `src/agentscope_platform/infrastructure/agentscope/runner.py` - 强制 deadline 与模型调用上限。
- `tests/test_execution_limits.py` - 默认值和无限配置拒绝测试。
- `tests/test_runner.py` - 模型构造输出上限和重试层测试。
- `src/agentscope_platform/domain/confirmation.py`、`application/confirmation.py`、
  `infrastructure/security/tool_confirmation.py` - 参数规范化、grant 签发/验证和一次性消费。
- `src/agentscope_platform/domain/tool.py`、`domain/agent.py`、`infrastructure/agentscope/tools.py` -
  参数绑定策略及 provider 调用前强制执行。
- `src/agentscope_platform/api/routes.py`、`api/dependencies.py`、`api/app.py` - 两阶段确认 API、
  header 验证与生命周期装配。
- `contracts/boundaries/tool-confirmation-*.schema.json`、`contracts/openapi.json`、
  `scripts/export_contracts.py` - 语言中立请求/响应契约。
- `tests/test_tool_confirmation.py`、`tests/tool_confirmation_support.py` 及受影响 API/工具测试 -
  篡改、跨租户、参数绑定、重放、Redis 故障与配置安全回归。
- `README.md`、`docs/contracts.md`、`docs/governed-tools.md`、`.env.example`、`compose.yml` -
  调用流程、配置、灰度和回滚说明。
- Java 仓 `deploy/docker-compose.yml`、`deploy/helm/platform/{values.yaml,templates/*}`、
  `deploy/test-production-cutover-config.sh` - AgentScope 专属确认密钥、Redis 与静态隔离断言。
- `src/agentscope_platform/domain/security.py`、
  `infrastructure/security/downstream_jwt.py` - 语言中立下游凭据及短时、action-bound 签发。
- `src/agentscope_platform/infrastructure/{mcp,sandbox}/*` - caller JWT 隔离与 provider 专属凭据。
- `src/agentscope_platform/infrastructure/security/internal_jwt.py`、`core/config.py` - 严格入站 JWT
  策略、有限 TTL 与独立 provider key 配置。
- `contracts/boundaries/downstream-service-token-claims.schema.json`、`scripts/export_contracts.py`、
  `tests/test_downstream_service_token.py` 及 JWT/MCP/sandbox/architecture 测试 - AC-03 契约与回归。
- Java 仓 `platform-security/{InternalToken,InternalSecurityProperties,PlatformSecurityAutoConfiguration}`
  及测试 - 跨语言严格声明、用途隔离和显式 HS256/RS256 签名算法。
- Java 仓 `async-task-service/.../AsyncTaskMetricsEndpointTest.java` - 使用自动装配签发器验证严格
  token 的 actuator 鉴权，并覆盖长 HS key 回归路径。
- 两仓部署配置、架构/运维文档及 `deploy/test-production-cutover-config.sh` - 严格上下文一致性、
  下游 key 仅注入 AgentScope，以及安全的 signer-first 滚动升级顺序。
- `src/agentscope_platform/domain/security.py`、`core/config.py`、
  `infrastructure/security/async_task_worker_jwt.py` - async worker claim 契约、独立 key 配置校验与
  operation/task-bound 凭据签发。
- `src/agentscope_platform/infrastructure/http/async_task_client.py` 及 async tests - 用户调用保留
  caller token，worker 调用只发送专用 token；覆盖声明、配置与原始 token 隔离。
- `contracts/boundaries/async-task-worker-token-claims.schema.json`、契约导出/测试及异步运行文档 -
  跨语言 worker 身份边界、启用与安全回滚说明。
- Java 仓 `platform-security/{AsyncTaskWorkerToken,AsyncTaskWorkerTokenForwarder,
  OutboundTenantForwarder,InternalTokenAuthFilter}` 及测试 - worker 凭据、预认证桥接与普通 JWT
  转发隔离。
- Java 仓 `async-task-service` controller/store/JDBC/filter 及测试 - owner 授权、worker filter、
  actor/worker/task/action 绑定和未过期租约原子约束。
- Java workflow/knowledge/agent worker clients 与两仓 Compose/Helm/运维文档 - lease-first 调用、
  独立 secret 最小挂载和非敏感上下文一致性门禁。
- Java 仓 `platform-security/{OutboundCallbackPolicy,OutboundWebhookSigner,
  InternalSecurityProperties,PlatformSecurityAutoConfiguration}` 及测试 - 统一 callback SSRF/DNS
  策略、精确 internal URL 例外、版本化 HMAC 和配置 fail-fast。
- Java `async-task-service` controller/notifier/outbox、`workflow-service` service/outbox 与
  `interop-service` A2A service/push forwarder 及测试 - 注册/投递双校验、禁止重定向、稳定 delivery id、
  失败分类与强制签名。
- Java Compose/Helm/ESO/生产门禁及 README、API、架构、运维、长任务、A2A 与
  `docs/平台工程/webhook-security.md` - 三把 callback key 最小权限隔离、HTTPS allowlist、接收方
  验签/去重、egress 兜底与不降级安全边界的回滚说明。
- `src/agentscope_platform/application/privacy.py`、`api/routes.py` 及
  `tests/test_{stream_privacy,stream_cancellation,sse_proxy}.py` - 任务/Reflexion 递归 PII 脱敏、稳定
  错误帧、坏帧关闭和满队列断连取消。
- Java `platform-security/PublicPayloadRedactor`、Conversation `StreamingPiiRedactor`、
  Reflexion/任务 SSE 与测试 - 共享 JSON 负载脱敏、跨 token 防绕过、稳定失败码和协作式取消。
- Java interop/voice 的 stream gateway、cancellation、executor 与测试 - 活动响应关闭、research
  任务取消、拒绝执行安全收尾，以及 ASR/TTS/provider 详情隔离。
- 两仓 SSE/异步/A2A/Voice/API 文档 - 公开错误契约、PII 规则、持久任务与非持久流的取消差异、
  provider 不可取消边界及安全回滚说明。
- Java `workflow-service/{WorkflowService,WorkflowIdempotencyStore,JdbcWorkflowIdempotencyStore,
  WorkflowHistoryCleaner}` 及测试 - 数据库唯一 claim、请求冲突、Flowable 同事务、升级收编、失败恢复、
  跨租户并发和 purge/retention 生命周期。
- Java workflow/API/架构/数据库文档与 AgentScope `docs/governed-tools.md` - 强幂等边界、键格式、
  409 契约、保留期和“下游支付仍需自己的幂等键”说明。
- `src/agentscope_platform/core/deadline.py`、`infrastructure/http/resilience.py` 及 HTTP/MCP/sandbox
  clients - monotonic 父 deadline、共享连接池、每依赖 bulkhead/circuit 与稳定错误映射。
- `src/agentscope_platform/api/app.py`、runner、配置/Compose、README/架构/异步文档及
  `tests/test_http_resilience.py` - 进程生命周期统一关闭、流式隔离、可调参数与故障回归。
- Java `platform-security/{RequestDeadlineContext,RequestDeadlineFilter,
  OutboundHttpResilienceInterceptor,PlatformSecurityAutoConfiguration}`、HttpClient5 依赖及测试 -
  入站/出站 deadline、按 origin 隔离、自动 builder 装配和池选择。
- Java Knowledge 百炼 rerank、Helm/Compose、运维/架构文档 - 移除 Simple 无池客户端并显式发布
  两仓 HTTP 可靠性配置和安全降级/回滚边界。
- `application/async_task.py`、async domain/ports/client/JWT、配置、测试与异步运行手册 - 唯一实例 owner、
  lease epoch 续租/写回、优雅 drain 和超时后不伪造终态。
- Java `platform-protocol` async DTO、`platform-security/AsyncTaskWorkerToken`、async-task controller/store/
  JDBC/event journal 及 workflow/knowledge/legacy clients - 跨语言 epoch fencing 与原子 progress append。
- Java async-task webhook/lifecycle 和 workflow HTTP/terminal-event outbox/relay 及 H2 测试 - 四条链路的
  claim TTL、故障重领与 stale owner 条件更新。
- 两仓 Compose、Helm library/values、workflow/async 配置与运维文档 - claim/drain 参数和 45 秒容器
  termination grace。
- `infrastructure/http/readiness.py`、confirmation replay store、API routes/app 与 readiness 测试 -
  必要依赖并发探测、超时、取消、稳定状态和 503 admission 语义。
- `application/observer.py`、runner、`observability/{runtime_metrics,prometheus,async_task_metrics}.py`
  及测试 - 运行延迟分布、inflight/backlog、token/cost、终止原因和 Prometheus histogram 渲染。
- Java async-task store/JDBC/metrics 与 Spring/H2 测试 - 中央 PENDING/RUNNING 数据库 Gauge、跨副本一致
  计数及受认证 Prometheus 实际值。
- 两仓 `.env`/Compose/Helm、README 与异步运行手册 - readiness timeout、模型费率、指标和告警说明。
- Java 仓 `deploy/helm/platform/templates/{_deployment.tpl,_serviceaccount.tpl,_pdb.tpl,workloads.yaml,
  networkpolicy.yaml}` 与 `values.yaml` - 专用 SA、Pod/容器安全上下文、有界临时盘、
  拓扑分散、HPA/PDB、NetworkPolicy 和最小密钥注入。
- Java 仓 `deploy/docker-compose.yml`、`deploy/docker-compose.knowledge-split.yml` 及 AgentScope
  `compose.yml` - 非 root、只读、capability drop、no-new-privileges 和 `/tmp` tmpfs。
- Java 仓 `deploy/test-runtime-hardening-config.sh`、`.github/workflows/agentscope-cutover-ci.yml`、
  `deploy/helm/README.md` 和 `docs/参考/operations.md` - AC-11 离线门禁、CI 路径与运维/回滚说明。
- Java 仓 `database-migrations/**` 与根 `pom.xml` - 8 schema 的 Flyway SQL/Java migrations、旧库
  expand/backfill、Flowable 7.1 schema、analytics demo 数据、CLI/Docker 镜像和 H2 集成测试。
- Java auth/async/workflow/knowledge/order/eventbus/analytics 的 JDBC 初始化、配置和测试 - 移除
  runtime DDL/自动建库，改为 schema contract 验证与缺 schema 启动失败测试。
- Java `deploy/docker-compose*.yml`、`deploy/mysql/init/`、Helm migrations/values/ESO - 独立 app/
  migrator 用户、Compose one-shot 依赖、Kubernetes Hook Job 与最小 secret 注入。
- Java `deploy/test-database-migration-config.sh`、CI workflow、`docs/平台工程/database-migrations.md`
  及现行架构/能力/运维文档 - AC-12 渲染门禁、expand-contract、baseline 与恢复/回滚说明。
- AgentScope `.github/workflows/ci.yml`、`.github/dependabot.yml`、
  `scripts/test_supply_chain_config.py` 和 `docs/software-supply-chain.md` - Python 依赖/包/镜像证据、
  tag-only OIDC 可信发布、自举策略门禁与验证/回滚说明。
- Java `.github/workflows/supply-chain.yml`、既有 CI immutable pins、`.github/dependabot.yml`、
  `deploy/test-supply-chain-config.sh` 和 `docs/平台工程/software-supply-chain.md` - 完整 Reactor、
  17 镜像矩阵、CycloneDX/Trivy/Cosign/attestation 与配置自举门禁。
- Java `agent-service/.../ExternalAsyncTaskClientTest.java` - 按生产实现验证唯一 worker instance 与
  lease epoch，并在终态镜像测试前显式取得租约。
- `src/agentscope_platform/{domain/session.py,application/session.py}`、session persistence/runner/API、
  capability registry、JSON Schema、契约导出与测试 - AC-14 的稳定 checkpoint、CAS 恢复和能力发现。
- Java `platform-protocol` capability/A2A DTO、`interop-service` Redis state/LKG、AES-GCM token、
  controller/service/config 与测试，以及两仓 Compose/Helm/A2A 文档 - 持久 context、加密 push 配置、
  registry 兼容和多副本生产配置。
- `domain/versioning.py`、`AgentTrajectory`、runner/API version headers、evaluation dataset/models/CLI、
  v4 report、contracts、adversarial fixture 与测试 - AC-15 的版本化轨迹、数据集、回放和反馈闭环。
- `docs/evaluation-versioning.md`、Shadow/contract/testing 文档，以及 Java eval control-plane 文档/
  `AgentScopeShadowReportReader` - 跨语言发布门禁、数据安全、回滚与 v4 fail-closed 规则。
- `docs/operations/production-release-runbook.md`、`production-evidence-template.json`、
  `scripts/test_production_runbook.py` 与 `tests/test_production_runbook.py` - AC-16 发布、恢复、回滚及
  机器证据 fail-closed 门禁。
- `.github/workflows/ci.yml`、`README.md`、`docs/testing.md` 与 Java
  `docs/平台工程/production-cutover-gates.md` - 将运行手册、对抗数据集和目标环境补证入口纳入 CI/文档。
- `docs/delivery/production-agent-hardening/{REVIEW_REPORT,QA_REPORT,DELIVERY_REPORT}.md` - 最终代码审查、
  QA、交付和生产 NO-GO 结论。

## Verification Log

| Command or check | Result | Notes |
| --- | --- | --- |
| 两仓 `git status --short` | pass | AgentScope 保留既有 dirty changes；Java 初始工作树干净 |
| `uv run pytest tests/test_execution_limits.py -q`（实现前） | fail as expected | 4 failed，证明原配置允许无限预算且缺少单次输出上限 |
| `uv run pytest tests/test_execution_limits.py tests/test_runner.py -q` | pass | 12 passed |
| `uv run ruff check <AC-01 affected files>` | pass | All checks passed |
| `docker compose -f compose.yml config --quiet` | pass | 新预算环境变量可正常渲染 |
| `git diff --check -- <AC-01 tracked files>` | pass | 无空白错误；统计包含这些文件原有未提交改动 |
| AC-02 新安全测试（实现前） | fail as expected | 缺少 confirmation domain/module，证明旧工具名确认无法满足参数绑定和防重放要求 |
| `uv run pytest tests/test_tool_confirmation.py tests/test_governed_tools.py tests/test_api.py tests/test_contracts.py -q` | pass | 67 passed；确认 API、策略、执行与契约回归 |
| `uv run ruff check .` / `uv run ruff format --check .` | pass | 216 files formatted，All checks passed |
| `uv run mypy src` | pass | 72 source files 无类型错误 |
| `uv run pytest` | pass | 369 passed，1 个既有 warning |
| `uv run python scripts/export_contracts.py --check` | pass | OpenAPI 与 JSON Schema 无漂移 |
| AgentScope `docker compose -f compose.yml config --quiet` | pass | confirmation/Redis 配置可渲染 |
| Java Compose base + knowledge split config | pass | 两种拓扑均可渲染 |
| Java `helm lint` / `helm template` | pass | 1 chart，0 failures；完整模板可离线渲染 |
| Java `bash deploy/test-production-cutover-config.sh` | pass | 签名密钥只注入 AgentScope；Redis replay 配置存在 |
| 两仓 `git diff --check` | pass | 无空白错误 |
| AC-03 Python 新测试（实现前） | fail as expected | 缺少 downstream token domain/issuer，证明 caller token 仍会传播 |
| `uv run ruff check .` / `uv run ruff format --check .` | pass | 220 files，All checks passed |
| `uv run mypy src` | pass | 74 source files 无类型错误 |
| `uv run pytest` | pass | 393 passed，1 个既有 warning |
| `uv run python scripts/export_contracts.py --check` | pass | 下游 token schema/OpenAPI 无漂移 |
| Java 严格 JWT 测试（实现前） | fail as expected | 缺少完整安全上下文 factory overload |
| Java security/auth/edge 选定 reactor | pass | platform-security 33、auth 93、edge 55（6 skipped） |
| Java 全量 `mvn -q -DskipITs test` | pass | 239 reports、1148 tests、0 failures/errors、9 skipped |
| Java 长 HS key 与 async metrics 聚焦回归 | pass | 显式 HS256 后单元与 Spring HTTP 鉴权均通过 |
| AgentScope/Java Compose config | pass | AgentScope、基础及 knowledge-split 拓扑可渲染 |
| Java `helm lint deploy/helm/platform` / `helm template` | pass | 1 chart，0 failures；模板可离线渲染 |
| Java `deploy/test-production-cutover-config.sh` | pass | strict JWT 上下文一致；confirmation/downstream key 仅注入 AgentScope |
| 两仓最终 `git diff --check` | pass | AC-03 无空白错误 |
| AC-04 owner 隔离测试（实现前） | fail as expected | 同租户用户原本可读取/控制其他用户任务 |
| AC-04 worker token 测试（实现前） | fail as expected | Python 缺 worker issuer；Java 缺 worker token 类型和构造器 |
| Java controller/JDBC 租约聚焦回归 | pass | 20 tests；无租约、过期租约与原子迁移均拒绝 |
| Java worker HTTP/security 聚焦回归 | pass | 普通 JWT、错 action、workerId 冒充、同租户跨 owner 均拒绝 |
| Java 受影响 reactor | pass | platform-security、async-task、workflow、knowledge、agent 及依赖全绿 |
| Python worker/async 聚焦回归 | pass | 24 passed；配置、签发、client 和 manager 覆盖 |
| Python `ruff check` / format | pass | 222 files，All checks passed |
| Python `mypy src` | pass | 75 source files 无类型错误 |
| Python 全量 `pytest -q` | pass | 404 passed |
| Python contract export check | pass | worker token JSON Schema/OpenAPI 无漂移 |
| Compose/Helm production gate | pass | key 挂载白名单、上下文一致、lint/template 全绿 |
| 两仓 `git diff --check` | pass | AC-04 代码、配置与文档无空白错误 |
| AC-05 callback policy/signer 聚焦回归 | pass | 空 allowlist fail-fast、IPv4/IPv6、混合 DNS、精确 internal URL、签名篡改/过期均覆盖 |
| AC-05 三发送端聚焦回归 | pass | async JDBC/内存、Workflow 与 A2A 均覆盖 v1 签名及 302 不跟随/不重试 |
| Java AC-05 受影响 reactor | pass | platform-security、async-task、workflow、interop 及依赖全绿；四目标模块共 216 tests |
| AC-05 Compose/Helm production gate | pass | 三条 HTTPS allowlist、唯一精确内网例外、三把独立 key 的长度/不复用/挂载范围均通过 |
| `helm lint` / `helm template` / Java `git diff --check` | pass | chart 1/1 通过，完整模板可渲染，无空白错误 |
| Python 切片全量门禁 | pass | ruff/format、mypy 75 files、pytest 404、contract export、diff check 全绿 |
| AC-06 Python 流式聚焦回归 | pass | 7 passed；PII、坏帧、上游关闭和 Reflexion 满队列取消均覆盖 |
| AC-06 Java 分路径聚焦回归 | pass | Conversation/Reflexion/task/Voice/A2A 脱敏、稳定错误与取消测试均通过 |
| AC-06 Java 受影响 reactor | pass | 六个目标模块共 457 tests，0 failures/errors |
| AC-06 Python 全量门禁 | pass | ruff/format 225 files、mypy 76 files、pytest 411、contract export 全绿 |
| AC-07 JDBC 账本聚焦测试 | pass | 11 tests；唯一 claim、参数冲突、跨租户、事务回滚、删除生命周期及 key/hash 校验 |
| AC-07 Flowable 原子性 profile | pass | 7 tests；真实 H2/MySQL-mode + Flowable 覆盖并发单实例、409、跨租户、失败恢复、旧实例收编/冲突与 purge 后复用 |
| AC-07 workflow 受影响 reactor | pass | `mvn -q -pl workflow-service -am -DskipITs test` 全绿 |
| AC-07 两仓 diff check | pass | Java 全仓及 AgentScope 文档无空白错误 |
| AC-08 Python lifecycle/deadline/fault 聚焦回归 | pass | 10 passed；池关闭、header、父时限、bulkhead、熔断恢复、SSE 全生命周期占槽均覆盖 |
| AC-08 Java deadline/interceptor/pooling 聚焦回归 | pass | 9 tests；非法/过期 deadline、并发拒绝、熔断/half-open、共享拦截器与 Apache 池均覆盖 |
| AC-08 Knowledge 受影响 reactor | pass | 百炼 rerank 使用 Boot pooled builder 后，`knowledge-service -am` 全绿 |
| AC-08 Python 全量门禁 | pass | ruff/format 228 files、mypy 78 files、pytest 419、contract export/Compose/diff check 全绿 |
| AC-08 Java 全量门禁 | pass | 254 reports、1210 tests、0 failures/errors、9 skipped |
| AC-08 部署门禁 | pass | 两种 Compose 拓扑、Helm lint/template、production cutover config 与 Java diff check 全绿 |
| AC-09 lease fencing 聚焦回归 | pass | controller/JDBC/token/client/manager 覆盖同服务多副本、epoch 续租、到期接管、迟到 status/progress 拒绝 |
| AC-09 relay 故障恢复聚焦回归 | pass | 四条 outbox 均覆盖重复 claim 阻断、TTL 重领、旧 owner 完成拒绝与当前 owner 成功 |
| AC-09 AgentScope 全量门禁 | pass | ruff/format 228 files、mypy 78 files、pytest 422、contract export 与 Compose 全绿 |
| AC-09 Java 受影响 reactor | pass | platform-security 62、workflow 70、async-task 57 tests，0 failures/errors |
| AC-09 部署门禁 | pass | 两种 Java Compose 拓扑、Helm lint/template、production cutover config 全绿 |
| AC-10 readiness 聚焦回归 | pass | 5 tests；必要/可选依赖、404/503、传输失败和稳定脱敏状态均覆盖 |
| AC-10 Python metrics 聚焦回归 | pass | 25 tests；histogram、inflight/backlog、token/cost、终止原因及 async 生命周期覆盖 |
| AC-10 Java metrics/JDBC 聚焦回归 | pass | 9 tests；认证 scrape 实际值与共享 H2 第二副本计数均通过 |
| AC-10 Java async-task reactor | pass | platform-security 62、observability 7、eventbus 9、async-task 58 tests，0 failures/errors |
| AC-10 部署门禁 | pass | 两仓 Compose、Helm lint/template 全绿；readiness/cost 默认值可渲染 |
| AC-11 静态安全门禁 | pass | 全 Compose profile 和 Helm split 渲染逐 workload 验证 SA、securityContext、密钥最小注入、NetworkPolicy、HPA/PDB 与拓扑 |
| AC-11 Compose 回归 | pass | Java base/split 及 AgentScope Compose 均成功渲染；AgentScope 唯一服务的 6 项运行安全断言全部通过 |
| AC-11 Helm 回归 | pass | `helm lint` 1 chart/0 failures；完整 `helm template` 成功，生成 14 Deployment/SA、3 HPA、3 PDB 和 2 NetworkPolicy |
| AC-11 兼容门禁 | pass | 原 production-cutover config 门禁、两仓 `git diff --check` 仍全绿 |
| AC-12 migration 集成测试 | pass | 8 个空 schema、幂等重跑、旧 auth/ingestion backfill、Flowable v3 与 CLI JDBC path 全绿 |
| AC-12 启动保护聚焦测试 | pass | auth、async-task、workflow、Knowledge 空库均 fail-fast，且验证未创建目标表 |
| AC-12 Java 受影响 reactor | pass | migrations/auth/async/workflow/knowledge/order/eventbus/channel/analytics 及依赖全绿 |
| AC-12 Flowable profile | pass | `mvn -q -pl workflow-service -am -Pflowable-it test`；预迁移后 runtime schema update=false 的原子性套件全绿 |
| AC-12 Compose/Helm/CI 静态门禁 | pass | 8 个 hardened migration 服务、应用完成依赖、4 个默认/8 个全量 Hook Job、独立凭据和 workflow 语法全绿 |
| AC-12 最小权限与 Hook bootstrap 回归 | pass | 受影响 7 个业务模块 reactor 与 analytics 聚焦测试全绿；Helm/Compose/迁移静态门禁验证 app 账号、独立预置迁移 Secret 和 runtime secret 不含 DDL 凭据 |
| AC-12 真实 MySQL Compose 迁移 | not run | 本机 Docker daemon 未运行；无法连接 Docker socket，未以 H2 结果冒充 MySQL 证据 |
| AC-13 AgentScope 静态策略/YAML | pass | immutable Action、只读普通 CI、tag-only release、扫描/签名/attestation 自举门禁与 Ruby YAML 解析全绿 |
| AC-13 AgentScope 依赖/构建/SBOM | pass | `uv audit`：105 packages、0 known vulnerabilities；`uv build` 成功；CycloneDX 1.5 可解析且含 105 components |
| AC-13 Java 静态策略/YAML | pass | workflow/dependabot YAML 可解析；17 个 Dockerfile 与 scan/release matrix 精确一致，写权限只存在 tag release |
| AC-13 Java Reactor | pass | `mvn -q -DskipITs test` 全量通过；AC-09 worker 测试更新后的聚焦 reactor 亦通过 |
| AC-13 Java package/SBOM | pass | `mvn -q -Dmaven.test.skip=true package` 成功；CycloneDX 1.6 aggregate 可解析且含 422 components |
| AC-13 本地镜像 Trivy | not run | 本机 Docker daemon 未运行；CI 已配置 1 个 AgentScope 与 17 个 Java 镜像的 HIGH/CRITICAL 阻断扫描 |
| AC-13 GHCR OIDC 签名/证明 | external evidence required | 必须由真实 `v*` GitHub run 提供 digest push、二次扫描、Cosign/Rekor、SLSA/SBOM attestation 与 admission 验证 |
| AC-14 session/capability 聚焦回归 | pass | Python session contract/store/service/API、capability registry 与 runner 共 26 tests 全绿；legacy capability JSON 精确兼容 |
| AC-14 Python 全量门禁 | pass | ruff/format、mypy 84 source files、contract export、450 tests、Compose 与 diff check 全绿；覆盖率 89.54% |
| AC-14 Java interop 回归 | pass | capability registry/LKG、A2A context、owner/push 注册、AES-GCM 密文与重启恢复聚焦测试及 interop reactor 全绿 |
| AC-14 Java 全量 Reactor | pass | `mvn -q -DskipITs test`：268 reports、1261 tests、0 failures/errors、9 skipped |
| AC-14 Compose/Helm production gate | pass | Agent session 与 interop state 均强制 Redis；A2A 加密 key 为独立 32-byte key；Helm lint/template 和 diff check 全绿 |
| AC-14 真实 Redis 多副本集成 | not run | 本机 Docker daemon 未运行；CAS/Lua、TTL、故障关闭由单元与静态门禁覆盖，真实 Redis failover 留待 CI/目标环境补证 |
| AC-15 contract/CLI/evaluation 聚焦回归 | pass | 运行版本、轨迹、dataset、adversarial、feedback import、replay、v4 report/version drift 与 CLI 共 100+ tests 全绿 |
| AC-15 Python 全量门禁 | pass | ruff/format、mypy 87 source files、contract export、467 tests、shadow smoke、dataset validate、Compose 与 diff check 全绿；覆盖率 89.58% |
| AC-15 Java eval-service | pass | v4/dataset digest parser 聚焦测试与 eval-service reactor 64 tests 全绿；v3/缺 dataset fail closed |
| AC-15 Java 全量 Reactor | pass | `mvn -q -DskipITs test`：268 reports、1262 tests、0 failures/errors、9 skipped |
| AC-15 真实模型/线上反馈演练 | external evidence required | 未访问生产反馈或真实远程模型；命名测试环境需提供 consent/export 审批、版本化双跑、对抗集结果与回放证据 |
| AC-16 运行手册单元/静态门禁 | pass | 2 tests；必选章节、命令、指标、19 项证据、RPO/RTO、最终报告边界和 GO fail-closed 规则均覆盖 |
| AC-16 Python package/Compose | pass | `uv build` 生成 sdist/wheel；AgentScope Compose 与 diff check 全绿 |
| AC-16 Java 最终静态门禁 | pass | production cutover、runtime hardening、database migration、supply chain 四组脚本全绿 |
| AC-16 默认证据 `--require-go` | NO-GO as designed | 模板保留未解析 release/digest 与 PENDING 外部证据，验证器拒绝生产切流 |
| 最终 AgentScope 全量门禁 | pass | ruff/format、mypy 87 source files、contract export、470 tests、89.60% coverage、Shadow smoke、adversarial dataset、供应链/运行手册、build、Compose、diff check 全绿 |
| 最终 Java 全量/静态门禁 | pass | 最近一次全量 Reactor 为 268 reports、1262 tests、0 failures/errors、9 skipped；最终文档变更后四组生产静态门禁与 diff check 复验全绿 |

## Decisions And Deviations

- AC-01 不再保留本地无限模式；统一有限默认值可消除环境变量遗漏导致的生产失控。
- LiteLLM 是唯一 provider 重试/failover 层；AgentScope 仍可显式配置重试，但默认 0。
- confirmation grant 使用单独 key，绝不复用 caller internal JWT key；生产多副本只允许 Redis
  权威 replay store，本地内存实现仅用于开发和确定性测试。
- 旧 `X-Agent-Confirmed-Tools` 不做兼容降级，因为它无法绑定参数且会形成授权升级路径。
- 部署隔离门禁在首次加入时发现配置误落到 legacy `agent-service`，已移至
  `agentscope-orchestrator` 并由 Compose/Helm 断言覆盖。
- 原始 caller JWT 不允许作为 provider credential；MCP/browser/code 使用各自 audience，且下游
  secret 不得等于 internal JWT 或 confirmation secret。
- 严格 reader 不提供生产兼容降级：先升级全部 edge signer，等待一个旧 token TTL，再升级 readers。
- JJWT 必须显式指定签名算法；仅在 header 校验算法但让库自动选算法，会使长 HS key 产生自拒绝 token。
- 用户任务授权必须同时绑定 tenant 与 owner；tenant 本身不是同租户用户之间的授权边界。
- worker 数据面不接受普通 internal JWT，也不允许兼容回退；worker 调用只携带 task/action-bound
  凭据，且 status/event 必须持有当前未过期租约。
- worker forwarder 必须先于普通 tenant forwarder；tenant forwarder 看到 worker header 后移除并
  跳过 internal JWT，兼容只持 RS256 公钥的下游节点。
- callback allowlist 使用精确 origin；唯一私网例外使用精确完整 URL 且只注入需要它的发送端。
  应用在注册和投递前都解析 DNS，但不声称消除 DNS-to-connect TOCTOU，生产必须再用 egress
  NetworkPolicy/防火墙阻断 metadata、控制面和非必要私网。
- 三类 HTTP callback 使用同一 v1 签名格式，但各用独立 key；回滚不得重新允许任意 URL、公网 HTTP、
  私网目标或无签名请求，优先回退到 Kafka/轮询或暂时关闭 HTTP 投递。
- SSE 脱敏在公开投影视图执行，不修改权威任务存储或内部计算结果；回滚不得重新暴露原始异常或 PII。
  持久任务 SSE 是观察通道，断开绝不能隐式取消业务任务；Reflexion 等请求内流则应停止 producer。
- Java 可关闭当前 HTTP 上游响应并停止后续写出/TTS，但 langchain4j 当前没有活跃 provider 调用的
  取消句柄；以 provider deadline 收敛，不能把“停止向客户端发送”描述为已取消模型计费。
- `dedupeId` 只在调用方显式提供时启用强幂等，且 Java 直调同样强制 1～128 位安全 opaque key；
  不传键仍表示一次新的合法副作用请求。账本只存 SHA-256 请求摘要，不复制用户正文。
- workflow-service 边界的原子幂等不等于外部支付系统 exactly-once；未来接真实退款执行时必须把同一
  业务键继续传给支付方，并遵守其事务/幂等契约。
- HTTP 可靠性层刻意不做自动重试：读请求的业务降级由各调用方显式决定，写请求继续依赖调用方
  幂等/outbox。Java deadline header 是传播/拒绝信号，真正 wall-clock 收敛仍需各客户端的
  connect/read timeout；两者必须同时配置。
- Java Boot builder 与实例级 JDK `HttpClient` 均复用连接；vendor SDK 自管客户端仍由各自 timeout/
  retry 配置约束，不把平台拦截器覆盖范围夸大为第三方 SDK 内部调用。
- `ASYNC_TASK_WORKER_ID` 是稳定服务身份而非副本身份；实际 lease owner 必须带进程唯一后缀，且所有
  写回携带当前 epoch。服务 token 只允许为自身前缀 owner 签发，不能冒充其它服务。
- outbox relay 是 at-least-once：claim fencing 防止旧副本改状态，但 broker/HTTP 已成功而 ack 前失联仍
  可能重复投递，接收方必须继续按稳定 delivery/event id 去重。
- 普通 async-task closure 仍不做隐式跨进程代码重放，继续由 AC-09 的 fencing、drain 和 orphan
  安全收口；显式 session API 已支持相同 goal 摘要下从语言中立 checkpoint 跨进程续跑。它不是
  任意新 goal 的对话记忆，副作用恢复也不会绕过原幂等摘要或重新确认。
- AgentScope `AgentState` 只允许在 infrastructure adapter 内临时重建；checkpoint 不保存 caller
  token、grant、原始 goal、模型对象或 AgentScope 序列化状态。A2A context 是独立的 Java 稳定契约。
- capability registry 使用规范 JSON 的 SHA-256 revision；旧 descriptor endpoint 保持精确兼容，
  Java 仅可从新 registry 或持久 last-known-good 恢复，不得伪造静态 Agent capability catalog。
- A2A push token 静态持久化使用独立 AES-256-GCM key；该 key 不得复用 callback HMAC，轮换需先
  停止写入并按运行手册处理旧 ciphertext，不能以明文兼容降级。
- 运行版本只保存摘要：prompt 原文、goal、回答、observation 与凭据不进入评测报告。model version
  绑定本服务看到的 gateway endpoint/model/参数；LiteLLM alias 背后的 provider 配置仍需外部发布
  版本佐证。工具实现行为变更但 metadata 不变时必须递增 `TOOL_IMPLEMENTATION_REVISION`。
- 旧 JSONL 继续支持本地兼容，但正式发布证据必须使用内容寻址 dataset；回放是同版本 case 的重新
  执行，不会重放历史副作用。批内版本漂移直接失败，不能把多个 deployment 版本混成一个结论。
- 反馈导入只接受显式同意且只读的严格最小 schema，并做常见 PII 遮蔽；它不是通用 DLP，原始导出
  仍须先走数据治理/留存审批，禁止直接把生产反馈文件提交到仓库。
- readiness 的必要依赖只覆盖承载当前已启用能力的基础设施；Knowledge/Analytics/Workflow/Order
  故障会在 checks 中显示 DOWN，但不阻断仍可只依赖模型完成的请求。必要 provider 只接受 2xx、
  受保护端点的 401/403，以及 MCP method probe 的 405，错误路径 404 不视为可用。
- Python token/cost 指标按进程记录；cost 是部署费率估算，默认费率 0 不得解释为真实零成本。
  Java 中央 backlog/inflight 直接查询共享任务表，所有副本值一致。
- NetworkPolicy 以默认拒绝为基线，同 namespace 和 DNS 明确放行；公网出站显式排除私网、
  link-local、metadata、multicast 和保留段。需访问私网依赖的部署必须以最小 CIDR 填入
  `networkPolicy.allowedEgressCidrs`，不提供宽泛私网回退。
- 只对已确认无状态、水平扩展安全的 edge、AgentScope 和 async-task 启用 HPA/PDB；AC-12 已移除
  schema 启动竞态，其余工作负载仍需各自完成共享状态/并发语义检查后才扩副本。
- ServiceAccount 不绑定 Role/RoleBinding 且禁用 token 挂载；公钥虽来自 Secret，但只通过单 key
  `secretKeyRef` 投影。容器既无 API token 也不会获得同 Secret 的其他 key。
- app 与 migration 数据库身份必须分离；应用发布只允许向前兼容的 expand migration。应用回滚保留
  已扩展 schema，禁止自动 down migration、手改 Flyway history 或临时赋予 app DDL 权限。
- 已有未纳管库以 version 0 baseline 后执行 additive backfill；analytics demo migration 仅服务本地
  演示，生产真实只读分析库保持关闭。
- Helm pre-install migration 不得依赖同一 release 后创建的 ExternalSecret；生产必须先由
  ESO/IaC 预置独立 `platform-migration-secrets` 并等待 Ready。本地 `change-me` Hook Secret 只用于渲染演示。
- 发布签名不引入长期私钥；普通 PR/main jobs 不持有 OIDC 或写权限。因为 registry digest 必须在
  push 后取得，二次扫描失败可能留下未签名孤立镜像；准入必须要求签名和 provenance，并拒绝该 digest。
- Action 更新只接受 immutable SHA 的审查 PR；版本注释不是安全边界，不能以 `@vN` 替代 commit。
- 生产外部环境门禁不以本地结果代替。
- 运行手册中的 RPO/RTO 是发布目标，不是本地测试已经证明的 SLA；每次候选版本必须附真实恢复时间、
  数据损失观测与目标环境证据。
- `scripts/test_production_runbook.py --require-go` 只负责证据准入，不执行部署、切流或回滚；这些动作仍
  必须由变更单授权的发布负责人执行。
- 任一外部检查缺失、PENDING、无 owner、无可追溯 HTTPS 证据或镜像 digest 未锁定时都保持 NO-GO，
  不允许以人工口头确认或本地单元测试代替。

## Blockers And Residual Risks

- AgentScope 多个目标文件已有未提交变更；实现前必须检查当前 diff。
- 目标云 IAM、生产 canary、容量、值班和恢复证据需要外部环境权限。
- 本机 Docker daemon 未运行，AC-12 的 MySQL 8.4 方言/授权/幂等 Compose 实测需在 Docker 可用或 CI
  环境补证；H2、构建、Compose JSON 与 Helm 渲染门禁均已通过。
- 同一 Docker 限制使 AC-13 本地镜像扫描未执行；真实 GHCR push、GitHub OIDC/Cosign、attestation
  与未签名 digest admission 拒绝只能由外部 tag workflow/目标集群补证。
- 同一 Docker 限制使 AC-14 未执行真实 Redis CAS/TTL/重启/failover 多副本集成测试；本地单元、
  Lua 行为和部署渲染已通过，目标环境证据必须在 AC-16 清单补齐。
- AC-15 只使用离线 stub/fixture 验证 runner；真实模型质量、对抗通过率、线上反馈 consent/DLP
  和相同 dataset 的目标环境回放需要 AC-16 外部证据，不能由本地自动化测试代替。
- AC-16 证据模板仍为预期 NO-GO：真实 workload identity/egress、MySQL 与 Redis 恢复、目标容量与
  autoscaling、完整高峰周期 soak、签名镜像准入、Shadow/对抗回放、租户 canary、监控值班及整服务
  回滚均需要目标环境/发布负责人补证；当前未授权生产操作。
- 2026-08-03 只读外部勘察确认当前机器仅有本地 `docker-desktop` context、Docker daemon 不可用且
  GitHub CLI 未登录。两仓公开远端没有 tag、release、deployment 或候选 artifact，最新 AgentScope
  CI 和 Java cutover CI 各有失败步骤；这些远端记录不对应当前未提交交付，不能用作 PASS 证据。
  逐项结果见 `TARGET_ENV_EVIDENCE_AUDIT.md`。

## Next Action

先提供命名非生产目标 URL 或目标集群 context/namespace、真实模型成本策略、candidate/rollback
不可变 digest、发布工作流 URL、证据 JSON 路径和逐项 owner。然后按
`TARGET_ENV_EVIDENCE_AUDIT.md` 与运行手册补齐 19 项真实证据并运行：

`uv run python scripts/test_production_runbook.py --evidence <release-evidence.json> --require-go`

返回 GO 后才可进入运行手册的 canary 步骤；当前不得改变生产 `AGENT_URI` 或执行生产切流。
