from agentscope_platform.application.ports import AgentRunner
from agentscope_platform.domain.agent import (
    AgentRunReply,
    AgentRunRequest,
    RunContext,
)


class AgentApplicationService:
    def __init__(self, runner: AgentRunner) -> None:
        self._runner = runner

    async def run(self, request: AgentRunRequest, context: RunContext) -> AgentRunReply:
        execution = await self._runner.run(request.goal.strip(), context)
        return AgentRunReply(
            goal=request.goal.strip(),
            steps=list(execution.steps),
            finalAnswer=execution.final_answer,
            stopReason=execution.stop_reason,
            depth=execution.depth,
            tenantId=context.identity.tenant_id,
        )
