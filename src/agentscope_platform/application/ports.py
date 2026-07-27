from typing import Protocol

from agentscope_platform.domain.agent import AgentExecution, RunContext


class AgentRunner(Protocol):
    async def run(self, goal: str, context: RunContext) -> AgentExecution:
        """Execute one agent goal without leaking framework-specific types."""
