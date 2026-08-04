from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from agentscope_platform.domain.agent import AgentExecution, AgentStep, RunContext
from agentscope_platform.domain.analytics import AnalyticsSqlPlan
from agentscope_platform.domain.async_task import (
    AsyncTaskEventAppend,
    AsyncTaskStatus,
    CentralAsyncTask,
    CentralAsyncTaskEvent,
)
from agentscope_platform.domain.confirmation import ToolConfirmationGrant
from agentscope_platform.domain.dag import (
    AgentDagCritique,
    DagPlan,
    DagPlanKind,
)
from agentscope_platform.domain.sandbox import (
    BrowserActionReply,
    BrowserActionRequest,
    CodeExecutionReply,
    CodeExecutionRequest,
)
from agentscope_platform.domain.session import AgentSessionCheckpoint


class AgentRunner(Protocol):
    async def run(self, goal: str, context: RunContext) -> AgentExecution:
        """Execute one agent goal without leaking framework-specific types."""


SessionProgressCallback = Callable[[tuple[AgentStep, ...], bool], Awaitable[None]]


class ResumableAgentRunner(Protocol):
    async def run_from_checkpoint(
        self,
        goal: str,
        checkpoint: AgentSessionCheckpoint,
        context: RunContext,
        progress: SessionProgressCallback,
    ) -> AgentExecution:
        """Resume from stable state without exposing framework state."""


class AgentSessionStore(Protocol):
    async def get(self, session_id: str) -> AgentSessionCheckpoint | None: ...

    async def compare_and_set(
        self,
        checkpoint: AgentSessionCheckpoint,
        expected_revision: int | None,
    ) -> bool: ...

    async def ready(self, timeout_seconds: float) -> bool: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class DependencyReadiness:
    name: str
    required: bool
    status: str


class ReadinessProbe(Protocol):
    async def check(self) -> tuple[DependencyReadiness, ...]: ...

    async def close(self) -> None: ...


class ToolConfirmationTokenCodec(Protocol):
    def encode(self, grant: ToolConfirmationGrant) -> str: ...

    def decode(self, token: str) -> ToolConfirmationGrant: ...


class ConfirmationReplayStore(Protocol):
    async def consume(self, grant: ToolConfirmationGrant) -> bool: ...

    async def ready(self, timeout_seconds: float) -> bool: ...

    async def close(self) -> None: ...


class ToolConfirmationConsumer(Protocol):
    async def consume(self, grant: ToolConfirmationGrant) -> bool: ...


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


class AnalyticsSqlPlanner(Protocol):
    async def plan(
        self,
        question: str,
        schema: str,
        context: RunContext,
    ) -> AnalyticsSqlPlan:
        """Produce SQL only; execution and tenant enforcement remain in Java."""


class McpGateway(Protocol):
    async def call(
        self,
        *,
        server_url: str,
        tool_name: str,
        arguments: dict[str, Any],
        context: RunContext,
        timeout_seconds: float,
    ) -> str:
        """Call one pre-approved remote MCP tool using trusted request context."""


class RemoteSandboxGateway(Protocol):
    async def browser_action(
        self,
        request: BrowserActionRequest,
        context: RunContext,
        timeout_seconds: float,
    ) -> BrowserActionReply: ...

    async def execute_code(
        self,
        request: CodeExecutionRequest,
        context: RunContext,
        timeout_seconds: float,
    ) -> CodeExecutionReply: ...

    async def close_browser(self, context: RunContext) -> None: ...


class ProgressSink(Protocol):
    async def emit(self, event: str, data: Any) -> None:
        """Publish one language-neutral orchestration progress event."""


class AsyncTaskMetrics(Protocol):
    def submitted(self, kind: str) -> None: ...

    def completed(self, kind: str, status: str) -> None: ...

    def heartbeat_failed(self) -> None: ...

    def running(self, delta: int, kind: str) -> None: ...

    def inflight(self, delta: int, kind: str) -> None: ...

    def backlog(self, delta: int, kind: str) -> None: ...


class AsyncTaskGateway(Protocol):
    async def create(
        self,
        *,
        task_id: str,
        kind: str,
        input_data: dict[str, Any],
        webhook_url: str | None,
        context: RunContext,
    ) -> CentralAsyncTask: ...

    async def get(self, task_id: str, context: RunContext) -> CentralAsyncTask | None: ...

    async def list(self, context: RunContext) -> list[CentralAsyncTask]: ...

    async def lease(
        self,
        task_id: str,
        worker_id: str,
        lease_seconds: float,
        context: RunContext,
        *,
        lease_epoch: int | None = None,
    ) -> CentralAsyncTask: ...

    async def update_status(
        self,
        task_id: str,
        status: AsyncTaskStatus,
        *,
        result: Any | None,
        error: str | None,
        worker_id: str,
        lease_epoch: int,
        context: RunContext,
    ) -> CentralAsyncTask: ...

    async def cancel(self, task_id: str, context: RunContext) -> bool: ...

    async def append_event(
        self,
        task_id: str,
        event: AsyncTaskEventAppend,
        context: RunContext,
    ) -> CentralAsyncTaskEvent: ...

    def stream(
        self,
        task_id: str,
        context: RunContext,
        *,
        last_event_id: str | None,
    ) -> AsyncIterator[bytes]: ...

    async def close(self) -> None: ...
