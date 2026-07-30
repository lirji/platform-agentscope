# QA Profile

## Target

- Environment: isolated localhost QA topology
- Python orchestrator: `http://127.0.0.1:18085`
- Central async task service: `http://127.0.0.1:18086`
- Optional second central instance: `http://127.0.0.1:18087`
- MySQL: disposable Docker container, host port `13316`
- Redis: disposable Docker container, host port `16389` (required by the shared
  Actuator health contributor)
- Model gateway and webhook receiver: local deterministic stub on `127.0.0.1:14000`
- Authentication: locally generated HS256 internal JWTs; raw tokens are not committed or
  copied into reports

## Safety And Cost Boundary

- Only localhost and a disposable Docker MySQL container are in scope.
- No production, shared test environment, paid model, or third-party webhook is used.
- The local model stub returns deterministic OpenAI-compatible responses and can introduce
  bounded latency for cancellation and crash tests.
- Test data uses synthetic tenants `qa-acme` and `qa-globex`.
- Orphan reaping starts disabled and is enabled only after normal execution and persistence
  checks pass.
- Business source is not modified during black-box execution. Failures are recorded and
  retried once before being classified.

## Required Services

| Service | Startup configuration |
|---|---|
| MySQL 8.4 | database `async_task`, user `root`, disposable QA password |
| Redis 7 | isolated, persistence disabled, used only for central health parity |
| `async-task-service` | JDBC store, webhook disabled initially, orphan reaper disabled |
| `agentscope-platform` | async enabled, central URL on port 18086, local gateway on port 14000 |
| local stub | OpenAI chat completion endpoint plus webhook observation endpoint |

## Health Checks

- Python: `GET /health`, `GET /readiness`
- Central: `GET /actuator/health`
- Model stub: `GET /health`

## Cleanup

Stop the two application processes and the model stub, then remove only the disposable
containers named `agentscope-phase3-qa-mysql` and `agentscope-phase3-qa-redis`. Preserve QA
plans, logs, JSON evidence, and the final report under the timestamped QA directory.

## 2026-07-29 Full-Stack Integration Startup

- The current full Java topology uses `../langchain4j-platform/deploy/docker-compose.yml`:
  edge `:18080`, legacy agent `:8085`, central async `:8086`, frontend `:8093`.
- The AgentScope candidate runs on `127.0.0.1:18085`; its order-service host URL must use
  `:8094` because the frontend owns host port 8093.
- The knowledge-service total health requires host Ollama on `127.0.0.1:11434`; with the
  existing `nomic-embed-text` model running, total health returns 200.
- A local direct-Ollama AgentScope async smoke reached `DONE`, proving the candidate/central
  lifecycle without cloud cost.
- `chat-default-fallback` is not currently compatible with AgentScope message content through
  LiteLLM (`'str' object has no attribute 'get'`), and a model-level `stopReason=ERROR` is
  currently persisted as central task `SUCCEEDED`. See
  `docs/qa/full-stack-startup-0729-1452/QA_REPORT.md`.

## 2026-07-29 Fallback And Terminal Semantics Retest

- Both startup defects above are resolved; the earlier bullets are retained as historical
  reproduction evidence.
- `chat-default-fallback` now uses Ollama's OpenAI-compatible `/v1` endpoint. A real
  AgentScope async probe returned central `SUCCEEDED`, business `DONE`, and `FALLBACK_OK`.
- A controlled missing-model probe returned central `FAILED`, null result, and
  `ASYNC_TASK_EXECUTION_FAILED`.
- The candidate was restored to `GATEWAY_MODEL=chat-default`; 25/25 Compose services and all
  selected health/authentication probes remain healthy.
- Evidence:
  `docs/qa/phase-3-fallback-terminal-semantics-0729-1507/results.json`.

## 2026-07-29 AgentScope Migration Acceptance

- Correct migration target is this independent `agentscope-platform` repository. The old
  Java Agent's `agent.task` mirror is only a compatibility baseline and must not be reported
  as the AgentScope migration implementation.
- A temporary candidate on `127.0.0.1:18084` can enable both candidate routing and async
  orchestration while the persistent rollback instance remains on `:18085` with candidate
  routing disabled.
- Real AgentScope async tasks use specific central kinds such as `agent.run` and `agent.dag`.
  A DAG run persisted 21 lifecycle/progress events and resumed with ids 11–21 after
  `Last-Event-ID: 10`.
- The current platform edge still routes `AGENT_URI` to the legacy Java Agent. Candidate
  direct compatibility is verified, but edge tenant gray routing remains a separate Phase 5
  release gate.
- A time-sensitive Critic false negative was fixed by supplying trusted server UTC evaluation
  time and an explicit ±120 second latency rule. Evidence:
  `docs/qa/agentscope-migration-acceptance-0729-1653/QA_REPORT.md`.
