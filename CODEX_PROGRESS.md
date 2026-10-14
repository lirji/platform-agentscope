# Codex Progress

## 任务目标

优化多步骤 DAG 的失败传播、能力隔离、调度、预算及有条件结果复用；保留旧接口和可回退路径。
用户授权出计划后连续实施，正常分支提交、合入并推送 main；不包含生产部署。

## 已完成

- 计划与报告：`docs/delivery/dag-optimization/{PLAN,PROJECT_REFACTORING_REPORT,RESULT}.md`。
- S1：失败依赖跳过、状态化证据、无工具汇总、服务端能力限制、异步非 DONE 综合结果写 FAILED。
- S2：依赖就绪调度、通用/Process 共享并发、租户限额、等待队列上限、真实进度和取消收敛。
- S3：规划到评审共享截止时间；实际模型调用前限制次数与保守 token 预留，并保留中央租户配额。
- S4：基于节点证据评审；确定性失败门禁；同次请求内 TTL 有界的只读结果复用与下游失效。
- S5：569 tests / 89.66% 覆盖率；Ruff/format/Mypy、契约、离线 Shadow、构建和 Compose PASS。
- 五个逻辑提交 8545684、49a251d、36db8d6、4b506f8、82651a7 已正常合入推送 origin/main。
- 源码 `82651a7` 的 CI 38529981435 SUCCESS（含镜像扫描）：https://github.com/lirji/platform-agentscope/actions/runs/38529981435 。收尾文档不改变已验证源码。
- 优化默认关闭；未执行部署、付费模型验证或生产流量切换。

## 已修改文件

- `src/agentscope_platform/application/{dag,dag_budget,dag_scheduler,dag_reuse,planning,async_task}.py`
- `src/agentscope_platform/domain/{agent,tool}.py`、`core/config.py`、`api/app.py`
- `src/agentscope_platform/infrastructure/agentscope/{runner,planner,reviewer,text_generator,closing_model,budget_model,dag_budget_model}.py`
- `tests/test_dag_{optimization,scheduling,budget,reuse,optimization_shadow}.py`
- `.env.example`、`compose.yml`、`README.md`、`docs/{dag-orchestration,async-orchestration}.md`
- `eval/baseline/dag-optimization-cases.jsonl`、`docs/delivery/dag-optimization/`、历史进度快照。

## 未完成

- 本轮本仓实施 S1–S5 完成。
- S6 节点持久恢复保持 CONDITIONAL，设计见 `RECOVERY_DESIGN.md`；需要 Java 中央任务服务版本化契约和真实恢复演练，不在本仓伪造实现。
- 运行中 Java/Python 真模型双跑、生产灰度及性能实测未执行，不作为本轮离线验证的已通过项。

## 当前问题

- Code Hygiene 自动发现未识别 Ruff formatter，状态为 IMPLEMENTATION_COMPLETE_WITH_LIMITATIONS；实际 `uv run ruff format --check .` 已通过。
- 历史 `.workflow/`、`.engineering/remediation/` 和私有/忽略文件保留；未新建或清理工作树。
- 既有 `~/.local/share/git-worktrees/agentscope-platform/cross-runtime-verification` 为 detached HEAD 22ba8db，保留其历史用途；原项目目录正常交付。

## 下一步建议

1. 有真实评测环境后，使用 `eval/baseline/dag-optimization-cases.jsonl` 做 Java/Python 双跑再评估启用优化模式。
2. 只有节点级恢复需求、中央契约和隔离演练条件齐备后再启动 S6，不重做已完成切片。

## 恢复 Prompt

读取 CODEX_PROGRESS.md 和 docs/delivery/dag-optimization/PLAN.md。本轮本仓 S1–S5 已实现验证并交付；不要重复实施或擅自开启生产优化。S6 按 RECOVERY_DESIGN.md 的条件另行推进。保留历史工作树与私有文件。
