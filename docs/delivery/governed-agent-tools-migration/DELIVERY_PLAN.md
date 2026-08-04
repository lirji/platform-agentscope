# Governed Agent Tools Migration Delivery Plan

## Requirement

Continue the approved AgentScope migration by adding the remaining governed tool capabilities in
dependency order: a language-neutral tool policy, `refund_start`, allowlisted MCP, and isolated
Browser/Code Sandbox adapters. Java services remain authoritative for workflow state and other
business side effects; Browser and Code execution must not run inside the orchestrator process.

## Repository Evidence

- `ReadonlyToolset` currently registers only seven read-only tools and `ReadOnlyFunctionTool` denies
  every tool not declared read-only.
- Legacy `RefundStartAction` calls Java `POST /workflow/refund/start`; that endpoint already accepts a
  tenant-scoped `dedupeId` and returns `COMPLETED` or `WAITING_APPROVAL`.
- Legacy `mcp_call`, `browser_*`, and `code_exec` are default-off. The legacy Browser runs Playwright
  in the Agent JVM and Code Exec is only subprocess-level isolation, so copying either implementation
  would violate the accepted target architecture.
- The synchronous AgentScope API is stateless and does not persist AgentScope HITL state. Therefore
  approval must be supplied as trusted request context before a side-effect tool is eligible; a model
  argument can never count as confirmation.
- The two repositories have unrelated, uncommitted work. All changes in this delivery remain scoped
  to new Phase 4 files and the smallest required integration points.

## Feasibility

- Verdict: conditional-go
- Constraints:
  - Preserve existing `/agent/**` JSON/SSE shapes and default behavior.
  - All new tools are default-off.
  - Tenant, user, scopes, confirmation, idempotency key, and trace come from verified request context,
    never model arguments.
  - Workflow execution remains Java-owned; MCP calls remain allowlisted; Browser/Code use remote
    sandbox contracts only.
  - No unconditional retry of a side effect.
- Dependencies:
  - Java `workflow-service` for `refund_start`.
  - An explicitly configured MCP endpoint for MCP tools.
  - Separately deployed Browser and Code sandbox providers before those adapters can be enabled.
- Risks and mitigations:
  - Accidental writes: default-off registration plus policy denial without explicit confirmation.
  - Duplicate workflows: require a bounded request idempotency key and forward it as `dedupeId`.
  - Cross-tenant calls: only forward verified internal JWT and trace; never serialize tenant input from
    the model.
  - Sandbox escape: the orchestrator exposes only HTTP adapters; it never starts local shells,
    interpreters, Playwright, or containers.
  - MCP recursion/unknown side effects: explicit server/tool allowlists and per-tool policy metadata.

## Product Design

- Actors and goals:
  - Authenticated platform users can request a governed action and explicitly confirm it.
  - Agent operators can enable one capability at a time and inspect its policy contract.
  - Workflow approvers retain exclusive control over approval completion.
- Scope:
  - Tool metadata and enforcement.
  - `refund_start` selection and Java HTTP execution.
  - MCP discovery/execution adapters with allowlists.
  - Remote Browser/Code sandbox contracts and adapters.
  - Contract, tenant, failure, evaluation, rollout, and rollback coverage.
- Out of scope:
  - Agent-driven approval completion, task claim/unclaim, workflow purge, or production enablement.
  - Embedding a shell, browser, container runtime, or business database in AgentScope.
  - Creating a production sandbox cluster or using production credentials.
- Business rules:
  - A side-effect tool requires explicit request confirmation and required scopes.
  - `refund_start` additionally requires an idempotency key; the model cannot provide or override it.
  - A confirmed start may create a workflow but may not approve it.
  - Default-off or denied tools are not executed and return a stable, sanitized observation.

## Acceptance Criteria

| ID | Observable behavior | Priority | Verification |
| --- | --- | --- | --- |
| AC-01 | Every registered tool has language-neutral metadata for read-only, side-effect, idempotency, confirmation, scopes, timeout, and retry | P0 | schema and registry tests |
| AC-02 | Read-only tools remain auto-allowed; side-effect tools are denied without required scope, confirmation, or idempotency | P0 | policy and AgentScope adapter tests |
| AC-03 | Confirmation and idempotency are derived from authenticated HTTP request context and cannot be supplied by model tool input | P0 | API/context and negative tool tests |
| AC-04 | `refund_start` is default-off and, when enabled and authorized, calls Java workflow with message, trusted chatId, and trusted dedupeId | P0 | HTTP mock integration tests |
| AC-05 | Duplicate `refund_start` calls carry the same caller-provided dedupe key; no client-side automatic retry occurs | P0 | request capture/failure tests |
| AC-06 | `WAITING_APPROVAL`, `COMPLETED`, deduplicated, 4xx/5xx, invalid response, and cross-tenant behavior map to stable sanitized tool results | P0 | tool integration tests |
| AC-07 | MCP tools are default-off and restricted by configured server/tool allowlists plus trusted scopes and confirmation policy | P1 | adapter/security tests |
| AC-08 | Browser and Code tools are remote adapters only; local process, filesystem, or Playwright execution is absent from the orchestrator | P0 | architecture tests |
| AC-09 | Browser sessions and Code jobs are tenant-bound, bounded by timeout/input/output limits, and default-off | P1 | contract/adapter tests |
| AC-10 | Each capability has offline old/new evaluation cases, rollout monitoring, and an explicit whole-capability rollback switch | P0 | fixture/doc/config tests |
| AC-11 | Existing HTTP/JSON/SSE contracts and read-only behavior remain compatible | P0 | snapshots and full regression |

