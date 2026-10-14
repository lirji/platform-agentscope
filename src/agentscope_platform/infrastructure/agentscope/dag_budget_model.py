"""在真实模型边界实施整次 DAG 准入, 与 Java 租户日配额并行生效。"""

import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

from agentscope.message import Msg
from agentscope.model import ChatResponse

from agentscope_platform.application.dag_budget import current_dag_budget
from agentscope_platform.application.dag_recovery import current_recovery


async def dag_budgeted_call(
    delegate: Callable[..., Awaitable[ChatResponse | AsyncGenerator[ChatResponse, None]]],
    messages: list[Msg],
    *,
    output_limit: int,
    **kwargs: Any,
) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
    """以 UTF-8 输入字节加输出上限保守预留; 不将此数值当作账单 token。"""
    budget = current_dag_budget()
    if budget is not None:
        encoded = json.dumps(
            {"messages": [msg.model_dump(mode="json") for msg in messages], "options": kwargs},
            ensure_ascii=False,
        ).encode("utf-8")
        # 模板/媒体开销保守预留与现有中央预算策略一致; 当前 DAG 使用文本输入。
        tokens = len(encoded) + max(1, output_limit) + 4096 + 16_384
        budget.reserve(tokens)
        recovery = current_recovery()
        if recovery is not None:
            await recovery.reserve(
                tokens, budget.limits.max_model_calls, budget.limits.max_reserved_tokens
            )
    return await delegate(messages, **kwargs)
