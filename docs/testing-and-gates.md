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
- 错误码、content-type、空列表、字段名。
- SSE 事件名、顺序和重连。
- interop-service 作为 consumer 的兼容性。

### 集成测试

- LiteLLM stub。
- knowledge/analytics/order/workflow stub。
- 内部 JWT 跨跳。
- OTel trace 与租户归因。
- async-task 状态机。

### 评测

旧服务为 baseline，新服务为 candidate。比较：

- 任务完成率。
- 工具选择准确率。
- 工具参数正确率。
- grounded answer 比例。
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
| 可观测性 | trace、tenant、model、tokens、cost 可关联 |
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

Phase 1 的离线评测样例位于 `eval/baseline/readonly-cases.jsonl`。它只验证案例结构、预期
工具和禁止副作用。CI 使用 HTTPX 离线 stub 验证双跑门禁本身；这不替代真实模型环境的
新旧双跑。测试环境执行方法见 [Shadow 双跑指南](shadow-evaluation.md)。
候选服务侧启用和回滚方法见[候选路由指南](candidate-route.md)；它不替代 edge 的实际
按租户切流演练。
