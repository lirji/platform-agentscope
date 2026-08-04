# Local Full-Stack Rebuild QA Plan

## Scope And Approval

- Target: localhost Docker Compose only.
- User approval: the 2026-08-03 request explicitly authorizes rebuilding, packaging, deploying,
  and inspecting the local AgentScope and langchain4j-platform applications.
- Existing volumes will be preserved. No `down -v`, image pruning, data deletion, production route
  mutation, production API, or shared test environment is in scope.
- External-model business calls are excluded; this run validates build, startup, health, routing,
  authentication entry, and page rendering without incurring model cost.

## Environment

- AgentScope repository: `/Users/liruijun/personal/LLM/agentscope-platform`
- Java/frontend repository: `/Users/liruijun/personal/LLM/langchain4j-platform`
- Compose launcher: `../langchain4j-platform/deploy/start-all.sh`
- Expected frontend: `http://localhost:8093`
- Expected edge gateway: `http://localhost:18080`
- Expected AgentScope container endpoint: `agentscope-orchestrator:8085`
- Expected authentication UI dependency: Casdoor at `http://localhost:8000`

## Cases

| ID | Priority | Action | Expected result |
| --- | --- | --- | --- |
| LRB-01 | P0 | Start Docker Desktop and inspect existing containers/ports | Docker daemon becomes reachable without deleting volumes |
| LRB-02 | P0 | Build AgentScope `orchestrator` image from the dirty working tree | `agentscope-platform:local` builds successfully |
| LRB-03 | P0 | Run `mvn -DskipTests package` from the Java reactor | Required service JARs and migration artifact package successfully |
| LRB-04 | P0 | Rebuild the full Java/infra/frontend Compose image set | Compose build completes, including the Vite/nginx frontend |
| LRB-05 | P0 | Deploy with `docker compose up -d --build` through `start-all.sh` | Migrations complete and application containers remain running/healthy |
| LRB-06 | P0 | Probe AgentScope health, edge authentication boundary, and frontend HTTP | Health is successful, edge is reachable, frontend returns HTTP 200 |
| LRB-07 | P1 | Open the frontend in an interactive browser and inspect the login/catalog shell | Page renders without browser-level fatal error and points at localhost edge |
| LRB-08 | P1 | Inspect failed/unhealthy containers and relevant logs | Any stable failure is classified as product or environment and reported |

## Evidence

- Build and Compose command exit codes.
- `docker compose ps` state and health.
- HTTP status and selected non-sensitive response headers/bodies.
- Browser-visible page state and screenshot when browser tooling is available.
- No secret values or generated authentication tokens are written to the report.
