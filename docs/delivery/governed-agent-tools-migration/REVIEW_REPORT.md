# Governed Agent Tools Review Report

## Scope

Reviewed the Tool Policy foundation, trusted request context, `refund_start`, allowlisted MCP,
remote Browser, remote Code Sandbox, contracts, evaluation fixtures, configuration, documentation,
and deployment defaults against AC-01 through AC-11.

## Verdict

- Local implementation: pass
- P0/P1 open code defects: none
- Production enablement: hold until the external gates below are evidenced

## Findings Resolved During Review

1. Sandbox operation/session IDs originally included volatile trace data even when a caller supplied
   an idempotency key. They now derive from trusted tenant/user plus the idempotency key and stable
   tool sequence; tests prove retry stability and cross-tenant separation.
2. MCP initially placed `Idempotency-Key` on the whole HTTP session, including `initialize`. It now
   injects the key only into `tools/call._meta`; JWT and trace remain trusted HTTP headers.
3. Browser screenshot/vision tools were read-only but shared mutable session state. Concurrency safety
   is now independent of read-only policy, and every Browser session tool is serialized.
4. Policy denials and provider failures lacked direct low-cardinality metrics. Dedicated counters now
   expose only tool/reason or tool/provider labels.
5. The repository had two tracked-clean Ruff format drifts. They were mechanically normalized so the
   existing full CI format gate passes; no behavior changed.

## Security Review

- AgentScope/framework types remain confined to `infrastructure/agentscope`.
- Model inputs cannot set tenant, user, token, trace, confirmation, or idempotency context.
- Every registered tool has policy metadata and immediate pre-execution enforcement.
- Side effects are non-concurrent, confirmed, idempotency-protected, bounded, and never automatically
  retried.
- MCP has no stdio path, no dynamic unknown-tool exposure, and blocks `platform.agent.*` recursion.
- Browser/Code have no local Playwright, shell, JVM, container, or filesystem execution path.
- Browser target hosts are operator-allowlisted and passed to the provider for redirect/subresource
  enforcement; provider-returned URLs are checked again.
- Code contract requires no network, ephemeral workspace, and explicit time/output/memory/process
  limits.
- Provider errors are stable and sanitized at the transport boundary; secrets are absent from schemas,
  fixtures, logs, and metric labels.

## Residual External Risks

- Java workflow dedupe retains its documented concurrent check-then-create race; the adapter does not
  claim exactly-once creation.
- No named live MCP endpoint was supplied, so protocol compatibility is proven with an in-process
  Streamable HTTP server rather than a deployment endpoint.
- The remote sandbox provider is outside this repository. Production remains blocked on provider-side
  escape, egress/DNS-rebinding/redirect, resource-exhaustion, forced-timeout, session-TTL, and audit
  evidence.
- Production canary, monitoring thresholds, on-call ownership, and change approval are not authorized
  by this task.
