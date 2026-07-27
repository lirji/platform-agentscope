# Phase 2 Planner 与 Analyst 切片

## 授权与范围

用户于 2026-07-27 要求继续迁移 Phase 2。本切片承接已提交的同步 DAG 引擎，进入实施。

本次交付：

- 兼容 `POST /agent/dag/plan-run`。
- 兼容 `POST /agent/analyst/run`。
- 通用 Planner 与数据分析专用 Planner 使用不同、可测试的规划规则。
- Planner 通过应用端口接入，AgentScope/OpenAI 模型类型只存在于基础设施层。
- 规划结果复用现有 DAG 校验、分层并行、上游传播和 synthesis。
- 空计划或无效结构化输出安全回退为单任务；模型未配置仍返回 503。
- 补充认证、租户/trace、计划回退、契约与旧/新 Shadow 结构测试。

暂不包含：

- critic/replan。
- `/agent/dag/plan-run/async`、`/agent/analyst/run/async`。
- Process、Voting、Reflexion、Prompt Chaining。

## 验收标准

1. 通用 Planner 产生 1～6 个语言中立 DAG 任务。
2. Analyst Planner 明确“先探表后取数”，只规划现有只读
   `schema_explore`、`analytics_sql` 能力，不声称 `code_exec` 已迁移。
3. 两个端点均复用相同 DAG 引擎并保持 `AgentDagRunReply`。
4. 空 goal 返回旧兼容 `400 {"error":"goal is required"}`。
5. 空计划、无效 JSON、结构不合法或规划调用失败回退为 `t1=原始 goal`，并且不泄露异常内容。
6. 无模型配置返回 503，不回退到无法执行的 worker。
7. 同一请求从 Planner 到 worker/synthesis 都使用同一 tenant/user/scope/dept/trace。
8. 全量质量门禁通过，旧服务和 edge 不做切流变更。

## 回滚

新端点尚未接入 edge。回滚只需停止测试环境对新端点的调用，旧
`langchain4j-platform/agent-service` 继续承载生产流量。

## 交付验证

2026-07-27 已完成：

- 代码审查发现 AgentScope 2.0.5 `ChatResponse` 继承字典混入后，`finished_reason` 应从映射
  值读取；已使用该方式正确传播取消，不把取消误判为可回退的空计划。
- Planner 默认 `temperature=0`、JSON object、`max_retries=0`，无工具且不会把内部 token
  写入提示词。
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy src`
- `uv run python scripts/export_contracts.py --check`
- `uv run pytest --cov=agentscope_platform --cov-report=term-missing --cov-fail-under=80`
  （129 passed，覆盖率 91.82%）
- `uv run python scripts/shadow-smoke.py`（8 samples）
- `uv build`
- `docker compose -f compose.yml config`
- `uv sync --frozen --dev`

真实通用/Analyst Planner 的旧新双跑需要测试模型和两端服务。本切片只确认专用 suite 与
门禁可执行，不伪造真实模型质量结论。
