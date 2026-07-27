import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from agentscope.message import Msg, TextBlock
from agentscope.model import ChatResponse, FinishedReason
from pydantic import SecretStr

from agentscope_platform.application.ports import DagPlanningError
from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.domain.dag import DagPlanKind
from agentscope_platform.infrastructure.agentscope.planner import (
    ANALYST_PLANNER_PROMPT,
    PROCESS_PLANNER_PROMPT,
    AgentScopeDagPlanner,
)
from agentscope_platform.infrastructure.agentscope.runner import (
    AgentNotConfiguredError,
)


class FakeModel:
    def __init__(
        self,
        content: str = '{"tasks":[]}',
        error: Exception | None = None,
    ) -> None:
        self.content = content
        self.error = error
        self.calls: list[tuple[list[Msg], dict[str, Any]]] = []

    async def __call__(
        self,
        messages: list[Msg],
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        self.calls.append((messages, kwargs))
        if self.error is not None:
            raise self.error
        return ChatResponse(
            content=[TextBlock(text=self.content)],
            is_last=True,
        )


def settings(api_key: str = "test-key") -> Settings:
    return Settings(
        _env_file=None,
        gateway_api_key=SecretStr(api_key),
        internal_auth_required=False,
    )


def context() -> RunContext:
    return RunContext(
        identity=TenantIdentity("acme", "alice"),
        internal_token="must-not-enter-planner-prompt",
        trace_id="trace-plan",
    )


async def test_planner_parses_language_neutral_plan_and_requests_json() -> None:
    model = FakeModel(
        '{"tasks":[{"id":"t1","description":"inspect",'
        '"dependsOn":[]},{"id":"t2","description":"answer",'
        '"dependsOn":["t1"]}]}'
    )
    planner = AgentScopeDagPlanner(settings(), model)

    plan = await planner.plan("goal", context(), DagPlanKind.GENERAL)

    assert [task.id for task in plan.tasks] == ["t1", "t2"]
    messages, kwargs = model.calls[0]
    assert kwargs["response_format"] == {"type": "json_object"}
    assert "multi-agent DAG" in messages[0].get_text_content()
    assert messages[1].get_text_content() == "User goal:\ngoal"
    assert "must-not-enter-planner-prompt" not in str(messages)


async def test_analyst_planner_uses_readonly_tool_specific_prompt() -> None:
    model = FakeModel()
    planner = AgentScopeDagPlanner(settings(), model)

    await planner.plan("分析退款趋势", context(), DagPlanKind.ANALYST)

    prompt = model.calls[0][0][0].get_text_content()
    assert prompt == ANALYST_PLANNER_PROMPT
    assert "schema_explore" in prompt
    assert "analytics_sql" in prompt
    assert "不得规划 code_exec" in prompt


async def test_process_planner_exposes_only_readonly_workflow_tools() -> None:
    model = FakeModel()
    planner = AgentScopeDagPlanner(settings(), model)

    await planner.plan("查询流程状态", context(), DagPlanKind.PROCESS)

    prompt = model.calls[0][0][0].get_text_content()
    assert prompt == PROCESS_PLANNER_PROMPT
    assert "workflow_status" in prompt
    assert "workflow_tasks" in prompt
    assert "不得规划 refund_start" in prompt


@pytest.mark.parametrize(
    "content",
    [
        "",
        "not-json",
        '{"tasks":[{"id":"","description":"x","dependsOn":[]}]}',
        '{"tasks":[{"id":" ","description":"x","dependsOn":[]}]}',
        '{"tasks":[{"id":"t1","description":"x","dependsOn":[]},'
        '{"id":"t2","description":"x","dependsOn":[]},'
        '{"id":"t3","description":"x","dependsOn":[]},'
        '{"id":"t4","description":"x","dependsOn":[]},'
        '{"id":"t5","description":"x","dependsOn":[]},'
        '{"id":"t6","description":"x","dependsOn":[]},'
        '{"id":"t7","description":"x","dependsOn":[]}]}',
    ],
)
async def test_planner_rejects_invalid_model_contract(content: str) -> None:
    planner = AgentScopeDagPlanner(settings(), FakeModel(content))

    with pytest.raises(DagPlanningError, match="Planner"):
        await planner.plan("goal", context(), DagPlanKind.GENERAL)


async def test_planner_sanitizes_model_error() -> None:
    planner = AgentScopeDagPlanner(
        settings(),
        FakeModel(error=RuntimeError("provider leaked secret")),
    )

    with pytest.raises(DagPlanningError, match="Planner model call failed") as exc:
        await planner.plan("goal", context(), DagPlanKind.GENERAL)

    assert "provider leaked secret" not in str(exc.value)


async def test_planner_requires_model_configuration_without_calling_model() -> None:
    model = FakeModel()
    planner = AgentScopeDagPlanner(settings(""), model)

    with pytest.raises(AgentNotConfiguredError):
        await planner.plan("goal", context(), DagPlanKind.GENERAL)

    assert model.calls == []


async def test_planner_propagates_agentscope_interruption_as_cancellation() -> None:
    class InterruptedModel(FakeModel):
        async def __call__(
            self,
            messages: list[Msg],
            **kwargs: Any,
        ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
            self.calls.append((messages, kwargs))
            return ChatResponse(
                content=[],
                is_last=True,
                finished_reason=FinishedReason.INTERRUPTED,
            )

    planner = AgentScopeDagPlanner(settings(), InterruptedModel())

    with pytest.raises(asyncio.CancelledError):
        await planner.plan("goal", context(), DagPlanKind.GENERAL)
