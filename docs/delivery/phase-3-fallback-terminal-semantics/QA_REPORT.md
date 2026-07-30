# Phase 3 Fallback And Terminal Semantics QA Report

## Conclusion

两个 P1 均已修复并通过 localhost 完整拓扑验证。fallback 真实请求成功；受控模型错误
不再产生中央伪成功。候选服务已恢复为正常 `chat-default`，全栈继续运行。

## Results

| Check | Result | Evidence |
| --- | --- | --- |
| Focused regression | pass | 12 async manager/application/API tests |
| Python repository gates | pass | 204 tests, 88.92% coverage, Ruff, format, mypy |
| Contracts/shadow/build | pass | snapshots stable, 8 samples, wheel/sdist built |
| Compose configuration | pass | both repositories parse |
| Fallback semantic probe | pass | `SUCCEEDED`, `DONE`, `FALLBACK_OK` |
| Failure terminal probe | pass | `FAILED`, null result, stable error code |
| Runtime topology | pass | 25/25 running, no unhealthy/restarting |
| Health/readiness/frontend | pass | all selected endpoints return 200 |
| Metrics authentication | pass | anonymous 401, authenticated 200 on both services |

## Defect Disposition

- `FULLSTACK-QA-001`: resolved. `chat-default-fallback` now uses Ollama's
  OpenAI-compatible `/v1` endpoint through LiteLLM.
- `FULLSTACK-QA-002`: resolved. The async agent route uses an application-level execution
  boundary that rejects `stopReason=ERROR`; `AsyncTaskManager` writes central `FAILED`.

## Compatibility And Security

- 同步 `/agent/run` 继续返回兼容的 `stopReason=ERROR`；自动化测试显式覆盖。
- 对外 DTO 和 OpenAPI snapshot 未变化。
- 中央失败结果不包含模型原始异常，只返回稳定错误码。
- 测试 token 未写入文件或报告。
- 未调用付费模型，未修改生产路由。

## Residual Risks

- 本地 `llama3.1` 与主模型在工具调用、JSON schema、上下文窗和质量上不等价。
- 本次证明 fallback 的代表性 AgentScope 请求可用，不等于生产质量或容量门禁通过。
- 生产灰度仍需真实新旧双跑、成本/延迟基线与独立审批。

详细机器可读证据见
`../../qa/phase-3-fallback-terminal-semantics-0729-1507/results.json`。
