# Phase 2 DAG 编排首个垂直切片

## 授权与范围

用户于 2026-07-27 明确要求继续在新项目迁移 Phase 2 多 Agent 编排。本切片据此进入实施，
无需再次等待确认。

本次交付：

- 兼容 `POST /agent/dag/run` 的语言中立请求/响应契约。
- 校验任务上限、重复 ID 和循环依赖。
- 按拓扑层顺序执行、同层 worker 有界并发。
- 将直接依赖的结果传给下游 worker，最后执行 synthesis。
- 所有 worker 和 synthesis 显式复用同一 `RunContext`，覆盖并发跨租户隔离测试。
- 生成 OpenAPI/JSON Schema，补充旧/新双跑评测案例与回滚说明。

暂不包含：

- 模型自动规划 `/agent/dag/plan-run`。
- critic/replan、Analyst Planner、Voting、Reflexion、Prompt Chaining。
- async-task、SSE、webhook。
- 写工具、副作用工具和 edge 切流。

## 验收标准

1. 链式与菱形 DAG 的层级、任务顺序和上游结果传播正确。
2. 同层任务实际并发，且不混淆 tenant、user、scope、department、token 或 trace。
3. 空任务、任务超限、重复 ID、循环依赖返回稳定的 `400 {"error": ...}`。
4. 为兼容旧服务，未知依赖不阻断执行；仅存在于契约回显，不作为可用上游结果。
5. worker 返回 `ERROR` 时保留任务结果并继续 synthesis；未捕获的基础设施异常整体失败。
6. `/agent/dag/run` 必须通过内部 JWT；无 token 或伪造 token 均拒绝。
7. Ruff、格式、Mypy、Pytest、契约快照、离线评测样例和构建门禁全部通过。

## 风险与回滚

- 并发调用共享 runner 的风险通过每次运行新建 Agent、不可变 `RunContext` 和并发隔离测试控制。
- 旧实现会忽略未知依赖；本切片保留该行为，后续如要改为严格校验必须做版本化。
- 本切片不会修改 edge 或旧 `langchain4j-platform`。回滚方式是停止调用新端点，旧服务继续
  处理现有 `/agent/dag/**` 流量。
- `attempts` 暂返回空数组、`acceptedByThreshold=true`；critic/replan 落地后再填充尝试记录。

## 后续切片

1. `/agent/dag/plan-run` 与 Analyst Planner。
2. critic/replan 及旧基线评测。
3. Voting、Reflexion、Prompt Chaining。
4. Phase 3 async-task、SSE 与 webhook。

## 交付验证

2026-07-27 已完成：

- 代码审查：修复并发 worker 异常被 `ExceptionGroup` 包装后无法复用既有 503 映射的问题；
  任一未捕获异常现在会取消同层其余任务，并保留原始异常。
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy src`
- `uv run python scripts/export_contracts.py --check`
- `uv run pytest --cov=agentscope_platform --cov-report=term-missing --cov-fail-under=80`
  （106 passed，覆盖率 91.40%）
- `uv run python scripts/shadow-smoke.py`（8 samples）
- `uv build`
- `docker compose -f compose.yml config`

现有 CI 已自动覆盖新增契约与测试，无需新增并行流水线。真实旧/新 DAG 双跑需要启动两端
服务和本地/测试依赖后执行 `agentscope-dag-shadow-eval`，不在本次离线环境中伪造通过结论。
