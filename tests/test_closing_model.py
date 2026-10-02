from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

import pytest
from agentscope.credential import OpenAICredential
from agentscope.message import TextBlock
from agentscope.model import ChatResponse, OpenAIChatModel
from pydantic import SecretStr

from agentscope_platform.infrastructure.agentscope.closing_model import ClosingOpenAIChatModel


async def test_parser_close_failure_still_closes_the_underlying_http_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[str] = []

    class Response:
        async def close(self) -> None:
            closed.append("http")

    async def parser(*args: Any) -> AsyncGenerator[ChatResponse, None]:
        try:
            yield ChatResponse(content=[TextBlock(text="hello")], is_last=False)
        finally:
            closed.append("parser")
            raise RuntimeError("parser cleanup failed")

    async def call(model: ClosingOpenAIChatModel, *args: Any, **kwargs: Any) -> Any:
        # 走真实资源捕获边界, 不创建外部提供商连接.
        return model._parse_stream_response(datetime.now(), Response())

    monkeypatch.setattr(OpenAIChatModel, "_parse_stream_response", parser)
    monkeypatch.setattr(OpenAIChatModel, "__call__", call)
    model = ClosingOpenAIChatModel(
        credential=OpenAICredential(api_key=SecretStr("fake-only")), model="fake", stream=True
    )
    stream = await model([])
    assert not isinstance(stream, ChatResponse)
    await anext(stream)
    with pytest.raises(RuntimeError, match="parser cleanup failed"):
        await stream.aclose()
    assert closed == ["parser", "http"]
