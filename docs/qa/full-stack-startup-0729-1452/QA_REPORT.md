# Full-Stack Startup QA Report

## Conclusion

The full localhost topology is running and suitable for continued integration testing.
Java Compose reports 25/25 services running with no unhealthy or restarting container.
AgentScope is running separately on `127.0.0.1:18085` with the intended
`chat-default` LiteLLM configuration and async execution enabled.

Startup and infrastructure checks pass. Two model-failure semantics defects were confirmed
during the no-cost fallback probe and must be fixed or explicitly accepted before claiming
fallback readiness.

## Environment

| Component | Address / mode |
| --- | --- |
| Edge gateway | `http://127.0.0.1:18080` |
| Legacy Java agent | `http://127.0.0.1:8085` |
| Central async-task service | `http://127.0.0.1:8086`, JDBC |
| AgentScope candidate | `http://127.0.0.1:18085` |
| LiteLLM | `http://127.0.0.1:4000` |
| Local Ollama | `http://127.0.0.1:11434` |
| Capability frontend | `http://127.0.0.1:8093` |

## Results

| Check | Result | Evidence |
| --- | --- | --- |
| Full Maven package | pass | 23/23 reactor modules succeeded |
| Java Compose startup | pass | 25/25 running, no unhealthy/restarting |
| Candidate health/readiness | pass | both 200 |
| Edge and core Java health | pass | edge, conversation, workflow, analytics, knowledge, agent, async all 200 |
| Gateway/model infrastructure | pass | LiteLLM and Ollama 200 |
| Frontend HTTP | pass | 200 |
| Candidate unauthenticated task access | pass | 401 |
| Central unauthenticated metrics | pass | 401 |
| Authenticated candidate/central metrics | pass | both 200; async series visible |
| Direct local-model async semantic smoke | pass | 202 → `SUCCEEDED`, result `stopReason=DONE`, non-empty answer |
| LiteLLM Ollama fallback semantic smoke | fail | defects below |

## Defects

### FULLSTACK-QA-001 — LiteLLM `chat-default-fallback` rejects AgentScope messages

- Severity: P1
- Reproduction:
  1. Start AgentScope with `GATEWAY_MODEL=chat-default-fallback`.
  2. Submit a simple no-tool `/agent/run/async` request.
- Expected: the local `llama3.1` fallback produces a normal answer.
- Actual: LiteLLM returns 500 while its Ollama prompt transformer raises
  `AttributeError: 'str' object has no attribute 'get'`.
- Isolation evidence: the same AgentScope request succeeds with `stopReason=DONE` when it
  calls the local Ollama OpenAI-compatible endpoint directly.
- Impact: the documented zero-cloud fallback is not valid for AgentScope traffic when the
  primary provider is unavailable.

### FULLSTACK-QA-002 — Model execution error is persisted as task `SUCCEEDED`

- Severity: P1
- Reproduction:
  1. Trigger the fallback failure above.
  2. Query the central task through the AgentScope task endpoint.
- Expected: the async task is `FAILED`, or the success contract explicitly excludes an
  Agent result whose `stopReason` is `ERROR`.
- Actual: the central task is `SUCCEEDED` with a non-null result containing
  `stopReason=ERROR`.
- Impact: task-level success metrics and callers can treat a model failure as successful
  completion.

The attempted `vision-default` local probe returned 400 because the installed
`qwen2.5vl` model does not support tools. This is an environment/model capability mismatch,
not counted as an additional product defect.

## Resolution Follow-up — 2026-07-29

- `FULLSTACK-QA-001`: resolved by routing the fallback through Ollama's
  OpenAI-compatible `/v1` endpoint. Real AgentScope probe: `SUCCEEDED` / `DONE`.
- `FULLSTACK-QA-002`: resolved by mapping async `stopReason=ERROR` to central `FAILED`,
  null result, and `ASYNC_TASK_EXECUTION_FAILED`.
- Full evidence:
  `docs/qa/phase-3-fallback-terminal-semantics-0729-1507/results.json`.

## Current Running State

- The candidate was restored to `GATEWAY_MODEL=chat-default` after the local probes.
- `ASYNC_TASK_ENABLED=true` only for the localhost candidate.
- Java orphan reaping remains at its Compose default (`false`).
- No cloud semantic request was sent during this run; the next real old/new comparison needs
  explicit cost approval.
