# Phase 3 Async Observability Review Report

## Decision

Corrective implementation is merge-ready. No open P0/P1/P2 code defect was found in the
metrics slice after remediation and full verification. This is not an approval to enable
production async traffic.

## Reviewed Scope

- Java registry dependency, exporter configuration, authentication filter behavior, and
  Spring integration test.
- Python meter-provider lifecycle, Prometheus text rendering, endpoint authentication,
  async metric call sites, and API tests.
- OpenAPI snapshot, CI reachability, runbook, rollback, and localhost QA evidence.

## Findings And Remediation

| Severity | Finding | Resolution |
| --- | --- | --- |
| P1 | Java exposed no Prometheus registry and Python used a no-op meter provider | Added the Java registry/export setting and a process-wide Python SDK reader plus authenticated endpoint |
| Test | Initial QA assertion scanned every Java built-in series and treated Kafka's bounded `result="success"` label as an async payload leak | Restricted the adversarial check to custom `async_task_*` series and reran the complete profile |
| None open | No remaining correctness, security, or compatibility defect in reviewed scope | Full gates and localhost black-box evidence pass |

## Security And Compatibility Review

- Both metric endpoints use the existing internal-token authentication path; health probes
  remain the only anonymous management surface.
- Custom metric labels are limited to `kind`, `status`, `event`, and `duplicate`. No task ID,
  tenant, user, prompt, result body, or token is emitted.
- AgentScope types remain inside the infrastructure adapter boundary.
- No task DTO, task state, SSE frame, webhook payload, feature-flag default, or production
  route changed.
- The added endpoint is represented in the generated OpenAPI snapshot and exercised by the
  existing CI test job.

## Residual Operational Risks

- Python metrics are process-local. Every worker/pod must be scraped directly; scraping one
  load-balanced instance is not a complete aggregate.
- Counter state resets on process restart, which Prometheus rate queries must handle.
- Alert routing and production-sized retention/load behavior require a shared test topology.
- The local deterministic model and in-memory central store are regression tools, not
  production performance evidence.
