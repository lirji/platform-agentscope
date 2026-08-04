# Codex Progress

## 任务目标

按批准的生产加固方案完成 AgentScope 与受影响 Java 平台模块的 AC-01～AC-16，并在每个实现切片后
执行测试。工程交付完成后必须保持生产 NO-GO，直到目标环境的发布、IAM、恢复、容量、评测、
canary、监控和回滚证据全部通过机器门禁。

## 已完成

- AC-01～AC-16 的设计、实现、代码审查、QA、文档和本地工程验证全部完成。
- Agent 运行具备有限 token/时间/单次输出预算；provider retry 责任明确。
- 写工具使用 tenant/user/tool/参数/幂等键绑定的一次性短时确认 grant，Redis 原子防重放。
- MCP、browser、code 和 worker 使用用途、audience、action 与资源绑定的独立服务身份。
- async task 控制面绑定 tenant+owner；worker 写回由 lease owner+epoch fencing 保护。
- callback 具备 HTTPS allowlist、DNS/SSRF/redirect 防护和分服务 HMAC；SSE 统一隐私与错误映射。
- Workflow 退款启动使用数据库唯一、事务原子的幂等账本。
- HTTP 客户端统一连接池、deadline、bulkhead/circuit；副作用不做无条件重试。
- 多副本任务、outbox、session 和 A2A context 具备 CAS/lease/恢复/drain 语义。
- readiness、低基数 metrics、Compose/Helm 最小权限、网络策略、HPA/PDB 和拓扑分散已补齐。
- 数据库 schema 由独立 Flyway expand-contract migration 管理；应用身份没有 DDL 权限。
- 两仓供应链 CI 包含锁定 Action、SBOM、漏洞扫描、tag-only OIDC 发布、签名和 attestation。
- 持久 session/checkpoint、capability registry 和 A2A context 使用语言中立版本化格式；
  AgentScope 类型没有越过 infrastructure adapter。
- 轨迹绑定 prompt/model/tool 内容版本；Shadow v4、内容寻址数据集、严格回放、对抗集和最小化
  反馈导入已完成。
- AC-16 统一运行手册和 `agent-production-evidence.v1` 证据门禁已完成。19 项外部证据任一缺失
  都 fail closed；默认模板执行 `--require-go` 会按设计返回 NO-GO。
- 最终 AgentScope 门禁通过：Ruff、format、Mypy 87 source files、contract export、470 tests、
  89.60% coverage、Shadow smoke、对抗数据集校验、供应链/运行手册检查、sdist/wheel、Compose
  和 diff check。
- 最终 Java 代码全量回归通过：268 reports、1262 tests、0 failures/errors、9 skipped；最终文档
  变更后 production cutover、runtime hardening、database migration、supply chain 四组静态门禁
  与 diff check 复验通过。
- 最终报告：
  - `docs/delivery/production-agent-hardening/REVIEW_REPORT.md`
  - `docs/delivery/production-agent-hardening/QA_REPORT.md`
  - `docs/delivery/production-agent-hardening/DELIVERY_REPORT.md`
- 2026-08-03 完成第一轮只读外部证据勘察：公开远端没有 tag、release、deployment 或候选制品；
  AgentScope 最新 CI 与 Java cutover CI 各有一个失败步骤，不能作为当前 dirty 交付的候选证据。
  详细记录见 `docs/delivery/production-agent-hardening/TARGET_ENV_EVIDENCE_AUDIT.md`。
- 2026-08-03 按用户授权完成两仓 dirty working tree 的本地重建和 Docker Compose 部署：
  AgentScope、Java packaging-only 产物、完整服务/迁移/前端镜像均已构建；8/8 migration 成功，
  16/16 HTTP 探针符合预期，匿名 edge chat 返回 401，运行中容器 restart count 均为 0。
- Chrome 已验证能力控制台登录页和 `acme` 本地 Casdoor 跳转，未输入凭据或执行模型业务调用。
  证据见 `docs/qa/local-full-stack-rebuild-0803-1711/QA_REPORT.md`。

## 已修改文件

- AgentScope：`src/agentscope_platform/**`、`tests/**`、`contracts/**`、`scripts/**`、
  `eval/datasets/**`、`compose.yml`、`.github/**`、`docs/**` 和相关配置。
- Java：安全、async-task、workflow、interop、eval、migration、observability 相关模块，以及
  `deploy/docker-compose.yml`、`deploy/helm/platform/**`、`.github/**` 和相关文档。
