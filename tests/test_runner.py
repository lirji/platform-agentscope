import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import cast

from agentscope.agent import Agent
from agentscope.event import (
    ExceedMaxItersEvent,
    ModelCallEndEvent,
    ReplyEndEvent,
    TextBlockDeltaEvent,
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    ToolResultEndEvent,
    ToolResultStartEvent,
    ToolResultTextDeltaEvent,
)
from agentscope.message import AssistantMsg, ToolResultState
from agentscope.types import ReplyFinishedReason
from pydantic import SecretStr
from pytest import MonkeyPatch

from agentscope_platform.application.observer import RunObservation
from agentscope_platform.application.ports import RemoteSandboxGateway
from agentscope_platform.core.config import Settings
from agentscope_platform.core.context import current_run_context
from agentscope_platform.domain.agent import AgentStep, RunContext, TenantIdentity
from agentscope_platform.domain.sandbox import (
    BrowserActionReply,
    BrowserActionRequest,
    CodeExecutionReply,
    CodeExecutionRequest,
)
from agentscope_platform.domain.session import (
    AgentSessionCheckpoint,
    AgentSessionStatus,
    goal_sha256,
)
from agentscope_platform.infrastructure.agentscope.runner import (
    AgentScopeRunner,
    _agentscope_max_iters,
)
from agentscope_platform.infrastructure.http.platform_client import PlatformClient
from tool_confirmation_support import CONFIRMATION_SECRET, DOWNSTREAM_SECRET


class FakeAgent:
    def __init__(
        self,
        items: list[object],
        delay: float = 0,
        error: BaseException | None = None,
    ) -> None:
        self._items = items
        self._delay = delay
        self._error = error

    async def reply_stream(
        self,
        *args: object,
        **kwargs: object,
    ) -> AsyncGenerator[object, None]:
        del args, kwargs
        for item in self._items:
            if self._delay:
                await asyncio.sleep(self._delay)
            yield item
        if self._error:
            raise self._error


class CapturingObserver:
    def __init__(self) -> None:
        self.observations: list[RunObservation] = []

    def started(self, model: str) -> None:
        del model

    def record(self, observation: RunObservation) -> None:
        self.observations.append(observation)


class StubRunner(AgentScopeRunner):
    def __init__(
        self,
        settings: Settings,
        agent: FakeAgent,
        observer: CapturingObserver,
        sandbox_gateway: RemoteSandboxGateway | None = None,
    ) -> None:
        super().__init__(
            settings,
            PlatformClient(settings),
            observer,
            sandbox_gateway=sandbox_gateway,
        )
        self._agent = agent

    def _build_agent(self) -> Agent:
        return cast(Agent, self._agent)

    def _build_resumable_agent(self, checkpoint: AgentSessionCheckpoint) -> Agent:
        del checkpoint
        return cast(Agent, self._agent)


class CloseOnlySandboxGateway:
    def __init__(self) -> None:
        self.closed: list[RunContext] = []

    async def browser_action(
        self,
        request: BrowserActionRequest,
        context: RunContext,
        timeout_seconds: float,
    ) -> BrowserActionReply:
        del request, context, timeout_seconds
        raise AssertionError("not expected")

    async def execute_code(
        self,
        request: CodeExecutionRequest,
        context: RunContext,
        timeout_seconds: float,
    ) -> CodeExecutionReply:
        del request, context, timeout_seconds
        raise AssertionError("not expected")

    async def close_browser(self, context: RunContext) -> None:
        self.closed.append(context)


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "gateway_api_key": SecretStr("test-key"),
        "internal_auth_required": False,
        "agent_confirmation_secret": SecretStr(CONFIRMATION_SECRET),
        "agent_downstream_jwt_secret": SecretStr(DOWNSTREAM_SECRET),
    }
    values.update(overrides)
    return Settings(**values)


def context() -> RunContext:
    return RunContext(
        identity=TenantIdentity("acme", "alice"),
        internal_token="must-not-enter-observation",
        trace_id="trace-123",
    )


