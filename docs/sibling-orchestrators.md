# Sibling Orchestrators

Phase 2 同步迁移新增三个只读编排入口，均要求与 `/agent/run` 相同的内部 JWT：

- `POST /agent/chain`：服务端预定义 Prompt Chain，步骤串行，gate 失败立即短路。
- `POST /agent/vote`：同题有界并行生成候选，使用 majority 或 synthesis 决策。
- `POST /agent/reflexive`：首答经 Critic 评分，未达阈值时有限次改进。

## 契约与安全边界

Chain 请求只接受 `input`。额外的 `steps` 字段会被忽略，调用方无法覆盖服务端 instruction。
每一步只接收上一步输出；支持 `gateMinLength`、`gateMustContain` 和 `gateMustMatch`。

Voting 的 `n` 必须在 1 到 `AGENT_VOTING_MAX_CANDIDATES` 之间，且在任何模型调用前校验。
majority 使用 trim + 大小写无关比较，同票时稳定选择先出现的答案；synthesis 的 agreement
返回 `null`，避免 Java `Double.NaN` 形成非标准 JSON。

Reflexion 复用 DAG Critic 的 correctness、completeness、clarity 三维结构化评分，但使用独立
权重和阈值。`AGENT_REFLEXION_MAX_ATTEMPTS` 沿用旧配置语义，表示首答之后允许的最大改进
次数，因此返回 attempt 总数最多为该值加一。

三个编排器均不注册工具，不执行业务写操作。运行上下文只用于身份、trace 和日志归因，
内部 token 不进入模型 prompt。模型故障返回脱敏 502；取消信号不转成成功响应。

## 配置

| 环境变量 | 默认值 | 说明 |
| --- | ---: | --- |
| `AGENT_CHAINING_STEPS_JSON` | translate + summarize | 服务端 Chain JSON 数组 |
| `AGENT_VOTING_N` | 3 | 未指定 `n` 时的候选数 |
| `AGENT_VOTING_MAX_CANDIDATES` | 10 | 单请求候选数上限 |
| `AGENT_VOTING_STRATEGY` | majority | `majority` 或 `synthesis` |
| `AGENT_VOTING_MIN_AGREEMENT` | 0.5 | majority confident 阈值 |
| `AGENT_SIBLING_MAX_PARALLEL_WORKERS` | 10 | 当前进程共享的 Voting 并发上限 |
| `AGENT_REFLEXION_THRESHOLD` | 0.75 | Reflexion 接受阈值 |
| `AGENT_REFLEXION_MAX_ATTEMPTS` | 2 | 首答后的最大改进次数 |
| `AGENT_REFLEXION_WEIGHT_CORRECTNESS` | 0.4 | 正确性权重 |
| `AGENT_REFLEXION_WEIGHT_COMPLETENESS` | 0.4 | 完整性权重 |
| `AGENT_REFLEXION_WEIGHT_CLARITY` | 0.2 | 清晰度权重 |

`eval/baseline/sibling-cases.jsonl` 固化只读回归输入。生产切流前仍需对旧、新服务执行真实
模型双跑并比较答案质量、P95 和成本。

## 未迁移

`/agent/reflexive/stream`、异步任务状态/SSE/webhook 和 Process 编排不属于本切片，继续由
旧 `agent-service` 承担。
