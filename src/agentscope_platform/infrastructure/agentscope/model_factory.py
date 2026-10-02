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
    from agentscope_platform.infrastructure.agentscope.budget_model import BudgetedOpenAIChatModel

    if settings.token_budget_enabled and max_retries != 0:
        raise ValueError("shared model budget requires fail-once provider calls")
    if settings.token_budget_enabled and max_tokens is None:
        max_tokens = settings.token_budget_max_output_tokens
    model_type = BudgetedOpenAIChatModel if settings.token_budget_enabled else OpenAIChatModel
    model = model_type(
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
    if isinstance(model, BudgetedOpenAIChatModel):
        model.budget_settings = settings
    return model
