import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any, Protocol

from agentscope.message import Msg, SystemMsg, TextBlock, UserMsg
from agentscope.model import ChatResponse, FinishedReason, OpenAIChatModel

from agentscope_platform.application.ports import TextGenerationError, TextGenerator
from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import RunContext
from agentscope_platform.infrastructure.agentscope.model_factory import (
    build_openai_chat_model,
)
from agentscope_platform.infrastructure.agentscope.runner import (
    AgentNotConfiguredError,
)

log = logging.getLogger(__name__)
MAX_GENERATION_INPUT_CHARS = 65_536
MAX_GENERATION_RESPONSE_CHARS = 65_536


class _TextModel(Protocol):
    async def __call__(
        self,
        messages: list[Msg],
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]: ...


class AgentScopeTextGenerator(TextGenerator):
    def __init__(
        self,
        settings: Settings,
        general_model: _TextModel | None = None,
        deterministic_model: _TextModel | None = None,
    ) -> None:
        self._settings = settings
        self._general_model = general_model or self._build_model(settings.gateway_temperature)
        self._deterministic_model = deterministic_model or self._build_model(0)

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        context: RunContext,
        *,
        deterministic: bool = False,
    ) -> str:
        if not self._settings.agent_enabled:
            raise AgentNotConfiguredError("GATEWAY_API_KEY is not configured")
        if len(system_prompt) + len(user_prompt) > MAX_GENERATION_INPUT_CHARS:
            raise TextGenerationError("generation input exceeds safe size")
        model = self._deterministic_model if deterministic else self._general_model
        try:
            response = await model(
                [
                    SystemMsg(name="system", content=system_prompt),
                    UserMsg(name="user", content=user_prompt),
                ]
            )
            if not isinstance(response, ChatResponse):
                raise TextGenerationError("streaming generation response is unsupported")
            if response.get("finished_reason") == FinishedReason.INTERRUPTED:
                raise asyncio.CancelledError
            text = "".join(
                block.text for block in response.content if isinstance(block, TextBlock)
            ).strip()
            if not text or len(text) > MAX_GENERATION_RESPONSE_CHARS:
                raise TextGenerationError("generation response size is invalid")
            return text
        except asyncio.CancelledError:
            raise
        except TextGenerationError:
            raise
        except Exception as exc:
            log.warning(
                "Sibling model call failed: %s",
                type(exc).__name__,
                extra={
                    "trace_id": context.trace_id,
                    "tenant_id": context.identity.tenant_id,
                },
            )
            raise TextGenerationError("generation model call failed") from exc

    def _build_model(self, temperature: float) -> OpenAIChatModel:
        return build_openai_chat_model(
            self._settings,
            temperature=temperature,
            stream=False,
            max_tokens=self._settings.agent_planner_max_tokens,
            max_retries=self._settings.agent_planner_max_retries,
            timeout_seconds=self._settings.agent_planner_timeout_seconds,
            parallel_tool_calls=False,
        )
