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

## Changed Files

- `src/agentscope_platform/evaluation/` - models, runner, gate, and CLI.
- `scripts/shadow-smoke.py` - deterministic offline paired-target smoke.
- `tests/test_shadow_evaluation.py`, `tests/test_shadow_cli.py` - unit/security/integration tests.
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
| Pytest with coverage gate | pass | 53 passed, 90.21% coverage |
| `uv run python scripts/shadow-smoke.py` | pass | 8 paired samples |
| Real localhost dual-target CLI integration | pass | Report written, exit 0 |
| Package build | pass | sdist and wheel |
| Shell syntax / Compose model / diff whitespace | pass | No issues |

## Decisions And Deviations

- Complement rather than replace the retained Java eval-service.
- Do not add `/agent/v2` routing before live gate evidence exists.
- Add absolute 80% floors and contract-error hard failures after review found that relative-only
  comparison could pass when both targets failed.
- Treat expected tools as an ordered subsequence, so schema-first cases cannot pass in reverse.

## Blockers And Residual Risks

- Real old/new model evaluation still needs an explicitly named test environment and credentials.
- Cost is not present in `/agent/run`; approve it from LiteLLM/platform metering evidence alongside
  this report.

## Next Action

Run `agentscope-shadow-eval` in a named test environment, approve thresholds and cost evidence, then
perform a reversible `/agent/v2` or façade shadow-routing exercise.
