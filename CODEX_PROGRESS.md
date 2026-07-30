# Codex Progress

## 任务目标

按已批准的最终架构拆分两仓：AgentScope/Python 只拥有推理和编排；Java 服务继续拥有数据、
事务、安全和副作用。批准范围包括 S3-compatible Knowledge 原文权威存储、独立 Agent Protocol
Gateway 和独立评测 job。

## 已完成

- 交付计划已批准：
  `docs/delivery/ai-runtime-boundary-decomposition/DELIVERY_PLAN.md`。
- 新增 ADR、责任矩阵和 Python 架构边界测试。
- interop Agent capability 已改为 AgentScope live discovery 单一来源：
  - 冷启动 AgentScope 不可达时只暴露本地 ping；
  - TTL 刷新失败使用 last-known-good；
  - Java 不再静态复制 Agent tool descriptor；
  - interop Compose 不再默认依赖 Java `agent-service`。
- 评测 `ShadowCase`/`ShadowReport` 已导出语言中立 JSON Schema。
- Knowledge Java 数据面已新增：
  - `DocumentSourceStore` S3-compatible 端口、AWS SDK v2 adapter 与内存 adapter；
  - 带 content hash 的不可变对象 key 和租户边界；
  - JDBC/内存 ingestion job store、乐观 revision、幂等键和 reconcile；
  - tenant/user/scopes/department/trace 的 durable job 上下文；
  - `PENDING/RUNNING/SUCCEEDED/FAILED` 逐 sink 抢占和幂等恢复 worker 核心；
  - durable `/rag/ingestions` v2 API 和语言中立 JSON Schema。
- Knowledge 同一 artifact 已新增 `combined/query/ingest-api/ingest-worker` 角色、HTTP surface
  限制和启动期持久化依赖检查。
- Knowledge worker 已接通完整 Java 数据面处理链：
  - 从 S3-compatible 原文读取，单次解析/切分/contextual enrich/embedding；
  - Vector 与 Elasticsearch 使用带 `documentVersion` 的稳定 id；
  - Authorization 在 Registry 前执行，Registry 是最终可见性提交点；
  - query 按 Registry 当前版本过滤半完成 Vector/ES 命中；
  - 原文准备失败与逐 sink 失败均可 reconcile。
- 新增 JDBC worker 轮询和 async-task `knowledge.ingestion` 生命周期桥接；通用任务只保存
  job/document/version/hash，不保存原文字节。
- ingest-api 和 worker 现在都强制共享持久化 Registry；query 暂停无版本 provenance 的
  GraphRAG。
- combined 同步路径与 v2 split worker 的内存双跑通过，docId/text 查询结果一致。
- 新增不改变默认 edge 路由的 `docker-compose.knowledge-split.yml`，包含 MinIO 本地拓扑。
- Helm 已新增默认关闭的 Knowledge query/ingest-api/worker release artifact；worker 不暴露
  Service，S3/JDBC 凭据保留为 External Secrets 覆盖占位值。
- Python 全量质量门禁通过：ruff、mypy（59 source files）、pytest（277 passed，1 warning）。
- Knowledge 全量 Maven 回归通过：274 tests，3 skipped；S3 adapter 复验 2/2。
- Python contract + architecture 最终复验：66 passed。
- Slice 5 Analytics 边界已实现：AgentScope 确定性 SQL planner、语言中立 schema、Java
  guarded executor 和默认关闭的 shadow 双跑；租户占位符只在 Java 可信边界绑定。
- Slice 5 Workflow AI adapter 已实现：Python 只生成 ticket/reply 草稿；Java
  `agentscope-shadow` 始终返回 conversation primary 结果，候选失败/LOW 判断均不影响
  Flowable、人工审批和 outbox。
- Analytics Maven 回归 39 tests、Workflow Maven 回归 43 tests、Slice 5 Python targeted
  37 tests 均通过。
- Knowledge 版本 GC 已实现：默认关闭，Registry 当前版本 + 最近 N 版 + grace period 保护，
  tenant/doc/version 精确清理 Vector/ES/带 provenance Graph；旧 Graph 和 S3 原文不猜测删除。
- Knowledge 全量 Maven 回归更新为 279 tests、3 skipped；Compose/Helm GC 配置静态门禁通过。
- 评测控制面已收口：
  - Java eval-service 只读解析 Python snake_case shadow-report 摘要，不重新执行 Agent shadow；
  - edge 不再暴露 `/eval/**`，Compose 仅 `evaluation` profile 启动；
  - Helm 默认 `enabled=false`，不渲染 Deployment/Service；
  - eval 63 tests、edge 55 tests（6 skipped）通过。