- 完整逐文件/逐切片记录见
  `docs/delivery/production-agent-hardening/DELIVERY_STATUS.md`。
- 外部证据勘察记录：
  `docs/delivery/production-agent-hardening/TARGET_ENV_EVIDENCE_AUDIT.md`。

注意：两个仓库在任务开始时已有大量用户未提交修改；没有 reset、覆盖或清理这些变化。

## 未完成

- 真实 MySQL 8.4 migration/权限/幂等 Compose 演练。
- 真实 Redis 多副本 CAS、TTL、重启和 failover 演练。
- 最终镜像 build/Trivy、真实 GHCR tag 发布、Cosign/Rekor/SLSA/SBOM attestation 和准入拒绝证据。
- 目标云 workload identity、callback egress、容量/HPA、完整高峰周期 soak。
- 真实模型 Shadow v4、对抗集、反馈治理及相同 dataset replay。
- 命名租户 canary、dashboard/alert/on-call、变更批准、Redis/MySQL 恢复和整服务回滚。

这些事项都需要外部环境、发布负责人或生产授权，不属于本地工程缺陷。当前不允许生产切流。

## 当前问题

- 本机 Docker daemon 当前可用，本地全栈容器保持运行，前端位于 `http://localhost:8093`。
- Java 的文档化打包命令 `mvn -DskipTests package` 会在 `platform-eventbus` 的 testCompile
  阶段因 migration 测试类型不在 classpath 而失败；本轮仅用
  `mvn -Dmaven.test.skip=true package` 完成 packaging-only 构建，不能算测试通过。
- 已有 MySQL volume 不会自动重跑当前 init SQL，且 `CREATE USER IF NOT EXISTS` 不会收敛旧密码；
  本轮已补齐本地 migrator 账号并收敛 `nl2sql_ro` 开发凭据，未删除业务数据。
- 目标环境和真实 registry/cluster 的权限、地址、负责人及证据在当前工作区不可用。
- 当前只配置了本机 `docker-desktop` Kubernetes context，GitHub CLI 未登录；公开远端与本地
  dirty 工作树的 base commit 一致，但没有包含 AC-01～AC-16 的不可变 candidate/tag/image。
- 生产证据模板仍为 `decision=NO_GO`，candidate/rollback digest 未解析，19 项检查为 PENDING；
  `--require-go` 已确认会返回非零退出码。
- 未修改生产 `AGENT_URI`，也未执行任何生产部署、切流、回滚或数据删除。

## 下一步建议

1. 提供命名非生产目标 URL 或目标集群 context/namespace，并明确真实模型成本策略；发布负责人
   同时提供 candidate/rollback digest、发布工作流 URL、证据 JSON 路径和逐项 owner。
2. 严格执行 `docs/operations/production-release-runbook.md` 中的恢复、容量、Shadow/对抗、
   canary、监控和整服务回滚演练。
3. 运行：

   ```bash
   uv run python scripts/test_production_runbook.py \
     --evidence <release-evidence.json> \
     --require-go
   ```

4. 只有命令返回 GO 且变更单获得授权后，才进入 canary；该命令本身不执行部署。

## 重要上下文

- Java 继续拥有业务数据、事务、安全、任务、Workflow 和副作用；Python 只负责推理与编排。
- AgentScope 类型只能位于 `infrastructure/agentscope/`。
- 旧 `/agent/run` JSON 和 legacy capability projection 保持兼容。
- Legacy Java Agent 只作为整服务回滚目标，不做 per-request 自动 fallback。
- schema 回滚保留 additive expand 结果，禁止自动 down migration。
- 最终工程结论为 PASS；生产发布结论为 NO-GO，二者不得混写。

## 已发现的问题

- 审查中发现并修复 Helm session/interop 断言读取错误对象、model version 未绑定 gateway endpoint、
  per-tool version map 校验不足、Java 接受 v3/无 dataset 报告，以及发布证据仅为文字描述的问题。
- 外部证据缺口已被机器门禁显式化，不再以文档备注或口头确认处理。

## 恢复 Prompt

请读取 `CODEX_PROGRESS.md`、
`docs/delivery/production-agent-hardening/DELIVERY_STATUS.md` 和
`docs/operations/production-release-runbook.md`。AC-01～AC-16 的本地工程交付已经完成，不要
重新实现；从目标环境外部证据收集与验证继续。保留两仓所有既有 dirty changes，不要修改生产
`AGENT_URI`，不要执行生产切流、删除或回滚，除非获得明确授权。
