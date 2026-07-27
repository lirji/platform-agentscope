# Phase 1 Semantic And Cost Gate Delivery Plan

## Requirement

Continue Phase 1 by closing the deterministic answer-evidence gap and preparing target-attributed
cost comparison without persisting answers, observations, credentials, or provider payloads.

## Repository Evidence

- The existing Shadow gate retains final answers only in memory and reports tool/contract metrics.
- A non-seeded-tenant run proved that correct tool selection can coexist with a failed business
  result.
- Candidate and retained services both accept `X-Trace-Id`.
- LiteLLM currently mixes chat and embedding spend because requests are not joined to Shadow
  target/case/run identity.
- The retained Java eval-service supports semantic/judge assertions but stores response snippets
  and does not solve per-target multi-call cost attribution for this CLI.

## Feasibility

- Verdict: conditional-go.
- Conditions:
  - Semantic evidence is deterministic and suite-owned; no answer text is persisted.
  - Every target invocation receives a unique non-secret trace ID.
  - Cost is joined from an operator-exported JSONL ledger keyed by trace ID; the tool never reads
    LiteLLM credentials or raw provider records.
- Risks and mitigations:
  - Brittle exact text: support required terms, alternative term groups, and prohibited terms.
  - False cost pass from missing rows: any unmeasured run fails the cost gate.
  - Duplicate model/tool calls: aggregate all ledger rows for one trace.
  - Decimal drift: use decimal currency values and serialize them as strings.

## Product Design

- Actors and goals:
  - Migration engineers prove required business facts are present without retaining answers.
  - FinOps/release engineers join sanitized trace-level token/spend rows and receive a deterministic
    cost verdict.
- Scope:
  - Optional answer assertions in JSONL, semantic pass metrics/gates, unique trace correlation,
    sanitized cost-ledger join, CLI, tests, docs, and offline CI smoke coverage.
- Out of scope:
  - Provider billing API access, production credentials, probabilistic LLM judge, and edge cutover.
- Business rules:
  - A case with answer assertions passes only when all required groups and prohibited-term checks
    pass.
  - Reports contain only scores/verdicts, never answers or matched text.
  - Cost gate fails when either target has a sample with no ledger row.

## Acceptance Criteria

| ID | Observable behavior | Priority | Verification |
| --- | --- | --- | --- |
| AC-01 | Suite supports required, alternative, and prohibited answer evidence | P0 | Model and evaluator tests |
| AC-02 | Answer failure marks the run failed without storing answer content | P0 | Negative serialization test |
| AC-03 | Gate enforces absolute and relative semantic pass rates when assertions exist | P0 | Pure gate tests |
| AC-04 | Every paired request carries a unique `X-Trace-Id` recorded in its sanitized sample | P0 | HTTP integration test |
| AC-05 | Cost join aggregates multiple ledger rows per trace and per target | P0 | Deterministic ledger test |
| AC-06 | Missing trace cost or candidate cost regression fails the cost gate | P0 | Boundary tests |
| AC-07 | Cost report contains decimal token/cost summaries but no provider payload or credentials | P0 | Serialization test |
| AC-08 | CLI has stable 0/1/2 exit semantics and writes a sanitized report | P1 | CLI tests |
| AC-09 | Seeded order case requires its requested business facts | P0 | Suite inspection and real run |

## UI/UX Design

- Applicability: not applicable; operator CLIs and JSON artifacts only.

## Technical Solution

- Extend `ShadowCase` with optional aliased answer assertions and `RunSample`/summaries with
  answer-evidence metrics.
- Generate a UUID trace for each target/case/run and send it as `X-Trace-Id`.
- Add `evaluation/cost.py` and a console entrypoint that joins an existing Shadow report with a
  JSONL ledger of trace, token, and USD rows.
- Use `Decimal` internally and string serialization for USD values.
- Add order facts to the committed read-only suite.

## Implementation Sequence

1. Answer assertion models, evaluator, metrics, and tests (AC-01..04, AC-09).
2. Cost ledger models, join/gate/CLI, and tests (AC-05..08).
3. Offline/real validation, review, docs, and final report.

## Verification Plan

| AC/Risk | Test level | Case or command | Required evidence |
| --- | --- | --- | --- |
| AC-01..04 | Unit/integration | Shadow evaluator tests | Exact pass/fail and no content leak |
| AC-05..08 | Unit/CLI | Cost join and subprocess tests | Exact totals, regressions, exit codes |
| AC-09 | Local live | Seeded `tenantA` old/new run | Required order facts pass |
| Regression | Repository | Ruff, Mypy, pytest, build, Compose | All pass |

## Documentation Plan

Update Shadow runbook, suite guidance, testing gates, migration roadmap, README, and delivery
artifacts.

## CI Plan

Extend the existing offline smoke/tests; no credentials or remote calls.

## Rollout And Rollback

- Rollout: add assertions case-by-case, export trace-keyed spend from the test stack, then run the
  cost join gate.
- Rollback: remove optional assertions or cost-join invocation; runtime Agent APIs are unchanged.

## Assumptions And Open Decisions

- Default candidate semantic minimum is 80% with a five-point relative tolerance.
- Default cost limit is legacy cost × 1.25 plus USD 0.001.
- Provider-specific export remains an operator concern; this repository defines the safe ledger
  contract.

## Approval

- Status: approved.
- Approved scope: semantic grading and target/run cost attribution from the previous handoff.
- Evidence: user message “继续” on 2026-07-27.
