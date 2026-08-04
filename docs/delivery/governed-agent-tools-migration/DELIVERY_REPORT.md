# Governed Agent Tools Delivery Report

## Delivered

- One language-neutral Tool Policy for every Agent tool, with trusted scope, confirmation,
  idempotency, timeout, retry, and side-effect enforcement.
- Default-off `refund_start` that starts—but never approves—the retained Java workflow.
- Default-off standard Streamable HTTP MCP with explicit server/tool bindings and per-tool policy.
- Default-off remote Browser tools with opaque sessions, exact host allowlist, serialized actions,
  bounded input/output, and end-of-run cleanup.
- Default-off remote Java `code_exec` with no local fallback and explicit no-network/ephemeral/resource
  constraints.
- Exported JSON Schemas, cross-tenant/provider/error tests, offline old/new safety fixtures, metrics,
  operator documentation, rollout and capability-level rollback controls.

## Compatibility

Existing `/agent/**` JSON/SSE contracts and the default seven read-only tools are unchanged. New
capabilities do not register unless their individual flags and required configuration are present.
Java remains authoritative for workflow state, transactions, security, approval, and outbox behavior.

## CI

The existing `.github/workflows/ci.yml` already executes every required contract, lint, format, type,
coverage, shadow, package, Compose, and image gate. No workflow expansion was necessary; the local
CI-equivalent command set is green.

## Rollout State

- Code delivery: complete
- Local gates: complete
- Live MCP/sandbox provider validation: pending external environment
- Production enablement: not performed and not authorized

Use `docs/governed-tools.md` for configuration, monitoring, canary order, and rollback. Do not enable
Browser or Code in production until the independent provider isolation gates in the QA and review
reports are satisfied.
