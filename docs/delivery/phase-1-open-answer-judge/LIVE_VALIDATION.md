# Live Validation Evidence

## Environment

- Date: 2026-07-27.
- Scope: localhost only; no remote model or production endpoint.
- Targets: retained Java `agent-service` and candidate `agentscope-platform`.
- Model and judge: LiteLLM v1.74.3 using local Ollama `llama3.1` through its OpenAI-compatible
  `/v1` endpoint.
- Identity: short-lived `tenantA` internal JWT; value was not persisted.
- Cases: RAG refund policy and analytics trend, three runs per target/case.
- Report: ignored local artifact `reports/open-answer-judge-live.json`; contains scores and stable
  errors only.

## Environment Corrections

The first full attempt used a token without candidate-required `uid` and `exp`; candidate correctly
returned 401. A calibration attempt then exposed an old LiteLLM `ollama/` adapter failure on
AgentScope's OpenAI content arrays. Neither result is product-quality evidence.

The final run used a valid short-lived identity and the same local model through Ollama's native
OpenAI endpoint. A candidate time probe returned HTTP 200, `DONE`, and `current_time` before the
scored run.

## Final Open-Answer Run

The gate rejected the local model result:

| Target | Runs | Completion | Tool accuracy | Judge evaluated | Judge pass | Mean score |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Legacy | 6 | 0.00 | 0.75 | 0/6 | not comparable | n/a |
| Candidate | 6 | 1.00 | 0.75 | 6/6 | 0/6 | 0.0833 |

Candidate RAG scores were `0.0`, `0.0`, and `0.5`. Candidate analytics scores were all `0.0`;
those samples selected `schema_explore` but omitted `analytics_sql`. The Judge recorded
`JUDGE_SCORE_BELOW_THRESHOLD` or the earlier tool error and did not persist answer text or
rationale.

The retained Java Agent did not produce a `DONE` result for any open-answer sample under this local
8B model (`LOOP`/`MAX_STEPS`), so the gate also emitted
`judge_score regression: one target has no evaluated score`. Missing baseline scores were not
treated as a pass.

## Verdict

- Judge transport, opt-in, scoring, threshold enforcement, sanitization, and fail-closed comparison:
  validated.
- Model-quality gate for this local profile: fail.
- Edge cutover: not approved.

The rejected result is useful evidence: the feature prevents a low-quality or non-comparable model
profile from being promoted. A release-quality rerun needs an approved test model that can complete
both retained and candidate cases; remote use also requires data-retention approval.

## Additional Local Model Qualification

After the implementation commit, the already-installed local `qwen3:14b` was tested as a possible
way to remove the model-quality blocker without networking. A time-tool probe completed, but the
open-answer calibration was not viable:

- Qwen's default thinking output exhausted a 32-token JSON Judge response without producing
  content, so the local profile kept `llama3.1` as the Judge and used Qwen only for Agent calls.
- Open-answer Agent generations repeatedly reached Ollama's 120-second request timeout.
- The calibration produced no report after more than the configured target timeout and was
  explicitly terminated; outstanding local requests were cancelled and all temporary services
  were stopped.

This second local profile is also disqualified. It does not change the implementation verdict or
the committed gate result; it narrows the remaining action to an explicitly approved,
release-capable test model and data path.
