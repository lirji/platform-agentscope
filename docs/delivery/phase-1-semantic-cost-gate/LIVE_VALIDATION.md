# Live Validation Evidence

## Environment

- Date: 2026-07-27.
- Localhost retained Java services, candidate AgentScope, LiteLLM, Jaeger, and Ollama.
- Identity: short-lived `tenantA` internal token; value not persisted.
- Tracing: one unique W3C trace per target/case/run.
- Cost source: LiteLLM `litellm_request` response IDs joined to `LiteLLM_SpendLogs.request_id`.

## Semantic Defect And Retest

The first semantic run failed candidate order evidence at `0.857`: the answer used formatted amount
`1,200.00`, while the suite accepted only `1200`. This was an equivalent-format false negative, not
a missing fact. The assertion moved amount formats into one `anyOf` group; all other facts remain
required.

The full three-run retest passed:

| Target | Overall pass | Completion | Tool accuracy | Order evidence | Forbidden | P95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Legacy | 0.75 | 0.9167 | 1.00 | 3/3 | 3 | 20.215s |
| Candidate | 1.00 | 1.00 | 1.00 | 3/3 | 0 | 13.681s |

Legacy had one `MAX_STEPS` and three forbidden-tool samples. Candidate completed and passed all 12.

## Trace-Attributed Cost Gate

All 24 target runs had one or more cost rows. Multiple chat/embedding rows were aggregated by trace,
and unique request IDs prevented duplicate spend:

| Target | Runs measured | Model/embedding calls | Input tokens | Output tokens | Estimated USD |
| --- | ---: | ---: | ---: | ---: | ---: |
| Legacy | 12/12 | 429 | 112,948 | 5,853 | 0.01105914 |
| Candidate | 12/12 | 163 | 58,819 | 3,991 | 0.00360950 |

Default candidate limit was about USD 0.01482392, so the cost gate passed. Candidate estimated cost
was about 32.6% of legacy for this local run.

These values are LiteLLM price-table estimates over local Ollama traffic, not an external provider
invoice. They validate attribution and the relative gate, not billing reconciliation.

## Remaining Boundary

Only the order fixture has deterministic business-fact assertions. RAG and analytics remain
open-ended and still require Java eval-service/model-grader evidence before production cutover.
Actual edge test-tenant cutover/rollback is also external.
