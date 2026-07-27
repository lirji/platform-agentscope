# Phase 1 Candidate Route Delivery Plan

## Requirement

Continue the approved AgentScope migration after the live Shadow gate by exposing a reversible,
candidate-only `/agent/v2/run` route and exercising its rollback behavior locally.

## Repository Evidence

- The candidate already serves the legacy-compatible `POST /agent/run` contract.
- Authentication and tenant propagation are centralized in `RunContextDependency`.
- The edge gateway remains in `../langchain4j-platform`; this repository must not silently mutate
  its runtime routing.
- The migration roadmap requires a `/agent/v2/**` or façade route before Phase 1 cutover.

## Feasibility

- Verdict: go for candidate-side route readiness; conditional-go for edge traffic cutover.
- Constraints:
  - The new route must be absent by default.
  - It must reuse the existing contract and security path.
  - Enabling or disabling it is a restart-time configuration change.
- Risks and mitigations:
  - Accidental exposure: default `AGENT_V2_ENABLED=false`.
  - Security drift: use the same handler and dependency as `/agent/run`.
  - Misleading rollout claim: explicitly separate candidate route exercise from edge routing.

## Product Design

- Actors and goals:
  - Operators enable a stable candidate URL for controlled edge/facade routing.
  - Operators rollback by disabling the route and restoring the edge target to legacy.
- Scope:
  - Candidate-side feature flag, route, readiness visibility, tests, and rollback runbook.
- Out of scope:
  - Production edge mutation, traffic percentage selection, write tools, and Phase 2.
- Business rules:
  - Disabled means `/agent/v2/run` is not registered and returns 404.
  - Enabled means it has the same request, response, authentication, and tenant behavior as
    `/agent/run`.

## Acceptance Criteria

| ID | Observable behavior | Priority | Verification |
| --- | --- | --- | --- |
| AC-01 | `/agent/v2/run` returns 404 when the feature flag is disabled | P0 | API test |
| AC-02 | Enabled route preserves the legacy-compatible request/reply contract | P0 | API test |
| AC-03 | Enabled route rejects missing and forged internal tokens | P0 | API tests |
| AC-04 | Tenant, user, department, scopes, and trace propagate unchanged | P0 | API test |
| AC-05 | Readiness reports whether the candidate route is enabled | P1 | API test |
| AC-06 | Compose/env documentation defaults the route to disabled and documents rollback | P0 | Config inspection and local exercise |

## UI/UX Design

- Applicability: not applicable; this is an internal HTTP route and operator configuration.

## Technical Solution

- Add `agent_v2_enabled: bool = False` to settings.
- Define a dedicated `candidate_router` and register it only when the flag is enabled.
- Delegate both public paths to one private handler to prevent behavior drift.
- Surface `candidateRoute` in readiness without making route disablement a readiness failure.
- Add focused API tests and operator documentation.

## Implementation Sequence

1. Configuration, conditional route registration, and contract/security tests (AC-01..05).
2. Environment/Compose/runbook documentation and local enable-disable exercise (AC-06).
3. Review, full regression, and delivery evidence.

## Verification Plan

| AC/Risk | Test level | Case or command | Required evidence |
| --- | --- | --- | --- |
| AC-01..05 | API | `uv run pytest tests/test_api.py` | Exact status/body/context assertions |
| AC-06 | Config/black-box | Compose model plus two local app starts | 200 enabled, 404 disabled |
| Regression | Repository | Ruff, Mypy, full pytest, build | All pass |

## Documentation Plan

Update `.env.example`, README, migration roadmap, testing gates, and add a candidate-route runbook.

## CI Plan

No new job is needed; focused tests run in the existing full test job.

## Rollout And Rollback

- Candidate: set `AGENT_V2_ENABLED=true`, restart, verify readiness and authenticated probe.
- Edge: route only approved test tenants/capabilities to the candidate URL.
- Rollback: restore edge routing to legacy, set the candidate flag to `false`, restart, and verify
  `/agent/v2/run` returns 404.

## Assumptions And Open Decisions

- Edge-specific tenant/percentage selection remains a later change in the legacy repository.
- Local Ollama has no external API charge; monetary cost approval remains unresolved.

## Approval

- Status: approved.
- Approved scope: continue the previously handed-off repeated validation and reversible
  `/agent/v2` route exercise.
- Evidence: user message “继续” on 2026-07-27.
