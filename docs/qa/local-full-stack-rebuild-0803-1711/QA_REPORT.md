# Local Full-Stack Rebuild QA Report

## Result

- Verdict: **PASS WITH FINDINGS** for the requested localhost rebuild, deployment, and
  unauthenticated page/authentication-entry inspection.
- Frontend: `http://localhost:8093` renders the capability console login page.
- Authentication entry: tenant `acme` redirects to the local Casdoor authorization page at
  `http://localhost:8000`; no credentials were entered.
- Runtime: all 16 probed HTTP endpoints returned their expected status, all 8 migration jobs
  exited `0`, and every running Compose container had restart count `0` at final verification.
- The local edge container resolves `AGENT_URI` to
  `http://agentscope-orchestrator:8085`; this is Compose-local routing only.
- This result is local QA evidence only. It does not change the production `NO_GO` decision or
  authorize production `AGENT_URI` mutation, canary, cutover, rollback, or deletion.

## Safety Boundary

- Only localhost Docker Desktop, the two local repositories, and their existing local Docker
  volumes were used.
- Existing uncommitted changes in both repositories were preserved. No reset, checkout,
  cleanup, `down -v`, image prune, volume deletion, or `--remove-orphans` was used.
- No production or shared environment was contacted.
- No model inference/business scenario was executed. A model-catalog availability preflight
  ran without an inference request.
- Secret values and authentication tokens are excluded from this report.

## Build Evidence

| Target | Result | Evidence / qualification |
| --- | --- | --- |
| AgentScope image | PASS | `docker compose -f compose.yml build orchestrator` built `agentscope-platform:local`. |
| Java reactor, documented command | FAIL | `mvn -DskipTests package` reached test compilation and failed in `platform-eventbus`: `ProcessedEventStoreTest` could not resolve `SchemaName` / `SchemaMigrationRunner`. |
| Java reactor, packaging-only fallback | PASS | `mvn -Dmaven.test.skip=true package` completed all 24 reactor modules. Test sources were not compiled or run in this fallback. |
| Full Compose image set | PASS after one retry | First build hit transient registry metadata `EOF` errors for public base images; one retry with bounded parallelism succeeded, including backend, migration, Elasticsearch, AgentScope, Vite, and nginx images. |

The exact Java command used by `deploy/start-all.sh` is therefore not green even though the
packaging-only fallback produced all required JARs. This is a reproducible deployment-automation
finding, not a successful test run.

## Deployment Evidence

The repository launcher was not invoked directly because it unconditionally passes
`--remove-orphans`, which would conflict with the requirement to preserve existing local
containers. Its build/environment/up sequence was reproduced manually without orphan removal.

The existing MySQL volume predated the current initialization SQL, so initial migrations failed
with missing `*_migrator` accounts. The repository's idempotent
`deploy/mysql/init/001-platform-databases.sql` was applied to the existing local MySQL instance;
all 8 migration jobs then exited `0`.

`analytics-service` subsequently exposed a second old-volume compatibility issue: the
`nl2sql_ro` account existed with a password different from the Compose development setting.
Because `CREATE USER IF NOT EXISTS` does not converge an existing account's password, the local
account was changed to the repository's documented development value and its existing SELECT
grant was reaffirmed. No application data or schema was deleted. `analytics-service` then
started and returned `UP`.

## Final Runtime Verification

| Probe | Expected | Actual |
| --- | ---: | ---: |
| Config `:8888/actuator/health` | 200 | 200 |
| Conversation `:8081/actuator/health` | 200 | 200 |
| Workflow `:8082/actuator/health` | 200 | 200 |
| Analytics `:8083/actuator/health` | 200 | 200 |
| Knowledge `:8084/actuator/health` | 200 | 200 |
| Async task `:8086/actuator/health` | 200 | 200 |
| Channel `:8087/actuator/health` | 200 | 200 |
| Interop `:8088/actuator/health` | 200 | 200 |
| Voice `:8091/actuator/health` | 200 | 200 |
| Auth `:8092/actuator/health` | 200 | 200 |
| Order `:8094/actuator/health` | 200 | 200 |
| Vision `:18090/actuator/health` | 200 | 200 |
| Edge `:18080/actuator/health` | 200 | 200 |
| AgentScope `:18085/health` | 200 | 200 |
| Frontend `:8093/` | 200 | 200 |
| Casdoor discovery `:8000/.well-known/openid-configuration` | 200 | 200 |
| Edge `/chat` without authentication | 401 | 401 |

- Migration jobs: 8 succeeded, 0 failed.
- Running Compose containers with nonzero restart count: 0.
- Older optional/orphan containers (`agent-service`, `eval-service`, split knowledge services,
  and MinIO helpers) remain stopped exactly as found; they are not part of the current base
  Compose startup and were deliberately not removed or restarted.

## Browser Verification

- Initial URL: `http://localhost:8093/`; the SPA redirected to
  `http://localhost:8093/login?redirect=/` as expected for an unauthenticated session.
- Page title: `能力展示与试用控制台`.
- Visible shell: capability-console branding, conversation/RAG, Agent orchestration,
  multimodal/voice descriptions, tenant input, and the Casdoor login button.
- Browser console: no application warnings or errors on the final local-console render.
- Empty tenant submission displayed the expected validation alert.
- Tenant `acme` redirected to the local OIDC authorization endpoint; the Casdoor page title was
  `Acme Tenant` and showed its password/code/WebAuthn/Face ID login options.
- No username, password, token, or other credential was entered. The final browser tab was
  returned to the capability-console login page and left open for manual inspection.

## Case Results

| ID | Result | Notes |
| --- | --- | --- |
| LRB-01 | PASS | Docker Desktop became reachable; existing volumes were retained. |
| LRB-02 | PASS | AgentScope local image rebuilt. |
| LRB-03 | FAIL / workaround PASS | Exact `-DskipTests` command fails test compilation; packaging-only fallback succeeded. |
| LRB-04 | PASS after retry | Full image set rebuilt after one transient registry retry. |
| LRB-05 | CONDITIONAL PASS | Manual non-destructive equivalent deployed; old-volume account bootstrap was required. |
| LRB-06 | PASS | Health, frontend, and unauthenticated 401 boundary matched expectations. |
| LRB-07 | PASS | Console and Casdoor pages rendered; final console had no browser error/warning. |
| LRB-08 | PASS | Stable startup failures were diagnosed and recorded; final base topology is healthy. |

## Findings

1. **P1 — documented Java packaging command is not currently reproducible.**
   `mvn -DskipTests package` still compiles tests and fails because the eventbus test source lacks
   the migration test classes on its test classpath. `start-all.sh` uses this exact command.
2. **P1 — existing MySQL volumes do not converge to the current local account bootstrap.**
   Init scripts run only on first initialization, and `CREATE USER IF NOT EXISTS` does not update
   an existing password. A previously initialized volume can therefore fail migrations and
   analytics startup until an operator manually reapplies account/grant state.
3. **P2 — the all-in-one local launcher always removes orphans.**
   This prevents using the launcher when stopped optional containers must be preserved. A
   non-destructive startup mode would make local recovery and inspection safer.

The public registry `EOF` was transient and succeeded on the required single retry, so it is
classified as an environment event rather than a product defect.

## Not Covered

- Authenticated business flows after Casdoor sign-in.
- Paid/remote model inference, RAG correctness, tool side effects, or async business execution.
- Production Kubernetes, workload identity, registry signing/attestation, canary, monitoring,
  restore, or rollback evidence.
