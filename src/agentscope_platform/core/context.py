from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

from agentscope_platform.domain.agent import RunContext

_run_context: ContextVar[RunContext | None] = ContextVar("run_context", default=None)


def bind_run_context(context: RunContext) -> Token[RunContext | None]:
    return _run_context.set(context)


def reset_run_context(token: Token[RunContext | None]) -> None:
    _run_context.reset(token)


def current_run_context() -> RunContext:
    context = _run_context.get()
    if context is None:
        raise RuntimeError("run context is not bound")
    return context


@contextmanager
def run_context(context: RunContext) -> Iterator[None]:
    """局部模型调用绑定可信上下文, 退出时还原在途请求, 避免 planner 丢失身份。"""
    token = bind_run_context(context)
    try:
        yield
    finally:
        reset_run_context(token)
