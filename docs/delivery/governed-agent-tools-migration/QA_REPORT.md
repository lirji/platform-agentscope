# Governed Agent Tools QA Report

## Result

- Date: 2026-08-03
- Environment: local macOS, Python 3.12.13
- Overall local verdict: pass
- Production/live-provider verdict: not executed; default-off hold

## Automated Evidence

| Gate | Result |
| --- | --- |
| `uv sync --frozen --dev` | pass; 114 locked packages checked |
| `uv run python scripts/export_contracts.py --check` | pass |
| `uv run ruff check .` | pass |
| `uv run ruff format --check .` | pass; 208 files formatted |
| `uv run mypy src` | pass; 69 source files |
| `uv run pytest --cov=agentscope_platform --cov-report=term-missing --cov-fail-under=80` | pass; 349 tests, 89.23% coverage |
| `uv run pytest -q` final rerun | pass; 349 tests |
| `uv run python scripts/shadow-smoke.py` | pass; 8 samples |
| `uv build` | pass; sdist and wheel built |
| `docker compose -f compose.yml config` | pass |
| `git diff --check` | pass |

## Acceptance Evidence

| Acceptance criterion | Evidence | Result |
| --- | --- | --- |
| AC-01/02 | Tool schema, registry enumeration, pure policy and AgentScope permission tests | pass |
| AC-03 | authenticated header parsing and model-argument override rejection | pass |
| AC-04/05/06 | Java workflow HTTP mocks, duplicate key, statuses, no retry, two-tenant tokens | pass |
| AC-07 | MCP binding schema, allowlist, recursion rejection, real Streamable HTTP protocol test | pass |
| AC-08 | architecture AST tests prohibit local MCP/sandbox execution imports | pass |
| AC-09 | opaque tenant-bound sessions/jobs, host allowlist, limits, cleanup, timeout tests | pass |
| AC-10 | three `stub_only` governed fixture suites and per-capability rollback docs | pass |
| AC-11 | contract snapshots, full regression, shadow smoke, build, Compose | pass |

## Not Executed

- Real workflow/MCP old-new model shadow in a named shared environment.
- Real sandbox escape and resource-isolation test suite.
- Production canary or route change.

These omissions are environment/authorization gates, not local test substitutes. All feature flags
remain false by default.
