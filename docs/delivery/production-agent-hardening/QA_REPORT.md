# Production Agent Hardening QA Report

## Decision

- Local engineering QA: PASS
- Production release QA: CONDITIONAL / NO-GO pending external evidence
- Environment: macOS, Python 3.12/uv, Java 21/Maven; Docker CLI available, Docker daemon unavailable
- Date: 2026-08-03

## Acceptance Matrix

| AC | Verified behavior | Result | Primary evidence |
| --- | --- | --- | --- |
| AC-01 | finite run/token/model budgets and stable termination | PASS | settings/runner and full regression |
| AC-02 | one-time, short-lived, parameter/identity/idempotency-bound confirmation | PASS | tamper/replay/Redis failure tests |
| AC-03 | provider-specific short credentials; strict JWT policy | PASS | Python/Java JWT and client tests |
| AC-04 | tenant+owner control plane and service-only worker plane | PASS | controller/store/cross-owner tests |
| AC-05 | callback SSRF/DNS/redirect policy and isolated HMAC keys | PASS | policy/outbox/push and deployment gates |
| AC-06 | stream PII/error redaction and cancellation semantics | PASS | Python/Java stream tests |
| AC-07 | database-unique transactional workflow idempotency | PASS | concurrent conflict/rollback tests |
| AC-08 | pooled HTTP, deadline, bulkhead/circuit and safe degradation | PASS | lifecycle/concurrency/fault tests |
| AC-09 | lease epoch, CAS/claim fencing, recovery and drain | PASS | multi-owner/stale-writer/outbox tests |
| AC-10 | required-dependency readiness and runtime/task metrics | PASS | readiness and Prometheus tests |
| AC-11 | least-privilege runtime, network, secrets, HA primitives | PASS | Compose/Helm hardening gate |
| AC-12 | external versioned expand-contract migrations | PASS locally; live MySQL pending | H2/reactor/static gates |
| AC-13 | locked CI, SBOM, scanning, OIDC signing/attestation design | PASS locally; real release pending | supply-chain gates/build |
| AC-14 | durable neutral session/A2A context/capability registry | PASS; live Redis pending | contract/store/API/interop tests |
| AC-15 | content-addressed trajectory, dataset/replay/adversarial/feedback | PASS; real-model run pending | v4/CLI/version-drift/eval tests |
| AC-16 | executable release/monitor/rollback/RPO/RTO/evidence runbook | PASS locally; external checks pending | runbook validator and template |

## Final Local Verification

| Check | Result |
| --- | --- |
| Python Ruff / format | PASS |
| Python Mypy | PASS, 87 source files |
| Python contract export | PASS |
| Python full pytest | PASS, 470 tests |
| Python coverage | PASS, 89.60% (85% gate) |
| Shadow smoke / adversarial dataset digest | PASS, 8 samples / valid SHA-256 |
| Python package build | PASS, sdist and wheel |
| AgentScope Compose render | PASS |
| Java eval-service reactor | PASS, 64 tests |
| Java full Reactor | PASS, 268 reports / 1262 tests / 0 failures/errors / 9 skipped |
| Java production/runtime/migration/supply-chain static gates | PASS |
| Both repository diff checks | PASS |

## Not Run Locally

- MySQL 8.4 Compose migration, permissions and idempotent rerun;
- live Redis multi-replica CAS/TTL/restart/failover;
- Docker image build/Trivy for the final diff;
- real GHCR tag release, Cosign/Rekor/SLSA/SBOM attestation and admission rejection;
- target cloud IAM, backup/PITR restore, peak capacity/HPA, full peak-cycle soak;
- production Shadow v4/adversarial/feedback replay, tenant canary, dashboards/alerts/on-call and rollback.

The machine evidence template keeps these items PENDING and the decision NO-GO. Local PASS must not be
used to edit them to PASS without their target-environment artifacts.
