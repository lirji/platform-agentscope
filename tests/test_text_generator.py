import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from agentscope.message import Msg, TextBlock
from agentscope.model import ChatResponse, FinishedReason
from pydantic import SecretStr

from agentscope_platform.application.ports import TextGenerationError
from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.infrastructure.agentscope.runner import (
    AgentNotConfiguredError,
)
from agentscope_platform.infrastructure.agentscope.text_generator import (
    AgentScopeTextGenerator,
)


class FakeModel:
    def __init__(
        self,
        content: str = "answer",
        *,
        error: Exception | None = None,
        interrupted: bool = False,
    ) -> None:
        self.content = content
        self.error = error
        self.interrupted = interrupted
        self.calls: list[tuple[list[Msg], dict[str, Any]]] = []

    async def __call__(
        self,
        messages: list[Msg],
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        self.calls.append((messages, kwargs))
        if self.error:
            raise self.error
        return ChatResponse(
            content=[] if self.interrupted else [TextBlock(text=self.content)],
            is_last=True,
            finished_reason=(FinishedReason.INTERRUPTED if self.interrupted else None),
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
        internal_token="never-copy-this-token",
        trace_id="trace",
    )


async def test_text_generator_selects_general_and_deterministic_models() -> None:
    general = FakeModel(" general ")
    deterministic = FakeModel("deterministic")
    generator = AgentScopeTextGenerator(settings(), general, deterministic)

    first = await generator.generate("system", "user", context())
    second = await generator.generate(
        "system",
        "user",
        context(),
        deterministic=True,
    )

    assert first == "general"
    assert second == "deterministic"
    assert len(general.calls) == 1
    assert len(deterministic.calls) == 1
    assert "never-copy-this-token" not in str(general.calls)


async def test_text_generator_sanitizes_provider_failure() -> None:
    model = FakeModel(error=RuntimeError("provider secret"))
    generator = AgentScopeTextGenerator(settings(), model, model)

    with pytest.raises(TextGenerationError, match="model call failed") as exc:
        await generator.generate("system", "user", context())

    assert "provider secret" not in str(exc.value)


async def test_text_generator_propagates_interruption_as_cancellation() -> None:
    model = FakeModel(interrupted=True)
    generator = AgentScopeTextGenerator(settings(), model, model)

    with pytest.raises(asyncio.CancelledError):
        await generator.generate("system", "user", context())


async def test_text_generator_rejects_missing_configuration_before_model_call() -> None:
    model = FakeModel()
    generator = AgentScopeTextGenerator(settings(""), model, model)

    with pytest.raises(AgentNotConfiguredError):
        await generator.generate("system", "user", context())

    assert model.calls == []


@pytest.mark.parametrize("content", ["", "x" * 65_537])
async def test_text_generator_rejects_invalid_response_size(content: str) -> None:
    model = FakeModel(content)
    generator = AgentScopeTextGenerator(settings(), model, model)

    with pytest.raises(TextGenerationError, match="response size"):
        await generator.generate("system", "user", context())
