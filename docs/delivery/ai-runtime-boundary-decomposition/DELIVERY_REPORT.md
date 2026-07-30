# Delivery Report

## Delivered

- Split S3-compatible IAM into ingest-write and worker-read roles; removed source credentials from
  query and global Helm secrets.
- Added repeatable Compose/Helm production configuration checks and a real MinIO allow/deny smoke.
- Fixed orphan handling for legacy `agent.task`, including stale RUNNING tasks without a lease.
- Added Qdrant/embedding to Knowledge readiness.
- Completed Qdrant failure/recovery, concurrent ingestion/query, idempotency, tenant isolation,
  bounded soak, Knowledge canary/rollback and Agent whole-service rollback drills.
- Updated CI paths/checks and the production cutover runbook.
- Restored the final local topology to AgentScope plus combined Knowledge; the legacy Java Agent
  rollback container is stopped, while its image/config/data are retained.

## Release Decision

Local production-equivalent gate: **PASS**.

Actual production cutover: **CONDITIONAL NO-GO**. The remaining work is environmental and
operational: cloud IAM evidence, target-size capacity/autoscaling, a full peak-cycle soak, approved
canary tenants/thresholds, monitoring/on-call sign-off and a change record.

## Key Results

- 24/24 concurrent ingestion jobs READY; 8 identical submissions produced one job.
- 100/100 queries succeeded at concurrency 10; P95 0.240s and P99 0.250s.
- 120-second soak: 59/59 queries, five ingestions READY, no relevant restart.
- Knowledge combined/split/rollback and AgentScope/legacy/restore each returned valid business
  results; paid models were used for the Agent drill.
- Java full reactor: 1165 tests, 0 failures, 0 errors, 5 skipped.

## Rollback

- Stop new traffic and require zero PENDING/RUNNING tasks for the affected capability.
- Knowledge: route edge from split `knowledge-query` to combined `knowledge-service`.
- Agent: switch edge and interop together from AgentScope to the retained Java `agent-service`.
- Never replay an in-flight request automatically across backends.
- Keep old images, schema readers and task audit records for at least one complete rollback window.

Operational details:
`../langchain4j-platform/docs/平台工程/production-cutover-gates.md`.
