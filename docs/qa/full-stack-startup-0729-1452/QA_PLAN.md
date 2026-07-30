# Full-Stack Startup QA Plan

## Scope

Start the current worktree of `langchain4j-platform` and `agentscope-platform` on
localhost, then run startup-level black-box checks without paid model calls.

## Approved Actions

- Build the 23-module Java reactor with tests skipped; the complete test gates had already
  passed before this startup run.
- Build and start the existing 25-service Java Docker Compose topology.
- Start local Ollama using already installed models.
- Start the AgentScope candidate on port 18085 with async execution enabled against the
  Java central async-task service.
- Exercise health, readiness, authentication, metrics, and one synthetic async task.

Approval evidence: after receiving the staged startup/test outline, the user explicitly
requested “你帮我启动”.

## Cost And Safety Boundary

- Targets are localhost only.
- No production route or `AGENT_URI` is changed.
- No batch or Judge evaluation is executed.
- A local Ollama model is used for semantic smoke; the configured DeepSeek model is not
  invoked by this plan.

## Acceptance Checks

1. The Java reactor packages successfully.
2. All 25 Compose services remain running without unhealthy/restarting state.
3. Edge, core Java services, LiteLLM, Ollama, frontend, and AgentScope endpoints return 200.
4. Candidate and central metrics enforce internal authentication and return 200 with a
   synthetic internal token.
5. An AgentScope async task persists through the Java central service and reaches a
   meaningful `DONE` result using a local model.