- Java `agent-service` 已退出默认 Compose/Helm 运行拓扑，AgentScope 是 edge/interop 默认目标；
  `legacy-agent` profile、Helm enable 开关和整体回滚配置仍保留，未删除任何 Java 代码或资源。
- Python ruff、mypy 59 files、contract + architecture 72 tests 复验通过；eval/legacy-agent
  Compose 与 Helm 默认/显式启用双向渲染门禁通过。
- Slice 6 Conversation decision gate 已完成本地骨架，结论为 HOLD / shadow-only：
  - 新增无可信身份、无 memory/profile/cache 的 conversation generation JSON Schema；
  - Java `/chat` primary 生成后可异步调用独立候选，默认关闭；
  - candidate failure/timeout/queue rejection 不影响 primary，缓存命中与护栏阻断不触发 shadow；
  - 异步线程显式传播 tenant 与 trace，正文不进入指标或日志；
  - AgentScope 架构测试禁止在当前 orchestrator 内新增 Chat/runtime endpoint；
  - conversation-service 123 tests、Python contract/architecture 74 tests、Compose/Helm 静态检查通过。
- Conversation decision gate 继续推进：
  - generation request 增加 Java 权威 memory 的有界只读 history，primary 生成前捕获；
  - 默认限制 12 条/6000 总字符/单条 2000 字符，契约硬上限 32 条/单条 4000 字符；
  - shadow 关闭时使用 no-op reader，不额外读取 Redis；
  - candidate stream 定义 `{sequence,type,data}` schema，离线校验连续序号、唯一末尾终态及
    token/done/error data 语义；
  - conversation-service 更新为 129 tests，Python targeted 更新为 85 tests，mypy 60 files；
    Compose/Helm/schema/diff 静态检查通过。
- 2026-07-30 已从 `langchain4j-platform` 总入口完成一次集中式全项目回归：
  - Java 默认 23 模块 1,143 tests（1,134 passed、9 external integration skipped），
    另有 contract 5、Flowable/H2 9、Embedded Kafka 2 项专用测试通过；
  - Java 23 模块可执行 JAR 打包通过；
  - Capability Showcase 66 files / 553 tests、type-check、production build 通过；
  - AgentScope ruff、mypy 60 files、contract export check、pytest 290 tests 通过；
  - 6 组 Compose config、Helm 默认/Knowledge split/legacy+eval 渲染和全部 shell 静态检查通过。
  - 完整报告：
    `../langchain4j-platform/docs/qa/overall-project-0730-1401/QA_REPORT.md`。
- 2026-07-30 Docker 恢复后完成 Chrome 真实整栈复检：
  - Casdoor `alice / acme / Bearer` 会话覆盖目录全部 9 模块；
  - 同步/SSE Chat、RAG 入库回查、AgentScope ReAct 与自动规划 DAG、异步任务、
    NL2SQL、工作流、视觉、MCP/A2A、渠道发现均通过；
  - 真实调用百炼文本、embedding、rerank 和视觉模型；
  - Eval 目录假就绪、Knowledge split 启动失败等证据见
    `../langchain4j-platform/docs/qa/overall-project-0730-1401/CHROME_REPORT.md`。
- 已修复上述整栈复检发现的问题：
  - Knowledge S3 客户端改用 AWS URL Connection HTTP client，消除运行时缺类；
  - split embedding/rerank/vector collection 配置与基础环境隔离，ingest API 默认改为
    `18095`；
  - Qdrant point id 从稳定业务键确定性映射为 UUID；
  - query 角色显式允许无副作用的 POST 查询端点，同时继续拒绝写入端点；
  - Eval 六项离线能力默认标记为未发布，RAG 静态状态与 live discovery 对齐；
  - Vision 上游无效请求统一映射为稳定、脱敏的 400。
- 修复后全量门禁通过：Java 23 模块 1,164 tests（0 failures、0 errors、5 skipped）；
  AgentScope 290 tests；前端 66 files / 555 tests、type-check 和 production build。
- Knowledge split 真实闭环通过：S3-compatible 原文写入 MinIO，durable job 达到 READY，
  Vector/Elasticsearch/Authorization/Registry/Graph sink 全部成功，split query 返回该原文。