## UI/UX Design

- Applicability: no UI changes in this repository.
- API interaction: callers first submit the exact tool and arguments to `POST /agent/tool-confirmations`
  with an `Idempotency-Key`, then pass the returned short-lived grant in
  `X-Agent-Confirmation-Grants`; absence is a safe denial, not an implicit prompt or execution.
- Future UI work should render confirmation from the tool metadata contract, but that frontend is not
  modified in this delivery.

## Technical Solution

- Chosen approach:
  - Add framework-neutral `ToolMetadata` and `ToolPolicy` domain types.
  - Extend `RunContext` with verified, argument-bound confirmation grants and request idempotency key.
  - Add `GovernedFunctionTool` in `infrastructure/agentscope`; it translates pure policy decisions to
    AgentScope permission decisions.
  - Keep read-only tools on the same registry but give them explicit metadata.
  - Add `GovernedToolset` adapters; register each only behind its feature flag.
  - Call workflow/MCP/sandbox providers over bounded HTTP clients carrying internal token and trace.
- Alternatives rejected:
  - Trusting `confirmed=true` from model input: the model is not an authorization source.
  - AgentScope in-memory HITL resume for `/agent/run`: current API rebuilds the Agent per request and
    does not expose a durable confirmation session contract.
  - Copying Java Playwright/JShell implementations: violates process isolation and duplicates legacy
    runtime risks.
- Modules and file map:
  - `domain/tool.py`: metadata, enums, policy decisions.
  - `domain/agent.py`, `api/dependencies.py`: trusted confirmation/idempotency context.
  - `infrastructure/agentscope/tools.py`, `governed_tools.py`, `runner.py`: enforcement and registration.
  - `infrastructure/http/models.py`, `platform_client.py`, later MCP/sandbox clients: provider contracts.
  - `core/config.py`, `.env.example`, `compose.yml`: default-off flags and bounded settings.
  - `contracts/boundaries/tool-policy.schema.json`, tests and evaluation fixtures.
- Contracts and data:
  - Confirmation header is a bounded comma-separated set of signed grants. Each grant binds
    tenant/user/tool/canonical argument digest/idempotency key/expiry/nonce and is consumed once.
  - `Idempotency-Key` is a caller-generated opaque key, validated for length/character safety.
  - `refund_start` sends `{message, chatId, dedupeId}`; tenant/user stay in the signed internal token.
- Security and reliability:
  - Scope and confirmation checks occur immediately before tool execution.
  - No retry for workflow starts. Provider timeouts are bounded and errors sanitized.
  - Remote sandbox URLs must be explicitly configured; provider credentials are environment secrets.
- Observability:
  - Existing trajectory records tool name/status without token or full request context.
  - Add policy-denied and provider-failed counters/log fields only with low-cardinality tool/reason.
- Compatibility and migration:
  - All flags default false. Rollback disables one capability and restarts the orchestrator.
  - Existing Java agent remains the whole-service rollback target until production gates pass.

## Implementation Sequence

1. Tool policy/context/schema foundation (AC-01/02/03/11).
2. `refund_start` vertical slice (AC-04/05/06/10/11).
3. Allowlisted MCP adapter (AC-07/10/11).
4. Remote Browser and Code Sandbox adapters (AC-08/09/10/11).
5. Review, local QA, documentation, and CI reconciliation (all ACs).

## Verification Plan

| AC/Risk | Test level | Case or command | Required evidence |
| --- | --- | --- | --- |
| AC-01/02/03 | unit/API | policy decisions; trusted header parsing; model input negative cases | deterministic allow/deny reasons |
| AC-04/05/06 | HTTP integration | `httpx.MockTransport` workflow start cases | exact body/headers and stable results |
| AC-07 | unit/integration | MCP allow/deny/discovery/failure | no unknown tool call |
| AC-08/09 | architecture/integration | forbidden local modules/imports; remote stub | no local execution and bounded payload |
| AC-10 | contract/docs | fixture parsers and rollback config checks | all tools represented |
| AC-11 | regression | contract export, ruff, mypy, pytest | all green |

## Documentation Plan

- Update README, architecture, development, contracts, migration plan, testing gates, and a governed
  tools operator guide to match only implemented behavior.
- Add rollout and rollback instructions per capability.

## CI Plan

- Reuse existing GitHub Actions quality job. Add new contract/exported artifacts and tests to the
  existing commands; add a separate check only if remote-sandbox architecture needs static validation.

## Rollout And Rollback

- Roll out policy code with all new capabilities off.
- Enable one capability for a test tenant/environment, run old/new cases, then canary.
- Monitor policy denials, provider failures, latency, duplicate workflow rate, and sandbox timeouts.
- Roll back by disabling the individual flag. For broader regression, route the complete Agent service
  back to the retained Java image; never perform per-request silent fallback after a partial side effect.

## Assumptions And Open Decisions

- The API exposes a two-phase confirmation resource suitable for current callers. A future interactive
  UI may persist the pending approval checkpoint without weakening the signed grant policy.
- No production MCP or sandbox endpoint is assumed. External live validation remains conditional on
  an explicitly named test environment and credentials.

## Approval

- Status: approved
- Approved scope: the migration order recommended in the preceding response: Tool Policy,
  `refund_start`, MCP, remote Browser, and remote Code Sandbox, followed by quality gates.
- Evidence: user message on 2026-08-03, “按照你的建议继续迁移”.