def completed_events() -> list[object]:
    return [
        ToolCallStartEvent(reply_id="r", tool_call_id="c", tool_call_name="rag_search"),
        ToolCallDeltaEvent(reply_id="r", tool_call_id="c", delta='{"query":"refund"}'),
        ToolCallEndEvent(reply_id="r", tool_call_id="c"),
        ToolResultStartEvent(reply_id="r", tool_call_id="c", tool_call_name="rag_search"),
        ToolResultTextDeltaEvent(reply_id="r", tool_call_id="c", delta="found"),
        ToolResultEndEvent(
            reply_id="r",
            tool_call_id="c",
            state=ToolResultState.SUCCESS,
        ),
        ModelCallEndEvent(reply_id="r", input_tokens=12, output_tokens=3),
        ReplyEndEvent(
            session_id="s",
            reply_id="r",
            finished_reason=ReplyFinishedReason.COMPLETED,
        ),
        AssistantMsg(name="platform-agent", content="final"),
    ]


def session_checkpoint() -> AgentSessionCheckpoint:
    now = datetime.now(UTC)
    return AgentSessionCheckpoint(
        sessionId="sess-11111111111111111111111111111111",
        revision=1,
        tenantId="acme",
        userId="alice",
        goalSha256=goal_sha256("goal"),
        status=AgentSessionStatus.RUNNING,
        steps=[AgentStep(n=1, action="previous_search", observation="safe result")],
        leaseOwnerId="worker-a",
        leaseExpiresAt=now + timedelta(seconds=30),
        createdAt=now,
        updatedAt=now,
        expiresAt=now + timedelta(hours=1),
    )


def test_agentscope_iteration_budget_preserves_legacy_action_steps() -> None:
    assert _agentscope_max_iters(1) == 1
    assert _agentscope_max_iters(4) == 7
    assert _agentscope_max_iters(8) == 15


