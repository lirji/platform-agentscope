# DAG 多 Agent 编排

## 已迁能力

新服务提供同步 `POST /agent/dag/run`。默认兼容模式执行如下：

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
| `AGENT_DAG_MAX_PARALLEL_WORKERS` | 8 | 兼容模式每个 DAG service 的并发上限；优化模式通用/Process 共享 |
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

- 同层按原请求顺序排列；最终 `taskResults` 按稳定拓扑层顺序返回。
- 未知依赖按旧 Java 行为从拓扑约束中忽略，但在结果 `dependsOn` 中保留。
- 兼容模式关闭 critic/replan 时返回 `attempts=[]` 和 `acceptedByThreshold=true`。
- `webhookUrl` 仅为 DTO 兼容保留，同步端点不会使用它。

## 可选优化模式

通过 `AGENT_DAG_OPTIMIZATION_ENABLED=true` 显式启用；默认 false 保留旧执行路径。HTTP/JSON 字段不变，但以下语义有意变化：

- 未知依赖返回 400；失败/超时节点的下游为 `stopReason=SKIPPED`，不运行模型。综合结果为 `PARTIAL`，`acceptedByThreshold=false`，异步写中央 FAILED。
- 依赖完成即可启动后继，无整层屏障；响应仍按稳定拓扑顺序。`dag-worker-queued` 表示等待，`dag-worker-start` 表示已获得槽位，`dag-worker-result` 立即报告完成。level 事件是拓扑分组，组之间可重叠。
- worker 从服务端获得固定只读能力集合，ToolPolicy 同时执行允许列表及原有权限。模型不能扩大列表；通用模式不开放 MCP、Sandbox 或写工具。Process 使用 workflow/RAG 和已有开关、确认、幂等约束下的 refund_start；Process 不重规划。
- synthesis 使用无工具 TextGenerator。Critic/Replanner 接收节点状态与工具观察，必需节点失败直接零分，不能由模型高分覆盖。
- 仅同一次请求、TTL 内、输入未变的成功节点可以复用；只允许无工具推理或 rag_search/schema_explore。时钟、订单/流程状态、analytics_sql、未知及写工具不复用。上游重跑产生新的执行版本，使下游失效。复用发 `dag-worker-reused`，不伪造 worker-start。
- 规划、排队、执行、汇总、评审共享总截止时间。真实模型调用前检查 DAG 预算，再检查既有 Java 租户日配额。预算按 UTF-8 输入字节、输出上限和保守协议/媒体余量累计预留，**不是精确计费 token**；未知 usage、失败不返还本次预算。优化模式要求模型/Planner retries=0，提供商或网关自身的隐藏重试不计为额外 SDK 调用。
- 输入证据超限失败关闭，不静默截断事实。简单单任务仍保留汇总，避免直接返回 worker 的子任务文案改变最终回答契约。

| 优化配置 | 默认值 | 作用 |
|---|---:|---|
| `AGENT_DAG_OPTIMIZATION_ENABLED` | false | 显式启用新语义 |
| `AGENT_DAG_TENANT_MAX_WORKERS` | 2 | 每进程每租户 worker 上限 |
| `AGENT_DAG_MAX_INFLIGHT_WORKERS` | 128 | 全部运行及等待 worker 上限 |
| `AGENT_DAG_TENANT_MAX_INFLIGHT_WORKERS` | 32 | 单租户运行及等待 worker 上限 |
| `AGENT_DAG_TIMEOUT_SECONDS` | 300 | 覆盖规划到评审，且不晚于 token 到期前 2 秒 |
| `AGENT_DAG_MAX_MODEL_CALLS` | 64 | 整次执行真实模型调用数上限 |
| `AGENT_DAG_MAX_RESERVED_TOKENS` | 240000 | 保守预留量上限，不表示账单 |
| `AGENT_DAG_MAX_EVIDENCE_CHARS` | 48000 | 模型证据输入字符上限 |
| `AGENT_DAG_RESULT_REUSE_TTL_SECONDS` | 30 | 只读证据复用时长，0 禁用 |

超限分别为 HTTP 429 `AGENT_DAG_BUDGET_EXCEEDED`、504 `AGENT_DAG_DEADLINE_EXCEEDED`、503 `AGENT_DAG_CAPACITY_EXCEEDED`，都携带 traceId。并发/排队限制是每进程的 DAG worker 限制，不是所有端点或跨副本全局配额；模型总预算覆盖本 DAG 的所有模型角色。模型事实正确性仍需业务评测，代码门禁只能确定节点执行状态。

轮内复用不等于持久恢复。节点恢复的中央契约、失败窗口及演练前置条件见 [恢复设计](delivery/dag-optimization/RECOVERY_DESIGN.md)。

关闭优化开关即可回退调度/质量/复用新语义；已经发生的外部写入不会被回退撤销。异步对非 DONE 综合结果记为 FAILED 是独立正确性修复，完整回退需恢复上一应用版本。无需数据库迁移或删除任何任务数据。

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

## 异步及其他编排

`/agent/dag/run/async`、`/agent/dag/plan-run/async`、Analyst 异步入口以及 DAG 进度、SSE、取消和中央 webhook 已实现，见 [异步手册](async-orchestration.md)。Voting、Reflexion、Prompt Chaining 见 [其他编排](sibling-orchestrators.md)。

优化模式新增只读 suite 为 `eval/baseline/dag-optimization-cases.jsonl`，可用同一 shadow CLI 的 `--suite` 参数选择。离线测试只证明结构和确定性执行行为，不替代真实模型质量及 Java/Python 双跑；未通过生产门禁前不得切换生产 AGENT_URI。
