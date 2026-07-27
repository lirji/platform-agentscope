# Delivery Status

## Goal

Deliver the contract-backed Phase 1 read-only ReAct vertical slice.

## State

- Phase: review and verification complete
- Status: complete-with-external-validation-pending
- Last updated: 2026-07-27

## Completed

- Phase 0 scaffold committed as `64bb738`.
- Delivery feasibility, product design, technical design, acceptance criteria, and approval recorded.
- Versioned compatibility schemas, OpenAPI snapshot, and read-only evaluation fixture added.
- `rag_search`, `order_query`, `schema_explore`, and `analytics_sql` implemented over retained
  Java services with immutable tenant/token/trace propagation.
- AgentScope events mapped to deterministic legacy `AgentStep` objects without reasoning leakage.
- Budget, loop, max-step, timeout, cancellation, and safe error stop reasons implemented.
- Safe run governance logs, optional OpenTelemetry, and CI quality gates added.
- Review, QA, documentation synchronization, package build, and real-process smoke test completed.

## Changed Files

- `contracts/`, `scripts/export_contracts.py` - generated compatibility contract assets.
- `eval/baseline/readonly-cases.jsonl` - deterministic read-only evaluation inputs.
- `src/agentscope_platform/infrastructure/agentscope/` - read-only tools, trajectory, and runner.
- `src/agentscope_platform/infrastructure/http/` - retained-service contracts and client.
- `src/agentscope_platform/infrastructure/observability/` - safe logs and optional tracing.
- `.github/workflows/ci.yml` - frozen install, contract, quality, test, build, and Compose gates.
- `tests/` - contract, HTTP, tools, trajectory, runner, observability, and governance coverage.
- `README.md`, `docs/` - delivery state, contracts, migration status, and verification commands.

## Verification Log

| Command or check | Result | Notes |
| --- | --- | --- |
| `git commit -m "chore(scaffold): initialize agentscope platform"` | pass | Commit `64bb738` |
| Legacy source inspection | pass | DTOs, tools, HTTP clients, and stop reasons checked |
| AgentScope event signature inspection | pass | Tool/reply/model/max-iteration event fields checked |
| `uv run python scripts/export_contracts.py --check` | pass | Committed artifacts current |
| `uv run ruff check .` / `uv run ruff format --check .` | pass | 52 files formatted |
| `uv run mypy src` | pass | 29 source files checked |
| `uv run pytest ... --cov-fail-under=80` | pass | 35 tests, 88.62% coverage |
| `uv build` | pass | sdist and wheel built |
| `docker compose -f compose.yml config` | pass | Compose model valid |
| Real Uvicorn `/health`, `/readiness`, `/info` smoke | pass | HTTP 200 and trace header |
| Docker image build | blocked by environment | Docker daemon is not running |

## Decisions And Deviations

- Use AgentScope 2.0 events but do not expose hidden reasoning in legacy `thought`.
- This delivery does not change edge routing or execute live model-quality evaluation.
- Existing Java services remain the authorization authority; this adapter does not invent a new
  top-level `agent` scope requirement absent from the legacy service.

## Blockers And Residual Risks

- Live old/new quality comparison remains external until LiteLLM and retained services are available.
- Container image execution remains unverified until a Docker daemon is available; package and
  Compose validation succeeded.

## Next Action

Provision a test environment for old/new shadow evaluation, approve quality/latency/cost thresholds,
and only then add `/agent/v2` or façade routing. Do not start Phase 2 write-capable orchestration
before the Phase 1 production exit criteria are met.
