"""显式关闭当前SDK未向内层传播aclose的HTTP流, 不依赖异步生成器GC."""

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextvars import ContextVar
from datetime import datetime
from typing import Any

from agentscope.message import Msg
from agentscope.model import ChatResponse, OpenAIChatModel

_closers: ContextVar[list[Callable[[], Awaitable[None]]] | None] = ContextVar(
    "openai_stream_closers", default=None
)


class ClosingOpenAIChatModel(OpenAIChatModel):
    """逐调用保存资源, 同一模型并发时不共享连接/关闭回调."""

    def _parse_stream_response(
        self, start_datetime: datetime, response: Any
    ) -> AsyncGenerator[ChatResponse, None]:
        inner = super()._parse_stream_response(start_datetime, response)
        resources = _closers.get()
        if resources is None:
            raise RuntimeError("model stream has no resource owner")
        # HTTP响应在解析generator开始迭代前已经打开, 因此两层都必须显式关闭.
        resources.extend([response.close, inner.aclose])
        return inner

    async def __call__(
        self,
        messages: list[Msg],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        resources: list[Callable[[], Awaitable[None]]] = []
        token = _closers.set(resources)

        async def close() -> None:
            if resources:
                closer = resources.pop()
                try:
                    await closer()
                finally:
                    # parser关闭异常也不能跳过HTTP响应关闭.
                    await close()

        try:
            result = await super().__call__(
                messages, tools=tools, tool_choice=tool_choice, **kwargs
            )
        except BaseException:
            await close()
            raise
        finally:
            _closers.reset(token)
        if isinstance(result, ChatResponse):
            await close()
            return result

        async def stream() -> AsyncGenerator[ChatResponse, None]:
            try:
                async for chunk in result:
                    yield chunk
            finally:
                try:
                    await result.aclose()
                finally:
                    await close()

        return stream()
