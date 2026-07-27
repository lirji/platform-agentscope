# Delivery Status

## Goal

Provide a safe, repeatable old/new Agent shadow-evaluation gate without changing runtime routing.

## State

- Phase: delivery complete
- Status: complete
- Last updated: 2026-07-27

## Completed

- Repository, legacy agent contract, existing Java dual-run capability, and current evaluation
  fixture inspected.
- Feasibility, product behavior, technical solution, acceptance matrix, and approval recorded.
- Shadow models, paired HTTP runner, sanitized samples, metric summaries, and deterministic gate
  implemented (AC-01..07).
- CLI exit semantics, real-localhost integration test, and offline CI smoke implemented (AC-08..09).
- Adversarial review repaired false-pass and expected-tool-order defects.
- QA, documentation, CI synchronization, package build, and full regression completed.
- Post-delivery localhost live validation started the retained Java stack, LiteLLM, legacy Agent,
  and candidate AgentScope service against the same logical model and short-lived tenant identity.
- The first live gate exposed an AgentScope/legacy step-budget semantic mismatch; the mapping was
  repaired and the same four-case live gate then passed.

## Changed Files

- `src/agentscope_platform/evaluation/` - models, runner, gate, and CLI.
- `scripts/shadow-smoke.py` - deterministic offline paired-target smoke.
- `tests/test_shadow_evaluation.py`, `tests/test_shadow_cli.py` - unit/security/integration tests.
- `src/agentscope_platform/infrastructure/agentscope/runner.py`, `tests/test_runner.py` - preserve
  legacy action-step semantics over AgentScope reasoning/acting iteration accounting.
- `.github/workflows/ci.yml`, `pyproject.toml` - CI smoke and console entrypoint.
- `docs/shadow-evaluation.md`, README and migration/testing docs - operator guidance and state.
- `docs/delivery/phase-1-shadow-evaluation/` - delivery evidence.

## Verification Log

| Command or check | Result | Notes |
| --- | --- | --- |
| Repository and legacy source inspection | pass | `/agent/run`, eval dual-run, route boundaries |
| `uv lock --check && uv sync --frozen --dev` | pass | 114 packages checked |
| Contract snapshot check | pass | No drift |
| Ruff lint / format | pass | 65 files |
| `uv run mypy src` | pass | 33 source files |
| Pytest with coverage gate | pass | 54 passed, 90.22% coverage |
| `uv run python scripts/shadow-smoke.py` | pass | 8 paired samples |
| Real localhost dual-target CLI integration | pass | Report written, exit 0 |
| Package build | pass | sdist and wheel |
| Shell syntax / Compose model / diff whitespace | pass | No issues |
| Live Shadow run before iteration fix | fail | Candidate analytics stopped at `MAX_STEPS`; 75% completion |
| Focused runner regression | pass | Legacy 1/4/8 steps map to AgentScope 1/7/15 iterations |
| Live Shadow retest after fix | pass | Candidate 4/4 complete, 100% tool accuracy, no forbidden tool |

## Decisions And Deviations

- Complement rather than replace the retained Java eval-service.
- Do not add `/agent/v2` routing before live gate evidence exists.
- Add absolute 80% floors and contract-error hard failures after review found that relative-only
  comparison could pass when both targets failed.
- Treat expected tools as an ordered subsequence, so schema-first cases cannot pass in reverse.
- Translate a legacy action-step budget `n` to `2n-1` AgentScope iterations: AgentScope counts
  reasoning and acting separately, while the legacy loop counts one decision/action per step.

## Blockers And Residual Risks

- Real old/new model evaluation still needs an explicitly named test environment and credentials.
- Cost is not present in `/agent/run`; approve it from LiteLLM/platform metering evidence alongside
  this report.
- The live retest used one run per case. At least three repeated runs are still required before a
  statistical quality/latency decision.

## Next Action

Repeat the live suite at least three times under an approved cost budget, approve thresholds and
cost evidence, then perform a reversible `/agent/v2` or façade shadow-routing exercise.
