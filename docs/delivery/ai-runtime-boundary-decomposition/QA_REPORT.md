# QA Report

## Result

- Local production-equivalent cutover gates: **PASS**
- Actual production cutover: **CONDITIONAL NO-GO**

The implementation and drill are release-ready, but localhost evidence cannot replace target-cloud
IAM audit, target-capacity results, a full peak-cycle soak, production canary approval and on-call
change control.

## Production Gate Evidence

| Gate | Result | Evidence |
| --- | --- | --- |
| S3 IAM | pass | ingest can write but not read; worker can read but not write/delete; query has no source credential |
| Failure injection | pass | Qdrant outage held job `15df16b5-430a-43ad-b179-3ccae6e0ba5d` at PARTIAL; cross-tenant GET returned 404; reconcile reached READY after recovery |
| Readiness recovery | pass | query readiness 200 → 503 while Qdrant stopped → 200 after recovery; three business warm-ups returned 200 with three hits each |
| Concurrent submit | pass | 24/24 accepted and all 24 READY |
| Idempotency | pass | 8 simultaneous identical requests resolved to one job ID |
| Query capacity | pass | 100/100 at concurrency 10; P50 0.162s, P95 0.240s, P99 0.250s |
| Tenant isolation | pass | globex query exposed none of the acme load/idempotency/resilience documents |
| Bounded soak | pass | 120s; 59/59 queries, P95 0.065s; 5/5 ingestions READY; no relevant container restart |
| Knowledge canary/rollback | pass | combined → split → combined, five hits at each stage |
| Agent rollback | pass | AgentScope → legacy Java → AgentScope; both paid-model calls HTTP 200 and backend headers matched |
| Task drain | pass | active Agent tasks were zero before and after; six stale legacy tasks preserved as `FAILED / ASYNC_TASK_ORPHANED` |

An uncontrolled 100-at-once query burst immediately after Qdrant restart produced 100 HTTP 500
responses while gRPC was in backoff. This was not discarded: readiness now explicitly includes
Qdrant and embedding, and the release procedure additionally requires three successful business
warm-ups before traffic resumes.

## Automated Regression

- Java full reactor: 23 modules, 1165 tests, 0 failures, 0 errors, 5 skipped.
- Production configuration gate: Compose merge, role separation, Knowledge route override,
  readiness membership, Helm lint/render all passed.
- Real MinIO IAM allow/deny smoke passed.
- Existing broad Python/frontend/authenticated Chrome regressions remain passed; this slice did not
  change their source.

## Reproducible Checks

```bash
bash deploy/test-production-cutover-config.sh
bash deploy/smoke-knowledge-s3-iam.sh
mvn test
```

Runbook:
`../langchain4j-platform/docs/平台工程/production-cutover-gates.md`.

## Required Target-Environment Evidence

1. Cloud IAM policy simulator or object-store audit log for the deployed workload identities.
2. Peak concurrency, resource headroom and autoscaling results on target node sizes.
3. At least one complete business peak-cycle soak.
4. Approved canary tenants, expansion thresholds, stop conditions, monitoring and rollback owner.
5. Change record and on-call confirmation before changing the production default route.
