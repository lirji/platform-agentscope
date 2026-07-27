# Delivery Status

## Goal

Expose and verify a default-off, reversible candidate `/agent/v2/run` route.

## State

- Phase: delivery complete
- Status: complete
- Last updated: 2026-07-27

## Completed

- Repository and prior Shadow evidence inspected.
- Feasibility, product behavior, acceptance criteria, implementation, and rollback plan recorded.
- Default-off V2 route, shared handler, readiness state, tests, config, and runbook completed.
- Candidate-side enabled/disabled restart exercise passed.
- Seeded-tenant three-run old/new gate passed.

## Changed Files

- `docs/delivery/phase-1-canary-route/DELIVERY_PLAN.md` - approved delivery design.
- `docs/delivery/phase-1-canary-route/DELIVERY_STATUS.md` - resumable workflow state.
- `src/agentscope_platform/api/app.py`, `api/routes.py`, `core/config.py` - route implementation.
- `tests/test_api.py` - contract, security, context, and readiness tests.
- `.env.example`, `compose.yml`, `docs/candidate-route.md` - operator configuration and rollback.
- `REVIEW_REPORT.md`, `QA_REPORT.md`, `DELIVERY_REPORT.md` - final evidence.

## Verification Log

| Command or check | Result | Notes |
| --- | --- | --- |
| Repository/status inspection | pass | Clean baseline at `9ed1e91` |
| Focused API/static checks | pass | 9 tests; Ruff and Mypy pass |
| Full local quality gate | pass | 57 tests, 90.31%; build and Compose pass |
| Three-run seeded-tenant Shadow gate | pass | Both 12/12; candidate P95 12.734s |
| Enabled V2 real probe | pass | 200/DONE, tenant and trace preserved |
| Disabled V2 rollback probe | pass | Readiness DISABLED, route 404 |

## Decisions And Deviations

- Implement candidate-side route readiness only; do not mutate the legacy edge gateway.
- Keep the route absent by default.
- Reject the non-seeded-tenant repeated attempt as business evidence and rerun with `tenantA`.

## Blockers And Residual Risks

- Edge tenant/percentage routing is outside this repository.
- Deterministic order evidence and trace-attributed estimated cost now pass; open-ended model
  grading and edge routing remain cutover gates.

## Next Action

The follow-up semantic/cost gate is complete. Next, exercise the legacy edge with a test tenant
before any production cutover.
