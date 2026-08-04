# Agent Platform Production Hardening Delivery Plan

## Requirement

按 2026-08-03 两仓生产审查建议，持续修复 AgentScope 与 langchain4j-platform 的安全、
可靠性、部署、可观测性和 Agent 产品化缺口；每个实现切片完成后先运行聚焦测试，再进入下一项。

## Repository Evidence

- AgentScope 只拥有推理与编排，Java 继续拥有数据、事务、安全与副作用；现有架构测试必须保持。
- 现有生产切换报告结论为 NO-GO，目标环境 IAM、容量、canary、值班和恢复证据仍缺失。
- AgentScope 当前工作树包含既有未提交迁移改动；所有实现必须逐文件检查并保留这些变化。
- Java 仓库在本交付开始时工作树干净，可按模块形成独立、可测试切片。

## Feasibility

- Verdict: conditional-go
- Constraints: 不访问生产凭据或地址；不部署；不删除 legacy 回滚路径；不把 Java 领域逻辑复制到 Python。
- Dependencies: Python 3.12/uv、Java 21/Maven；部分集成门禁需要 Docker；目标环境门禁需要用户侧云权限与变更批准。
- Risks and mitigations:
  - 范围跨两仓且较大：按安全 P0、可靠性 P1、Agent 能力、最终门禁分片，每片独立测试。
  - 两仓状态不对称：AgentScope 修改前逐文件查看 diff；禁止 reset/覆盖既有改动。
  - 安全契约可能影响调用方：保留明确的灰度配置或兼容读取路径，生产模式 fail-closed。
  - 外部环境无法本地证明：记录为 blocked external check，不把模拟结果写成生产通过。

## Product Design

- Actors and goals: 平台调用者获得有界、可审计的 Agent 执行；租户用户只能操作自身资源；worker
  使用独立服务身份；运维人员可以安全扩容、回滚和定位故障。
- Scope: 上一轮审查列出的 P0/P1 修复、Agent 产品化能力、测试、文档和 CI 门禁。
- Out of scope: 生产部署和变更单执行；生产密钥创建；Java 领域服务重写；未通过双跑前删除 legacy agent；
  与生产加固无关的 UI 重构；将训练框架引入生产编排服务。
- Business rules:
  - 所有副作用调用必须同时满足 scope、参数绑定确认和幂等要求。
  - 用户控制面按 tenant + owner 授权；worker 数据面只接受受信服务身份。
  - 任一回调都不得访问本地、私网、链路本地或云 metadata 地址。
  - Agent 请求必须受 wall-clock、token、并发和成本预算约束。

## Acceptance Criteria

| ID | Observable behavior | Priority | Verification |
| --- | --- | --- | --- |
| AC-01 | 生产配置拒绝无限 Agent timeout/token budget，执行达到任一预算后产生稳定终止原因 | P0 | Settings/runner 单测、配置门禁 |
| AC-02 | 副作用确认是一次性、短时且绑定 tenant/user/tool/规范化参数摘要 | P0 | API、跨租户、重放与参数篡改单测 |
| AC-03 | 调用 MCP/sandbox 不转发原始用户内部 JWT，内部 JWT 校验具备 issuer/audience/key-id 策略 | P0 | client/JWT 单测和配置门禁 |
| AC-04 | async-task 用户 API 强制 owner 隔离，worker API 强制服务身份和 worker 约束 | P0 | controller/跨租户/worker 授权测试 |
| AC-05 | async/workflow/A2A 回调统一阻断 SSRF，使用预注册/签名/受控重定向策略 | P0 | IPv4/IPv6/DNS/redirect/签名单测 |
| AC-06 | 流式接口不泄露 PII 或底层异常，客户端断开可传播取消或明确记录不可取消边界 | P0 | 流式控制器与取消测试 |
| AC-07 | 退款等副作用幂等由数据库唯一约束和事务原子保证 | P0 | 并发与冲突回归测试 |
| AC-08 | HTTP 客户端复用连接池，依赖调用具备 deadline、bulkhead/circuit-breaker 和安全降级 | P1 | 生命周期、超时、并发、故障测试 |
| AC-09 | 异步 Agent/relay 可在多副本下安全 claim、续租、fencing、恢复和 drain | P1 | store/worker 多实例与故障恢复测试 |
| AC-10 | readiness 覆盖必要依赖；指标包含延迟分布、inflight、backlog、token/cost 和终止原因 | P1 | 健康检查与 Prometheus 测试 |
| AC-11 | Helm/Compose 使用最小权限 service account/secret/network/securityContext，并具备 PDB/拓扑/HPA | P1 | Helm/Compose 静态门禁与渲染测试 |
| AC-12 | 应用启动不执行生产 schema 演进，使用版本化 expand-contract migration | P1 | migration 集成测试和启动测试 |
| AC-13 | CI 覆盖两仓真实模块并生成/扫描 SBOM、镜像和依赖，发布物可签名追溯 | P1 | workflow 语法与底层命令本地验证 |
| AC-14 | Agent checkpoint/session、真实 A2A context 和能力注册具备语言中立持久契约 | P2 | contract、恢复、兼容与架构测试 |
| AC-15 | Prompt/model/tool 版本进入轨迹；评测支持版本数据集、回放、对抗和线上反馈导入 | P2 | schema/CLI/evaluation 测试 |
| AC-16 | 发布、监控、回滚、RPO/RTO 和目标环境外部门禁具备可执行 runbook | P2 | 文档静态检查与目标环境证据清单 |

## UI/UX Design

- Applicability: 当前修复均为后端、契约和运维面，不改变用户 UI；若后续需要展示降级/预算/确认状态，
  另行沿用 capability-showcase 现有组件和无障碍约定。
