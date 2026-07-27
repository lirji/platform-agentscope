# DAG 多 Agent 编排

## 已迁能力

新服务提供同步 `POST /agent/dag/run`：

1. 校验目标、任务、任务上限、重复 ID 和循环依赖。
2. 按输入顺序生成稳定的拓扑层。
3. 层与层串行执行，同层 worker 受 `AGENT_DAG_MAX_PARALLEL_WORKERS` 限制并行执行。
4. 下游 worker 只接收其 `dependsOn` 中已经完成的直接上游结果。
5. 全部任务完成后，单独运行 synthesis Agent 生成最终答案。

每个 worker 和 synthesis 都使用入口验证后生成的同一不可变 `RunContext`。模型不能提供
或覆盖 tenant、user、scope、department、内部 token 和 trace。

同步规划入口：

- `/agent/dag/plan-run`：通用 Planner，按用户语言和问题维度生成 1～6 个任务。
- `/agent/analyst/run`：只读数据分析 Planner，优先 `schema_explore` 确认结构，再让
  `analytics_sql` 取数。

Planner 使用独立模型调用和 JSON 契约，不开放工具。空计划或结构/调用失败会回退为单任务；
模型未配置和客户端取消不会被回退掩盖。

## Critic / Replan

质量闭环默认与旧部署一致：

1. Critic 对 synthesis 的正确性、完整性、清晰度分别给出 0～1 分。
2. 按配置权重归一化聚合；权重总和为零时使用等权平均。
3. 聚合分低于阈值时，Replanner 根据上轮计划、答案和主要问题修订 DAG。
4. 达到阈值或用尽重规划次数后停止。每轮完整写入 `attempts`。

Reviewer/Replanner 不开放工具，不允许把上一轮答案当作指令，也不得引入原计划未包含的工具
或副作用。评审/重规划结构失败会失败关闭；空修订计划返回 400。可通过
`AGENT_DAG_REPLAN_ENABLED=false` 回滚到无评审执行。模型或结构失败返回不含底层异常的
502，并附带 traceId。

## 配置

| 环境变量 | 默认值 | 说明 |
|---|---:|---|
| `AGENT_DAG_MAX_TASKS` | 6 | 单次请求允许的最大任务数 |
| `AGENT_DAG_MAX_PARALLEL_WORKERS` | 8 | 当前进程所有 DAG 请求共享的 worker 并发上限 |
| `AGENT_DAG_REPLAN_ENABLED` | true | 开启 Critic/Replan |
| `AGENT_DAG_REPLAN_MAX_REPLANS` | 1 | 最多重规划次数 |
| `AGENT_DAG_REPLAN_THRESHOLD` | 0.75 | 接受阈值 |
| `AGENT_DAG_REPLAN_WEIGHT_CORRECTNESS` | 0.5 | 正确性权重 |
| `AGENT_DAG_REPLAN_WEIGHT_COMPLETENESS` | 0.35 | 完整性权重 |
| `AGENT_DAG_REPLAN_WEIGHT_CLARITY` | 0.15 | 清晰度权重 |
| `AGENT_PLANNER_MAX_TOKENS` | 1200 | Planner JSON 输出 token 上限 |
| `AGENT_PLANNER_TIMEOUT_SECONDS` | 30 | 单次 Planner 模型调用超时 |
| `AGENT_PLANNER_MAX_RETRIES` | 0 | Planner 模型自动重试次数 |

worker 的 AgentScope max steps、timeout、token budget 和 loop 策略继续使用现有 Agent
运行配置。worker 返回 `ERROR`、`TIMEOUT` 等结果时不会伪装成成功；结果会进入 synthesis，
由综合回答明确说明限制。未捕获的编排基础设施异常会使整个 HTTP 请求失败。

## 兼容行为

- 同层任务和最终 `taskResults` 保持原请求顺序。
- 未知依赖按旧 Java 行为从拓扑约束中忽略，但在结果 `dependsOn` 中保留。
- 首个切片未启用 critic/replan，响应固定为 `attempts=[]` 和
  `acceptedByThreshold=true`。
- `webhookUrl` 仅为 DTO 兼容保留，同步端点不会使用它。

## 旧/新结构双跑

启动旧、新服务并准备同租户短时内部 token：

```bash
export SHADOW_INTERNAL_TOKEN='replace-with-short-lived-test-token'

uv run agentscope-dag-shadow-eval \
  --legacy-url http://localhost:28085 \
  --candidate-url http://localhost:18085 \
  --output reports/dag-shadow.json
```

规划入口使用独立 suite：

```bash
uv run agentscope-dag-shadow-eval \
  --legacy-url http://localhost:28085 \
  --candidate-url http://localhost:18085 \
  --suite eval/baseline/planner-cases.jsonl \
  --output reports/planner-shadow.json
```

Critic attempt 证据使用：

```bash
uv run agentscope-dag-shadow-eval \
  --legacy-url http://localhost:28085 \
  --candidate-url http://localhost:18085 \
  --suite eval/baseline/critic-cases.jsonl \
  --output reports/critic-shadow.json
```

默认仅允许 localhost。远程测试环境必须显式使用 `--allow-remote-targets`，且不得指向生产
环境。凭据只从环境变量读取。报告仅包含 case ID、目标标签、状态码、延迟、通过状态和稳定
错误码，不保存 goal、worker 输出、synthesis 答案或 token。

## 回滚

当前切片不修改 edge。旧 `agent-service` 继续承载生产 `/agent/dag/**` 路由；停止对新服务
调用即可回滚。待 DAG 双跑达到旧基线并完成测试租户切流审批后，再单独修改 edge。

## 尚未迁移

- `/agent/dag/run/async`、`/agent/dag/plan-run/async`
- DAG `dag-*` 进度事件、SSE、取消和 webhook
- Analyst 异步入口、Voting、Reflexion、Prompt Chaining
