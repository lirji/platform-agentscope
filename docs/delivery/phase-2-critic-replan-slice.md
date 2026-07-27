# Phase 2 Critic / Replan 切片

## 授权与范围

用户要求持续迁移 Phase 2。本切片承接同步 DAG 与 Planner，直接实施质量闭环。

本次交付：

- 对每轮 synthesis 进行 correctness、completeness、clarity 三维评审。
- 按旧默认权重 `0.5/0.35/0.15` 归一化聚合。
- 低于阈值时有限次数修订 DAG 并重新执行。
- 完整填充 `attempts`、`critique`、`aggregate` 和 `acceptedByThreshold`。
- 兼容旧部署默认：replan 开、阈值 0.75、最多重规划 1 次。
- Reviewer/Replanner 通过应用端口隔离，结构化模型类型留在基础设施层。

暂不包含异步进度事件、Process 和其他 sibling orchestrators。

## 验收标准

1. 首轮达标不重规划，响应包含一个 attempt。
2. 首轮不达标时修订计划并重新执行，最多执行配置的重规划次数。
3. 达到阈值时 `acceptedByThreshold=true`；耗尽次数仍不达标时为 false。
4. 零权重退化为三维等权平均，禁止 NaN。
5. Reviewer/Replanner 空或非法结构以脱敏 502 失败关闭，不把未评审答案标为达标。
6. 空修订计划返回旧兼容 `400 {"error":"replanner returned an empty plan"}`。
7. 取消和“模型未配置”继续向上传播；异常内容不进入响应或日志。
8. replan 关闭时保持前两个切片的 `attempts=[]` 行为。

## 回滚

可通过 `AGENT_DAG_REPLAN_ENABLED=false` 即时关闭质量闭环并保留 DAG 执行。edge 与旧服务
仍不修改。

## 交付验证

2026-07-27 已完成：

- Critic/Replanner 使用确定性 JSON、无工具、默认零重试；上一轮答案明确标记为不可信数据。
- 代码审查补充脱敏 502 映射，并禁止 Replanner 引入旧计划之外的工具或副作用。
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy src`
- `uv run python scripts/export_contracts.py --check`
- `uv run pytest --cov=agentscope_platform --cov-report=term-missing --cov-fail-under=80`
  （148 passed，覆盖率 92.17%）
- `uv run python scripts/shadow-smoke.py`（8 samples）
- `uv build`
- `docker compose -f compose.yml config`
- `uv sync --frozen --dev`

真实 Critic 评分与 replan 质量仍需在两端测试服务上使用
`eval/baseline/critic-cases.jsonl` 双跑，本次不伪造模型基线结论。
