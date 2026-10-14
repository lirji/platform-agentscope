# Codex Progress

## 任务目标

优化多步骤 DAG 的失败传播、能力隔离、调度、预算及有条件的结果复用；保持旧接口契约和可回退路径。
用户已授权制定计划后连续实施，以及正常分支提交、合入并推送 main；不授权生产部署。

## 已完成

- 读取代码、迁移记录和 Git 状态；基线 `4c5f673`，原目录任务分支 `refactor/dag-orchestration`。
- 基线 `uv sync --dev`、Ruff、Mypy、pytest 通过：530 passed。
- 计划见 `docs/delivery/dag-optimization/PLAN.md`。

- S1 已完成：7 项新测试、全量 537 passed；Ruff/format/Mypy/契约快照通过。

- S2 已完成：就绪调度、共享与租户并发、事件和取消验证通过，相关 40 项 PASS。

- S3 已完成：整体时限与模型边界预算，全量 553 passed。

## 已修改文件

- `CODEX_PROGRESS.md`
- `docs/delivery/dag-optimization/PLAN.md`
- `docs/delivery/history/progress-before-dag-optimization.md`

## 未完成

- S4 证据评审与只读结果复用。
- S5 全量验证、契约/双跑用例、文档和 Git 交付。
- S6 节点持久恢复为条件阶段：依赖 Java 中央任务服务新增持久化契约与真实恢复验收，不在本仓伪造实现。

## 当前问题

- 原有 `.engineering/remediation/`、`.workflow/` 未跟踪目录不属于本任务，保留。
- 真实模型/旧新服务双跑及跨服务恢复未验证；优化默认关闭，禁止据离线验证切生产流量。

## 下一步建议

1. 先写行为测试并确认在旧实现失败，再逐片实现和验证。
2. 每个已验证逻辑单元独立提交，最终正常合入推送 main，检查远程 CI。

## 恢复 Prompt

读取 CODEX_PROGRESS.md 和 docs/delivery/dag-optimization/PLAN.md，从未完成切片继续，不重做基线，不修改无关文件，不等待继续。遵守默认关闭优化模式和无生产部署边界。
