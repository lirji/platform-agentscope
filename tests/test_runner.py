import asyncio
from collections.abc import AsyncGenerator
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

from agentscope_platform.application.observer import RunObservation
from agentscope_platform.core.config import Settings
from agentscope_platform.core.context import current_run_context
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.infrastructure.agentscope.runner import AgentScopeRunner
from agentscope_platform.infrastructure.http.platform_client import PlatformClient


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

    def record(self, observation: RunObservation) -> None:
        self.observations.append(observation)


class StubRunner(AgentScopeRunner):
    def __init__(
        self,
        settings: Settings,
        agent: FakeAgent,
        observer: CapturingObserver,
    ) -> None:
        super().__init__(settings, PlatformClient(settings), observer)
        self._agent = agent

    def _build_agent(self) -> Agent:
        return cast(Agent, self._agent)


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "gateway_api_key": SecretStr("test-key"),
        "internal_auth_required": False,
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
