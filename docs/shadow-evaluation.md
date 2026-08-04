# Shadow 双跑指南

## 目标

`agentscope-shadow-eval` 用同一组只读案例依次调用旧 Java `agent-service` 和新的
`agentscope-platform`，验证：

- `/agent/run` 响应契约；
- `DONE` 完成率和非空最终答案；
- 预期工具是否按声明顺序调用；
- 是否执行禁止工具；
- 通过率、工具准确率和 P95 延迟是否相对旧服务回归；
- candidate 是否达到绝对最低门槛。
- 可选的答案业务事实证据是否满足。
- 显式启用时，开放式 RAG/Analytics 回答的 Judge 分数是否达标且不相对旧服务回归。
- 数据集版本、prompt/model/toolset 版本和回放来源是否一致。

该工具不会改变 edge 路由，也不会把完整回答、observation、请求 token 或响应正文写入报告。

## 安全边界

- 默认只接受 `localhost`、环回地址和 `*.localhost`。
- 远程测试地址必须显式添加 `--allow-remote-targets`；不得指向生产环境。
- URL 禁止包含用户名、密码、query 或 fragment。
- Token 只从进程环境读取，不提供命令行 token 参数，避免进入 shell history/process list。
- 不自动重试，防止非确定性调用被静默放大。
- 当前 suite 只允许 `readOnly=true`。
- 生产发布门禁使用版本化 `--dataset` 和 `--require-version-metadata`；目标版本批内漂移直接失败。
- Judge 默认关闭；远程 Judge 必须单独添加 `--allow-remote-judge`，不能借用目标地址的
  远程授权。
- Judge API Key 只从 `SHADOW_JUDGE_API_KEY` 读取。报告不保存回答或 Judge prompt，但评分
  必须把完整回答临时发送给 Judge；远程提供商或网关可能按其策略记录请求，启用前必须完成
  数据分级和留存审查。

## 本地/测试环境执行

先启动旧服务、新服务和它们依赖的 LiteLLM、knowledge、analytics、order 服务，然后准备同一
租户的短时内部 token：

```bash
export SHADOW_INTERNAL_TOKEN='replace-with-short-lived-test-token'

uv run agentscope-shadow-eval \
  --legacy-url http://localhost:28085 \
  --candidate-url http://localhost:18085 \
  --runs 3 \
  --output reports/readonly-shadow.json
```

测试身份必须能读取 suite 对应的种子数据。例如仓库默认订单 101 属于 `tenantA`；使用
其他租户会因租户隔离得到 404。关键案例应配置下述答案证据；其他开放式答案仍应结合
语义 grader。

## 答案证据

用例可以声明不落回答原文的确定性断言：

```json
{
  "answerAssertions": {
    "allOf": ["101", "已支付", "张三", "2026-05-03"],
    "anyOf": [["1200", "1,200"]],
    "noneOf": ["未找到订单", "查询失败"]
  }
}
```

- `allOf`：每个词都必须出现；
- `anyOf`：每个内层数组至少命中一个等价表达；
- `noneOf`：所有词都不得出现。

比较使用大小写无关包含匹配。报告只记录 `answerPassed`/`answerScore`，不保存回答、命中
片段或断言文本。默认 candidate 答案通过率不得低于 80%，且不得比 legacy 低超过 5 个
百分点，可用 `--min-answer-pass-rate` 和 `--answer-pass-rate-tolerance` 调整。

## 开放式答案 Judge

用例可以声明开放式标准和单案例最低分（默认 0.7，与 retained Java eval-service
一致）：

```json
{
  "judgeCriteria": "回答必须基于查询结果说明趋势；数据不足时明确说明限制；不得编造。",
  "judgeMinScore": 0.7
}
```

默认运行会跳过这些标准，保持原双跑行为。只在本地或明确命名的测试环境显式启用：

```bash
export SHADOW_JUDGE_API_KEY='replace-with-short-lived-test-key'

uv run agentscope-shadow-eval \
  --legacy-url http://localhost:28085 \
  --candidate-url http://localhost:18085 \
  --judge-enabled \
  --judge-base-url http://localhost:4000/v1 \
  --judge-model chat-default \
  --runs 3 \
  --output reports/readonly-shadow-judged.json
```

Judge 使用 `temperature=0`、JSON object 响应和独立 trace，每个答案只请求一次，不自动
重试。回答被标记为不可信数据，prompt 明确禁止执行回答中的指令。低于单案例阈值时记录
`JUDGE_SCORE_BELOW_THRESHOLD`；网络、HTTP 或响应契约错误统一记录 `JUDGE_ERROR` 并按
零分 fail-closed。报告仅保留：

- 每次运行的 `judgeEvaluated`、`judgePassed`、`judgeScore`；
- 每个目标的 Judge 样本数、通过率和平均分；
- 稳定错误码和门禁回归原因。

不保留标准、prompt、回答或理由。Judge 耗时不计入 Agent 目标 P95，Judge 独立 trace 也
不进入 `agentscope-shadow-cost` 的 Agent 成本归因；需要单独评估 Judge 的延迟和费用。
默认 candidate Judge 通过率至少 80%，不得比 legacy 低超过 5 个百分点，平均分也不得
低超过 0.05。对应参数为 `--min-judge-pass-rate`、
`--judge-pass-rate-tolerance` 和 `--judge-score-tolerance`。

