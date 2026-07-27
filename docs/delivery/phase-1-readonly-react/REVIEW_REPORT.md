# Review Report

## Scope

Adversarial review of the Phase 1 contract assets, tenant-aware retained-service clients, read-only
tools, AgentScope event mapping, runner limits, observability, tests, CI, and documentation.

## Confirmed Findings And Resolutions

1. **Stale public phase metadata and documentation**
   - Impact: operators could mistake the service for the Phase 0 scaffold or assume trajectory
     mapping was still absent.
   - Resolution: `/info`, README, contracts, migration plan, and test-gate docs now describe the
     Phase 1 code slice and explicitly separate offline completion from production parity.

2. **Potential secret-bearing observer boundary**
   - Impact: passing `RunContext` to logging would make internal tokens easy to leak later.
   - Resolution: the observer accepts a flattened immutable `RunObservation` containing only
     trace, tenant, user, model, stop, duration, token counts, and tool names. Tests assert that
     token and API-key fields do not exist.

3. **Hidden reasoning compatibility risk**
   - Impact: copying framework reasoning into legacy `thought` could leak chain-of-thought.
   - Resolution: the field remains contract-compatible but is always an empty string; tool
     call/input/result evidence remains available.

## Rejected Suspicions

- A new top-level `agent` scope check was not added: the inspected legacy agent entrypoint does not
  enforce one, and retained services remain responsible for resource authorization.
- Read-only tools returning `ToolChunk` with the framework's running state is intentional:
  AgentScope aggregates the final chunk into a successful `ToolResponse`; explicit failures use
  the error state.
- Framework exceptions are not returned verbatim, preventing provider details and credentials from
  entering API responses.

## Residual Risks

- No live LiteLLM or retained Java services were available, so tool-selection quality and real
  provider event behavior require shadow evaluation.
- Cost is not calculated locally because pricing is gateway/model specific; token counts and model
  identity are emitted so the platform metering layer can derive it.
- Docker image execution was not run because the local Docker daemon is unavailable.

## Outcome

No unresolved P0/P1 code finding was identified. The slice is ready for an environment-backed
Phase 1 shadow evaluation, not yet for production cutover.
