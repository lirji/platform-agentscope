# Delivery Status

## Goal

交付 Phase 3 异步任务、SSE、取消、webhook 和安全的重启孤儿终结。

## State

- Phase: Phase 8 - delivery reporting
- Implementation: complete
- Release recommendation: conditional-go for test environment; no-go for production cutover
- Last updated: 2026-07-29

## Completed

- 用户批准的 A+D 组合方案已在两仓实现。
- Python 完成五类 async、任务 CRUD/SSE、Reflexion SSE、manager/client/token deadline。
- 中央完成原子终态、持久事件、append API、SSE 回放、webhook 兼容和定向 reaper。
- 契约、配置、部署默认值、评测场景、运行/回滚文档和既有 CI 门禁已同步。
- 代码评审发现的队列截止、状态竞争、SSE replay/live 重复和 retry-after-terminal 问题已修复。

## Verification Log

| Command or check | Result | Notes |
| --- | --- | --- |
| `uv sync --frozen --dev` | pass | 锁定依赖可安装 |
| contract/Ruff/format/mypy | pass | 53 source files type checked |
| `uv run pytest` | pass | 199 passed |
| pytest coverage gate | pass | 89.06%, threshold 80% |
| shadow smoke/build/Compose config | pass | 8 samples；sdist/wheel 成功 |
| `mvn -pl async-task-service -am test` | pass | async module 43 tests；reactor success |
| authenticated metrics retest | pass | 双侧 401/200、12/12 双跑、240/240 localhost soak |
| `git diff --check`（两仓） | pass | 无 whitespace error |

## Decisions And Deviations

- 进程崩溃不恢复模型调用；reaper 仅处理五种新 Agent kind。
- Python 不投 webhook；中央 JDBC outbox 是唯一 HTTP webhook 投递方。
- 既有 GitHub Actions 已覆盖新 Python 测试/契约，无需新增权限或重复 workflow。
- 旧仓已有 knowledge/doc unrelated dirty changes，实施未修改或清理这些文件。
- 未提交 Git commit；工作树保留给用户审阅。

## Blockers And Residual Risks

- `ASYNC-QA-001` 已关闭；真实模型 async 双跑、共享拓扑容量/告警验证仍需要外部测试环境。
- DNS rebinding 需要网络层 egress/allowlist。
- 任务最大寿命受原内部 JWT 的剩余 TTL 限制。

## Next Action

按 `QA_REPORT.md` 在测试环境执行外部门禁；通过后单独审批灰度，不直接修改生产路由。
