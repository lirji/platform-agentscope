from agentscope.credential import OpenAICredential
from agentscope.model import OpenAIChatModel
from pydantic import SecretStr

from agentscope_platform.core.config import Settings


def build_openai_chat_model(
    settings: Settings,
    *,
    temperature: float,
    stream: bool,
    max_tokens: int | None = None,
    max_retries: int = 3,
    timeout_seconds: float | None = None,
    parallel_tool_calls: bool = True,
) -> OpenAIChatModel:
    credential = OpenAICredential(
        api_key=SecretStr(settings.gateway_api_key.get_secret_value()),
        base_url=settings.gateway_base_url,
    )
    return OpenAIChatModel(
        credential=credential,
        model=settings.gateway_model,
        parameters=OpenAIChatModel.Parameters(
            temperature=temperature,
            max_tokens=max_tokens,
            parallel_tool_calls=parallel_tool_calls,
        ),
        stream=stream,
        max_retries=max_retries,
        client_kwargs=({"timeout": timeout_seconds} if timeout_seconds is not None else None),
    )
