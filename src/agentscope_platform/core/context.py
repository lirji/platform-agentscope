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
