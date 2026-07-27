# QA Report

## Acceptance Results

| Acceptance criterion | Result | Evidence |
| --- | --- | --- |
| AC-01 contract shape | pass | Generated JSON Schemas/OpenAPI and drift test |
| AC-02 RAG semantics | pass | Source, truncation, empty/error, and tenant-mismatch tests |
| AC-03 retained read tools | pass | Order, schema, analytics formatting and guard tests |
| AC-04 token/trace propagation | pass | HTTPX mock transport path/body/header assertions |
| AC-05 deterministic trajectory | pass | Sequential and parallel AgentScope event tests |
| AC-06 stable stop reasons | pass | Done, budget, loop, max-step, timeout, cancel, error tests |
| AC-07 read-only permission | pass | Explicit allow/deny permission tests |
| AC-08 safe observation | pass | Token/tool/stop metrics and no-secret boundary tests |
| AC-09 evaluation fixture | pass | JSONL structure and forbidden-mutation validation |
| AC-10 CI parity | pass | Workflow commands executed locally except image runtime |

## Automated Verification

- Contract snapshot check: pass.
- Ruff lint and format: pass.
- Mypy strict mode: pass for 29 source files.
- Pytest: 35 passed.
- Coverage: 88.62%, above the 80% repository gate.
- Python sdist/wheel build: pass.
- Shell syntax and Compose configuration: pass.

## Runtime Smoke

A real Uvicorn process was started on localhost with non-production smoke settings:

- `GET /health`: 200, `{"status":"UP"}`.
- `GET /readiness`: 200, agent/model checks `UP`.
- `GET /info`: 200, phase `1-readonly-react`.
- `X-Trace-Id` was present on the response.
- The process shut down cleanly.

## Environment-Limited Checks

- Docker image build/run: not executed because the Docker API socket was unavailable.
- Live model and Java retained-service integration: credentials/services were not supplied.
- Old/new quality, P95 latency, and cost comparison: deferred to the shadow environment.

These limitations block production equivalence claims, but not committing the isolated Phase 1
implementation.
