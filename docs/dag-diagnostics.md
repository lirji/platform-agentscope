# DAG 运行诊断与成本归因

应用默认开启 `AGENT_DAG_DIAGNOSTICS_ENABLED=true`，覆盖 DAG、plan-run、Analyst、Process 的同步/异步执行，以及兼容/优化模式。关闭开关即可停止新诊断。旧 HTTP 响应、既有进度事件字段与中央预算结算保持原语义。

## 查看方式

- 同步请求：按响应头 `X-Trace-Id` 在 `dag_diagnostics` 结构化日志中检索。
- 异步请求：沿用 `/agent/tasks/{taskId}/stream` SSE，新增 `dag-diagnostic-model`、`dag-diagnostic-operation`、`dag-diagnostic-summary`。外层仍为 `{taskId,event,data,ts}`；诊断 DTO 在 `data` 内，`schemaVersion=1`。
- 先升级中央 async-task-service 的三个事件名允许列表，再升级 Python；旧中央会拒绝这些事件，Python记录投递故障，业务执行继续。没有数据库迁移。
- 任务查询/事件重放继续沿用原身份隔离、租约和保留策略。未启用异步 progress 时只输出日志/指标。

`executionId` 是一次进程执行片段；同一异步任务接管后产生新 executionId。`operationId` 关联角色、轮次和节点，`callId` 标识一个实际 SDK 模型调用。使用事件重放时按 callId 去重，不能重复累加相同事件。

诊断不包含 goal、提示词、答案、工具参数/结果、凭据或异常正文。日志含 trace/tenant/node 等关联标识，应沿用项目日志访问与保留控制。

## 运行解释

操作事件按 `planner / worker / synthesis / critic / replanner` 归属，包含：

- `durationMs`：操作总耗时，包含编排/检查点开销。
- `queueMs`：worker 等待容量槽位的时间；即使取消或拒绝也记录已等待时长。
- `executionMs`：worker 在 runner 内执行的耗时，包括模型与工具；其他角色使用 durationMs。复用/跳过节点为零。
- `status`：实际终止状态；摘要 status 对齐最终 DAG 综合状态，acceptedByThreshold 独立表示质量是否接受。
- `reason`：`replan_reused`、`checkpoint_reused`、`reuse_input_changed`、`reuse_expired`、`previous_failed`、`non_reusable_tools`、`reuse_disabled`、`no_reusable_result`、`checkpoint_incomplete`、`checkpoint_not_reusable`、`checkpoint_input_changed`、`upstream_failed` 或 `executed`。

每轮 `criticalPaths` 为按**已观测 worker executionMs 加权**的最长依赖路径；排队、Planner、汇总和评审单独看。它不是整次请求墙钟耗时，也不跨接管拼接。`complete=false` 表示该轮存在未观测节点；被复用节点执行耗时为零。

## 用量与费用

实际模型边界覆盖所有五类角色，预算拒绝发生在调用前时不会产生“已调用”记录。流式只读取完整终帧 usage；中间累计快照不相加。异常、取消、缺失/非法 usage 为 null。复用节点不会新增模型调用记录。

启用费用估算需要配置：

```dotenv
AGENT_DAG_COST_RATES_CONFIGURED=true
AGENT_INPUT_COST_USD_PER_MILLION_TOKENS=<当前模型输入单价>
AGENT_OUTPUT_COST_USD_PER_MILLION_TOKENS=<当前模型输出单价>
```

默认 `AGENT_DAG_COST_RATES_CONFIGURED=false`，费用为未知。显式启用后零费率代表已知免费；费率快照随模型事件记录。金额以 Decimal 计算并序列化为十进制字符串，币种 USD。

`estimatedCostUsd = (inputTokens × inputRatePerMillion + outputTokens × outputRatePerMillion) / 1000000`。

这是按部署配置的统一输入/输出费率估算，未单独核算缓存 token、阶梯定价、隐藏供应商重试或额外媒体费，不是供应商账单。预算预留量继续仅用于准入，绝不作为实际 token。可按角色/节点/轮次汇总 model 事件；不要把既有 `agent_run` 成本和 `agent_dag` 成本相加，两者有重叠。

摘要的 `knownInputTokens / knownOutputTokens / knownEstimatedCostUsd` 仅累计有证据的部分；同时检查 `unknownUsageCalls / unpricedCalls`。任一未知时 `estimatedCostUsd=null`，不可展示成完整总费用。

恢复片段设置 `resumed=true / historyComplete=false`，总费用保持 null。崩溃可能发生于提供商计费之后、日志/事件记录之前；已有检查点不能补齐这一未知费用。跨片段重做的模型调用是新调用，可能产生新费用。任务总恢复次数可依据已收到摘要中的 resumed 片段统计，但缺失片段时只能视为已观测次数。

## 指标与故障边界

`/metrics` 新增：

- `agent_dag_model_calls_total{role,status}`、`agent_dag_model_tokens_total{role,direction}`
- `agent_dag_usage_unknown_total{role}`、`agent_dag_price_unknown_total{role}`、`agent_dag_estimated_cost_usd_total{role}`
- `agent_dag_operation_duration_ms{role,status}`、`agent_dag_worker_queue_ms{status}`
- `agent_dag_operations_total{role,status,reason}`、`agent_dag_segments_total{status,resumed}`
- `agent_dag_diagnostic_delivery_failures_total`、`agent_dag_diagnostic_dropped_records_total`

指标不包含租户、任务、节点、trace 或模型提供商任意字符串标签。排查具体任务使用结构化日志/授权事件。

诊断使用最多256条待投递事件和256个节点摘要；单次中央投递与片段结束排空各有250ms上限，摘要另有250ms投递上限。模型日志/指标立即记录，异步中央事件经有界后台队列发送。超限计入 droppedRecords，投递失败计入 deliveryFailures，并产生固定告警日志。摘要自身投递失败只能通过本地告警发现，不能保证收到失败摘要。

诊断是尽力观测，不是审计或计费权威；故障时保持业务执行，但明确披露记录缺口。取消优先结束工作，不为诊断网络 IO 延迟取消；持久任务临近绝对截止时间时跳过诊断 IO。日志输出器采用现有同步机制，其运行配置仍应避免阻塞。

## 回滚与验证

设置 `AGENT_DAG_DIAGNOSTICS_ENABLED=false`；无需删除事件或改数据库。中央允许列表扩展可以保留。若回滚中央到旧版本，应先停用 Python 诊断，避免拒绝事件告警。

测试与交付记录见 [实施计划](delivery/dag-diagnostics/PLAN.md)。离线模型适配器测试验证用量归因和行为兼容，不表示真实模型质量、账单或生产容量已经验收。
