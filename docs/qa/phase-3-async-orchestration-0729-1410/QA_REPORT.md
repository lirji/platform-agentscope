# Phase 3 Async Orchestration QA Report

## Conclusion

**Conditional no-go for production cutover.**

The localhost release candidate passed the functional, security, persistence, crash,
reaper, webhook, rollback, response-loss, deterministic dual-run, and bounded-capacity
checks. One P1 observability defect remains: the Java Prometheus endpoint is absent and the
Python async counters use a no-op meter provider with no configured metric exporter.
Production traffic must not be switched until this is fixed and re-tested.

All localhost QA processes were stopped after evidence collection. The disposable MySQL
and Redis containers, including their synthetic test data, were removed.

Retest note (2026-07-29): `ASYNC-QA-001` was fixed and closed by the authenticated metrics
retest in `docs/delivery/phase-3-async-observability/QA_REPORT.md`. The production cutover
recommendation remains no-go because the separate real-model, shared-topology, alerting, and
gray-approval gates are still outstanding.

## Summary

| Result | Count |
|---|---:|
| Planned cases passed | 28 |
| Planned cases failed | 1 |
| Additional fault/capacity cases passed | 2 |
| P0 failures | 0 |
| P1 failures | 1 |

The first central health attempt returned 503 because the isolated profile omitted Redis,
while the shared Actuator health contributor requires it. Adding an isolated Redis target
made health return 200. This is classified as a corrected QA profile issue, not a product
failure.

## Functional And Security Results

- All five kinds (`agent.run`, `agent.dag`, `agent.dag-plan`, `agent.analyst`,
  `agent.process`) returned 202 and reached one `SUCCEEDED` terminal state.
- Every submission and task projection contained exactly the legacy ten fields.
- Missing, malformed, and expired internal tokens returned 401.
- A `qa-globex` caller received 404 for a `qa-acme` task and an empty list.
- The same-tenant list contract remained tenant-scoped, while non-Agent kinds were hidden
  by the Python facade.
- Duplicate task creation returned 409. Duplicate `eventKey` append returned the original
  sequence. Wrong-worker event/status writes and terminal progress writes returned 409.
- A deliberately slow execution cancelled to `CANCELLED`; its late model response did not
  overwrite the terminal state.
- Stored task input/result contained zero JWT-like token matches.

Evidence: `baseline-results.json`.

## SSE And Persistence

- The normal DAG stream emitted task-scoped IDs 1 through 11 in strictly increasing order.
- Reconnect after ID 1 replayed only IDs 2 through 11.
- After restarting the central Java process, both the terminal snapshot and all 11 events
  remained available from JDBC.
- A consumer delayed by 200 ms per non-empty SSE line still received all 11 events while
  the producer reached `SUCCEEDED`.

Evidence: `baseline-results.json`, `slow-sse-results.json`, `fault-results.json`.

## Crash And Reaper

- Python was killed with SIGKILL during a 20-second model request. The central task remained
  `RUNNING`, retained only the worker lease, and persisted no token field.
- With orphan reaping disabled, no central background transition occurred.
- Two Java instances then scanned the same JDBC store with short QA thresholds. Expired
  supported Agent tasks became `FAILED/ASYNC_TASK_ORPHANED`.
- The race task had exactly one terminal event. An unsupported kind remained `PENDING`.
  A fresh supported lease remained `RUNNING` during its valid lease and was reaped only
  after lease expiry plus grace.

Evidence: `reaper-targets.json`, `fault-results.json`.

## Webhook Outbox

- Success receiver: one call, outbox `DELIVERED`.
- Retry receiver: responses `503`, `503`, `204`; three calls, outbox `DELIVERED`.
- Dead receiver: three `503` responses; one tenant-scoped inspection row with
  `status=DEAD`, `attempts=3`.
- Every payload used the legacy ten fields and included the expected task/tenant headers.

Evidence: `webhook-results.json`.

## Rollback, Response Loss, And Capacity

- With `ASYNC_TASK_ENABLED=false`, async submission returned 503 while synchronous
  `/agent/run` remained 200 with `stopReason=DONE`; readiness remained 200.
- A fault proxy committed the central create and replaced its first response with 503.
  Python recovered by deterministic `taskId`, returned 202, leased the single row, and
  finished it as `SUCCEEDED`.
- Twelve local deterministic old-style sync/new async comparisons matched exactly.
- Forty concurrent localhost submissions were all accepted and all reached `SUCCEEDED`.
  Submission latency was p50 1316.81 ms, p95 1610.16 ms, max 1619.54 ms. These figures
  include a deliberately simple Python fault proxy and are not production capacity claims.

Evidence: `rollback-results.json`, `response-loss-results.json`,
`capacity-results.json`.

## Defect

### ASYNC-QA-001 — Async metrics are not externally observable

- Severity: P1 / Medium
- Reproduction:
  1. Execute async tasks and orphan/webhook paths.
  2. Request authenticated `GET /actuator/prometheus` from `async-task-service`.
  3. Request `GET /metrics` from the Python service.
- Actual:
  - Java returns 404; `/actuator` exposes only health and info.
  - The async module does not include a Prometheus registry dependency.
  - Python defines OpenTelemetry counters, but only tracing is configured; the default
    meter provider is no-op and no metric reader/exporter is installed.
- Expected: release metrics for submissions, completions, running work, heartbeat failures,
  orphan transitions, and webhook results are exported with low-cardinality labels.
- Impact: operators cannot prove heartbeat/reaper health or create production alerts, so
  the observability gate in the delivery plan cannot pass.

## Remaining Production Gates

The following were intentionally not claimed by this localhost run:

1. Real model/tool dual-run evaluation against the old platform and agreed quality thresholds.
2. Shared test/staging topology with load balancer, multiple Python workers, TLS/DNS, real
   Redis/MySQL failover, and actual webhook network policy.
3. Sustained soak/capacity testing with production-sized prompts, event bodies, concurrency,
   and database retention.
4. Alert verification after ASYNC-QA-001 is fixed.
5. Final gray-traffic and rollback approval; production `AGENT_URI` remains unchanged.

## Recommended Next Action

Fix ASYNC-QA-001 without changing the tested task contracts, add a black-box metrics
assertion to CI/staging, rerun this profile, and then proceed to real old/new dual-run and
sustained capacity testing. Keep both async execution and the orphan reaper disabled in
production until those gates pass.