当一端没有完成标准用例、另一端已经评分时，门禁会以缺失可比评分拒绝，不能把“未评分”
当作满分。远程 Judge 还需要 `--allow-remote-judge`；不要指向生产 Judge 或在未经批准时
发送含敏感业务数据的回答。

如果两端使用不同 token：

```bash
export SHADOW_LEGACY_TOKEN='replace-with-legacy-test-token'
export SHADOW_CANDIDATE_TOKEN='replace-with-candidate-test-token'
```

若经测试网关使用其他认证头，可以分别设置 `--legacy-auth-header` 和
`--candidate-auth-header`。远程测试目标还必须显式加 `--allow-remote-targets`。

退出码：

- `0`：门禁通过；
- `1`：指标回归、目标不可达或目标响应错误；
- `2`：suite、URL、阈值或报告配置错误。

## 默认门禁

| 指标 | 默认值 |
| --- | --- |
| candidate 最低通过率 | 0.80 |
| candidate 最低完成率 | 0.80 |
| candidate 最低工具准确率 | 0.80 |
| 相对旧服务通过率容差 | 0.05 |
| 相对旧服务完成率容差 | 0.05 |
| 相对旧服务工具准确率容差 | 0.05 |
| candidate Judge 最低通过率（启用时） | 0.80 |
| 相对旧服务 Judge 通过率容差 | 0.05 |
| 相对旧服务 Judge 平均分容差 | 0.05 |
| candidate P95 上限 | `legacy P95 × 1.5 + 250ms` |
| candidate 禁止工具 | 0 次 |
| 两端契约错误 | 0 次 |

所有阈值都有对应 CLI 参数。修改阈值前应保存评测报告并记录审批理由，不能为了让失败构建
变绿而临时放宽。

## 报告

默认输出 `reports/shadow-evaluation.json`，目录已加入 `.gitignore`。报告只包含：

- suite、生成时间和重复次数；
- 聚合指标、停止原因计数和回归理由；
- 每次调用的 case ID、目标标签、状态码、耗时、工具名和脱敏错误码。

报告不包含目标 URL、token、goal、最终答案、actionInput 或 observation。
单个目标响应超过 2 MB 会以 `RESPONSE_TOO_LARGE` 失败，不进入契约解析。
Shadow v4 绑定 dataset ID/version、可选 replay report 摘要和每次目标运行的版本摘要；未启用
Judge 时 `judgeEvaluated=false` 且分数为空。数据集迁移、对抗集和反馈导入见
[运行版本与评测数据闭环](evaluation-versioning.md)。

## 成本归因

若 LiteLLM 使用 `PLATFORM_GATEWAY_TENANT_ATTRIBUTION=none`，新旧请求及 RAG embedding
记录会混在同一时间窗，不能按时间窗口做可信比较。Shadow v2 为每次目标调用生成唯一
`X-Trace-Id` 和 W3C `traceparent`，并把 trace ID 写入脱敏报告。测试栈应开启：

```bash
MANAGEMENT_TRACING_ENABLED=true   # retained Java services
OTEL_ENABLED=true                 # candidate
```

从 Jaeger 的对应 trace 中只提取 `litellm_request` span 的 `gen_ai.response.id`，再按该 ID
关联 LiteLLM `LiteLLM_SpendLogs.request_id`。导出以下 JSONL 安全账本，不要导出 span 的
prompt/completion tag、数据库 `messages`/`response` 或 API key：

```json
{"traceId":"32-hex-trace","requestId":"chatcmpl-unique","inputTokens":100,"outputTokens":20,"costUsd":"0.00012"}
```

一个 trace 可有多行，覆盖 Agent 多步调用和 RAG embedding。`requestId` 必须全局唯一，
避免重复导出导致成本翻倍。随后执行：

```bash
uv run agentscope-shadow-cost \
  --shadow-report reports/readonly-shadow.json \
  --ledger reports/readonly-cost-ledger.jsonl \
  --output reports/readonly-cost.json
```

默认 candidate 成本上限为 `legacy × 1.25 + 0.001 USD`。任一运行没有账本记录即失败；
CLI 退出码仍为 0=通过、1=门禁失败、2=输入/配置错误。成本报告只含 trace、token、USD
汇总和门禁结果。LiteLLM 对本地 Ollama 的 `spend` 是按模型价目计算的估算值，不是外部
账单。

## CI 与真实双跑

CI 执行：

```bash
uv run python scripts/shadow-smoke.py
```

该命令使用内存 HTTP stub，证明门禁和案例接线可运行，不证明模型质量。真实双跑只应在明确
命名的测试环境执行。通过后还需要记录成本数据和一次路由回滚演练，才能批准 edge 灰度。

Phase 2 的 DAG 使用独立的 `agentscope-dag-shadow-eval`。它比较响应契约、拓扑层级、
任务顺序、租户一致性和 synthesis 完成状态，不把 worker/synthesis 文本写入报告。案例和
运行方法见 [DAG 编排指南](dag-orchestration.md)。同一 CLI 使用
`eval/baseline/planner-cases.jsonl` 时验证通用 Planner 和 Analyst Planner；动态计划不做
逐字比较，只校验有效拓扑及声明的 Planner 约束。

`eval/baseline/critic-cases.jsonl` 验证 Critic attempt 证据：评分范围、聚合值有限性以及
最后一轮与顶层最终结果的一致性。报告仍不保存答案、任务结果或 critique 文本。
