# Delivery Status

## Goal

在不形成 Python 新单体的前提下，建立并实施 AgentScope 推理/编排层与 Java
数据/事务/安全/副作用领域服务之间的稳定边界。

## State

- Phase: Local production-equivalent cutover gates complete
- Status: local release candidate passed; actual production cutover remains conditional NO-GO
- Last updated: 2026-07-30

## Completed

- 完成两个仓库的模块、调用、数据所有权、部署和迁移文档只读评估。
- 确认当前不是从单体直接拆服务，而是对已存在的微服务做运行面、协议面和语言边界收敛。
- 选择“窄 AgentScope + Java 领域数据面 + 独立协议/评测控制面”方案。
- 完成产品范围、AC-01 至 AC-13、技术方案、实施波次、验证、CI、rollout 和 rollback 设计。
- UI/UX 判定为不适用；现有 API/SSE 行为作为兼容约束。
- 用户已批准详细计划及 S3-compatible 原文权威存储方案。
- Slice 0：新增跨仓 ADR、责任矩阵与 Python 架构依赖门禁，覆盖 AC-01/02。
- Slice 1：interop Agent capability 改为 AgentScope live discovery 单一来源；冷启动失败只暴露
  本地 ping，刷新失败使用 last-known-good；移除 interop 对 Java agent 容器的默认启动依赖。
- Slice 2：导出评测 case/report JSON Schema，明确 Python runner 是独立 CLI/CI job。
- Slice 3：Java Knowledge 数据面已完成 S3-compatible 原文 adapter、不可变带 hash 对象 key、
  JDBC/内存 job store、版本/逐 sink 状态机、乐观并发、幂等、reconcile 和跨租户测试。
- Slice 4（进行中）：新增 `combined/query/ingest-api/ingest-worker` 运行角色及 fail-fast
  数据面约束；新增 durable `/rag/ingestions` v2 API、语言中立 job schema、worker sink 抢占
  与上下文恢复核心，以及不切默认 edge 路由的可选 Compose 拓扑。
- Slice 4 worker 已接通生产处理链：S3 原文解析/切分/embedding 一次完成，Vector/ES 使用
  documentVersion 稳定主键，Authorization 先于 Registry，Registry 作为最后可见性提交点。
- query 已按共享 Registry 当前版本过滤 Vector/ES 命中；split query 暂时禁止无版本
  provenance 的 GraphRAG，避免半完成版本泄漏。
- worker 已增加 JDBC 轮询、失败恢复和 async-task `knowledge.ingestion` 生命周期桥接；
  async-task 冲突会回读并校验任务类型，不把原文放入通用任务 payload。
- ingest-api/worker 启动时强制共享持久化 Registry；Compose 已改为 Redis，并保持 edge 默认
  路由与 combined rollback target 不变。
- Helm 已增加默认关闭的 query/ingest-api/worker workload；worker 不生成 Service，启用前
  必须由环境 values/External Secrets 覆盖 S3 和 JDBC 占位凭据。
- 增加 combined 同步路径与 v2 split worker 的同输入双跑，查询到的 docId/text 一致。
- Analytics 已形成候选 `Python planner -> Java guarded executor` 边界：Python 请求体不含
  tenant/用户/数据库凭据，Java 从可信上下文绑定 `:tenantId`，并重新执行表白名单、只读、
  LIMIT 和租户谓词校验；默认关闭且仅 shadow，不改变原 NL2SQL 响应。
- Workflow 已新增 AgentScope 工单/答复草稿端点及 Java `agentscope-shadow` adapter；
  conversation 仍是 primary，候选结果被丢弃，不能改变 Flowable 路由、人工审批决定、reply
  或事务 outbox。
- Knowledge 旧版本派生索引 GC 已实现：默认关闭，只在 combined/ingest-worker 装配；保留
  Registry 当前版本、最近两个回滚版本和七天 grace period，并按 tenant/doc/version 精确清理
  Vector、ES 与新格式 Graph provenance。S3 原文不自动删除，旧无 provenance Graph 数据
  fail-safe 保留。
- 评测控制面已退出默认在线路由：edge 不再发布 `/eval/**`，Compose 仅在 `evaluation`
  profile 启动 Java harness，Helm 默认不渲染 eval workload。Java 只读兼容 Python
  snake_case shadow-report 摘要，不重新执行 Agent shadow。
- Java `agent-service` 已退出默认运行拓扑：Compose 仅在 `legacy-agent` profile 启动，
  Helm 默认 `enabled=false`；AgentScope 仍是 edge/interop 默认目标。Java 源码和显式整体
  回滚配置保留，待生产 release gate 后再决定是否删除。
- Conversation decision gate 结论为 HOLD / shadow-only：新增语言中立、无身份和无状态的
  generation schema；Java `/chat` 在完成护栏/RAG/primary 后可异步 shadow 独立候选。
  candidate 失败、超时或线程池饱和不影响 primary，且不能写入 memory/profile/cache。
