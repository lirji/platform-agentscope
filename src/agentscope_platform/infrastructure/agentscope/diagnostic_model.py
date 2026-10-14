"""在实际模型边界观察终态 usage, 不改变预算和供应商重试行为。"""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from decimal import Decimal
from time import monotonic
from typing import Any, Literal

from agentscope.model import ChatResponse, FinishedReason

from agentscope_platform.application.dag_diagnostics import current_operation
from agentscope_platform.domain.dag_diagnostics import SUCCESS_STOP_REASON


async def observed_model_call(
    delegate: Callable[..., Awaitable[ChatResponse | AsyncGenerator[ChatResponse, None]]],
    *,
    model: str,
    input_rate: Decimal | None,
    output_rate: Decimal | None,
    **kwargs: Any,
) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
    """流式快照只取最终完整 usage; 中断不能把中间累计值当作完整消费。"""
    operation = current_operation()
    if operation is None or operation.session is None:
        return await delegate(**kwargs)
    started = monotonic()
    status: Literal["DONE", "ERROR", "CANCELLED"] = "ERROR"
    usage: tuple[int, int] | None = None
    recorded = False

    def consume(response: ChatResponse) -> None:
        nonlocal usage, status
        if response.is_last and response.get("finished_reason") == FinishedReason.COMPLETED:
            status = "DONE"
            if response.usage is not None:
                usage = (response.usage.input_tokens, response.usage.output_tokens)

    def record() -> None:
        nonlocal recorded
        if recorded:
            return
        recorded = True
        operation.unfinished_calls.discard(finalize)
        operation.model_finished(
            model,
            status,
            max(0.0, (monotonic() - started) * 1000),
            usage[0] if usage else None,
            usage[1] if usage else None,
            input_rate,
            output_rate,
        )

    def finalize() -> None:
        """流未消费完就退出操作时记录未知消费, 不让汇总误报为零。"""
        nonlocal status
        if not recorded:
            status = "CANCELLED"
            record()

    operation.unfinished_calls.add(finalize)

    try:
        result = await delegate(**kwargs)
    except BaseException as exc:
        if isinstance(exc, asyncio.CancelledError):
            status = "CANCELLED"
        record()
        raise
    if isinstance(result, ChatResponse):
        consume(result)
        record()
        return result

    async def stream() -> AsyncGenerator[ChatResponse, None]:
        nonlocal status
        try:
            async for chunk in result:
                consume(chunk)
                yield chunk
                if chunk.is_last:
                    break
        except (asyncio.CancelledError, GeneratorExit):
            if status != SUCCESS_STOP_REASON:
                status = "CANCELLED"
            raise
        finally:
            # 在资源关闭前记录, 关闭异常不能丢失已知 usage。
            record()
            await result.aclose()

    return stream()
