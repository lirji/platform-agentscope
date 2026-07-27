import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from agentscope.message import Msg, TextBlock
from agentscope.model import ChatResponse, FinishedReason
from pydantic import SecretStr

from agentscope_platform.application.ports import DagQualityError
from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.domain.dag import AgentDagCritique, DagPlan
from agentscope_platform.infrastructure.agentscope.reviewer import (
    AgentScopeDagQualityReviewer,
)
from agentscope_platform.infrastructure.agentscope.runner import (
    AgentNotConfiguredError,
)


class FakeModel:
    def __init__(
        self,
        contents: list[str] | None = None,
        error: Exception | None = None,
        interrupted: bool = False,
    ) -> None:
        self.contents = list(contents or [])
        self.error = error
        self.interrupted = interrupted
        self.calls: list[tuple[list[Msg], dict[str, Any]]] = []

    async def __call__(
        self,
        messages: list[Msg],
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        self.calls.append((messages, kwargs))
        if self.error is not None:
            raise self.error
        if self.interrupted:
            return ChatResponse(
                content=[],
                is_last=True,
                finished_reason=FinishedReason.INTERRUPTED,
            )
        return ChatResponse(
            content=[TextBlock(text=self.contents.pop(0))],
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
        internal_token="must-not-enter-review-prompt",
        trace_id="review-trace",
    )


async def test_reviewer_scores_and_revises_with_json_contracts() -> None:
    model = FakeModel(
        [
            '{"correctness":0.6,"completeness":0.5,"clarity":0.7,"mainIssue":"missing evidence"}',
            '{"tasks":[{"id":"t1","description":"collect evidence","dependsOn":[]}]}',
        ]
    )
    reviewer = AgentScopeDagQualityReviewer(settings(), model)
    run_context = context()

    review = await reviewer.critique(
        "question",
        "weak answer",
        run_context,
    )
    plan = await reviewer.revise(
        "question",
        DagPlan.model_validate(
            {
                "tasks": [
                    {
                        "id": "t1",
                        "description": "initial",
                        "dependsOn": [],
                    }
                ]
            }
        ),
        "weak answer",
        review,
        run_context,
    )

    assert review.main_issue == "missing evidence"
    assert plan.tasks[0].description == "collect evidence"
    assert all(call[1]["response_format"] == {"type": "json_object"} for call in model.calls)
    assert "UNTRUSTED ANSWER" in model.calls[0][0][1].get_text_content()
    assert "PREVIOUS PLAN" in model.calls[1][0][1].get_text_content()
    assert "must-not-enter-review-prompt" not in str(model.calls)


@pytest.mark.parametrize(
    "content",
    [
        "",
        "not-json",
        '{"correctness":1.2,"completeness":0.5,"clarity":0.5,"mainIssue":"invalid"}',
        '{"correctness":0.5,"completeness":0.5,"clarity":0.5}',
    ],
)
async def test_critic_rejects_invalid_contract(content: str) -> None:
    reviewer = AgentScopeDagQualityReviewer(settings(), FakeModel([content]))

    with pytest.raises(DagQualityError, match="critic"):
        await reviewer.critique("question", "answer", context())


async def test_reviewer_sanitizes_model_failure() -> None:
    reviewer = AgentScopeDagQualityReviewer(
        settings(),
        FakeModel(error=RuntimeError("provider secret leaked")),
    )

    with pytest.raises(DagQualityError, match="critic model call failed") as exc:
        await reviewer.critique("question", "answer", context())

    assert "provider secret leaked" not in str(exc.value)


async def test_reviewer_propagates_cancellation() -> None:
    reviewer = AgentScopeDagQualityReviewer(
        settings(),
        FakeModel(interrupted=True),
    )

    with pytest.raises(asyncio.CancelledError):
        await reviewer.critique("question", "answer", context())


async def test_reviewer_requires_model_configuration() -> None:
    model = FakeModel()
    reviewer = AgentScopeDagQualityReviewer(settings(""), model)

    with pytest.raises(AgentNotConfiguredError):
        await reviewer.critique("question", "answer", context())

    assert model.calls == []


async def test_replanner_can_return_empty_plan_for_service_validation() -> None:
    reviewer = AgentScopeDagQualityReviewer(
        settings(),
        FakeModel(['{"tasks":[]}']),
    )

    revised = await reviewer.revise(
        "question",
        DagPlan(),
        "answer",
        AgentDagCritique(
            correctness=0.2,
            completeness=0.2,
            clarity=0.2,
            mainIssue="missing",
        ),
        context(),
    )

    assert revised.tasks == []
