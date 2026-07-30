# Phase 3 Async Observability QA Report

## Conclusion

`ASYNC-QA-001` is closed. The corrective slice passes automated and isolated localhost
verification. Phase 3 remains a no-go for production gray cutover until real old/new targets,
shared infrastructure, alerting, and production-representative soak gates pass.

## Automated Gates

| Gate | Result |
| --- | --- |
| Contract snapshot | pass |
| Ruff check / format | pass |
| mypy | pass, 54 source files |
| Python tests | pass, 201 tests |
| Python coverage | pass, 89% (threshold 80%) |
| Offline shadow smoke | pass, 8 samples |
| Python package build / Compose validation | pass |
| Java affected reactor | pass |
| Java async-task-service | pass, 43 tests |
| Two-repository whitespace check | pass |

## Localhost Black-Box Results

- Python `/metrics`: anonymous 401, authenticated 200, Prometheus 0.0.4 content type.
- Java `/actuator/prometheus`: anonymous 401, authenticated 200.
- Python submission, successful completion, and running series were present.
- An intentionally unleased `agent.run` task was reaped and produced the Java
  `async_task_orphan_failed_total` series.
- Custom async series contained none of the prohibited task, tenant, user, prompt, result,
  or token labels.
- Twelve deterministic sync/async pairs matched on `finalAnswer` and `stopReason`.
- The bounded soak ran for 30.033 seconds: 240 submitted, 240 succeeded, zero failed,
  7.991 tasks/s. Submission p95 was 233.448 ms; end-to-end p95 was 312.898 ms.

Evidence: `docs/qa/phase-3-async-observability-0729-1436/results.json`.

## Corrected QA Assertion

The first run completed its workload but the final label assertion failed because a standard
Spring Kafka metric uses the bounded label `result="success"`. The privacy/cardinality rule is
for the custom async metrics. The test was narrowed to `agent_async_task_*` and
`async_task_*`, then rerun successfully.

## Environment And Cleanup

The profile used only loopback services, a deterministic local model stub, synthetic QA
tokens, and an in-memory central store. It made no paid model call and changed no shared or
production data. All processes were stopped; ports 14000, 18085, and 18086 were verified clear.

## External Gates Not Executed

- No `.env`, shadow token, candidate/legacy target, Judge key, or model gateway credential was
  available; expected old/new ports were not running.
- Therefore no real-model semantic/cost gate, shared MySQL/Redis multi-instance soak, alert
  delivery check, or gray-traffic approval is claimed.
- Production `AGENT_URI` remains unchanged and both async/orphan feature flags remain disabled
  by default.
