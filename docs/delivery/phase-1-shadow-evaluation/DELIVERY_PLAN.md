# Phase 1 Shadow Evaluation Delivery Plan

## Requirement

Continue the approved migration roadmap after the read-only ReAct code slice by making the remaining
old/new comparison gate reproducible without changing production routing.

## Repository Evidence

- `eval/baseline/readonly-cases.jsonl` already defines expected and forbidden tools.
- Both legacy and candidate expose the compatible synchronous `POST /agent/run` contract.
- The retained Java `eval-service` supports general dual-run quality gates, but it does not enforce
  Agent-specific forbidden-tool or P95 latency thresholds.
- The candidate is not yet routed by edge and no live LiteLLM/retained-service test stack is
  available in this environment.

## Feasibility

- Verdict: conditional-go.
- Conditions:
  - Implement and test the harness entirely against localhost stubs.
  - Require explicit opt-in before a remote test target can be contacted.
  - Read credentials only from environment variables and never persist them in reports.
- Dependencies:
  - Existing HTTPX, Pydantic, compatible `/agent/run` endpoints, and the committed JSONL suite.
- Risks and mitigations:
  - Accidental production traffic: localhost-only target validation by default.
  - Credential leakage: environment-only secrets and metadata-only reports.
  - Model non-determinism: configurable repeated runs and tolerance-based relative gates.
  - Misleading parity claim: external execution remains blocked until a named test stack exists.

## Product Design

- Actors and goals:
  - Migration engineers run one command against an old oracle and new candidate.
  - Reviewers receive a machine-readable report and non-zero exit status on regression.
- Scope:
  - Contract validity, expected/forbidden tool behavior, completion rate, stop reasons, and P95
    latency.
  - Relative legacy/candidate thresholds and a sanitized JSON report.
- Out of scope:
  - Edge routing changes, production traffic, model-graded answer quality, cost derivation, write
    tools, and Phase 2 orchestration.
- Business rules:
  - A run passes only when HTTP and contract validation pass, expected tools are present, forbidden
    tools are absent, and the final answer is non-empty.
  - Any forbidden-tool execution fails the entire gate.
  - Credentials and response content are not written to the report.

## Acceptance Criteria

| ID | Observable behavior | Priority | Verification |
| --- | --- | --- | --- |
| AC-01 | The same JSONL cases run against legacy and candidate for configurable repetitions | P0 | HTTP mock integration test |
| AC-02 | Responses are validated against `AgentRunReply` and malformed/non-2xx responses fail safely | P0 | Boundary/error tests |
| AC-03 | Expected-tool coverage and forbidden-tool violations are measured per target | P0 | Deterministic metric tests |
| AC-04 | Gate enforces absolute floors, relative regression limits, contract validity, and no forbidden action | P0 | Pure gate tests |
| AC-05 | Candidate P95 latency is compared with legacy using configured ratio/slack | P1 | Boundary metric tests |
| AC-06 | Reports contain metadata/results but no credentials, answers, or observations | P0 | Serialization/security test |
| AC-07 | Non-local targets require explicit operator opt-in and URLs cannot embed credentials | P0 | Target validation tests |
| AC-08 | CLI exits 0 on pass, 1 on target/gate failure, and 2 on configuration/report error | P1 | CLI integration tests |
| AC-09 | CI runs an offline localhost shadow smoke without model or Java dependencies | P1 | Workflow and local command |

## UI/UX Design

- Applicability: Not applicable; this is an operator CLI and JSON artifact.
- CLI output is a one-line verdict plus the report path; diagnostic details remain in sanitized
  JSON.

## Technical Solution

- Chosen approach:
  - Add a framework-independent evaluation model and gate.
  - Add an HTTPX-based shadow runner and a console entrypoint.
  - Reuse the existing read-only JSONL suite instead of creating another source of truth.
- Alternatives rejected:
  - Modify Java `eval-service`: outside the new project and insufficient for Agent-specific
    forbidden-tool/P95 policy.
  - Add edge shadow routing now: requires a live environment and changes traffic behavior.
  - Persist full responses: unnecessary and risks business-data leakage.
- Modules and file map:
  - `src/agentscope_platform/evaluation/models.py`
  - `src/agentscope_platform/evaluation/shadow.py`
  - `src/agentscope_platform/evaluation/cli.py`
  - `tests/test_shadow_evaluation.py`, `tests/test_shadow_cli.py`
  - `scripts/shadow-smoke.py`, CI, README, migration/testing docs.
- Security and reliability:
  - Explicit URL validation, environment-only credentials, bounded timeout, sequential calls,
    sanitized reports, no retries.
- Compatibility and migration:
  - No runtime API change and no edge route mutation.

## Implementation Sequence

1. Models, metrics, and pure gate (AC-03..06).
2. HTTP runner and target safety (AC-01, AC-02, AC-07).
3. CLI, offline smoke, documentation, and CI (AC-08, AC-09).
4. Review, QA, and full verification.

## Verification Plan

| AC/Risk | Test level | Case or command | Required evidence |
| --- | --- | --- | --- |
| AC-01..02 | Integration | HTTPX mock targets | Paired calls and safe failures |
| AC-03..05 | Unit | Deterministic samples | Exact rates/P95/regressions |
| AC-06..07 | Security | Serialized report and URL cases | No sensitive fields; remote denied |
| AC-08 | CLI | Stub server/subprocess | Exact exit codes |
| AC-09 | CI parity | `python scripts/shadow-smoke.py` | Offline pass |

## Documentation Plan

Update README, migration roadmap, testing gates, and add a Shadow evaluation runbook.

## CI Plan

Add a deterministic localhost-only smoke after unit tests. No credentials or remote service calls.

## Rollout And Rollback

- Rollout: use the CLI manually in a named test environment, then schedule it before any route
  change.
- Rollback: remove the evaluation invocation; runtime service behavior is unaffected.

## Assumptions And Open Decisions

- Default minimum pass/completion/tool-accuracy rates are 80%; relative tolerances are 5 percentage
  points.
- Default candidate P95 limit is `legacy P95 * 1.5 + 250 ms`.
- Quality grading and monetary cost thresholds remain external decisions.

## Approval

- Status: approved.
- Approved scope: remaining Phase 1 shadow-evaluation preparation from the existing migration plan.
- Evidence: user message “继续” after Phase 1 implementation commit and explicit next-step handoff.
