from contextvars import ContextVar, Token
from time import monotonic, time

_deadline: ContextVar[float | None] = ContextVar("dependency_deadline", default=None)


def bind_deadline(timeout_seconds: float) -> Token[float | None]:
    """Bind a monotonic deadline without extending an already tighter parent deadline."""
    candidate = monotonic() + max(0.0, timeout_seconds)
    parent = _deadline.get()
    return _deadline.set(candidate if parent is None else min(parent, candidate))


def reset_deadline(token: Token[float | None]) -> None:
    _deadline.reset(token)


def remaining_seconds(maximum_seconds: float) -> float:
    deadline = _deadline.get()
    if deadline is None:
        return maximum_seconds
    return min(maximum_seconds, max(0.0, deadline - monotonic()))


def outbound_deadline_epoch_ms(maximum_seconds: float) -> int:
    """Return an epoch deadline for language-neutral downstream propagation."""
    return int((time() + remaining_seconds(maximum_seconds)) * 1000)
