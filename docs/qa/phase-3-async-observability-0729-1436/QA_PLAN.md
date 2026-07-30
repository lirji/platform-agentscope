# Phase 3 Async Observability QA Plan

## Scope

Retest `ASYNC-QA-001` on an isolated localhost topology and run the safest useful
follow-on gates: authenticated black-box metric scrapes, deterministic sync/async
comparison, and a bounded 30-second soak.

## Environment

- AgentScope service: `127.0.0.1:18085`
- Central async-task service: `127.0.0.1:18086`, in-memory store
- Model gateway: deterministic local stub on `127.0.0.1:14000`
- Authentication: synthetic QA-only HS256 token
- External services, production data, and paid model calls: none

## Acceptance Checks

1. Both metric endpoints reject an anonymous request with 401.
2. An authenticated Python scrape returns the submission, completion, and running series.
3. An authenticated Java scrape returns the orphan-failure series after an intentional
   unleased task is reaped.
4. Neither scrape contains task, tenant, user, prompt, result, or token labels.
5. Twelve deterministic synchronous and asynchronous runs match on `finalAnswer` and
   `stopReason`.
6. Eight tasks per batch run for at least 30 seconds with no failed task.

The soak is a local bounded regression check, not a production capacity claim.
