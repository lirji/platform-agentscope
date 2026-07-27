# Phase 1 Read-only ReAct Delivery Plan

## Requirement

Continue the approved migration plan after the Phase 0 scaffold: establish a contract-backed,
tenant-safe, read-only ReAct vertical slice that can be compared with the legacy Java
`agent-service`.

## Repository Evidence

- The legacy service exposes `AgentRunRequest`, `AgentRunReply`, and `AgentStep` from
  `platform-protocol`.
- `RagSearchAction`, `OrderQueryAction`, `SchemaExploreAction`, and `AnalyticsSqlAction` are
  read-only adapters over retained Java services.
- `DeepAgentService` uses `DONE`, `MAX_STEPS`, `TIMEOUT`, `BUDGET`, `LOOP`, `CANCELLED`, and
  `ERROR` stop reasons.
- AgentScope 2.0 emits tool-call, tool-result, model-usage, max-iteration, and reply-end events.

## Feasibility

- Verdict: go
- Constraints:
  - No production credentials or live platform stack are available in this delivery.
  - Agent output quality cannot be compared without an approved model/test environment.
  - The existing Java services remain authoritative for data and authorization.
- Dependencies:
  - AgentScope 2.0.5, LiteLLM-compatible model endpoint, retained Java services.
- Risks and mitigations:
  - Contract drift: committed JSON Schema and OpenAPI snapshots plus tests.
  - Tenant loss: all HTTP tools derive identity/token from `RunContext`; never from model input.
  - Chain-of-thought leakage: keep the legacy `thought` field but return an empty string.
  - Tool retries/side effects: only explicitly read-only tools are registered and auto-allowed.
  - Framework event churn: isolate event mapping under the AgentScope infrastructure adapter.

## Product Design

- Actors and goals:
  - Existing API consumers call `/agent/run` without changing JSON shape.
  - Platform operators can trace model/tool execution and token usage.
  - Developers can add read-only tools without bypassing tenant propagation.
- Scope:
  - Four retained-service tools plus `current_time`.
  - AgentScope event-to-legacy-step mapping.
  - Timeout, token budget, max-iteration, cancellation, and error mapping.
  - Contract snapshots, offline evaluation cases, observability hooks, CI.
- Out of scope:
  - Write tools, workflow mutations, browser/code sandbox, async task API, DAG, live traffic cutover.
  - Claiming model-quality parity without a real baseline environment.
- Business rules:
  - Business facts must come from tools.
  - Tool tenant identity cannot be supplied by the model.
  - At most ten analytics rows and 600 characters per RAG snippet are echoed to the model.
  - Internal tokens and API keys never appear in logs or responses.

## Acceptance Criteria

| ID | Observable behavior | Priority | Verification |
| --- | --- | --- | --- |
| AC-01 | `/agent/run` request/reply schemas match the legacy field names and required fields | P0 | Schema snapshot and API tests |
| AC-02 | `rag_search` preserves source IDs, truncation, empty-result, and error behavior | P0 | Tool unit/integration tests |
| AC-03 | `order_query`, `schema_explore`, and `analytics_sql` preserve legacy output semantics | P0 | Tool unit/integration tests |
| AC-04 | Every retained-service call propagates the validated internal token and trace ID | P0 | HTTP mock transport tests |
| AC-05 | Tool call/input/result events map deterministically to ordered legacy `AgentStep` objects | P0 | Event-mapper tests |
| AC-06 | Max iterations, timeout, budget, cancellation, and framework errors map to stable stop reasons | P0 | Runner tests with fake event streams |
| AC-07 | Only declared read-only tools can execute without confirmation | P0 | Permission tests |
| AC-08 | Runs emit traceable token/tool/stop metrics without secrets | P1 | Observer tests and log-field review |
| AC-09 | Offline read-only evaluation cases identify expected tools and forbidden mutations | P1 | Fixture validation test |
| AC-10 | CI runs lockfile sync, Ruff, formatting, Mypy, tests, package build, and Compose validation | P1 | Workflow inspection and local command parity |

