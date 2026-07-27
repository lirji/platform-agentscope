from typing import Protocol

from agentscope_platform.domain.agent import AgentExecution, RunContext
from agentscope_platform.domain.dag import DagPlan, DagPlanKind


class AgentRunner(Protocol):
    async def run(self, goal: str, context: RunContext) -> AgentExecution:
        """Execute one agent goal without leaking framework-specific types."""


class DagPlanningError(RuntimeError):
    """A sanitized, recoverable Planner failure."""


class DagPlanner(Protocol):
    async def plan(
        self,
        goal: str,
        context: RunContext,
        kind: DagPlanKind,
    ) -> DagPlan:
        """Produce a language-neutral DAG plan for one request."""
