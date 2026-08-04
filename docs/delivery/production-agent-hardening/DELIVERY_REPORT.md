# Production Agent Hardening Delivery Report

## Outcome

AC-01 through AC-16 are implemented, reviewed, tested and documented across AgentScope and the affected
Java platform modules. The codebase is ready for a controlled target-environment qualification. It is not
authorized for production cutover until the external evidence record passes the executable GO gate.

## Delivered

- Bounded Agent execution, governed side effects and strict cross-service identity.
- Owner-isolated async control plane, worker fencing, durable outbox recovery and safe drain.
- Callback SSRF/signing, stream privacy/cancellation, workflow idempotency and HTTP resilience.
- Readiness, SLO-oriented metrics, hardened Compose/Helm, least-secret networking and HA primitives.
- Externalized expand-contract database migrations and trusted SBOM/scanned/signed release workflows.
- Language-neutral durable sessions, A2A context, capability registry and Redis last-known-good recovery.
- Content-addressed prompt/model/tool trajectories, Shadow v4, versioned datasets, strict replay,
  adversarial fixtures and consented/read-only feedback import.
- Unified production runbook with monitoring/stop thresholds, whole-service rollback, Redis/MySQL recovery,
  RPO/RTO targets and a machine-readable 19-check evidence gate.

## Compatibility And Ownership

- Java remains authoritative for business data, transactions, async tasks, workflow and side effects.
- AgentScope framework objects stay in the infrastructure adapter.
- Existing `/agent/run` JSON and legacy capability projection remain compatible.
- New cross-process state is versioned and language neutral; secrets and raw user/model content are not
  used as persistent control-plane state.
- Legacy Java Agent is retained as an explicit whole-service rollback target; there is no per-request
  automatic fallback or replay.

## Verification Summary

- AgentScope: Ruff, format, Mypy (87 source files), contract export, 470 tests with 89.60% coverage,
  Shadow smoke, dataset validation, package build, Compose render, supply-chain/runbook gates and diff
  check passed.
- Java: affected module tests, full Reactor, Helm/Compose production gate, runtime hardening, migration,
  supply-chain and diff checks passed.
- Detailed command history and counts are in `DELIVERY_STATUS.md`; test scope and omissions are in
  `QA_REPORT.md`; adversarial review and residual risks are in `REVIEW_REPORT.md`.

## Release And Rollback

Follow `docs/operations/production-release-runbook.md`. A release record must contain immutable candidate
and rollback digests, approved dataset/report versions, named owners, stop thresholds and all external
evidence. Canary progresses by named tenant/cohort and cannot skip stages.

Rollback is: stop expansion and new submissions, drain or explicitly terminate PENDING/RUNNING work,
verify the previous trusted digest, start/probe Java, switch edge+interop together, validate only new
requests, preserve sessions/outboxes/audit/schema, then separately exercise restoration to AgentScope.
Security controls and expanded schema are not destructively rolled back.

## Production Decision

Current decision: **NO-GO for production cutover** because real IAM, restore, capacity, full peak-cycle
soak, canary, alerts/on-call, signed registry/admission and whole-service target-environment evidence are
not available in this workspace.

To qualify a release, copy `docs/operations/production-evidence-template.json`, attach real HTTPS evidence,
set `decision=GO` only after approval, and run:

```bash
uv run python scripts/test_production_runbook.py \
  --evidence REPLACE_WITH_RELEASE_EVIDENCE_PATH \
  --require-go
```

Exit code 0 permits a release decision meeting; it does not itself execute a deployment.