- AgentScope 架构门禁会阻止在现有 orchestrator 中新增 `/chat` 或
  `/internal/conversation/generate`，确保未来候选必须是独立进程。
- Conversation shadow request 已加入 Java 权威 memory 的有界只读 history：在 primary
  生成前捕获，默认 12 条/6000 总字符/单条 2000 字符，契约硬上限 32 条/单条 4000 字符；
  shadow 关闭时 no-op，不额外读取 Redis。
- Candidate stream 已定义独立 `{sequence,type,data}` schema 与离线序列校验器，强制连续序号、
  唯一末尾 `done|error`，禁止终态后 token；Java 的 blocked/grounding 仍不下放。
- Post-QA 修复完成：Knowledge S3 client 改用 URLConnection，split 端口与配置族隔离；
  Qdrant 使用确定性 UUID，query 角色允许白名单 POST 检索。
- 真实 MinIO/MySQL/Redis/Qdrant/ES/async-task split 闭环达到 READY，五个 required sink
  全部成功，独立 query 命中 S3 原文。
- Eval 默认目录诚实标记为离线未部署，Vision provider 非法请求稳定映射 400，
  RAG 静态状态不再覆盖 live runtime 事实。
- Slice 7 本地生产等价门禁完成：
  - S3 原文凭据拆为 ingest-write 与 worker-read 两个角色，query 无原文凭据；
  - Qdrant 故障期间任务保持 PARTIAL，跨租户读取 404，恢复后 reconcile 到 READY；
  - Knowledge readiness 显式纳入 Qdrant/embedding，真实停启验证 200 → 503 → 200；
  - 24/24 并发提交 READY，8 个同幂等请求收敛为一个 job；
  - 查询 100/100 成功（并发 10，P95 0.240s，P99 0.250s）；
  - 120 秒 soak 中 59/59 查询与 5/5 入库成功，无相关容器重启；
  - Knowledge combined/split/combined 与 AgentScope/legacy/AgentScope 回滚演练通过；
  - 六个遗留 Agent 任务保留审计并归档为 `FAILED / ASYNC_TASK_ORPHANED`。

## Changed Files

- `docs/delivery/ai-runtime-boundary-decomposition/DELIVERY_PLAN.md` - 详细交付与拆分计划。
- `docs/delivery/ai-runtime-boundary-decomposition/DELIVERY_STATUS.md` - 工作流状态和恢复入口。
- `docs/adr/0002-ai-runtime-domain-boundaries.md` - 已接受的架构决策。
- `docs/service-decomposition.md` - 目标拓扑和责任矩阵。
- `tests/test_architecture_boundaries.py` - 自动依赖门禁。
- `scripts/export_contracts.py`、`tests/test_contracts.py`、`contracts/evaluation/*` - 评测契约。
- `../langchain4j-platform/docs/架构边界/ai-runtime-boundaries.md` - Java 侧边界说明。
- `../langchain4j-platform/interop-service/**` - live-only capability discovery 与测试。
- `../langchain4j-platform/deploy/docker-compose.yml` - interop 不再默认依赖 Java agent。
- `../langchain4j-platform/knowledge-service/.../ingest/job/**` - S3 source port 与 ingestion 状态机。
- `../langchain4j-platform/knowledge-service/.../controller/IngestionController.java` - durable
  ingestion v2 API。
- `../langchain4j-platform/platform-protocol/.../knowledge/ingestion-job.schema.json` - 跨语言契约。
- `../langchain4j-platform/deploy/docker-compose.knowledge-split.yml` - 可选拆分拓扑及 MinIO。
- `../langchain4j-platform/docs/架构边界/knowledge-runtime-split.md` - 运维边界与回滚。

## Verification Log

