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

该工具不会改变 edge 路由，也不会把完整回答、observation、请求 token 或响应正文写入报告。

## 安全边界

- 默认只接受 `localhost`、环回地址和 `*.localhost`。
- 远程测试地址必须显式添加 `--allow-remote-targets`；不得指向生产环境。
- URL 禁止包含用户名、密码、query 或 fragment。
- Token 只从进程环境读取，不提供命令行 token 参数，避免进入 shell history/process list。
- 不自动重试，防止非确定性调用被静默放大。
- 当前 suite 只允许 `readOnly=true`。

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
