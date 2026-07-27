# Code Review Report

## Scope And Diff Base

- Base: `e50d3ae feat(api): add reversible candidate route`.
- Scope: answer evidence, trace correlation, cost join/gate/CLI, suite, tests, and docs.
- Review covered correctness, false passes/failures, data leakage, duplicate accounting, missing
  measurements, filesystem safety, compatibility, and operability.

## Confirmed Findings

| Severity | Finding | Failure scenario | Evidence | Resolution |
| --- | --- | --- | --- | --- |
| High | Tool selection could pass a failed business result | Wrong tenant returns order 404 but `order_query` is present | Prior live invalid-tenant run | Added in-memory answer evidence and order facts |
| Medium | Equivalent amount format caused false failure | Candidate emits `1,200.00`, suite required `1200` | First live semantic run scored 0.857 | Added an `anyOf` equivalent-format group |
| High | Duplicate spend rows could inflate one target | Same provider row appears twice in ledger | Initial ledger contract lacked request identity | Require globally unique `requestId` and reject duplicates |
| Medium | Output could overwrite an input artifact | Operator sets output equal to Shadow report or ledger | Cost CLI path handling | Reject output/input path collision |

## Rejected Suspicions

| Suspicion | Why rejected | Evidence |
| --- | --- | --- |
| Answer evidence leaks business text | Evaluation is transient; reports store only booleans/scores | Negative serialization tests |
| Missing cost silently becomes zero | Missing rows fail per target before relative comparison | Cost gate boundary tests |
| Multiple calls per Agent run are lost | All unique request rows for one trace are summed | Aggregation tests and live 429/163 call evidence |
| LLM judge should replace deterministic facts | Deterministic facts are stable and private; open-ended grading remains complementary | Plan scope and residual risks |

## Checks Rerun After Fixes

- Ruff and formatting: pass.
- Mypy strict: 35 source files, pass.
- Full pytest: 65 passed.
- Coverage: 90.81%.
- Contract snapshot, offline Shadow smoke, package build, Compose model, and diff checks: pass.
- Live three-run semantic and trace-cost gates: pass.

## Residual Risks

- Exact evidence terms require deliberate suite maintenance when business formatting changes.
- Open-ended RAG/analytics quality is not graded by deterministic order facts.
- OTel/LiteLLM exports may contain prompts; operators must export only the documented safe columns.
- LiteLLM local spend is an estimate, not invoice reconciliation.

## Verdict

Pass for deterministic semantic evidence and trace-attributed estimated-cost gating.
