# Review Report

## Scope

Production cutover readiness for IAM, dependency failure recovery, concurrency/capacity, bounded
soak, canary, task drain and whole-service rollback.

## Findings

- Critical: none open in the local implementation.
- High fixed: S3 source credentials were globally shared across workloads.
- High fixed: stale `agent.task` records with `RUNNING` and a null lease could never be reaped.
- High fixed: Knowledge readiness did not include Qdrant/embedding and could admit traffic during
  Qdrant gRPC recovery backoff.
- Medium: the first uncontrolled 100-concurrent burst after dependency restart failed entirely.
  The explicit readiness dependency gate plus three successful business warm-ups now prevents that
  state from receiving traffic; target capacity still needs environment-specific tuning.

## Boundary And Security Review

- AgentScope ownership did not expand; it remains inference and orchestration only.
- S3, ingestion state, Vector/ES/Graph/Authz/Registry writes remain in Java.
- ingest and worker now receive distinct least-privilege S3 credentials; query receives none.
- Orphan recovery changes terminal state for auditability and does not delete task history.
- Rollback switches an entire backend after drain; no request-level silent fallback or replay was
  introduced.
- No production endpoint, production credential or production route was accessed.

## Residual Risks

- Local MinIO policies prove intended permissions, not the target cloud's identity binding.
- The 120-second soak is a bounded engineering check, not a full business-cycle endurance run.
- Target SLOs, peak concurrency and autoscaling limits are not inferable from the developer machine.
- Production canary needs named tenants, monitoring/alert ownership and change approval.
- Knowledge version GC remains disabled until separate real-sink failure testing is complete.

## Decision

Local release candidate: **PASS**.

Production default-route change: **NO-GO until the target-environment evidence above is attached**.