- Flow and component map: Not applicable.
- State matrix: API 统一区分 unauthorized、forbidden、budget-exhausted、timeout、cancelled、degraded。
- Responsive and accessibility behavior: Not applicable.

## Technical Solution

- Chosen approach: 保持 Python 编排/Java 权威领域边界，以小型垂直切片逐项 fail-closed 加固。
- Alternatives rejected:
  - 一次性重写或合并微服务：回归半径过大，破坏已验证边界。
  - 继续增加 Agent 模式后再补安全：扩大未受控攻击面。
  - 仅靠网关过滤：内部横向调用和后台 worker 仍需服务自身授权。
  - 用本地 smoke 代替生产 canary/恢复：证据范围不匹配。
- Modules and file map:
  - AgentScope: `core/config.py`、`api/dependencies.py`、`domain/tool.py`、security/MCP/sandbox/http
    adapters、runner/async/observability、contracts/evaluation、tests、Compose/Helm 文档。
  - Java: `platform-security`、`async-task-service`、`workflow-service`、`interop-service`、
    `conversation-service`、`edge-gateway`、部署 Helm/Compose、数据库 migration、CI 与 runbook。
- Contracts and data: 所有新跨进程状态使用 Pydantic/OpenAPI/JSON Schema 或 platform-protocol DTO；
  禁止持久化 AgentScope 内部状态对象。
- Security and reliability: 默认拒绝、短期委托凭证、owner/service 双平面、统一出站策略、事务唯一键、
  lease epoch/fencing、deadline 传播、有限重试和负载拒绝。
- Observability: trace/tenant/version/stop reason 作为低基数字段；敏感正文不进入日志或指标。
- Compatibility and migration: 本地/测试保留明确兼容开关；生产 profile 对无限预算、不安全回调、
  共享身份和内存权威状态 fail-fast；所有改变包含回滚说明。

## Implementation Sequence

1. Agent 执行 timeout/token/deadline 预算（AC-01）。
2. 参数绑定的一次性人工确认（AC-02）。
3. 下游服务身份与 JWT 严格校验（AC-03）。
4. async-task 用户/worker 授权分面（AC-04）。
5. 统一出站回调 SSRF/签名策略（AC-05）。
6. 流式隐私、错误与取消（AC-06）。
7. 数据库原子幂等（AC-07）。
8. HTTP 生命周期、并发隔离和故障策略（AC-08）。
9. durable async/relay 多副本安全（AC-09）。
10. readiness、指标和 SLO（AC-10）。
11. Helm/Compose 运行时安全、HA 和密钥隔离（AC-11）。
12. 版本化数据库迁移（AC-12）。
13. CI/SBOM/扫描/签名门禁（AC-13）。
14. checkpoint/session/capability/prompt/evaluation 产品闭环（AC-14～AC-15）。
15. 全量回归、运维 runbook 和目标环境证据清单（AC-16）。

## Verification Plan

| AC/Risk | Test level | Case or command | Required evidence |
| --- | --- | --- | --- |
| Python 单项 | unit/contract | `uv run pytest <focused tests>` | 退出码 0、用例数和覆盖行为 |
| Python 切片 | lint/type/regression | `uv run ruff check .`; `uv run mypy src`; `uv run pytest` | 全绿且无契约漂移 |
| Java 单项 | unit/module | `mvn -pl <module> -am test` 或聚焦 `-Dtest` | 退出码 0、测试统计 |
| Java 切片 | reactor/package | `mvn test`; `mvn -DskipTests package` | 全模块全绿 |
| 部署 | static/render | Compose config、Helm lint/template、仓库门禁脚本 | 渲染值与安全断言 |
| 外部环境 | integration/ops | production-cutover runbook | 云 IAM/canary/soak/restore 的真实证据 |

## Documentation Plan

- 每片更新 `DELIVERY_STATUS.md`；最终生成 REVIEW/QA/DELIVERY_REPORT。
- 同步安全配置、API、部署、SLO、故障处理、迁移、发布与回滚文档。
- 更新根 `CODEX_PROGRESS.md`，确保跨会话从第一个未完成切片恢复。

## CI Plan

- 沿用 GitHub Actions；覆盖 Python lint/type/test/contract 和 Java 完整 reactor/专用 profile。
- 增加依赖与镜像扫描、SBOM、最小权限、并发取消和路径覆盖门禁。
- 签名只配置无密钥 OIDC 流程，不创建或使用生产凭据，不自动部署。

## Rollout And Rollback

- 每个安全特性先在本地/测试验证，再按 tenant canary；出现授权错误、P95/P99、错误率、成本或
  质量门禁越界立即停止扩量。
- 保留旧配置和 legacy agent 路径作为短期回滚，但生产不允许回退到无限预算、原始 token 转发、
  任意 callback 或跨 owner 访问。
- 数据变更采用 expand-contract；回滚只关闭新读取/执行路径，不删除新字段或迁移记录。

## Assumptions And Open Decisions

- 用户“按照你的推荐进行修复和优化”视为批准上一轮审查的完整代码/测试/文档范围。
- 目标环境的 IAM、生产 canary、完整高峰周期和恢复演练需要后续外部权限；本交付先完成代码、
  本地门禁和可执行 runbook。
- 算法训练实验轨道为可选职业增强，不作为生产加固完成条件，也不引入生产运行依赖。

## Approval

- Status: approved
- Approved scope: 上一轮推荐中的生产安全与可靠性优先修复、随后 Agent 产品闭环；每项修改后测试。
- Evidence: 用户消息“按照你的推荐进行修复和优化，每次修改完一项，要跑测试”。
