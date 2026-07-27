# Delivery Status

## Goal

Add a default-off, sanitized model judge gate for open-ended RAG and analytics Shadow answers.

## State

- Phase: delivery complete
- Status: complete
- Last updated: 2026-07-27

## Completed

- Read repository rules and the prior semantic/cost delivery state.
- Inspected the retained Java judge and current Python Shadow evaluator, CLI, suite, tests, and CI.
- Recorded feasibility, product rules, technical design, acceptance criteria, verification, and
  rollback.
- Implemented the default-off Judge client, Shadow v3 models/gates, CLI controls, suite criteria,
  offline smoke, and focused tests.
- Completed review, full regression, documentation, local real-model QA, and safe cleanup.

## Changed Files

- `docs/delivery/phase-1-open-answer-judge/DELIVERY_PLAN.md` - approved design.
- `docs/delivery/phase-1-open-answer-judge/DELIVERY_STATUS.md` - workflow state.
- `src/agentscope_platform/evaluation/` - Judge transport and Shadow v3 gate.
- `eval/baseline/readonly-cases.jsonl`, `scripts/shadow-smoke.py` - criteria and CI smoke.
- `tests/test_answer_judge.py`, `tests/test_shadow_evaluation.py`, `tests/test_shadow_cli.py` -
  focused evidence.
- `docs/shadow-evaluation.md` and delivery evidence - operator and release guidance.

## Verification Log

| Command or check | Result | Notes |
| --- | --- | --- |
| Repository/status inspection | pass | Clean baseline at `67d71ec` |
| Retained Java judge inspection | pass | Default-off, temp=0, score threshold 0.7 |
| Focused Judge/Shadow/CLI tests | pass | 40 tests after final CLI coverage |
| Full CI-equivalent quality gate | pass | 85 tests, 91.33% coverage |
| Local open-answer gate | fail-safe | Candidate 6/6 evaluated but 0 passed; legacy not comparable |
| Validation stack cleanup | pass | Only unrelated Apollo/Open WebUI containers remain |

## Decisions And Deviations

- Use a schema-constrained OpenAI-compatible HTTP client rather than importing AgentScope into the
  evaluation domain.
- Give remote judge access its own opt-in rather than reusing target opt-in.
- Keep the failed local quality result; do not relax thresholds to manufacture a pass.

## Blockers And Residual Risks

- Local `llama3.1` is not a release-quality baseline: retained cases did not complete and candidate
  scores failed.
- Local `qwen3:14b` qualification also failed: open-answer generations repeatedly hit the local
  120-second inference timeout and the calibration was terminated without a report.
- A remote/stronger-model rerun needs explicit data-retention and network approval.

## Next Action

Commit the completed implementation. Keep edge routing unchanged; next obtain an approved stronger
test model and rerun the open-answer gate before any test-tenant cutover.
