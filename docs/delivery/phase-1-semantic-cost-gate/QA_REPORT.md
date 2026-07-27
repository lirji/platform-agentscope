# QA Report

## Environment Profile

- Target: local old/new services with LiteLLM, Jaeger, retained dependencies, and Ollama.
- Version: working tree based on `e50d3ae`.
- Test data: read-only suite and seeded `tenantA` order 101.
- Secrets: short-lived internal token only in process environment.

## Cases

| ID | AC/Risk | Setup and steps | Expected | Actual/evidence | Verdict |
| --- | --- | --- | --- | --- | --- |
| QA-01 | AC-01 | allOf/anyOf/noneOf positive and negative answers | Exact score/verdict | Assertions pass | pass |
| QA-02 | AC-02 | Serialize failed sensitive answer | No answer/observation | Negative content check | pass |
| QA-03 | AC-03 | Candidate semantic zero vs legacy one | Absolute/relative regressions | Both emitted | pass |
| QA-04 | AC-04 | Two cases/runs/targets | Unique trace headers/samples | All unique and correlated | pass |
| QA-05 | AC-05 | Multiple ledger rows on one trace | Sum calls/tokens/USD | Exact totals | pass |
| QA-06 | AC-06 | Missing row and expensive candidate | Gate fails | Exact regressions | pass |
| QA-07 | AC-07 | Serialize cost report | Decimal summaries only | No provider payload/key | pass |
| QA-08 | AC-08 | Cost CLI pass/fail/invalid | Exit 0/1/2 | Exact codes | pass |
| QA-09 | AC-09 | Live order facts, three runs | Both 3/3 | Legacy and candidate 3/3 | pass |
| QA-10 | Cost live | Join 24 traces to spend rows | No missing run | 24/24 measured; gate pass | pass |

## Defects And Retests

- Candidate amount formatting false negative: modeled as equivalent alternatives; full suite
  retested.
- Duplicate ledger request protection and output collision protection added during review; focused
  tests passed.

## Automated Regression

- 65 tests passed; coverage 90.81%.
- All static, contract, offline, package, and Compose checks passed.

## Blocked External Checks

- Open-ended answer grading for RAG and analytics.
- Edge test-tenant cutover and rollback.
- External provider invoice reconciliation.

## Verdict

Conditional-pass: deterministic fact and estimated-cost gates pass; the explicit external checks
remain.
