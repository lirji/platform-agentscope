# Delivery Status

## Goal

Migrate the remaining governed Agent tools without moving Java business state or local sandbox
execution into AgentScope.

## State

- Phase: delivery complete
- Status: complete (local); external live-provider/production gates remain hold
- Last updated: 2026-08-03

## Completed

- Read root progress, project rules, legacy actions, current AgentScope tool registry, Java workflow
  idempotency contract, deployment configuration, tests, and CI.
- Recorded feasibility, product behavior, technical design, AC-01 through AC-11, rollout, rollback, and
  explicit approval in `DELIVERY_PLAN.md`.
- Confirmed UI/UX is not applicable in this repository.
- Added language-neutral Tool Policy metadata, trusted confirmation/idempotency request context, and
  AgentScope permission translation for every registered tool.
- Migrated default-off `refund_start` through the retained Java workflow API with no automatic retry,
  tenant-bound token/trace propagation, stable status/error mapping, and offline safety fixtures.
- Migrated default-off MCP through the standard Streamable HTTP SDK with an explicit server/tool
  binding contract, per-tool policy, recursive-agent rejection, bounded arguments/results, and no
  stdio or dynamic unknown tools.
- Migrated Browser and Code to default-off remote-only HTTP contracts. Browser sessions/actions are
  opaque, tenant-bound, host-allowlisted, and cleaned up; Code jobs are no-network, ephemeral, and
  bounded by time, source/output, memory, and process limits. No local execution fallback exists.
- Completed evidence-based review, full local QA, documentation/contract synchronization, and
  CI-equivalent verification. Final reports are stored beside this status file.

## Changed Files

- `docs/delivery/governed-agent-tools-migration/DELIVERY_PLAN.md` - approved Phase 4 design.
- `docs/delivery/governed-agent-tools-migration/DELIVERY_STATUS.md` - resumable workflow state.
- `src/agentscope_platform/domain/{tool,mcp}.py` - language-neutral policy and MCP binding contracts.
- `src/agentscope_platform/infrastructure/agentscope/{tools,governed_tools}.py` - enforcement and tools.
- `src/agentscope_platform/infrastructure/mcp/client.py` - remote Streamable HTTP MCP adapter.
- `src/agentscope_platform/domain/sandbox.py` and `infrastructure/sandbox/client.py` - browser/code
  contracts and remote-only client.
- `contracts/{boundaries,evaluation}/*` and `eval/baseline/*governed-cases.jsonl` - exported schemas
  and side-effect-safe offline cases.
- `docs/governed-tools.md` and configuration files - operator rollout and rollback controls.

## Verification Log

| Command or check | Result | Notes |
| --- | --- | --- |
| Inspect legacy/new routes and tool implementations | pass | Remaining tools and Java boundaries confirmed |
| Inspect AgentScope 2.0.5 permission API | pass | Supports allow/deny/ask; current stateless API has no durable HITL resume |
| Inspect Java workflow start contract | pass | accepts `chatId`, `message`, `dedupeId`, `webhookUrl` |
| Tool Policy/refund targeted suite | pass | 89 tests; policy, API, provider, planner, contract |
| MCP unit/protocol suite | pass | 9 tests; real in-process Streamable HTTP protocol |
| Contract/architecture MCP suite | pass | 95 tests including no-stdio boundary |
| Ruff targeted/source checks | pass | no lint violations |
| Mypy | pass | 65 source files |
| Browser/Code unit/client suite | pass | policy, tenant, bounds, cleanup, timeout, no-retry |
| Sandbox contract/architecture suite | pass | 110 tests; local execution imports forbidden |
| Mypy after sandbox slice | pass | 69 source files |
| Full pytest + coverage | pass | 349 tests; 89.23% coverage |
| Full Ruff format | pass | 208 files formatted |
| Shadow/build/Compose | pass | 8 samples; sdist/wheel; valid Compose |

## Decisions And Deviations

- The approved user message allows execution past Gate A.
- Side-effect confirmation will be trusted request context, not a model argument or in-memory
  AgentScope confirmation session.
- Browser and Code will be remote adapters only, even though the legacy implementation ran locally.
- MCP dynamic discovery was deliberately narrowed to an operator-owned binding allowlist. This is a
  safety hardening: the legacy `mcp_call` could dispatch arbitrary discovered names.
- Legacy in-JVM Playwright and Java subprocess behavior is not copied. Provider isolation obligations
  are explicit in the request schema and remain a deployment gate outside this repository.
- Final review corrected sandbox retry IDs to exclude volatile traces when an idempotency key exists,
  scoped MCP idempotency to `tools/call` metadata, serialized Browser session reads, and added
  low-cardinality policy/provider failure counters.

## Blockers And Residual Risks

- No production MCP/sandbox endpoints or credentials are assumed. MCP protocol compatibility is
  proven against an in-process server; live-provider evidence remains environment-dependent.
- Java workflow dedupe currently documents a residual concurrent check-then-create race; the Python
  adapter cannot strengthen that Java data invariant and must not claim exactly-once creation.
- A real sandbox provider URL is not available. Local contracts and stubs are green, but escape,
  egress, DNS-rebinding, redirect, TTL, and resource-exhaustion evidence remains externally blocked.

## Next Action

Provide a named live MCP/sandbox test environment to execute the documented external gates; keep all
new feature flags disabled until those gates and a production change approval pass.
