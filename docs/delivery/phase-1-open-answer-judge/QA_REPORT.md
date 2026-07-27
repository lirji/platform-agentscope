# QA Report

## Environment Profile

- Target: local old/new Shadow comparison plus deterministic in-memory tests.
- Version: working tree based on `67d71ec`.
- Services: retained Java services, candidate AgentScope, local LiteLLM, and local Ollama.
- Test data: committed read-only suite and `tenantA`.
- Limitation: local `llama3.1` could not complete retained open-answer cases.

## Cases

| ID | AC/Risk | Setup and steps | Expected | Actual/evidence | Verdict |
| --- | --- | --- | --- | --- | --- |
| QA-01 | AC-01 | Validate criteria, blank/orphan/out-of-range thresholds | Only valid suite contracts load | Focused validation tests pass | pass |
| QA-02 | AC-02 | Run with and without Judge | Default skips; opt-in judges configured cases only | Evaluator and CLI tests pass | pass |
| QA-03 | AC-03 | Mock OpenAI-compatible Judge | Temp 0, JSON response, one request | Exact request assertions pass | pass |
| QA-04 | AC-04 | Low, malformed, HTTP error, oversized input | Stable fail-closed errors | `JUDGE_SCORE_BELOW_THRESHOLD`/`JUDGE_ERROR`; no retry | pass |
| QA-05 | AC-05 | Serialize sensitive fixtures | No answer/criteria/prompt/key/provider body | Negative serialization assertions pass | pass |
| QA-06 | AC-06 | Compare low candidate score/rate | Absolute and relative regressions | Gate emits pass-rate and score regressions | pass |
| QA-07 | AC-07 | Configure remote Judge without opt-in | Exit 2 | CLI returns configuration error | pass |
| QA-08 | AC-08 | Inspect baseline and run RAG/analytics 3 times | Criteria active and both targets comparable | Candidate 6/6 scored; legacy 0/6 completed | blocked |
| QA-09 | AC-09 | Run CI-equivalent commands | All offline quality gates pass | 85 tests, 91.33% coverage; build/smoke/config pass | pass |

## Defects And Retests

- Invalid calibration JWT: environment setup error; corrected with `sub=tenantA`, `uid`, scopes, and
  `exp`.
- LiteLLM `ollama/` content-array incompatibility: environment adapter error; switched the same
  local model to Ollama's native OpenAI endpoint. Candidate probe then passed.
- No in-scope implementation defect remained after review.

## Automated Regression

- 85 tests passed.
- Coverage: 91.33%, above the 80% gate.
- Ruff, formatting, Mypy, contract snapshots, offline Shadow smoke, build, and Compose validation
  passed.

## Blocked External Checks

- A comparable three-run legacy/candidate Judge baseline requires a stronger approved test model.
- Remote Judge validation requires explicit network/data-retention approval.

## Verdict

conditional-pass: software behavior is verified; live model-quality and cutover approval fail.