## UI/UX Design

- Applicability: Not applicable. No user-facing UI is changed.
- API error behavior remains JSON and traceable through `X-Trace-Id`.

## Technical Solution

- Chosen approach:
  - Keep stable domain DTOs and add committed contract snapshots.
  - Move tool formatting into a dedicated AgentScope read-only toolset.
  - Consume `Agent.reply_stream(..., yield_final_msg=True)` and map framework events in an
    adapter-local trajectory collector.
  - Add an application-neutral run observer port with a structured logging implementation.
- Alternatives rejected:
  - Return raw AgentScope events: breaks compatibility and framework isolation.
  - Copy Java domain services into Python: duplicates authoritative business logic.
  - Expose model reasoning: creates privacy/security risk and is not needed for tool auditability.
- Modules and file map:
  - `contracts/` and `scripts/export_contracts.py`
  - `eval/baseline/readonly-cases.jsonl`
  - `application/observer.py`
  - `infrastructure/agentscope/trajectory.py`, `readonly_tools.py`, updated `runner.py`
  - updated `infrastructure/http/platform_client.py`
  - `infrastructure/observability/`
  - focused tests and GitHub Actions CI
- Contracts and data:
  - No persistence changes.
  - JSON Schema/OpenAPI artifacts are language-neutral and versioned in Git.
- Security and reliability:
  - ContextVar-bound immutable identity, explicit timeouts, response size caps, no write tools.
- Observability:
  - Structured run completion event with trace, tenant, model, tools, token counts, duration, and
    stop reason. Optional OpenTelemetry FastAPI/HTTPX instrumentation.
- Compatibility and migration:
  - Existing route and response aliases remain unchanged.
  - Release through `/agent/v2` or façade/shadow mode later; no edge route change in this delivery.

## Implementation Sequence

1. Contract/evaluation assets (AC-01, AC-09).
2. HTTP client and read-only tools (AC-02, AC-03, AC-04, AC-07).
3. Event trajectory and runner limits (AC-05, AC-06).
4. Observability and CI (AC-08, AC-10).
5. Review, QA, documentation, and final verification.

## Verification Plan

| AC/Risk | Test level | Case or command | Required evidence |
| --- | --- | --- | --- |
| AC-01 | Contract | `pytest tests/test_contracts.py` | Snapshots equal generated schemas |
| AC-02..04 | Unit/integration | HTTPX MockTransport tests | Body/path/header/output assertions |
| AC-05..06 | Unit | Synthetic AgentScope events/fake runner | Exact step and stop-reason assertions |
| AC-07 | Unit | Permission decisions | ALLOW/DENY evidence |
| AC-08 | Unit | Capturing observer | No secret fields; correct metrics |
| AC-09 | Data validation | JSONL fixture test | Valid expected tools and no mutations |
| AC-10 | Build | CI-equivalent local commands | All commands exit 0 |

## Documentation Plan

Update README, contracts, migration plan, testing gates, and this delivery artifact set.

## CI Plan

Use GitHub Actions because the configured remote is GitHub. Run on Python 3.12 with uv lock
enforcement and the same commands verified locally. Do not deploy or require secrets.

## Rollout And Rollback

- No traffic is switched in this delivery.
- Rollout later through a separate `/agent/v2` route or legacy façade/shadow invocation.
- Rollback is routing back to the Java `agent-service`; contract artifacts remain valid.

## Assumptions And Open Decisions

- Assumption: retaining an empty `thought` string is compatible with current consumers and safer
  than exposing hidden reasoning.
- External decision deferred: approved quality/cost thresholds require a live baseline environment.

## Approval

- Status: approved
- Approved scope: Phase 1 work from `docs/migration-plan.md`.
- Evidence: user message “提交 git，然后继续后续任务” after accepting the scaffold and migration plan.
