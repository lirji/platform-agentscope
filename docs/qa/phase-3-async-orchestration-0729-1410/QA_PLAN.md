# Phase 3 Async Orchestration QA Plan

## Scope

Black-box validation of the approved Phase 3 asynchronous orchestration implementation:
the five Python submission endpoints, the central JDBC task/event authority, tenant
isolation, SSE replay, cancellation, recovery, orphan reaping, webhook outbox behavior,
observability, and rollback controls.

The user approved this execution sequence before the plan was materialized. Live actions
remain restricted to the localhost profile in `../QA_PROFILE.md`; no external-cost
dependency is used.

## Preconditions

1. Start a disposable MySQL 8.4 container on host port `13316`.
2. Start `async-task-service` on port `18086` with JDBC, webhook off, and orphan reaper off.
3. Start a deterministic OpenAI-compatible model/webhook stub on port `14000`.
4. Start the Python service on port `18085` with async enabled.
5. Generate short-lived signed tokens for `qa-acme/alice`, `qa-acme/bob`, and
   `qa-globex/eve`; never persist the token values in the repository.

## Test Cases

| ID | Priority | Scenario | Expected result |
|---|---:|---|---|
| ENV-01 | P0 | All service health/readiness endpoints | HTTP 200; Python reports model configured |
| SEC-01 | P0 | Protected endpoint without a token | HTTP 401 |
| SEC-02 | P0 | Invalid and expired tokens | HTTP 401 |
| SEC-03 | P0 | Same task queried by another tenant | HTTP 404 and no task data |
| SEC-04 | P0 | Same-tenant different user lists tasks | Tenant contract is preserved without cross-tenant leakage |
| CT-01 | P0 | Submit `agent.run` async | HTTP 202 and exact legacy ten-field task projection |
| CT-02 | P0 | Submit explicit `agent.dag` async | Unique terminal success; progress events are persisted |
| CT-03 | P0 | Submit `agent.dag-plan` async | Unique terminal success; plan/DAG progress is visible |
| CT-04 | P0 | Submit `agent.analyst` async | Unique terminal success |
| CT-05 | P0 | Submit read-only `agent.process` async | Unique terminal success; no mutating workflow call |
| CT-06 | P1 | Central non-Agent kind under same tenant | Hidden from Python list/get projection |
| LIFE-01 | P0 | Cancel a deliberately slow running task | Exactly one `CANCELLED` terminal state; late success does not win |
| LIFE-02 | P0 | Duplicate central `taskId` create | Second create is HTTP 409 and original task is unchanged |
| LIFE-03 | P0 | Wrong worker updates/appends events | HTTP 409 |
| LIFE-04 | P1 | Duplicate `eventKey` append | Idempotent response; no duplicate journal record |
| LIFE-05 | P1 | Progress append after terminal state | HTTP 409 |
| SSE-01 | P0 | Stream task from submission through terminal state | Monotonic task-scoped IDs and one terminal lifecycle event |
| SSE-02 | P0 | Reconnect with `Last-Event-ID` | Only later persisted events are replayed |
| SSE-03 | P1 | Slow/short-lived SSE consumer | Producer finishes; persisted events remain replayable |
| DB-01 | P0 | Restart central service | Task snapshots and event replay survive the restart |
| CRASH-01 | P0 | Kill Python during a slow task with reaper disabled | Task remains recoverable and token is absent from persistence |
| REAPER-01 | P0 | Enable reaper with short QA thresholds | Stale supported Agent task becomes `FAILED/ASYNC_TASK_ORPHANED` |
| REAPER-02 | P0 | Unsupported kind and fresh leased task | Neither is reaped |
| REAPER-03 | P1 | Two central instances scan the same DB | Atomic transition produces one terminal event |
| WH-01 | P0 | Terminal task webhook succeeds | Legacy payload/headers observed once and outbox becomes delivered |
| WH-02 | P1 | Receiver fails before succeeding | Bounded retry occurs and no dead row remains |
| WH-03 | P1 | Receiver always fails | Outbox reaches dead state and inspection endpoint exposes the row |
| OBS-01 | P1 | Prometheus scrape after execution/reaping/webhook | Expected low-cardinality counters are present |
| RB-01 | P0 | Restart Python with `ASYNC_TASK_ENABLED=false` | Async submission is HTTP 503 while sync execution still succeeds |

## Fault Injection Order

1. Validate the normal five-kind path and security boundary.
2. Exercise cancellation and SSE reconnect.
3. Restart only the central Java process and validate JDBC/event recovery.
4. Kill only the Python process during a slow task.
5. Restart central with short reaper thresholds; then add a second instance for the race.
6. Restart central with webhook enabled and exercise success, retry, and dead-letter paths.
7. Restart Python with async disabled for rollback validation, then restore the enabled
   localhost configuration.

## Evidence

Store redacted request/response JSON, SSE captures, service logs, process IDs, and SQL query
results in this directory. Raw JWTs and the disposable database password must not appear in
evidence. Each failure is retried once, with both observations recorded.

## Exit Criteria

- All P0 cases pass, or each failure has a reproducible bug record and production remains
  explicitly no-go.
- No cross-tenant data is disclosed.
- Each tested task has at most one terminal lifecycle event.
- Crash recovery, reaper scope, and rollback controls are evidenced.
- The final QA report states which external production gates remain untested.
