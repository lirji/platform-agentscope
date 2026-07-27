# Delivery Report

## Outcome

A safe, reproducible old/new Agent Shadow evaluation CLI is complete. It changes no runtime API or
traffic route and is ready to run in an explicitly named test environment.

## Requirement Coverage

| AC | Implementation evidence | Verification evidence | Status |
| --- | --- | --- | --- |
| AC-01 | Paired sequential executor and repetitions | Mock and real-localhost HTTP tests | complete |
| AC-02 | `AgentRunReply` validation and stable failures | HTTP/contract/network/size tests | complete |
| AC-03 | Ordered expected and forbidden tool metrics | Deterministic tool tests | complete |
| AC-04 | Absolute, relative, contract, forbidden gates | Pure regression matrix | complete |
| AC-05 | Nearest-rank P95 and ratio/slack limit | P95 regression case | complete |
| AC-06 | Metadata-only report model | Secret/business-content assertions | complete |
| AC-07 | Local-only URL policy and explicit remote opt-in | URL security matrix | complete |
| AC-08 | Console entrypoint and exit codes | CLI integration tests | complete |
| AC-09 | CI offline paired-target smoke | Local CI-equivalent command | complete |

## Changed Files

- `src/agentscope_platform/evaluation/`: Shadow models, execution, metrics, gate, CLI.
- `scripts/shadow-smoke.py`: offline CI smoke.
- `tests/test_shadow_evaluation.py`, `tests/test_shadow_cli.py`: 18 focused tests.
- `.github/workflows/ci.yml`, `pyproject.toml`, `.gitignore`: pipeline, entrypoint, report hygiene.
- `docs/shadow-evaluation.md` and affected project/migration/testing docs.

## Build And Test Results

- 53 tests passed with 90.21% total coverage.
- Ruff, formatting, Mypy strict, contract drift, package build, shell syntax, Compose, and diff checks
  passed.
- Offline Shadow smoke passed with eight paired samples.

## Code Review And QA Verdicts

- Code review: pass; no unresolved high/medium finding.
- QA: conditional-pass because live model/platform testing is external.

## Documentation Changes

Added complete CLI security, environment, threshold, exit-code, report, CI, and rollout guidance.
Updated migration state without claiming production parity.

## CI Changes And Validation

GitHub Actions now executes the offline Shadow smoke after the coverage-gated test suite. It needs
no secret and contacts no remote service.

## Deviations From Plan

- Strengthened the initial relative-only gate with absolute floors and contract hard failures.
- Enforced expected tool order and added a response-size cap after adversarial review.

## Rollout, Monitoring, And Rollback

Run the CLI against old/new test targets, retain the sanitized report outside Git, and combine it
with Java eval-service semantic scoring plus LiteLLM cost evidence. Runtime rollback is unchanged
because this delivery does not modify routing.

## Remaining Risks Or External Actions

Test-environment dual-run, approved thresholds, cost comparison, edge shadow routing, and rollback
evidence are still required before production cutover.