def test_runner_bounds_each_model_call_and_disables_duplicate_retries(
    monkeypatch: MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_build_model(
        configured: Settings,
        **kwargs: object,
    ) -> object:
        captured["settings"] = configured
        captured.update(kwargs)
        return object()

    def fake_agent(**kwargs: object) -> object:
        captured["agent"] = kwargs
        return object()

    monkeypatch.setattr(
        "agentscope_platform.infrastructure.agentscope.runner.build_openai_chat_model",
        fake_build_model,
    )
    monkeypatch.setattr(
        "agentscope_platform.infrastructure.agentscope.runner.Agent",
        fake_agent,
    )
    configured = settings(
        agent_max_tokens=2_000,
        agent_model_max_output_tokens=4_096,
        agent_model_max_retries=0,
    )
    runner = AgentScopeRunner(configured, PlatformClient(configured))

    built = runner._build_agent()

    assert built is not None
    assert captured["max_tokens"] == 2_000
    assert captured["max_retries"] == 0


async def test_runner_returns_steps_and_non_secret_observation() -> None:
    observer = CapturingObserver()
    runner = StubRunner(settings(), FakeAgent(completed_events()), observer)

    result = await runner.run("goal", context())

    assert result.final_answer == "final"
    assert result.stop_reason == "DONE"
    assert result.steps[0].action == "rag_search"
    assert result.steps[0].action_input == "refund"
    assert observer.observations == [
        RunObservation(
            trace_id="trace-123",
            tenant_id="acme",
            user_id="alice",
            model="chat-default",
            stop_reason="DONE",
            duration_ms=observer.observations[0].duration_ms,
            input_tokens=12,
            output_tokens=3,
            tools=("rag_search",),
        )
    ]
    assert not hasattr(observer.observations[0], "internal_token")
    try:
        current_run_context()
    except RuntimeError:
        pass
    else:
        raise AssertionError("run context leaked after execution")


async def test_resumable_runner_checkpoints_each_completed_tool_boundary() -> None:
    runner = StubRunner(settings(), FakeAgent(completed_events()), CapturingObserver())
    progress: list[tuple[tuple[AgentStep, ...], bool]] = []

    async def capture(steps: tuple[AgentStep, ...], side_effect: bool) -> None:
        progress.append((steps, side_effect))

    result = await runner.run_from_checkpoint(
        "goal",
        session_checkpoint(),
        context(),
        capture,
    )

    assert [step.action for step in result.steps] == ["previous_search", "rag_search"]
    assert len(progress) == 1
    assert [step.action for step in progress[0][0]] == ["previous_search", "rag_search"]
    assert not progress[0][1]


def test_resumable_runner_reconstructs_only_adapter_local_agentscope_state(
    monkeypatch: MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "agentscope_platform.infrastructure.agentscope.runner.build_openai_chat_model",
        lambda *args, **kwargs: object(),
    )

    def fake_agent(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(
        "agentscope_platform.infrastructure.agentscope.runner.Agent",
        fake_agent,
    )
    configured = settings()
    runner = AgentScopeRunner(configured, PlatformClient(configured))

    runner._build_resumable_agent(session_checkpoint())

    state = captured["state"]
    serialized = state.model_dump_json()  # type: ignore[union-attr]
    assert "previous_search" in serialized
    assert "safe result" in serialized
    assert "must-not-enter-observation" not in serialized
    assert state.session_id == session_checkpoint().session_id  # type: ignore[union-attr]


async def test_runner_closes_remote_browser_session_after_run() -> None:
    observer = CapturingObserver()
    sandbox = CloseOnlySandboxGateway()
    configured = settings(
        agent_browser_enabled=True,
        agent_browser_sandbox_url="https://browser-sandbox.test",
        agent_browser_allowed_hosts_json='["example.com"]',
    )
    runner = StubRunner(configured, FakeAgent(completed_events()), observer, sandbox)
    run_context = context()

    result = await runner.run("goal", run_context)

    assert result.stop_reason == "DONE"
    assert sandbox.closed == [run_context]


async def test_runner_enforces_token_budget() -> None:
    observer = CapturingObserver()
    events = [
        ModelCallEndEvent(reply_id="r", input_tokens=10, output_tokens=5),
        AssistantMsg(name="platform-agent", content="must not be reached"),
    ]
    runner = StubRunner(settings(agent_max_tokens=10), FakeAgent(events), observer)

    result = await runner.run("goal", context())

    assert result.stop_reason == "BUDGET"
    assert result.final_answer == "Agent stopped: BUDGET"
    assert observer.observations[0].input_tokens == 10


async def test_runner_maps_max_iterations_and_partial_text() -> None:
    observer = CapturingObserver()
    events = [
        TextBlockDeltaEvent(reply_id="r", block_id="b", delta="partial"),
        ExceedMaxItersEvent(reply_id="r", name="platform-agent"),
        ReplyEndEvent(
            session_id="s",
            reply_id="r",
            finished_reason=ReplyFinishedReason.EXCEED_MAX_ITERS,
        ),
    ]
    runner = StubRunner(settings(), FakeAgent(events), observer)

    result = await runner.run("goal", context())

    assert result.stop_reason == "MAX_STEPS"
    assert result.final_answer == "partial"


async def test_runner_maps_timeout_cancellation_and_error() -> None:
    timeout_runner = StubRunner(
        settings(agent_timeout_seconds=0.001),
        FakeAgent([AssistantMsg(name="a", content="late")], delay=0.05),
        CapturingObserver(),
    )
    cancelled_runner = StubRunner(
        settings(),
        FakeAgent([], error=asyncio.CancelledError()),
        CapturingObserver(),
    )
    error_runner = StubRunner(
        settings(),
        FakeAgent([], error=RuntimeError("provider included secret details")),
        CapturingObserver(),
    )

    timeout_result = await timeout_runner.run("goal", context())
    cancelled_result = await cancelled_runner.run("goal", context())
    error_result = await error_runner.run("goal", context())

    assert timeout_result.stop_reason == "TIMEOUT"
    assert cancelled_result.stop_reason == "CANCELLED"
    assert error_result.stop_reason == "ERROR"
    assert "secret details" not in error_result.final_answer


async def test_runner_stops_repeated_action_before_third_execution() -> None:
    observer = CapturingObserver()
    events: list[object] = []
    for index in range(3):
        call_id = f"c{index}"
        events.extend(
            [
                ToolCallStartEvent(
                    reply_id="r",
                    tool_call_id=call_id,
                    tool_call_name="rag_search",
                ),
                ToolCallDeltaEvent(
                    reply_id="r",
                    tool_call_id=call_id,
                    delta='{"query":"same"}',
                ),
                ToolCallEndEvent(reply_id="r", tool_call_id=call_id),
            ]
        )
        if index < 2:
            events.extend(
                [
                    ToolResultStartEvent(
                        reply_id="r",
                        tool_call_id=call_id,
                        tool_call_name="rag_search",
                    ),
                    ToolResultTextDeltaEvent(
                        reply_id="r",
                        tool_call_id=call_id,
                        delta="same",
                    ),
                    ToolResultEndEvent(
                        reply_id="r",
                        tool_call_id=call_id,
                        state=ToolResultState.SUCCESS,
                    ),
                ]
            )

    runner = StubRunner(settings(), FakeAgent(events), observer)

    result = await runner.run("goal", context())

    assert result.stop_reason == "LOOP"
    assert len(result.steps) == 3
    assert "action repeated 3x" in result.steps[-1].observation
