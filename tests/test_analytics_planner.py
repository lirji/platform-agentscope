from collections.abc import AsyncGenerator
from typing import Any

import pytest
from agentscope.message import Msg, TextBlock
from agentscope.model import ChatResponse
from pydantic import SecretStr

from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.infrastructure.agentscope.analytics_planner import (
    AgentScopeAnalyticsSqlPlanner,
    AnalyticsPlanningError,
)


class FakeModel:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[tuple[list[Msg], dict[str, Any]]] = []

    async def __call__(
        self,
        messages: list[Msg],
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        self.calls.append((messages, kwargs))
        return ChatResponse(content=[TextBlock(text=self.content)], is_last=True)


def settings() -> Settings:
    return Settings(_env_file=None, gateway_api_key=SecretStr("test-key"))


def context() -> RunContext:
    return RunContext(
        identity=TenantIdentity("acme", "alice"),
        internal_token="secret-token",
        trace_id="trace-plan",
    )


async def test_analytics_planner_returns_neutral_sql_plan_without_identity() -> None:
    model = FakeModel(
        '{"sql":"select count(*) from orders where tenant_id = :tenantId"}'
    )
    planner = AgentScopeAnalyticsSqlPlanner(settings(), model)

    plan = await planner.plan(
        "统计订单",
        "orders(tenant_id varchar, id bigint)",
        context(),
    )

    assert plan.sql.endswith("tenant_id = :tenantId")
    messages, kwargs = model.calls[0]
    assert kwargs["response_format"] == {"type": "json_object"}
    assert "orders(tenant_id varchar" in messages[1].get_text_content()
    assert "acme" not in str(messages)
    assert "alice" not in str(messages)
    assert "secret-token" not in str(messages)


async def test_analytics_planner_rejects_extra_contract_fields() -> None:
    planner = AgentScopeAnalyticsSqlPlanner(
        settings(),
        FakeModel(
            '{"sql":"select 1 where tenant_id = :tenantId",'
            '"tenantId":"acme"}'
        ),
    )

    with pytest.raises(AnalyticsPlanningError, match="invalid analytics SQL plan"):
        await planner.plan("q", "schema", context())
