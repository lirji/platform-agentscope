# Code Review Report

## Scope And Diff Base

Reviewed the complete diff from `67d71ec` across Judge client, Shadow models/evaluator/CLI, suite,
offline smoke, tests, runbook, and delivery artifacts.

## Confirmed Findings

| Severity | Finding | Failure scenario | Evidence | Resolution |
| --- | --- | --- | --- | --- |
| Medium | Remote Judge data-retention risk was not explicit | An operator could assume report sanitization means the answer never leaves the process | Judge sends the answer in the request; initial runbook wording covered only reports | Documented transient full-answer transfer, provider logging risk, and required data review |
| Medium | Positive CLI opt-in wiring lacked a focused test | Refactoring could construct a Judge but fail to pass it to evaluation | Initial tests covered missing key and remote rejection only | Added a successful opt-in test that verifies environment-only key construction and Judge injection |

## Rejected Suspicions

| Suspicion | Why rejected | Evidence |
| --- | --- | --- |
| A transient Judge failure should be retried | Retry would silently multiply cost and non-determinism; fail-closed is intentional | One HTTP request in client test; `JUDGE_ERROR` evaluator test |
| A missing legacy score could be treated as its default pass rate | The gate separately detects a one-sided missing mean score and rejects comparison | Live run emitted `judge_score regression: one target has no evaluated score` |
| Judge content may leak into the Shadow report | Only score/pass/evaluated/error fields cross the evaluator boundary | Serialization tests exclude answer, criteria, goal, provider error, and credential values |
| Agent P95 should include Judge time | P95 measures the target Agent call for continuity with Shadow v2; Judge is a separate optional service | Judge runs after target latency capture and uses an independent trace; runbook documents this |

## Checks Rerun After Fixes

- Ruff check and format check.
- Strict Mypy for `src`.
- Full pytest with coverage.
- Contract snapshots, offline Shadow smoke, package build, and Compose validation.
- Local real-model open-answer run.

## Residual Risks

- Model-based grading remains probabilistic and can share bias with the evaluated model.
- Remote Judge infrastructure may persist request content outside this repository's control.
- The local `llama3.1` profile failed quality and did not yield a comparable retained baseline.

## Verdict

conditional-pass: implementation has no confirmed high-severity issue; model-quality/cutover gate
remains failed.
