# Code Review Report

## Scope And Diff Base

- Base: `2738697 feat(agent): deliver read-only AgentScope migration slice`.
- Scope: evaluation models, paired HTTP execution, gates, CLI, tests, offline CI smoke, and docs.
- Review was performed as a fresh adversarial pass over the actual local diff.

## Confirmed Findings

| Severity | Finding | Failure scenario | Evidence | Resolution |
| --- | --- | --- | --- | --- |
| High | Relative-only gates could false-pass | Both targets fail every case with equal zero rates, so candidate is “not worse” | `shadow.py:271` gate construction | Added absolute 80% floors plus legacy/candidate contract-error hard failures |
| Medium | Expected tool order was not enforced | `analytics_sql` before `schema_explore` passed because both names were present | `shadow.py:188` tool extraction | Added ordered-subsequence validation and `EXPECTED_TOOL_ORDER` |
| Medium | Unbounded/untrusted response handling | A test target could return a huge or sensitive error body | `shadow.py:145` HTTP response path | Added 2 MB limit and stable errors without response/exception text |
| Medium | Ambiguous target labels | Swapped/custom labels could break or misattribute aggregation | `shadow.py:80` evaluator entry | Require exact `legacy` and `candidate` roles |

## Rejected Suspicions

| Suspicion | Why rejected | Evidence |
| --- | --- | --- |
| Duplicates Java eval-service | This gate is Agent-specific: forbidden tools, ordered tool selection, contract validation, and P95 policy; the Java service remains useful for semantic/judge scoring | Plan repository evidence and `docs/shadow-evaluation.md` |
| Credentials can leak through CLI | Token values have no CLI option, are read from environment, and are absent from report models | `cli.py:47`, `models.py` |
| CLI can silently hit production | Non-local URLs fail unless the operator supplies an explicit opt-in; embedded credentials/query/fragment are rejected | `shadow.py:63` |
| Report stores business answers | Samples contain only case ID, target label, metrics, tool names, and stable error codes | `models.py` and security serialization tests |

## Checks Rerun After Fixes

- Ruff lint and format: pass.
- Mypy strict: pass.
- 53 tests: pass.
- Coverage: 90.21%.
- Offline paired-target smoke: pass.
- Package and Compose validation: pass.

## Residual Risks

- Model answer correctness still needs Java eval-service semantic/judge evidence in the test stack.
- Monetary cost must be joined from LiteLLM/platform metering because `/agent/run` does not expose it.
- Explicit `--allow-remote-targets` is an operator trust boundary; the runbook prohibits production.

## Verdict

Pass for committing the Shadow evaluation tooling. Production routing remains gated on external QA.
