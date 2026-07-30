# Delivery Status

## Goal

关闭 `ASYNC-QA-001`，使两侧异步指标可抓取并通过自动化与 localhost 门禁。

## State

- Phase: delivery reporting
- Status: implementation and localhost verification complete
- Release recommendation: merge-ready corrective slice; no-go for production gray cutover
- Last updated: 2026-07-29

## Completed

- 读取原 Phase 3 交付与黑盒 QA 证据。
- 定位 Java 缺 registry、Python 缺 meter provider/reader 的根因。
- 记录用户对修复、门禁、双跑和压力验证的批准。
- AO-01：Java 增加 Prometheus registry、显式启用 exporter，并补认证集成测试。
- AO-02/03/04：Python 增加 OTel reader、受 JWT 保护的 `/metrics` 和低基数契约测试。
- AO-05：Python 201 项测试、89% coverage 与 Java async-task 43 项测试通过。
- AO-06：README、async runbook 和测试门禁文档已同步。
- AO-07：localhost 12/12 双跑匹配，30.033 秒 soak 的 240/240 任务成功。

## Changed Files

- `docs/delivery/phase-3-async-observability/DELIVERY_PLAN.md` - 已批准修复方案。
- `docs/delivery/phase-3-async-observability/DELIVERY_STATUS.md` - 工作流状态。
- `src/agentscope_platform/infrastructure/observability/prometheus.py` - OTel reader 和
  Prometheus 文本渲染。
- `src/agentscope_platform/infrastructure/observability/async_task_metrics.py` - 指标描述与单位。
- `src/agentscope_platform/api/app.py`, `api/routes.py` - 初始化与认证 scrape endpoint。
- `tests/test_metrics_endpoint.py` - Python endpoint/auth/标签门禁。
- `../langchain4j-platform/async-task-service/pom.xml` - Prometheus registry。
- `../langchain4j-platform/async-task-service/src/main/resources/application.yml` - 显式启用 exporter。
- `../langchain4j-platform/async-task-service/src/test/.../AsyncTaskMetricsEndpointTest.java`
  - Java endpoint/auth 集成门禁。

## Verification Log

| Command or check | Result | Notes |
| --- | --- | --- |
| repository/dirty-tree inspection | pass | 未触碰两仓无关用户修改 |
| dependency availability | pass | Python 复用现有 OTel SDK；Java registry 已在本地 Maven cache |
| focused Python metrics tests | pass | 2 passed；Ruff/mypy pass |
| focused Java metrics integration | pass | 认证 401、带 token 200、counter 可见 |
| Python complete CI equivalents | pass | contracts、Ruff、format、mypy、201 tests、89% coverage、shadow、build、Compose |
| Java affected reactor | pass | `mvn -o -pl async-task-service -am test`；async-task 43 tests |
| localhost metrics scrape | pass | 双侧匿名 401、认证 200、自定义低基数 series 可见 |
| deterministic dual-run | pass | 12/12 `finalAnswer`、`stopReason` 匹配 |
| bounded soak | pass | 30.033s；240/240；E2E p95 312.898ms |
| process cleanup | pass | 14000、18085、18086 均无监听进程 |

## Decisions And Deviations

- 不新增 Python 第三方依赖，避免不必要的联网与双 metrics 栈。
- UI/UX 不适用。
- Java Boot 条件报告显示默认 metrics export 在当前平台被视为关闭，因此显式设置
  `management.prometheus.metrics.export.enabled=true`；不改变其他 registry。
- 第一次 localhost 检查把 Java 内建 Kafka `result="success"` 标签误判为自定义指标泄漏；
  断言修正为仅检查 `agent_async_task_*` / `async_task_*` 后重跑通过。

## Blockers And Residual Risks

- Prometheus reader 是进程本地状态；多 worker/pod 环境必须逐实例抓取并由监控后端聚合。
- 真实模型和共享 staging 未提供目标、短时 token 或模型网关，无法完成生产代表性双跑、
  长时容量和告警触发验证。

## Next Action

在明确命名的测试环境执行真实模型新旧双跑、长时容量与告警验证；通过独立审批前不修改
生产 `AGENT_URI`，并保持 async/orphan 默认关闭。
