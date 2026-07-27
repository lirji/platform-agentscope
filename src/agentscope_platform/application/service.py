from agentscope_platform.application.ports import AgentRunner
from agentscope_platform.domain.agent import (
    AgentExecution,
    AgentRunReply,
    AgentRunRequest,
    RunContext,
)


class AgentApplicationService:
    def __init__(self, runner: AgentRunner) -> None:
        self._runner = runner

    async def run(self, request: AgentRunRequest, context: RunContext) -> AgentRunReply:
        execution = await self._runner.run(request.goal.strip(), context)
        return to_agent_reply(request.goal.strip(), execution, context)


def to_agent_reply(
    goal: str,
    execution: AgentExecution,
    context: RunContext,
) -> AgentRunReply:
    return AgentRunReply(
        goal=goal,
        steps=list(execution.steps),
        finalAnswer=execution.final_answer,
        stopReason=execution.stop_reason,
        depth=execution.depth,
        tenantId=context.identity.tenant_id,
    )
