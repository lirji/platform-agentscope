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

- S4 已完成：证据评审与有条件只读结果复用，全量 566 passed。

## 已修改文件

- `src/agentscope_platform/application/{dag,dag_budget,dag_scheduler,dag_reuse,planning,async_task}.py`
- `src/agentscope_platform/domain/{agent,tool}.py`、`core/config.py`、`api/app.py`
- `src/agentscope_platform/infrastructure/agentscope/{runner,planner,reviewer,text_generator,closing_model,budget_model,dag_budget_model}.py`
- `tests/test_dag_{optimization,scheduling,budget,reuse,optimization_shadow}.py`
- `.env.example`、`compose.yml`、`README.md`、`docs/{dag-orchestration,async-orchestration}.md`
- `eval/baseline/dag-optimization-cases.jsonl`、`docs/delivery/dag-optimization/`、历史进度快照。

## 未完成

- S5 本地验证完成：569 passed / 89.66%，静态、契约、离线 Shadow、构建与 Compose PASS；剩余最终批次提交、main 推送及 CI 核验。
- S6 节点持久恢复为条件阶段：依赖 Java 中央任务服务新增持久化契约与真实恢复验收，不在本仓伪造实现。

## 当前问题

- 原有 `.engineering/remediation/`、`.workflow/` 未跟踪目录不属于本任务，保留。
- 真实模型/旧新服务双跑及跨服务恢复未验证；优化默认关闭，禁止据离线验证切生产流量。

## 下一步建议

1. 提交最终队列限制、对照测试和文档批次，正常合入并推送 main。
2. 核验远程 CI，写入交付结果；保留既有工作树和私有/忽略文件。

## 恢复 Prompt

读取 CODEX_PROGRESS.md 和 docs/delivery/dag-optimization/PLAN.md，从未完成切片继续，不重做基线，不修改无关文件，不等待继续。遵守默认关闭优化模式和无生产部署边界。
