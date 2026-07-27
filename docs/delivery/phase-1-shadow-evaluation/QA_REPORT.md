# QA Report

## Environment Profile

- Target: local repository and localhost HTTP stub targets.
- Version: working tree after `2738697`.
- Services and dependencies: Python 3.12, HTTPX mock and real `ThreadingHTTPServer` targets.
- Test data: `eval/baseline/readonly-cases.jsonl`.
- Live extension: localhost LiteLLM, retained Java services, legacy Agent on `8085`, and candidate
  on `18085`, using one short-lived internal test identity.
- Known limitations at this delivery point: no edge test-tenant cutover or attributable cost. The
  subsequent semantic/cost delivery closes deterministic order facts and estimated-cost attribution.

## Cases

| ID | AC/Risk | Setup and steps | Expected | Actual/evidence | Verdict |
| --- | --- | --- | --- | --- | --- |
| QA-01 | AC-01 | Two localhost targets, same suite, repeated calls | Equal paired sample count | Exact host/call assertions | pass |
| QA-02 | AC-02 | 503, invalid JSON, network error, oversized response | Stable failures, no body leak | Error-code assertions | pass |
| QA-03 | AC-03 | Expected, missing, reversed, and forbidden tools | Correct per-run metrics | Deterministic unit tests | pass |
| QA-04 | AC-04 | Absolute/relative regression matrix | All applicable regressions emitted | Exact regression set | pass |
| QA-05 | AC-05 | Legacy 100 ms vs candidate 1000 ms | P95 regression | Gate fails with limit | pass |
| QA-06 | AC-06 | Serialize secrets/answers/observations | None appear | Negative content assertions | pass |
| QA-07 | AC-07 | Local, remote, credential URL, query URL | Safe URLs accepted; unsafe denied | Parameterized tests | pass |
| QA-08 | AC-08 | Real localhost servers through CLI | Report and exit 0; fail/config codes exact | CLI integration tests | pass |
| QA-09 | AC-09 | Run offline smoke | 8 samples and passing gate | Command exit 0 | pass |
| QA-10 | Compatibility | Live four-case run before repair | Equivalent step budget | Candidate analytics `MAX_STEPS` after four tools | fail |
| QA-11 | Compatibility retest | Map 8 legacy steps to 15 AgentScope iterations and rerun | Candidate completes all cases | 4/4 complete, tool accuracy 1.0 | pass |
| QA-12 | Repeated live gate | Three runs/case with seeded `tenantA` data | No candidate regression | Both targets 12/12 pass; candidate P95 12.734s | pass |
| QA-13 | Order business path | Inspect candidate order upstream status | Seeded order exists for test tenant | HTTP 200 on all three candidate calls | pass |

## Defects And Retests

- Relative-only false pass: fixed with absolute floors; gate matrix retested.
- Reversed expected tools: fixed with ordered-subsequence validation; negative case retested.
- Oversized/network detail exposure: fixed with stable errors and size cap; security test passed.
- AgentScope iteration semantic mismatch: fixed with `2n-1` mapping; focused and live retest passed.
- Non-seeded Shadow identity: first repeated attempt reached tenant-isolated 404 order results;
  corrected to `tenantA` and reran all cases. This also documented the semantic-grading gap.

## Automated Regression

- 57 tests passed.
- Total coverage 90.31%; evaluation runner coverage 92%.
- Ruff, formatting, Mypy, contract drift, package build, shell syntax, and Compose validation passed.

## Blocked External Checks

- Semantic/tool-result answer grading.
- Open-ended model grading and provider invoice reconciliation remain after the follow-up
  trace-attributed estimated-cost gate.
- Edge test-tenant routing and rollback exercise.

## Verdict

Conditional-pass: the repeated local tool/contract/P95 gate passes; production migration remains
blocked on semantic, attributable-cost, and edge-environment checks.
