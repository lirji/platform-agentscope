# Live Validation Evidence

## Environment

- Date: 2026-07-27.
- Scope: localhost only.
- Oracle: retained Java `agent-service` on `8085`.
- Candidate: `agentscope-platform` on `18085`.
- Shared dependencies: local LiteLLM, knowledge, analytics, order, async-task, workflow, MySQL,
  Redis, Qdrant, Elasticsearch, and Ollama host availability.
- Model route observed through LiteLLM: `deepseek-v4-flash`.
- Identity: short-lived HS256 internal test token for tenant `acme`; token is not persisted.
- Suite: four committed read-only cases, one run per case.

## Initial Run

Gate: fail.

| Target | Pass rate | Completion | Tool accuracy | Forbidden | P95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Legacy | 0.75 | 1.00 | 1.00 | 1 | 28.461s |
| Candidate | 0.75 | 0.75 | 1.00 | 0 | 13.603s |

The candidate analytics case executed the expected ordered tools but stopped at `MAX_STEPS`.
AgentScope counts reasoning and acting as separate iterations; the configuration had passed the
legacy action-step value directly to `ReActConfig.max_iters`.

## Repair

For a legacy budget of `n` decisions/actions:

- `n-1` tool actions plus a final reasoning answer require `2n-1` AgentScope iterations.
- `n` tool actions are still allowed, after which the framework returns `MAX_STEPS`.

The runner now applies `2n-1`, with regression assertions for 1, 4, and 8 action steps.

## Retest

Gate: pass with default thresholds.

| Target | Pass rate | Completion | Tool accuracy | Forbidden | P95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Legacy | 0.50 | 0.75 | 1.00 | 1 | 37.155s |
| Candidate | 1.00 | 1.00 | 1.00 | 0 | 39.531s |

Candidate cases:

- RAG: `DONE`, expected `rag_search` used.
- Order: `DONE`, only `order_query` used.
- Analytics: `DONE`, ordered `schema_explore` then `analytics_sql`.
- Current time: `DONE`, `current_time` used.

## Interpretation

This validates the real HTTP, authentication, model, AgentScope, event, tool, and retained-service
paths and proves the iteration-budget repair. It is not a production quality claim:

- one run per case is insufficient for non-deterministic statistics;
- the legacy result itself varied and used a forbidden analytics tool in the order case;
- RAG had empty/slow local data behavior and repeated model decisions;
- monetary cost was not joined into the report;
- edge routing and rollback were not exercised.

The next approval gate requires at least three runs per case under an explicitly accepted model-cost
budget, followed by cost evidence and a reversible route exercise.