- 真实 Vision 付费模型链路已到达供应商；测试图片被供应商拒绝后，服务按预期返回脱敏 400。
- 2026-07-30 Slice 7 本地生产等价门禁已完成：
  - MinIO 原文存储改为 ingest-write 与 worker-read 两组最小权限凭据，query 无凭据；
  - Qdrant 故障注入观察到 PARTIAL，跨租户读取 404，恢复后 reconcile 到 READY；
  - Knowledge readiness 纳入 Qdrant/embedding，真实停启为 200 → 503 → 200，恢复后 3 次
    业务查询均 200；
  - 24/24 并发提交 READY，8 个并发同幂等请求收敛为一个 job；
  - 100/100 查询在并发 10 下成功，P50 0.162s、P95 0.240s、P99 0.250s；
  - 120 秒 soak：59/59 查询、5/5 入库成功，无相关容器重启；
  - Knowledge combined/split/combined 与 AgentScope/legacy/AgentScope 回滚演练通过，
    Agent 两侧均触发真实付费模型；
  - 六个遗留 Agent 任务没有删除，已归档为 `FAILED / ASYNC_TASK_ORPHANED`。
- 最终 Java 全量回归：23 模块、1165 tests、0 failure、0 error、5 skipped；Compose/Helm
  production config gate 与真实 MinIO IAM smoke 通过。

## 已修改文件

- `docs/adr/0002-ai-runtime-domain-boundaries.md`
- `docs/service-decomposition.md`
- `docs/delivery/ai-runtime-boundary-decomposition/DELIVERY_PLAN.md`
- `docs/delivery/ai-runtime-boundary-decomposition/DELIVERY_STATUS.md`
- `tests/test_architecture_boundaries.py`
- `scripts/export_contracts.py`
- `tests/test_contracts.py`
- `contracts/evaluation/*`
- `../langchain4j-platform/docs/架构边界/ai-runtime-boundaries.md`
- `../langchain4j-platform/interop-service/src/main/java/com/lrj/platform/interop/*`
- `../langchain4j-platform/interop-service/src/test/java/com/lrj/platform/interop/*`
- `../langchain4j-platform/interop-service/src/main/resources/application.yml`
- `../langchain4j-platform/deploy/docker-compose.yml`
- `../langchain4j-platform/knowledge-service/src/main/java/com/lrj/platform/knowledge/ingest/job/*`
- `../langchain4j-platform/knowledge-service/src/test/java/com/lrj/platform/knowledge/ingest/job/*`
- `../langchain4j-platform/knowledge-service/src/main/java/com/lrj/platform/knowledge/KnowledgeRuntime*`
- `../langchain4j-platform/knowledge-service/src/main/java/com/lrj/platform/knowledge/KnowledgeRoleRequestFilter.java`
- `../langchain4j-platform/knowledge-service/src/main/java/com/lrj/platform/knowledge/controller/IngestionController.java`
- `../langchain4j-platform/platform-protocol/src/main/resources/contracts/knowledge/*`
- `../langchain4j-platform/deploy/docker-compose.knowledge-split.yml`
- `../langchain4j-platform/docs/架构边界/knowledge-runtime-split.md`
- `../langchain4j-platform/eval-service/src/main/java/com/lrj/platform/eval/AgentScopeShadowReportReader.java`
- `../langchain4j-platform/edge-gateway/src/main/resources/application.yml`
- `../langchain4j-platform/deploy/helm/platform/values.yaml`
- `../langchain4j-platform/docs/架构边界/evaluation-control-plane.md`
- `../langchain4j-platform/docs/架构边界/java-agent-retirement-gate.md`
- `../langchain4j-platform/docs/平台工程/eval-guide.md`
- `contracts/boundaries/conversation-generation.schema.json`
- `contracts/boundaries/conversation-stream-event.schema.json`
- `src/agentscope_platform/evaluation/conversation_stream.py`
- `../langchain4j-platform/platform-protocol/src/main/java/com/lrj/platform/protocol/conversation/ConversationGeneration*`
- `../langchain4j-platform/platform-protocol/src/main/java/com/lrj/platform/protocol/conversation/ConversationHistoryMessage.java`
- `../langchain4j-platform/platform-protocol/src/main/java/com/lrj/platform/protocol/conversation/ConversationStreamEvent.java`
- `../langchain4j-platform/conversation-service/src/main/java/com/lrj/platform/conversation/memory/ConversationHistory*`
- `../langchain4j-platform/conversation-service/src/main/java/com/lrj/platform/conversation/memory/StoreBackedConversationHistoryReader.java`
- `../langchain4j-platform/conversation-service/src/main/java/com/lrj/platform/conversation/shadow/*`
- `../langchain4j-platform/conversation-service/src/main/java/com/lrj/platform/conversation/ConversationController.java`
- `../langchain4j-platform/docs/架构边界/conversation-runtime-decision-gate.md`
- `../langchain4j-platform/deploy/smoke-knowledge-s3-iam.sh`
- `../langchain4j-platform/deploy/test-production-cutover-config.sh`
- `../langchain4j-platform/docs/平台工程/production-cutover-gates.md`
- `../langchain4j-platform/async-task-service/.../AsyncTaskOrphan*`
- `../langchain4j-platform/knowledge-service/src/main/resources/application.yml`
- `docs/delivery/ai-runtime-boundary-decomposition/{QA_REPORT,REVIEW_REPORT,DELIVERY_REPORT}.md`

