import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import httpx
import jwt
import pytest
from agentscope.message import UserMsg
from agentscope.model import ChatResponse, ChatUsage, FinishedReason
from pydantic import SecretStr, ValidationError

from agentscope_platform.core.config import Settings
from agentscope_platform.core.context import run_context
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.infrastructure.agentscope.budget_model import (
    BudgetAuthorityClient,
    BudgetedOpenAIChatModel,
    ModelBudgetError,
    Reservation,
    budgeted_call,
)
from agentscope_platform.infrastructure.agentscope.model_factory import build_openai_chat_model


def settings(**overrides: Any) -> Settings:
    return Settings(
        _env_file=None,
        token_budget_enabled=True,
        token_budget_service_secret=SecretStr("budget-service-key-isolated-at-least-32-bytes"),
        **overrides,
    )


def context() -> RunContext:
    return RunContext(TenantIdentity("t1", "u1"), None, "trace")


def response(*, usage: bool = True, interrupted: bool = False) -> ChatResponse:
    return ChatResponse(
        content=[],
        is_last=True,
        usage=ChatUsage(input_tokens=10, output_tokens=20, time=0.1) if usage else None,
        finished_reason=FinishedReason.INTERRUPTED if interrupted else FinishedReason.COMPLETED,
    )


class StubAuthority(BudgetAuthorityClient):
    def __init__(self, *, denied: bool = False) -> None:
        super().__init__(settings())
        self.denied = denied
        self.held: list[tuple[RunContext, int]] = []
        self.settled: list[tuple[RunContext, int]] = []

    async def reserve(self, owner: RunContext, tokens: int) -> Reservation:
        if self.denied:
            raise ModelBudgetError("quota denied")
        self.held.append((owner, tokens))
        return Reservation("op", "2026-10-01", tokens)

    async def settle(self, owner: RunContext, reservation: Reservation, actual: int) -> None:
        self.settled.append((owner, actual))


async def test_provider_not_called_after_denial() -> None:
    called = False

    async def model(messages: Any, **kwargs: Any) -> ChatResponse:
        nonlocal called
        called = True
        return response()

    authority = StubAuthority(denied=True)
    with run_context(context()), pytest.raises(ModelBudgetError):
        await budgeted_call(
            model, authority, settings(), [UserMsg(name="u", content="hello")], output_limit=4096
        )
    assert not called


@pytest.mark.parametrize("usage,interrupted", [(False, False), (True, True)])
async def test_unknown_or_interrupted_usage_remains_reserved(
    usage: bool, interrupted: bool
) -> None:
    async def model(messages: Any, **kwargs: Any) -> ChatResponse:
        return response(usage=usage, interrupted=interrupted)

    authority = StubAuthority()
    with run_context(context()):
        await budgeted_call(
            model, authority, settings(), [UserMsg(name="u", content="hi")], output_limit=4096
        )
    assert len(authority.held) == 1
    assert not authority.settled


async def test_cancellation_retains_reservation() -> None:
    async def model(messages: Any, **kwargs: Any) -> ChatResponse:
        raise asyncio.CancelledError

    authority = StubAuthority()
    with run_context(context()), pytest.raises(asyncio.CancelledError):
        await budgeted_call(
            model, authority, settings(), [UserMsg(name="u", content="hi")], output_limit=4096
        )
    assert len(authority.held) == 1
    assert not authority.settled


async def test_stream_settles_once_captures_context_and_closes_upstream() -> None:
    closed = False

    async def chunks() -> AsyncGenerator[ChatResponse, None]:
        nonlocal closed
        try:
            yield ChatResponse(content=[], is_last=False)
            yield response()
            yield response()
        finally:
            closed = True

    async def model(messages: Any, **kwargs: Any) -> AsyncGenerator[ChatResponse, None]:
        return chunks()

    authority = StubAuthority()
    owner = context()
    with run_context(owner):
        stream = await budgeted_call(
            model, authority, settings(), [UserMsg(name="u", content="hi")], output_limit=4096
        )
    assert not isinstance(stream, ChatResponse)
    chunks_seen = [chunk async for chunk in stream]
    assert len(chunks_seen) == 2
    assert authority.settled == [(owner, 30)]
    assert closed


async def test_disconnected_stream_closes_provider_and_keeps_unknown_usage() -> None:
    closed = False

    async def chunks() -> AsyncGenerator[ChatResponse, None]:
        nonlocal closed
        try:
            yield ChatResponse(content=[], is_last=False)
            yield response()
        finally:
            closed = True

    async def model(messages: Any, **kwargs: Any) -> AsyncGenerator[ChatResponse, None]:
        return chunks()

    authority = StubAuthority()
    with run_context(context()):
        stream = await budgeted_call(
            model, authority, settings(), [UserMsg(name="u", content="hi")], output_limit=4096
        )
    assert not isinstance(stream, ChatResponse)
    await anext(stream)
    await stream.aclose()
    assert closed
    assert not authority.settled


async def test_rpc_retries_same_signed_operation_and_binds_payload() -> None:
    received: list[dict[str, Any]] = []
    claims_seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        received.append(body)
        claims_seen.append(
            jwt.decode(
                request.headers["Authorization"][7:],
                settings().token_budget_service_secret.get_secret_value(),
                algorithms=["HS256"],
                audience="platform-metering",
                issuer="agentscope-platform",
            )
        )
        if len(received) == 1:
            raise httpx.ReadTimeout("response lost", request=request)
        if request.url.path.endswith("reservations"):
            return httpx.Response(
                200,
                json={
                    "operationId": body["operationId"],
                    "day": datetime.now(UTC).date().isoformat(),
                    "reservedTokens": body["tokens"],
                },
            )
        return httpx.Response(204)

    authority = BudgetAuthorityClient(settings(), httpx.MockTransport(handler))
    owner = context()
    reservation = await authority.reserve(owner, 5000)
    await authority.settle(owner, reservation, 30)
    assert received[0] == received[1]
    assert claims_seen[0] == claims_seen[1]
    assert claims_seen[0]["tenant"] == "t1"
    assert claims_seen[0]["actor_uid"] == "u1"
    assert claims_seen[0]["tokens"] == 5000
    assert claims_seen[-1]["actual_tokens"] == 30
    assert claims_seen[-1]["act"] == "settle"


def test_factory_bounds_output_and_requires_dedicated_credential() -> None:
    model = build_openai_chat_model(
        settings(gateway_api_key=SecretStr("fake-key")), temperature=0, stream=False, max_retries=0
    )
    assert isinstance(model, BudgetedOpenAIChatModel)
    assert model.parameters.model_dump()["max_tokens"] == 4096
    with pytest.raises(ValueError, match="fail-once"):
        build_openai_chat_model(settings(), temperature=0, stream=False, max_retries=1)
    with pytest.raises(ValidationError, match="dedicated"):
        settings(internal_jwt_secret=settings().token_budget_service_secret)
