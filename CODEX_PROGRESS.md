# Codex Progress

## 任务目标

交付本仓历史安全整改、适配新版 PyJWT 的测试、同步过期文档，并完成 Java 依赖整改准备。
用户 2026-10-14 确认暂无非生产环境，本轮不执行真实模型/MCP/Sandbox 验收或 Java 大版本升级。
规范记录：`docs/delivery/pending-security-remediation.md`。

## 已完成

- 已建任务分支 `fix/pending-security-remediation`，基线 a7526db；原有本任务修改保留并纳入交付。
- 生产禁止关闭鉴权；JWT 非规范编码改为在解码边界拒绝，同时验证合法 grant 单次消费。
- 聚焦 26 passed；最终全量 526 passed / 89.44%；Ruff/format/Mypy/契约/静态门禁/Shadow 通过。
- 审计发现 multidict 漏洞并升级唯一锁版本 6.7.1 → 6.9.1；105 个生产包审计无已知漏洞。
- Java 最新扫描提取完成：88 条 HIGH/CRITICAL 记录、31 个包坐标；兼容路线及 MyBatis 新约束已整理。
- 迁移路线图、README、异步运行手册、能力边界和历史 CI 状态已同步。
- 修复首次远程镜像扫描的 Perl 漏洞，Dockerfile 断言至少 5.36.0-7+deb12u4。
- 07af2d8 / 16f8deb / 9abcc5d / fd3a44b 已正常合并并推送 main。
- fd3a44b 的 CI 38508544838 SUCCESS，包含全量回归、构建和镜像扫描；后续仅交付文档收尾。
  证据：https://github.com/lirji/platform-agentscope/actions/runs/38508544838

## 已修改文件

- `src/agentscope_platform/core/config.py`
- `tests/test_config.py`、`tests/test_tool_confirmation.py`、`tests/test_shadow_cli.py`
- `Dockerfile`、`docs/software-supply-chain.md`、`uv.lock`、`README.md`、`docs/architecture.md`、`docs/async-orchestration.md`
- `docs/current-system-map.md`、`docs/migration-plan.md`、`docs/delivery/cross-runtime-reliability.md`
- `docs/delivery/pending-security-remediation.md`、`docs/delivery/dependency-remediation-readiness.md`
- `docs/delivery/dependency-remediation-scan-2026-10-14.json`、历史进度快照、本文件。

## 未完成

- 本轮本地整改和依赖准备已完成；后续 Java 实施及外部验收如下。
- 真实模型、MCP/Sandbox、运行中旧服务 OpenAPI、生产 19 项证据等待外部环境，不在本轮执行范围。
- Java 依赖升级等待后续版本组合设计与评审；本轮只交付准备材料。

## 当前问题

- Java 最新 SBOM 仍 FAIL，镜像扫描未执行；不得沿用旧 85 条记录的合并例外声称本次安全通过。
- 历史 ESS `.workflow/` 与 `.engineering/remediation/` 保留未跟踪状态，历史阻塞/审批不改写。
- main 当前检出在既有 `~/.local/share/git-worktrees/agentscope-platform/cross-runtime-verification`。
- 本地 ARM64 镜像构建曾因 wheel 下载超时中断，未完成本机容器 smoke；远程 Linux 构建和扫描已通过。
- 生产仍 NO-GO，未修改生产目标或执行任何部署。

## 下一步建议

1. 后续 Java 工作按 `docs/delivery/dependency-remediation-readiness.md` 从 D1 组合设计开始，不直接批量改 POM。
2. 环境可用后补真实模型/MCP/Sandbox、运行中旧服务契约比较及生产证据；保持 NO-GO。
3. 保留历史治理记录、worktree 和私有配置；后续 CI 状态查 Actions，不重复已通过源码验证。

## 恢复 Prompt

读取 CODEX_PROGRESS.md 和 docs/delivery/pending-security-remediation.md。本轮整改与准备已交付，不重复实施。
用户已授权正常 Git 交付；无需重复询问。暂无真实测试环境，本轮不升级 Java 或部署生产。
历史进度完整保留在 docs/delivery/history/progress-before-pending-security-remediation.md，勿重复已完成能力。
