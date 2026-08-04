# Production Agent Hardening Review Report

## Review Decision

- Engineering scope: PASS
- Production cutover: NO-GO until the machine-readable external evidence gate passes
- Review date: 2026-08-03
- Scope: AgentScope orchestrator plus the affected security, async-task, workflow, interop, eval,
  deployment, migration and supply-chain surfaces in `langchain4j-platform`

The implementation satisfies AC-01 through AC-16 locally without changing the Java/Python ownership
boundary or the legacy `/agent/run` JSON contract. No open correctness, security, compatibility or
maintainability defect remains in the reviewed code scope. Target-cloud IAM, real restore, capacity,
peak-cycle soak, production canary, alert/on-call and change-approval evidence remain external release
blockers and are deliberately not represented as locally passed.

## Architecture And Contract Review

- AgentScope types remain under `infrastructure/agentscope/`; domain/application contracts are Pydantic,
  JSON Schema or Java protocol DTOs.
- Java retains authoritative task, workflow, business and persistence logic; Python adapters call it over
  governed HTTP/MCP boundaries.
- Checkpoints, A2A context, capability registry, trajectories and evaluation datasets use stable,
  language-neutral schemas. No caller token, grant, raw goal, model object or AgentScope state is persisted.
- Legacy capability and Agent run JSON shapes remain compatible; new execution versions use response
  headers and internal trajectory fields.
- Java eval-service only reads Python Shadow v4 summaries; it does not become a second Agent evaluator.

## Security Review

- Runtime budgets, one-time parameter-bound confirmation, strict service identities, owner isolation,
  callback SSRF/HMAC, stream redaction and database idempotency fail closed.
- Multi-replica work uses lease epoch/CAS/claim fencing; stale workers and relays cannot overwrite a new
  owner. Side-effect resume still requires the original idempotency digest and a fresh grant.
- Containers, service accounts, secrets, NetworkPolicy, database identities and supply-chain permissions
  follow least privilege. Security rollback never restores unlimited budgets, ordinary JWT worker access,
  arbitrary callback targets, plaintext push tokens or down migrations.
- Feedback import is consent-only/read-only, uses a strict minimal schema, masks common PII and drops the
  raw feedback identifier. Documentation explicitly states that this is not a substitute for DLP review.

## Reliability And Operations Review

- Shared HTTP pools, deadline propagation, bulkheads/circuits, readiness, low-cardinality metrics, durable
  sessions and central task fencing are aligned with declared failure semantics.
- Database evolution is externalized to versioned expand-contract migrations; applications have no DDL
  bootstrap path.
- The final runbook defines release ownership, stop thresholds, whole-service rollback, post-restore
  validation and explicit RPO/RTO targets.
- `agent-production-evidence.v1` defaults to NO-GO. The release validator requires all 19 checks to be
  PASS with owner, UTC observation time and HTTPS evidence before accepting `decision=GO`.

## Findings Resolved During Review

| Finding | Risk | Resolution | Evidence |
| --- | --- | --- | --- |
| Helm session/interop assertions read Deployment-only values from the global ConfigMap | False deployment-gate failure and ambiguous coverage | Moved assertions to the exact rendered Deployment documents, including quoted values | production cutover config gate PASS |
| Model version omitted gateway endpoint | Different configured gateways could share a model digest | Added gateway endpoint to the hashed model configuration; LiteLLM alias mapping remains external evidence | execution version tests |
| Per-tool version map accepted malformed names/digests | Non-reproducible or forged trajectory metadata | Added strict tool-name and SHA-256 validators | adversarial version test |
| Java report reader accepted unversioned reports | v3 or dataset-free evidence could enter a release archive | Reader now requires Shadow v4, dataset schema, ID and SHA-256 version | eval-service tests |
| Production evidence was prose-only | Incomplete evidence could be mistaken for GO | Added executable validator and default NO-GO template | runbook tests and CI step |

## Residual Risks And Required External Evidence

- Docker daemon was unavailable locally, so MySQL 8.4 Compose migration/permissions, live Redis
  CAS/failover and local image scanning were not rerun against real containers.
- GHCR OIDC push, Cosign/Rekor, provenance/attestation and unsigned-image admission require a real tag run
  and target registry/cluster.
- Real-model Shadow v4, adversarial quality/cost, consented production feedback import and identical-dataset
  replay require a named test environment.
- Target-node peak load/HPA, a complete business peak-cycle soak, cloud IAM, callback egress, dashboards,
  alerts, on-call, change approval, Redis/MySQL restore and whole-service rollback/restore require target
  environment evidence.

These are release blockers, not code defects. Production remains NO-GO until
`scripts/test_production_runbook.py --evidence <record> --require-go` exits 0.
