"""通过 Java 预算权威覆盖真实模型调用, 包括 planner/reviewer 和流式终态。"""

import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import httpx
import jwt
from agentscope.message import Msg
from agentscope.model import ChatResponse, FinishedReason, OpenAIChatModel

from agentscope_platform.core.config import Settings
from agentscope_platform.core.context import current_run_context
from agentscope_platform.domain.agent import RunContext
from agentscope_platform.domain.metering import (
    BudgetReservationReply,
    BudgetReservationRequest,
    BudgetSettlementRequest,
)
from agentscope_platform.infrastructure.agentscope.closing_model import ClosingOpenAIChatModel


class ModelBudgetError(RuntimeError):
    """预算准入/结算失败, 不能以零消耗或绕过额度处理。"""


@dataclass(frozen=True)
class Reservation:
    operation_id: str
    day: str
    reserved_tokens: int


class BudgetAuthorityClient:
    """专用短时凭据绑定身份、RPC 和额度; 不持 Java 用户 JWT 签名权限。"""

    def __init__(
        self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._transport = transport

    async def reserve(self, context: RunContext, tokens: int) -> Reservation:
        operation = str(uuid4())
        payload = BudgetReservationRequest(operationId=operation, tokens=tokens).model_dump(
            by_alias=True
        )
        response = await self._request(context, "reserve", payload)
        try:
            body = BudgetReservationReply.model_validate(response.json()).model_dump(by_alias=True)
        except ValueError as exc:
            raise ModelBudgetError("budget reservation reply is invalid") from exc
        if (
            body.get("operationId") != operation
            or body.get("reservedTokens") != tokens
            or not isinstance(body.get("day"), str)
        ):
            raise ModelBudgetError("budget authority returned an inconsistent reservation")
        # 日期必须是规范日历日期, 不能将服务端异常内容传播给模型或日志。
        try:
            datetime.strptime(body["day"], "%Y-%m-%d")
        except ValueError as exc:
            raise ModelBudgetError("budget reservation day is invalid") from exc
        return Reservation(operation, body["day"], tokens)

    async def settle(self, context: RunContext, reservation: Reservation, actual: int) -> None:
        await self._request(
            context,
            "settle",
            BudgetSettlementRequest(
                operationId=reservation.operation_id,
                day=reservation.day,
                reservedTokens=reservation.reserved_tokens,
                actualTokens=actual,
            ).model_dump(by_alias=True),
        )

    async def _request(
        self, context: RunContext, action: str, payload: dict[str, Any]
    ) -> httpx.Response:
        now = int(datetime.now(UTC).timestamp())
        claims: dict[str, Any] = {
            "iss": "agentscope-platform",
            "aud": "platform-metering",
            "sub": "agentscope-platform",
            "token_use": "tenant_budget",
            "tenant": context.identity.tenant_id,
            "actor_uid": context.identity.user_id,
            "operation_id": payload["operationId"],
            "act": action,
            "jti": str(uuid4()),
            "iat": now,
            "exp": now + 30,
        }
        for field, value in payload.items():
            claim = {
                "tokens": "tokens",
                "day": "day",
                "reservedTokens": "reserved_tokens",
                "actualTokens": "actual_tokens",
            }.get(field)
            if claim:
                claims[claim] = value
        token = jwt.encode(
            claims,
            self._settings.token_budget_service_secret.get_secret_value(),
            algorithm="HS256",
            headers={"kid": "metering-v1", "typ": "JWT"},
        )
        endpoint = "reservations" if action == "reserve" else "settlements"
        url = f"{self._settings.token_budget_base_url.rstrip('/')}/internal/metering/{endpoint}"
        # 仅重试相同的幂等 RPC, 不重试模型调用; 网络未知结果保留原 operation。
        async with httpx.AsyncClient(
            timeout=self._settings.token_budget_timeout_seconds,
            transport=self._transport,
            trust_env=False,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
        ) as client:
            for attempt in range(2):
                try:
                    response = await client.post(
                        url, json=payload, headers={"Authorization": f"Bearer {token}"}
                    )
                    if response.status_code == 503 and attempt == 0:
                        continue
                    if response.status_code not in {200, 204}:
                        raise ModelBudgetError(
                            f"budget authority rejected {action}: HTTP {response.status_code}"
                        )
                    return response
                except httpx.TransportError as exc:
                    if attempt == 1:
                        raise ModelBudgetError("budget authority is unavailable") from exc
        raise ModelBudgetError("budget authority is unavailable")


async def budgeted_call(
    delegate: Callable[..., Awaitable[ChatResponse | AsyncGenerator[ChatResponse, None]]],
    authority: BudgetAuthorityClient,
    settings: Settings,
    messages: list[Msg],
    *,
    output_limit: int,
    **kwargs: Any,
) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
    """未知 usage 或取消保持预留; 闭合流式生成器会传递给底层以停止候选连接。"""
    context = current_run_context()
    encoded = json.dumps(
        [msg.model_dump(mode="json") for msg in messages], ensure_ascii=False
    ).encode("utf-8")
    tools = json.dumps(kwargs.get("tools"), ensure_ascii=False).encode("utf-8")
    size = len(encoded) + len(tools)
    if size > settings.token_budget_max_input_bytes:
        raise ModelBudgetError("model input exceeds budget limit")
    if output_limit < 1 or output_limit > settings.token_budget_max_output_tokens:
        raise ModelBudgetError("model output exceeds budget limit")
    if any(key in kwargs for key in ("max_tokens", "max_completion_tokens")):
        raise ModelBudgetError("model output override bypasses budget limit")
    # 非文本输入另预留保守额度; 真正的提供商 usage 可能超估算, 结算仍记录全量。
    media = sum(
        1
        for msg in messages
        for block in (msg.content if isinstance(msg.content, list) else [])
        if getattr(block, "type", "text") not in {"text", "tool_call", "tool_result", "thinking"}
    )
    reservation = await authority.reserve(
        context,
        size + len(messages) * 256 + output_limit + media * settings.token_budget_media_allowance,
    )
    response = await delegate(messages, **kwargs)

    async def settle(result: ChatResponse) -> None:
        if (
            result.is_last
            and result.get("finished_reason") == FinishedReason.COMPLETED
            and result.usage is not None
        ):
            usage = result.usage.input_tokens + result.usage.output_tokens
            if result.usage.input_tokens < 0 or result.usage.output_tokens < 0:
                raise ModelBudgetError("model usage is invalid")
            await authority.settle(context, reservation, usage)

    if isinstance(response, ChatResponse):
        await settle(response)
        return response

    async def stream() -> AsyncGenerator[ChatResponse, None]:
        try:
            async for chunk in response:
                if chunk.is_last:
                    await settle(chunk)
                    yield chunk
                    break
                yield chunk
        finally:
            await response.aclose()

    return stream()


class BudgetedOpenAIChatModel(ClosingOpenAIChatModel):
    """继承保持 AgentScope 模型接口兼容, 仅在实际调用最外层增加准入。"""

    budget_settings: Settings

    async def __call__(
        self,
        messages: list[Msg],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        limit = cast(OpenAIChatModel.Parameters, self.parameters).max_tokens
        if limit is None:
            raise ModelBudgetError("model output must be explicitly bounded")
        return await budgeted_call(
            super().__call__,
            BudgetAuthorityClient(self.budget_settings),
            self.budget_settings,
            messages,
            output_limit=limit,
            tools=tools,
            tool_choice=tool_choice,
            **kwargs,
        )
