# Delivery Report

## Outcome

Phase 1 Shadow now detects missing business facts without persisting answers and can join all
model/embedding costs to exact target runs through W3C traces and unique provider request IDs.

## Requirement Coverage

| AC | Implementation evidence | Verification evidence | Status |
| --- | --- | --- | --- |
| AC-01 | `AnswerAssertions` | Positive/negative/group tests | complete |
| AC-02 | Score-only `RunSample` fields | Serialization leak test | complete |
| AC-03 | Semantic summary and gates | Absolute/relative tests | complete |
| AC-04 | Unique trace and traceparent headers | HTTP request/sample assertions | complete |
| AC-05 | Trace ledger aggregation | Exact multi-row totals | complete |
| AC-06 | Missing/cost regressions | Boundary gate tests | complete |
| AC-07 | Sanitized decimal cost report | Negative payload/key assertions | complete |
| AC-08 | `agentscope-shadow-cost` | Exit-code tests | complete |
| AC-09 | Order suite facts | Live three-run 3/3 evidence | complete |

## Changed Files

- `evaluation/models.py`, `shadow.py`, `cli.py`: answer evidence, trace, and gates.
- `evaluation/cost.py`, `cost_cli.py`: cost ledger, aggregation, report, and CLI.
- `eval/baseline/readonly-cases.jsonl`: seeded order facts.
- `tests/test_shadow_evaluation.py`, `test_cost_attribution.py`: focused coverage.
- `scripts/shadow-smoke.py`, `pyproject.toml`: offline fixture and console entrypoint.
- Shadow, testing, migration, README, and delivery documentation.

## Build And Test Results

- 65 tests passed; 90.81% coverage.
- Ruff, format, Mypy, contracts, offline smoke, package build, Compose, and diff checks passed.
- Candidate live semantic/tool gate: 12/12, order evidence 3/3, P95 13.681s.
- Candidate estimated cost: USD 0.00360950 vs legacy USD 0.01105914; gate passed.

## Code Review And QA Verdicts

- Review: pass.
- QA: conditional-pass for external open-ended grading, edge, and invoice checks.

## Documentation Changes

Documented answer assertion semantics, tracing prerequisites, safe spend export, ledger schema,
thresholds, exit codes, and billing-estimate boundary.

## CI Changes And Validation

No new remote job or secret is needed. Existing unit suite and offline smoke exercise the new
fields and gate behavior; all CI-equivalent commands passed locally.

## Deviations From Plan

- Live evidence required an `anyOf` alternative for formatted amount `1,200.00`.
- Review strengthened the ledger with mandatory unique request IDs.

## Rollout, Monitoring, And Rollback

Add deterministic facts only to stable cases, enable tracing in a named test stack, export only safe
spend columns, and run both gates. Removing assertions or the cost-join invocation rolls back
evaluation only; runtime APIs are unchanged.

## Remaining Risks Or External Actions

- Add model-graded RAG/analytics cases through retained eval-service.
- Exercise actual edge test-tenant routing and rollback.
- Reconcile estimates with provider invoices if a paid provider is used.