| Command or check | Result | Notes |
| --- | --- | --- |
| 读取两个仓库状态与模块清单 | pass | 两仓均有大量既有未提交修改 |
| 检查 edge 路由、Compose、服务职责和数据边界 | pass | 证据已写入计划 |
| 检查交付技能 Gate A 要求 | pass | 当前只写 planning artifacts |
| 代码/测试 | not run | Gate A 前禁止修改和验证业务实现 |
| `uv run pytest tests/test_architecture_boundaries.py` | pass | 59 passed |
| Python contract + architecture targeted suite | pass | 66 passed |
| `uv run ruff check ...` | pass | no findings |
| `uv run mypy src` | pass | 55 source files |
| `mvn -pl interop-service -am test` | pass | 59 tests |
| Knowledge ingestion state targeted Maven test | pass | 4 tests |
| Knowledge S3/job/API/role/worker targeted Maven suite | pass | 已纳入下方全量回归 |
| Knowledge split Compose config | pass | 基础 + optional override 静态解析 |
| Knowledge ingestion JSON Schema parse | pass | Draft 2020-12 文档可解析 |
| `mvn -pl knowledge-service -am test` | pass | Knowledge 279 tests，3 skipped；依赖模块同时通过 |
| Knowledge combined/split in-memory 双跑 | pass | 同输入 docId/text 查询结果一致 |
| Knowledge async-task HTTP adapter tests | pass | create/sync/409 回读校验 |
| Python contract + architecture targeted suite（最终复验） | pass | 66 passed |
| `docker compose ... config --quiet` | pass | Compose syntax valid |
| `helm lint` + default/split `helm template` | pass | 默认不渲染 split；启用时 3 Deployment、2 Service |
| `uv run ruff check .` | pass | full repository |
| `uv run mypy src` | pass | 59 source files |
| `uv run pytest` | pass | 277 passed, 1 warning |
| Analytics Maven regression | pass | analytics-service 39 tests |
| Workflow Maven regression | pass | workflow-service 43 tests |
| Slice 5 Python targeted suite | pass | 37 tests |
| Eval + edge Maven regression | pass | eval-service 63；edge-gateway 55，6 skipped |
| Eval Compose/Helm isolation render | pass | 默认无 eval；显式 profile/enable 时生成 |
| Legacy Java Agent deployment render | pass | 默认无 agent-service；显式 profile/enable 时生成 |
| Python quality + contract/architecture recheck | pass | ruff、mypy 59 files、pytest 72 |
| Conversation Maven regression | pass | conversation-service 129 tests |
| Conversation contract + architecture gate | pass | Python targeted 85 tests；mypy 60 files |
| Conversation Compose/Helm static validation | pass | shadow 默认关闭、base URL 为空 |
| Java full reactor regression | pass | 23 modules；0 failure |
| Knowledge post-fix package/tests | pass | 280 tests，3 skipped |
| Vision provider error mapping | pass | 7 tests；真实 provider 1×1 PNG 返回 400 |
| Frontend regression | pass | 66 files / 555 tests；type-check + build |
| Python full quality gates | pass | ruff、mypy 60 files、pytest 290 |
| Knowledge split Compose/runtime | pass | 三角色运行，ingest API 18095 |
| S3 durable ingestion | pass | job READY；5 sinks SUCCEEDED；MinIO object verified |
| Split query | pass | HTTP 200；命中刚入库原文 |
| Final Chrome UI | pass | Eval 6 项离线能力未启用且按钮禁用；RAG ready/live 状态一致，UI 查询返回 5 条 |
| Production config gate | pass | Compose/Helm、S3 role、Knowledge route override、readiness membership |
| Real MinIO IAM smoke | pass | ingest 仅写；worker 仅读；query 无凭据 |
| Qdrant failure/recovery | pass | PARTIAL → READY；readiness 200 → 503 → 200；3 次业务 warm-up 通过 |
| Concurrent ingestion/idempotency | pass | 24/24 READY；8 个重复请求产生一个 job |
| Query capacity | pass | 100/100；concurrency 10；P50 0.162s/P95 0.240s/P99 0.250s |
| Bounded soak | pass | 120s；59/59 query；5/5 ingest；无相关容器重启 |
| Knowledge + Agent rollback | pass | 两条链路均完成切换、验证与恢复；Agent 使用真实付费模型 |
| Java final full reactor | pass | 23 modules；1165 tests；0 failures/errors；5 skipped |

## Decisions And Deviations

- 用户已批准详细切片和 S3-compatible Knowledge 原文权威存储依赖。
- 为避免覆盖既有 dirty changes，计划优先从新文件和自动发现测试开始。
- 生产删除、生产切流、commit、push 和 deploy 不在自动授权范围。

## Blockers And Residual Risks

- 本地 MinIO IAM、故障恢复、并发与有界 soak 已通过；仍需目标云 workload identity 审计、
  目标规格峰值/自动扩缩结果和完整业务高峰周期 soak，不能用开发机数值替代。
- split query 暂停 GraphRAG，直到 graph triple/hit 增加 documentId/documentVersion provenance。
- 版本 GC 尚未在真实 Qdrant、Elasticsearch 和 JDBC Graph 上做故障注入；默认保持关闭。
- 当前 async-task、interop、knowledge 和 CI 文件已有未提交修改，实施前必须逐项重叠审计。
- 真实模型、外部 IAM 和生产流量验证需要凭据/环境及单独授权。
- Analytics/Workflow 目前都只具备默认关闭的 shadow 接线；真实模型双跑、质量阈值和延迟
  预算尚未验证，不得切为 primary。
- Java Agent 已完成本地真实模型整体回滚与恢复演练，且任务排空为零；生产 canary 租户、
  监控阈值、变更单和回滚负责人仍未提供，因此仍禁止删除源码、镜像或生产资源。
- Conversation 已完成有界只读 history 和 candidate SSE event/序列契约，但尚无独立 candidate
  runtime、真实模型质量/延迟报告，以及真实断连、上游取消和背压验证，因此 decision gate
  保持 HOLD。

## Next Action

将同一套门禁带到目标环境：附上云 IAM 审计、目标容量/自动扩缩、完整高峰周期 soak、
canary 租户与扩量/停止阈值、监控值班和变更单。证据齐备前生产默认路由保持不变。
