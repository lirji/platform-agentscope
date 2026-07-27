from typing import Protocol

from agentscope_platform.domain.agent import AgentExecution, RunContext
from agentscope_platform.domain.dag import (
    AgentDagCritique,
    DagPlan,
    DagPlanKind,
)


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


class DagQualityError(RuntimeError):
    """A sanitized critic or replanner failure."""


class DagQualityReviewer(Protocol):
    async def critique(
        self,
        goal: str,
        answer: str,
        context: RunContext,
    ) -> AgentDagCritique:
        """Score one synthesized answer."""

    async def revise(
        self,
        goal: str,
        previous_plan: DagPlan,
        previous_answer: str,
        critique: AgentDagCritique,
        context: RunContext,
    ) -> DagPlan:
        """Return a revised language-neutral DAG plan."""


class TextGenerationError(RuntimeError):
    """A sanitized sibling-orchestrator model failure."""


class TextGenerator(Protocol):
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        context: RunContext,
        *,
        deterministic: bool = False,
    ) -> str:
        """Generate plain text without exposing framework-specific types."""
