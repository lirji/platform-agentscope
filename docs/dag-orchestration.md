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

## 配置

| 环境变量 | 默认值 | 说明 |
|---|---:|---|
| `AGENT_DAG_MAX_TASKS` | 6 | 单次请求允许的最大任务数 |
| `AGENT_DAG_MAX_PARALLEL_WORKERS` | 8 | 当前进程所有 DAG 请求共享的 worker 并发上限 |

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

默认仅允许 localhost。远程测试环境必须显式使用 `--allow-remote-targets`，且不得指向生产
环境。凭据只从环境变量读取。报告仅包含 case ID、目标标签、状态码、延迟、通过状态和稳定
错误码，不保存 goal、worker 输出、synthesis 答案或 token。

## 回滚

当前切片不修改 edge。旧 `agent-service` 继续承载生产 `/agent/dag/**` 路由；停止对新服务
调用即可回滚。待 DAG 双跑达到旧基线并完成测试租户切流审批后，再单独修改 edge。

## 尚未迁移

- `/agent/dag/plan-run`
- critic/replan 与 attempts 评分记录
- `/agent/dag/run/async`、`/agent/dag/plan-run/async`
- DAG `dag-*` 进度事件、SSE、取消和 webhook
- Analyst Planner、Voting、Reflexion、Prompt Chaining
