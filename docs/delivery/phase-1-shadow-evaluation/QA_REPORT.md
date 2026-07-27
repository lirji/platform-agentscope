# QA Report

## Environment Profile

- Target: local repository and localhost HTTP stub targets.
- Version: working tree after `2738697`.
- Services and dependencies: Python 3.12, HTTPX mock and real `ThreadingHTTPServer` targets.
- Test data: `eval/baseline/readonly-cases.jsonl`.
- Known limitations: no live LiteLLM, retained Java services, edge route, or test credentials.

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

## Defects And Retests

- Relative-only false pass: fixed with absolute floors; gate matrix retested.
- Reversed expected tools: fixed with ordered-subsequence validation; negative case retested.
- Oversized/network detail exposure: fixed with stable errors and size cap; security test passed.

## Automated Regression

- 53 tests passed.
- Total coverage 90.21%; evaluation runner coverage 92%.
- Ruff, formatting, Mypy, contract drift, package build, shell syntax, and Compose validation passed.

## Blocked External Checks

- Real old/new model quality and tool-selection comparison.
- P95 under realistic provider/service latency.
- LiteLLM monetary cost comparison.
- Edge shadow routing and rollback exercise.

## Verdict

Conditional-pass: tooling is locally release-ready; production migration gates remain blocked on the
explicit external checks above.
