import asyncio

import httpx
import pytest

from agentscope_platform.core.config import Settings
from agentscope_platform.core.deadline import bind_deadline, reset_deadline
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.infrastructure.http.platform_client import (
    PlatformClient,
    PlatformServiceError,
)
from agentscope_platform.infrastructure.http.resilience import (
    DependencyCallRejected,
    HttpDependencyGuard,
)


def context() -> RunContext:
    return RunContext(
        identity=TenantIdentity("acme", "alice"),
        internal_token="signed-internal-token",
        trace_id="trace-123",
    )


async def test_bulkhead_rejects_excess_work_without_starting_it() -> None:
    guard = HttpDependencyGuard(
        max_concurrent=1,
        failure_threshold=5,
        recovery_seconds=10,
    )
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def blocked() -> str:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return "ok"

    first = asyncio.create_task(guard.execute(blocked, timeout_seconds=1))
    await started.wait()
    with pytest.raises(DependencyCallRejected, match="bulkhead_full"):
        await guard.execute(blocked, timeout_seconds=1)
    assert calls == 1

    release.set()
    assert await first == "ok"


async def test_circuit_opens_then_allows_one_recovery_probe() -> None:
    now = [100.0]
    guard = HttpDependencyGuard(
        max_concurrent=2,
        failure_threshold=2,
        recovery_seconds=10,
        clock=lambda: now[0],
    )
    calls = 0

    async def unavailable() -> str:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("down")

    for _ in range(2):
        with pytest.raises(httpx.ConnectError):
            await guard.execute(unavailable, timeout_seconds=1)
    with pytest.raises(DependencyCallRejected, match="circuit_open"):
        await guard.execute(unavailable, timeout_seconds=1)
    assert calls == 2

    now[0] += 11
    assert await guard.execute(lambda: _value("recovered"), timeout_seconds=1) == "recovered"
    assert await guard.execute(lambda: _value("closed"), timeout_seconds=1) == "closed"


async def test_parent_deadline_caps_dependency_call() -> None:
    guard = HttpDependencyGuard(
        max_concurrent=1,
        failure_threshold=5,
        recovery_seconds=10,
    )
    token = bind_deadline(0.01)
    try:
        with pytest.raises(DependencyCallRejected, match="deadline_exceeded"):
            await guard.execute(lambda: _delayed_value(0.1), timeout_seconds=10)
    finally:
        reset_deadline(token)


async def test_stream_lease_holds_bulkhead_until_consumer_finishes() -> None:
    guard = HttpDependencyGuard(
        max_concurrent=1,
        failure_threshold=5,
        recovery_seconds=10,
    )
    entered = asyncio.Event()
    release = asyncio.Event()

    async def consume_stream() -> None:
        async with guard.lease(timeout_seconds=1):
            entered.set()
            await release.wait()

    first = asyncio.create_task(consume_stream())
    await entered.wait()
    with pytest.raises(DependencyCallRejected, match="bulkhead_full"):
        async with guard.lease(timeout_seconds=1):
            pass

    release.set()
    await first


async def test_platform_client_reuses_pool_propagates_deadline_and_closes_once() -> None:
    transport = TrackingTransport()
    client = PlatformClient(Settings(), transport)

    await client.query_knowledge("refund", 5, 0.5, None, context())
    await client.query_knowledge("refund", 5, 0.5, None, context())

    assert len(transport.requests) == 2
    assert all("X-Request-Deadline-Ms" in request.headers for request in transport.requests)
    assert transport.closed is False
    await client.close()
    assert transport.closed is True


async def test_platform_circuit_fails_closed_without_extra_network_call() -> None:
    attempts = 0

    def unavailable(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503)

    settings = Settings(
        http_circuit_failure_threshold=2,
        http_circuit_recovery_seconds=30,
    )
    client = PlatformClient(settings, httpx.MockTransport(unavailable))
    try:
        for _ in range(2):
            with pytest.raises(PlatformServiceError, match="returned HTTP 503"):
                await client.query_knowledge("refund", 5, 0.5, None, context())
        with pytest.raises(PlatformServiceError, match="circuit_open"):
            await client.query_knowledge("refund", 5, 0.5, None, context())
        assert attempts == 2
    finally:
        await client.close()


async def _value(value: str) -> str:
    return value


async def _delayed_value(delay: float) -> str:
    await asyncio.sleep(delay)
    return "late"


class TrackingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.closed = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            200,
            json={"query": "refund", "tenantId": "acme", "hits": []},
        )

    async def aclose(self) -> None:
        self.closed = True
