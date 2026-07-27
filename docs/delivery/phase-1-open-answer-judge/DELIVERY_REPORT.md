# Delivery Report

## Outcome

Delivered a default-off, OpenAI-compatible open-answer Judge for Shadow v3. It scores only
criteria-bearing completed answers, stores no answer/prompt/rationale, enforces absolute and
relative quality thresholds, and fails closed on low scores, provider errors, or one-sided missing
baselines.

The local real-model gate correctly failed: candidate answers scored below threshold and the
retained service produced no comparable completed answers under local `llama3.1`. Edge cutover
remains unapproved.

## Requirement Coverage

| AC | Implementation evidence | Verification evidence | Status |
| --- | --- | --- | --- |
| AC-01 | `ShadowCase.judgeCriteria/judgeMinScore` | Validation tests | complete |
| AC-02 | Optional `judge` port and `--judge-enabled` | Default-off, configured-only, positive CLI tests | complete |
| AC-03 | `LiteLLMAnswerJudge` deterministic JSON request | Exact one-request HTTP test | complete |
| AC-04 | Stable low-score and error mappings | Negative evaluator/client tests | complete |
| AC-05 | Score-only sample/summary fields | Sensitive serialization tests | complete |
| AC-06 | Judge pass-rate and mean-score gates | Pure and integrated gate assertions | complete |
| AC-07 | `validate_judge_url` and remote flag | URL and CLI exit-2 tests | complete |
| AC-08 | RAG/analytics criteria in baseline | Candidate 6/6 scored; legacy comparability blocked by local model | conditional |
| AC-09 | Offline smoke and CI-equivalent commands | 85 tests, 91.33% coverage; all other gates pass | complete |

## Changed Files

- `src/agentscope_platform/evaluation/judge.py` - framework-independent Judge port/client.
- `src/agentscope_platform/evaluation/models.py`, `shadow.py`, `cli.py` - Shadow v3 wiring, metrics,
  gate, and operator configuration.
- `eval/baseline/readonly-cases.jsonl`, `scripts/shadow-smoke.py` - criteria and offline coverage.
- `tests/test_answer_judge.py`, `test_shadow_evaluation.py`, `test_shadow_cli.py` - contract,
  security, gate, and CLI tests.
- `docs/shadow-evaluation.md` and this delivery directory - operator and evidence documentation.

## Build And Test Results

- `uv run ruff check .`: pass.
- `uv run ruff format --check .`: pass.
- `uv run mypy src`: pass.
- `uv run pytest --cov=agentscope_platform --cov-fail-under=80`: 85 passed, 91.33%.
- Contract snapshot check, offline Shadow smoke, `uv build`, and Compose config: pass.
- Local three-run open-answer gate: fail as designed; candidate 0/6 Judge pass, legacy 0/6
  comparable completions.

## Code Review And QA Verdicts

- Review: conditional-pass, no confirmed high-severity finding.
- QA: conditional-pass; implementation passes, live model-quality/cutover gate fails.

## Documentation Changes

Documented suite schema, opt-in command, credentials, remote endpoint control, prompt-injection
boundary, provider retention risk, error semantics, thresholds, Shadow v3 fields, latency/cost
exclusions, and rollback.

## CI Changes And Validation

No workflow structure changed. Existing CI now exercises criteria-bearing cases with a deterministic
in-memory Judge through `scripts/shadow-smoke.py`; all underlying commands passed locally.

## Deviations From Plan

- The final live run focused on the two open-answer cases rather than all four baseline cases.
- The approved local 8B model could not produce a comparable retained baseline; this is recorded as
  blocked instead of weakening thresholds or claiming a pass.

## Rollout, Monitoring, And Rollback

- Rollout only in local/test with `--judge-enabled` and an approved data path.
- Monitor Judge evaluated count, pass rate, mean score, `JUDGE_ERROR`, and one-sided missing score.
- Roll back by omitting `--judge-enabled`; runtime Agent APIs and default Shadow behavior remain
  unchanged.

## Remaining Risks Or External Actions

- Select an approved stronger test Judge/model and rerun both targets three times.
- Review remote provider request-retention policy before sending business answers.
- Keep edge routing on legacy until the quality gate and the separate test-tenant rollback exercise
  pass.
