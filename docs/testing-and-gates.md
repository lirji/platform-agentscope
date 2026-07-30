# 测试与发布门禁

## 1. 测试层次

### 单元测试

- DTO alias、空值和上限。
- JWT HS256/RS256、过期、伪造、非法 claims。
- ContextVar 绑定和清理。
- stop reason 映射。
- Tool Policy、超时和错误翻译。

### 契约测试

- `/agent/run` 请求/响应与旧 DTO 对齐。
- `/agent/v2/run` 默认关闭，开启时复用相同契约、安全和租户语义。
- `/agent/dag/run` 的 camelCase DTO、拓扑层级、任务顺序与旧错误形状。
- `/agent/dag/plan-run` 与 `/agent/analyst/run` 的规划类型、回退和上下文传播。
- critic 加权阈值、replan 次数、attempt 快照、耗尽未达标和关闭回滚。
- 错误码、content-type、空列表、字段名。
- SSE 事件名、顺序和重连。
- 五个 async submit 的 202/十字段快照、task kind 过滤、取消唯一终态，以及
  `agent.run` 执行 `ERROR` 的中央 `FAILED` 映射。
- 任意 UTF-8 chunk、CRLF、多行 data 和 Last-Event-ID 的 SSE 代理。
- token 截止、heartbeat 失败、shutdown、取消后 runner 吞取消的竞态。
- interop-service 作为 consumer 的兼容性。

### 集成测试

- LiteLLM stub。
- knowledge/analytics/order/workflow stub。
- 内部 JWT 跨跳。
- OTel trace 与租户归因。
- async-task 状态机。
- 中央 event journal 幂等/sequence/重启回放和 orphan allowlist。

### 评测

旧服务为 baseline，新服务为 candidate。比较：

- 任务完成率。
- 工具选择准确率。
- 工具参数正确率。
- grounded answer 比例。
- 关键案例的确定性业务事实证据（不保存答案）。
- 越权率。
- P50/P95/P99 延迟。
- token 与货币成本。
- 失败恢复与取消成功率。

## 2. 强制门禁

| 门禁 | 要求 |
|---|---|
| 静态检查 | Ruff、Mypy 全绿 |
| 单测 | 全绿；核心安全代码覆盖率目标 ≥ 90% |
| 契约 | 已迁端点 100% 通过 |
| 租户隔离 | 0 个跨租户读取 |
| 副作用 | 幂等与人工确认测试 100% |
| 评测 | 不低于批准的旧基线 |
| 可观测性 | trace、tenant、model、tokens、cost 可关联；两侧认证 metrics endpoint 可抓取 |
| 回滚 | 在测试环境完成一次切回旧服务 |

## 3. 非确定性验收

不比较最终文本是否逐字一致。优先比较：

- 是否调用正确工具。
- 是否使用当前租户数据。
- 是否引用真实结果。
- 是否遵守副作用约束。
- 是否在预算内完成。

需要文本质量时使用规则 grader 与模型 grader 组合，并保存 grader 版本和 prompt。

## 4. 本地命令

```bash
uv sync --frozen --dev
uv run python scripts/export_contracts.py --check
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest --cov=agentscope_platform --cov-report=term-missing --cov-fail-under=80
uv run python scripts/shadow-smoke.py
uv build
docker compose -f compose.yml config
```

Phase 1 的离线评测样例位于 `eval/baseline/readonly-cases.jsonl`。它验证案例结构、预期
工具、禁止副作用和已声明的答案事实证据。CI 使用 HTTPX 离线 stub 验证双跑门禁本身；
这不替代真实模型环境的新旧双跑。测试环境执行方法见
[Shadow 双跑指南](shadow-evaluation.md)。
候选服务侧启用和回滚方法见[候选路由指南](candidate-route.md)。2026-07-29 已完成本地
`acme` Casdoor 测试租户的实际 edge 切流/切回 Java 演练；生产环境仍须按同一门禁重新
取证并独立审批。

Phase 2 的只读 DAG 双跑样例位于 `eval/baseline/dag-cases.jsonl`。使用
`agentscope-dag-shadow-eval` 同时验证旧、新 `/agent/dag/run` 的响应契约、拓扑层级、
任务顺序、租户一致性和 synthesis 完成状态；报告不会保存任务结果或综合答案。

Phase 3 的异步场景清单位于 `eval/baseline/async-orchestration-cases.jsonl`。发布前必须在
双仓拓扑验证五类提交、取消、SSE 重连、Python SIGKILL 后 orphan 失败，以及 Process 写工具
调用为零；该外部故障注入不由离线单测伪装为已完成。

Planner 双跑样例位于 `eval/baseline/planner-cases.jsonl`。动态计划不要求新旧任务文本
逐字一致，但要求生成 1～6 个有效无环任务、响应顺序与拓扑一致；Analyst 用例额外要求
任务描述覆盖 `schema_explore` 和 `analytics_sql`。

Critic 双跑样例位于 `eval/baseline/critic-cases.jsonl`。门禁要求每个 attempt 有合法
三维评分和有限聚合值，且最后一个 attempt 与顶层最终结果一致。

Shadow v2 每次调用都有唯一 W3C trace。`agentscope-shadow-cost` 要求每个运行都有至少
一条 trace 账本记录并拒绝重复 `requestId`，从而把 Agent 多步及下游 embedding 合并到
同一次运行。账本契约和安全导出方法见 [Shadow 双跑指南](shadow-evaluation.md)。
