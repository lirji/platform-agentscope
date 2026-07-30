# Phase 3 Async Observability Delivery Plan

## Requirement

修复黑盒验收发现的 `ASYNC-QA-001`：异步编排指标虽已埋点，但 Java 与 Python
运行时均无法被监控系统抓取。补齐可抓取端点、自动化门禁、运行文档，并重跑本地双跑与
压力验证。

## Repository Evidence

- Java `AsyncTaskMetrics` 已向 `MeterRegistry` 写入 event append 与 orphan counters，
  但 `async-task-service/pom.xml` 缺少 `micrometer-registry-prometheus`，Actuator 只暴露
  health/info。
- Python `AsyncTaskMetrics` 使用 OpenTelemetry instruments，但
  `configure_tracing()` 只设置 `TracerProvider`；默认 `MeterProvider` 为 no-op。
- Python 已锁定 `opentelemetry-sdk`，可使用 SDK `InMemoryMetricReader`，无需引入或下载
  新依赖。
- 两侧管理端点继续使用现有内部认证语义；健康探针仍是唯一匿名开放路径。

## Feasibility

- Verdict: go
- Constraints:
  - 不改变任务、SSE、webhook 或外部业务 DTO。
  - 指标标签只允许固定 `kind`、`status`、`event`、`duplicate`，禁止 taskId、tenant、
    prompt、result、token。
  - 不新增生产路由或部署动作。
- Risks and mitigations:
  - OTel 全局 provider 只能设置一次：使用进程级幂等初始化和单一 reader。
  - 多次测试创建 App 导致累计值：契约断言验证名称、类型和标签，不依赖绝对计数。
  - Prometheus 文本转义：集中处理 label 名称和值，并只渲染 SDK 数值数据点。

## Product Design

- Actors and goals:
  - 平台监控使用内部 token 抓取 Java `/actuator/prometheus` 与 Python `/metrics`。
  - 运维能够观察提交、完成、运行中、heartbeat、orphan 和 event append 指标。
- Scope:
  - Java Prometheus registry 与 endpoint 集成测试。
  - Python OTel meter provider、Prometheus 文本 endpoint、认证/低基数测试。
  - Compose/runbook/QA 与交付证据同步。
- Out of scope:
  - Prometheus/Grafana 部署。
  - 告警阈值的生产调优。
  - 修改生产 `AGENT_URI` 或 feature flag。

## Acceptance Criteria

| ID | Observable behavior | Priority | Verification |
| --- | --- | --- | --- |
| AO-01 | Java `/actuator/prometheus` 经内部认证返回 200 和 async counters | P0 | Spring integration + localhost scrape |
| AO-02 | Python `/metrics` 无 token 返回 401，有效 token 返回 Prometheus 文本 | P0 | FastAPI API tests |
| AO-03 | Python async submission/completion/running/heartbeat 指标可见 | P0 | focused metrics + black-box tests |
| AO-04 | 两侧指标不包含 taskId、tenant、prompt、result 或 token 标签 | P0 | adversarial assertions |
| AO-05 | 既有任务契约、199 项回归和 Java async tests 不退化 | P0 | full repository gates |
| AO-06 | 运维文档说明路径、认证、指标名和回滚 | P1 | docs review |
| AO-07 | 本地确定性双跑与并发任务在修复后继续通过 | P1 | localhost QA |

## UI/UX Design

- Applicability: Not applicable.
- Evidence: 只修改服务端管理面与运维文档，不修改用户界面。

## Technical Solution

- Chosen approach:
  - Java 增加 Spring Boot 管理的 `micrometer-registry-prometheus`，复用现有 Actuator
    exposure 和内部认证 filter。
  - Python 新增进程级 OTel `MeterProvider` 与 `InMemoryMetricReader`，由 `/metrics`
    即时采集并渲染 Prometheus 0.0.4 文本。
  - `/metrics` 使用 `RunContextDependency`，沿用 `X-Internal-Token`。
- Alternatives rejected:
  - 直接改用 `prometheus_client`：增加新网络依赖且绕开现有 OTel instruments。
  - 只配置 OTLP push：不能关闭本次 `/metrics` 404 缺陷，也不便于当前黑盒门禁。
  - 公开匿名 metrics：扩大管理面访问范围，偏离现有 Java 安全语义。
- Modules and file map:
  - Python: `observability/setup.py`, `observability/prometheus.py`, `api/routes.py`,
    tests, README/runbook/QA artifacts.
  - Java: `async-task-service/pom.xml`, metrics endpoint integration test。
- Compatibility:
  - 不修改业务 OpenAPI DTO；新增只读管理 endpoint。
  - async 与 orphan feature flag 默认值不变。

## Implementation Sequence

1. 补 Python endpoint/auth/metric contract tests 与 Java endpoint integration test。
2. 实现 Python provider/reader/rendering 和 Java registry dependency。
3. 运行窄测试、完整双仓门禁、契约与构建。
4. 重跑隔离 localhost scrape、双跑和持续并发。
5. 评审、QA、文档和交付报告。

## Verification Plan

| AC/Risk | Test level | Command/case | Required evidence |
| --- | --- | --- | --- |
| AO-01 | Java integration | Maven async module test | HTTP 200 + metric name |
| AO-02/03/04 | Python API/unit | pytest metrics cases | auth, content type, labels |
| AO-05 | repository | Ruff/mypy/pytest/contracts/build/Maven | all pass |
| AO-06 | docs | diff review | exact paths/names/rollback |
| AO-07 | black-box | isolated topology | scrape + dual-run/load JSON |

## Documentation And CI Plan

- 更新 async runbook、README、交付/QA 状态。
- 既有 GitHub Actions 自动运行 Python 新测试；旧仓 Maven 流程自动运行新增 integration
  test，无需新权限或部署 job。

## Rollout And Rollback

1. 先部署 registry/endpoint 修复但保持 async 与 orphan 关闭。
2. 使用内部 scrape token 验证两侧指标出现。
3. 再在测试租户开启 async/orphan 并验证 counters 增长。
4. 回滚时恢复上一镜像；业务任务表、事件表和任务 API 不受影响。

## Assumptions And Approval

- 真实模型/共享 staging 需要另行提供凭据或明确环境；本轮不会猜测或调用。
- Status: approved
- Evidence: 用户在收到“修复 ASYNC-QA-001、补 metrics 门禁、再双跑/压测”的建议后明确回复
  “按照你的建议执行”。
