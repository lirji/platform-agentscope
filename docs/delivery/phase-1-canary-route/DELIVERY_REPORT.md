# Delivery Report

## Outcome

A default-off, authenticated `POST /agent/v2/run` candidate endpoint is implemented and locally
proven reversible. Existing `/agent/run` behavior is unchanged.

## Requirement Coverage

| AC | Implementation evidence | Verification evidence | Status |
| --- | --- | --- | --- |
| AC-01 | Conditional router registration | Default 404 test and local rollback probe | complete |
| AC-02 | Shared private run handler | Exact response contract test | complete |
| AC-03 | Shared `RunContextDependency` | Missing/forged token tests | complete |
| AC-04 | Shared context and service | Identity and trace assertions | complete |
| AC-05 | Readiness candidate-route check | Disabled/enabled tests and probes | complete |
| AC-06 | Env/Compose default and runbook | Compose validation and enable-disable exercise | complete |

## Changed Files

- `api/app.py`, `api/routes.py`, `core/config.py`: conditional V2 route.
- `tests/test_api.py`: route, security, context, and readiness coverage.
- `.env.example`, `compose.yml`: explicit default-off configuration.
- `docs/candidate-route.md`, README, migration/testing docs: rollout and rollback guidance.
- Delivery artifacts: traceable design, review, QA, and final evidence.

## Build And Test Results

- 57 tests passed; 90.31% coverage.
- Ruff, formatting, Mypy, contract drift, offline Shadow smoke, package build, Compose config, and
  diff checks passed.
- Real enabled route returned 200/DONE with the expected tenant.
- Real disabled route returned 404 after restart.
- Seeded-tenant repeated Shadow gate passed for both targets; candidate P95 was 12.734s.

## Code Review And QA Verdicts

- Review: pass for candidate route readiness.
- QA: conditional-pass because edge and cost evidence are external.

## Documentation Changes

Added exact enable, verification, traffic-ordering, and rollback instructions; synchronized roadmap
and test gates.

## CI Changes And Validation

No new CI job was required. Existing tests cover the flag and both route states; all underlying CI
commands passed locally.

## Deviations From Plan

- The first repeated run used an identity without seeded order data. It was rejected as business
  evidence and repeated in full with `tenantA`.

## Rollout, Monitoring, And Rollback

Enable only for a test tenant after restoring target-attributed metering. Route edge traffic to the
candidate after it is healthy. Roll back edge first, then disable and restart the candidate route.

## Remaining Risks Or External Actions

- Edge test-tenant routing and rollback are not changed by this repository.
- Semantic answer quality and per-target cost remain cutover blockers.
