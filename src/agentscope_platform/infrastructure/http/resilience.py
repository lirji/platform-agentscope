import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import monotonic
from typing import TypeVar

import httpx

from agentscope_platform.core.config import Settings
from agentscope_platform.core.deadline import remaining_seconds

ResponseT = TypeVar("ResponseT")


class DependencyCallRejected(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(slots=True)
class DependencyCallLease:
    """A bulkhead slot held for the full lifetime of a dependency operation."""

    failed: bool = False

    def mark_failed(self) -> None:
        self.failed = True


@dataclass(slots=True)
class _CircuitState:
    failures: int = 0
    open_until: float = 0.0
    probe_active: bool = False
    inflight: int = 0


class HttpDependencyGuard:
    """Small async bulkhead + circuit breaker with an absolute call deadline."""

    def __init__(
        self,
        *,
        max_concurrent: int,
        failure_threshold: int,
        recovery_seconds: float,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._max_concurrent = max_concurrent
        self._failure_threshold = failure_threshold
        self._recovery_seconds = recovery_seconds
        self._clock = clock
        self._state = _CircuitState()
        self._lock = asyncio.Lock()

    async def execute(
        self,
        operation: Callable[[], Awaitable[ResponseT]],
        *,
        timeout_seconds: float,
        response_failed: Callable[[ResponseT], bool] | None = None,
    ) -> ResponseT:
        async with self.lease(timeout_seconds=timeout_seconds) as lease:
            result = await operation()
            if response_failed is not None and response_failed(result):
                lease.mark_failed()
            return result

    @asynccontextmanager
    async def lease(self, *, timeout_seconds: float) -> AsyncIterator[DependencyCallLease]:
        """Hold concurrency/circuit state across streaming and regular calls."""

        probe = await self._enter()
        lease = DependencyCallLease()
        try:
            timeout = remaining_seconds(timeout_seconds)
            if timeout <= 0:
                lease.mark_failed()
                raise DependencyCallRejected("deadline_exceeded")
            try:
                async with asyncio.timeout(timeout):
                    yield lease
            except TimeoutError as exc:
                lease.mark_failed()
                raise DependencyCallRejected("deadline_exceeded") from exc
            except httpx.TransportError:
                lease.mark_failed()
                raise
        except asyncio.CancelledError:
            raise
        except Exception:
            lease.mark_failed()
            raise
        finally:
            await self._leave(failed=lease.failed, probe=probe)

    async def _enter(self) -> bool:
        async with self._lock:
            now = self._clock()
            if self._state.open_until > now:
                raise DependencyCallRejected("circuit_open")
            probe = self._state.open_until > 0
            if probe and self._state.probe_active:
                raise DependencyCallRejected("circuit_open")
            if self._state.inflight >= self._max_concurrent:
                raise DependencyCallRejected("bulkhead_full")
            self._state.inflight += 1
            if probe:
                self._state.probe_active = True
            return probe

    async def _leave(self, *, failed: bool, probe: bool) -> None:
        async with self._lock:
            self._state.inflight = max(0, self._state.inflight - 1)
            if probe:
                self._state.probe_active = False
            if failed:
                self._state.failures += 1
                if self._state.failures >= self._failure_threshold:
                    self._state.open_until = self._clock() + self._recovery_seconds
                return
            self._state.failures = 0
            self._state.open_until = 0.0


class DependencyGuardRegistry:
    def __init__(self, settings: Settings) -> None:
        self._max_concurrent = settings.http_dependency_max_concurrent
        self._failure_threshold = settings.http_circuit_failure_threshold
        self._recovery_seconds = settings.http_circuit_recovery_seconds
        self._guards: dict[str, HttpDependencyGuard] = {}

    def for_dependency(self, name: str) -> HttpDependencyGuard:
        guard = self._guards.get(name)
        if guard is None:
            guard = HttpDependencyGuard(
                max_concurrent=self._max_concurrent,
                failure_threshold=self._failure_threshold,
                recovery_seconds=self._recovery_seconds,
            )
            self._guards[name] = guard
        return guard


def httpx_limits(settings: Settings) -> httpx.Limits:
    return httpx.Limits(
        max_connections=settings.http_max_connections,
        max_keepalive_connections=settings.http_max_keepalive_connections,
        keepalive_expiry=settings.http_keepalive_expiry_seconds,
    )
