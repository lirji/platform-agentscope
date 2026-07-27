# Phase 1 Open Answer Judge Delivery Plan

## Requirement

Continue Phase 1 by adding an optional model-based quality gate for open-ended RAG and analytics
answers while preserving the Shadow report's no-answer-retention boundary.

## Repository Evidence

- The current Shadow evaluator can prove tool choice, completion, and deterministic answer facts,
  but RAG and analytics cases have no open-ended quality signal.
- The retained Java `eval-service` already treats LLM judge scoring as optional, deterministic
  (`temperature=0`), and default-off, with a default minimum score of 0.7.
- The Shadow evaluator keeps final answers only in process memory and excludes answers,
  observations, goals, URLs, and credentials from reports.
- The existing CLI accepts credentials only through environment variables and restricts network
  targets to local addresses unless explicitly opted in.

## Feasibility

- Verdict: go.
- Constraints:
  - Judge evaluation is default-off and opt-in at execution time.
  - Judge credentials are environment-only and judge endpoints inherit explicit local/remote
    network restrictions.
  - Reports store only score/pass/error metadata, never answers, criteria, prompts, or rationale.
  - A judge request is attempted once; failures fail the evaluated run closed.
- Risks and mitigations:
  - Prompt injection in an answer: delimit untrusted answer content and instruct the judge to
    evaluate it as data, returning schema-constrained JSON.
  - Self-grading bias: compare candidate and legacy with the same model/configuration and retain
    deterministic assertions for exact business facts.
  - Hidden cost: judge calls use separate traces and are explicitly excluded from Agent cost
    attribution.
  - Provider leakage: sanitize all judge failures to stable error codes.

## Product Design

- Actors and goals:
  - Migration engineers opt into a comparable score for answers that cannot be validated with
    exact terms alone.
  - Release reviewers see aggregate judge pass rate and mean score without accessing response
    content.
- Scope:
  - Optional suite criteria and per-case minimum score, OpenAI-compatible local judge client,
    sanitized report fields, absolute/relative gate metrics, CLI flags, tests, docs, and local
    live validation.
- Out of scope:
  - Persisted explanations, production judge traffic, human evaluation UI, and edge cutover.
- Business rules:
  - Cases without criteria are never sent to the judge.
  - Criteria are skipped when judge mode is disabled, preserving current default behavior.
  - In judge mode, malformed responses, timeout, or provider errors produce `JUDGE_ERROR`, score
    zero, and a failed run.
  - A judge score must meet the case threshold; otherwise the run fails with
    `JUDGE_SCORE_BELOW_THRESHOLD`.

## Acceptance Criteria

| ID | Observable behavior | Priority | Verification |
| --- | --- | --- | --- |
| AC-01 | Suite cases accept non-blank judge criteria and a 0..1 minimum score | P0 | Model validation tests |
| AC-02 | Judge mode is default-off and only criteria-bearing cases are judged | P0 | Evaluator and CLI tests |
| AC-03 | The judge client sends a deterministic schema-constrained request exactly once | P0 | HTTP client tests |
| AC-04 | Low score and provider/parse failures fail closed with stable sanitized errors | P0 | Negative evaluator tests |
| AC-05 | Reports contain judge score/verdict metrics but no answer, criteria, prompt, or credential | P0 | Serialization tests |
| AC-06 | Gate enforces candidate minimum and relative judge pass/score tolerances | P0 | Pure gate tests |
| AC-07 | Remote judge endpoints require a separate explicit opt-in | P0 | URL/CLI tests |
| AC-08 | RAG and analytics baseline cases define open-ended criteria | P1 | Suite inspection and live run |
| AC-09 | CI offline smoke and repository quality gates remain green | P0 | CI-equivalent local commands |

## UI/UX Design

- Applicability: not applicable; this is an operator CLI and JSON report contract.

## Technical Solution

- Add framework-independent `AnswerJudge`/`JudgeRequest`/`JudgeResult` types and an HTTPX
  OpenAI-compatible implementation under `evaluation/`.
- Extend suite, sample, summary, and thresholds with judge-only fields. Bump the Shadow report
  schema to version 3.
- Pass the answer to the judge only in memory after contract parsing. Store only the numeric score
  and stable verdict in `RunSample`.
- Add explicit `--judge-enabled`, endpoint/model/timeout, remote opt-in, and judge threshold flags.
  Read `SHADOW_JUDGE_API_KEY` only from the environment.
- Keep judge traffic on its own trace IDs so Agent cost attribution remains unchanged.

## Implementation Sequence

1. Models, judge client, evaluator wiring, and focused tests (AC-01..07).
2. CLI configuration, baseline criteria, offline smoke, and documentation (AC-02, AC-07..09).
3. Full review, local live judge run, QA evidence, and final report.

## Verification Plan

| AC/Risk | Test level | Case or command | Required evidence |
| --- | --- | --- | --- |
| AC-01..07 | Unit/integration | Judge/model/evaluator/CLI tests | Pass/fail, one request, no content leak |
| AC-08 | Local live | Old/new RAG and analytics judge run | Both targets evaluated; report sanitized |
| AC-09 | Repository | Ruff, format, Mypy, pytest, contracts, smoke, build, Compose | All pass |

## Documentation Plan

Update the Shadow runbook and delivery artifacts with configuration, security boundaries,
interpretation, cost exclusion, rollback, and live evidence.

## CI Plan

Exercise a deterministic in-memory judge in the existing offline Shadow smoke. Do not introduce
network calls or secrets into CI.

## Rollout And Rollback

- Rollout: add criteria to selected read-only cases, enable the judge only in local/test runs, and
  compare at least three repetitions before using the result for routing approval.
- Rollback: omit `--judge-enabled`; optional criteria remain inert and runtime Agent APIs are
  unchanged.

## Assumptions And Open Decisions

- The default per-case judge minimum remains aligned with the retained Java service at 0.7.
- The default candidate judge pass-rate minimum is 0.8; relative pass-rate and mean-score
  tolerances are 0.05.
- A shared judge model is a migration signal, not a substitute for deterministic facts or human
  review of high-risk answers.

## Approval

- Status: approved.
- Approved scope: continue the documented Phase 1 next action for open-ended scoring.
- Evidence: repeated user message “继续” on 2026-07-27 after the semantic/cost gate handoff.
