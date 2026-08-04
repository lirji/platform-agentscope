# Target Environment Evidence Audit

## Decision

- Observed at: `2026-08-03T09:01:42Z`
- Scope: read-only discovery of target-environment and public release evidence
- Result: **NO-GO / 19 required checks remain PENDING**

This audit is a discovery record, not a release evidence file. It must not be used as a
substitute for a named target environment, release owner approval, immutable image digests,
or the 19 target-environment artifacts required by
`docs/operations/production-release-runbook.md`.

## Safety Boundary Applied

- No production or shared test URL was inferred from placeholders or local development files.
- No token, password, production address, user content, or raw feedback was read into this report.
- No deployment, tag publication, image push, canary, traffic change, rollback, deletion, or data
  mutation was performed.
- Production `AGENT_URI` and `AGENT_BASE_URL` were not changed.
- Both repositories' pre-existing dirty worktrees were preserved.

## Access And Target Discovery

| Check | Observed result | Release impact |
| --- | --- | --- |
| Docker daemon | Unavailable; Docker socket does not exist | Cannot run real MySQL 8.4, Redis, image build, or local Trivy evidence |
| Kubernetes contexts | Only local `docker-desktop` is configured | No named target cluster or workload identity evidence is reachable |
| GitHub CLI | No authenticated GitHub host | Cannot inspect private environments, registry packages, attestations, or protected artifacts |
| Target URLs | No named test/candidate URL is present in repository configuration or process environment | Black-box target API, Shadow v4, adversarial, readiness, and canary checks are blocked |
| Release evidence instance | Only `production-evidence-template.json` exists | Release ID, owners, timestamps, evidence URIs, and candidate/rollback digests are unresolved |

The existing `docs/qa/QA_PROFILE.md` authorizes localhost and disposable Docker QA only. It does
not name a shared or production-like target. Therefore no remote API test was executed.

## Public Remote Evidence

The following public metadata was checked without authentication:

| Repository | Remote `main` | Tags / releases / deployments | Latest relevant workflow |
| --- | --- | --- | --- |
| `lirji/platform-agentscope` | `722fcc9d82bc7dde7b47af3d5b545979158adb33` | 0 / 0 / 0 | [CI run 30524235282](https://github.com/lirji/platform-agentscope/actions/runs/30524235282) failed at `Format check` |
| `lirji/langchain4j-platform` | `d83607d7d8d12e74a3bdd3fa1abce2182b63a2a2` | 0 / 0 / 0 | [AgentScope Cutover CI run 30524252057](https://github.com/lirji/langchain4j-platform/actions/runs/30524252057) failed at `Verify Bailian multimodal providers` |

Both remote SHAs equal the clean base commit under the current local dirty worktree. The
AC-01～AC-16 delivery is not represented by an immutable remote candidate commit or image digest.
The checked failed runs exposed no downloadable artifacts, and the remote workflow inventory does
not yet contain the uncommitted supply-chain release workflows. These runs therefore cannot be
attached as PASS evidence for the current delivery.

## Required Evidence Inventory

| Evidence ID | Status | Missing target evidence or authority |
| --- | --- | --- |
| `release.change_approval` | PENDING | Approved change record, release owner, release window, candidate and rollback versions |
| `release.oncall` | PENDING | Named on-call, incident commander, escalation test, and acknowledgement |
| `supply_chain.signature` | PENDING | Tagged candidate/rollback digests, Cosign/Rekor signature, provenance, and admission verification |
| `supply_chain.sbom_scan` | PENDING | Digest-bound SBOM, HIGH/CRITICAL scan result, and rejected unsigned/failed artifact evidence |
| `iam.workload_identity` | PENDING | Target account/cluster service-account binding and least-privilege audit |
| `security.egress_callbacks` | PENDING | Target NetworkPolicy/firewall, exact callback allowlist, DNS/SSRF, redirect, and HMAC observations |
| `database.migration` | PENDING | Real MySQL 8.4 Flyway expand/validate/idempotency run and proof that app identities have no DDL |
| `recovery.redis_restore` | PENDING | Isolated snapshot/AOF restore with measured RPO/RTO, owner isolation, CAS, TTL, lease, and grant replay checks |
| `recovery.mysql_restore` | PENDING | Isolated backup/PITR restore with measured RPO/RTO and task/outbox/idempotency/Flowable validation |
| `capacity.peak` | PENDING | Approved load model, target-sized load run, latency/error/cost/resource measurements |
| `capacity.autoscaling` | PENDING | Target HPA scale-out/scale-in and saturation/failure observations |
| `soak.peak_cycle` | PENDING | One complete business peak cycle with no task loss and stable backlog/resources |
| `evaluation.shadow_v4` | PENDING | Version-bound candidate/baseline v4 report and same-dataset replay from named URLs |
| `evaluation.adversarial` | PENDING | Target run of the approved adversarial dataset with forbidden-behavior assertions |
| `security.tenant_isolation` | PENDING | Named synthetic/canary tenants and cross-tenant API/audit observations |
| `canary.tenant` | PENDING | Authorized named tenant, staged observation records, stop thresholds, and owner sign-off |
| `observability.dashboard_alert` | PENDING | Dashboard snapshots, alert delivery exercise, and on-call acknowledgement |
| `rollback.full_service` | PENDING | Authorized full-service drain and route rollback rehearsal with immutable rollback digest |
| `rollback.post_restore` | PENDING | Independent evidence that the candidate can be restored after rollback without stale writers or replay |

## Machine Gate Verification

The current runbook static gate passes:

```text
production runbook static gate passed
```

The release gate against the default template exits `1` with `production release gate NO-GO`.
It rejects the unresolved release ID, candidate digest, rollback digest, `decision=NO_GO`, and all
19 PENDING checks with missing owner, UTC observation time, and HTTPS evidence URI. No field was
changed to manufacture a GO result.

## Exact Inputs Needed To Continue

1. A named non-production target base URL and confirmation that black-box requests and real-model
   cost are authorized, or an authenticated target Kubernetes context with its allowed namespaces.
2. The candidate and rollback immutable image digests plus the tagged GitHub release workflow URL.
3. A release evidence JSON path outside source-controlled secrets, with release/check owners and
   HTTPS evidence store locations.
4. Explicit production change authorization before any canary, traffic mutation, full-service
   rollback, or post-restore routing exercise.

Until items 1～3 are available, safe progress is limited to evidence discovery. Item 4 remains a
separate approval gate even after the machine evidence becomes GO.