注意：两个仓库原本已有大量未提交修改，上述只是本任务触及范围；不得 reset 或覆盖其它变化。

## 未完成

- Knowledge 版本 GC 在真实 Qdrant/ES/JDBC Graph 上的故障注入与运行观测。
- Java agent 本地任务排空、真实模型回滚与恢复已完成；生产 canary、变更批准和完整回滚周期
  证据仍缺失，实际删除/生产操作不授权。
- Analytics/Workflow 真实模型 shadow 评测、质量阈值和延迟门禁。
- Conversation 真实独立 candidate、真实模型多轮 shadow，以及 SSE 断连/上游取消/背压联调；
  history snapshot 和事件契约已完成，但 decision gate 仍为 HOLD，禁止在 AgentScope
  orchestrator 内实现 Chat。
- 目标环境云 IAM 审计、目标规格容量/自动扩缩、完整高峰周期 soak、真实 canary 变更单与
  值班/回滚负责人证据。

## 当前问题

- query 角色启动时已强制 hybrid 使用 Elasticsearch query，避免把进程内 keyword mirror 当
  权威来源；仍需真实双跑确认排序/召回兼容。
- ingest-api 与 worker 已分别使用写/读角色，query 无 S3 原文凭据；目标云的 workload
  identity 绑定仍需审计。
- split query 当前禁止 GraphRAG；需先让 graph hit 携带 documentId/documentVersion。
- optional split 的本地故障注入、容量、有界 soak 和整体回滚已通过；生产切流仍需目标环境
  容量、完整高峰周期 soak、canary/监控/变更批准。
- Conversation 当前只实际接线非流式 `/chat`；history 与 candidate stream 契约虽已完成，
  仍没有独立进程的真实断连、取消和背压验证，不能据此创建 runtime 或切换 primary。
- 当前 LangChain4j `TokenStream` 只有 callback + `start()`，没有 cancel API；不能把现有 Java
  流的客户端断连等同于上游模型已取消。candidate 必须在其 HTTP/SSE client 中单独证明取消。
- async-task、knowledge、interop、CI 等文件已有用户的未提交修改，继续前逐文件检查 diff。
- 本轮没有访问或猜测生产凭据/地址，也没有修改生产路由。
- 2026-07-30 Docker daemon 已恢复，edge、前端、AgentScope、Casdoor 和标准数据面均可达。
  Knowledge、Eval、Vision、RAG 的已知产品问题均已修复并通过自动化/容器验证。
- Chrome 登录态最终复验通过：Eval 显示 6 项在线 interop 就绪、6 项离线 Eval 未启用，
  Eval 运行按钮禁用并显示独立 harness/CLI/CI 提示；RAG 显示 ready 与真实运行形态，
  UI 查询“退款政策”返回 5 条结果。

## 下一步建议

1. 在目标环境执行 `docs/平台工程/production-cutover-gates.md`：收集云 IAM 审计、目标容量/
   自动扩缩、完整高峰周期 soak、canary 租户与扩量/停止阈值、监控值班和变更单。
2. 在可弃真实依赖上开启版本 GC，验证跨 sink 重试和回滚窗口后再考虑生产启用。
3. 运行 Analytics/Workflow 真实模型 shadow，补质量差异、超时和失败注入报告。
4. 在独立 Conversation candidate 进程执行真实模型多轮 shadow，并补 SSE 断连、上游取消、
   背压和错误映射联调；不得把实现加入 `agentscope-orchestrator`。
5. 目标环境 canary 和完整回滚周期通过
   `../langchain4j-platform/docs/架构边界/java-agent-retirement-gate.md` 后再讨论删除 Java
   agent；当前禁止生产默认切换。

## 恢复 Prompt

请读取 `CODEX_PROGRESS.md` 和
`docs/delivery/ai-runtime-boundary-decomposition/{DELIVERY_PLAN,DELIVERY_STATUS,QA_REPORT}.md`，
从目标环境外部门禁与 shadow 评测继续执行。保留两仓所有既有 dirty changes，不要重新规划
全部任务，不要等待我输入“继续”，除非遇到危险操作、生产权限或无法安全合并的重叠修改。
