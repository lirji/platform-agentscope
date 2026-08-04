import asyncio

import pytest

from agentscope_platform.api.routes import _reflexion_events
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.domain.sibling import ReflexionRequest


class BlockingReflexionService:
    def __init__(self) -> None:
        self.cancelled = asyncio.Event()

    async def run(self, request, context, progress):  # type: ignore[no-untyped-def]
        del request, context
        try:
            # Fill the bounded queue so the cancellation path exercises the former deadlock.
            for index in range(33):
                await progress.emit("answer", {"n": index, "answer": "safe"})
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


def context() -> RunContext:
    return RunContext(
        identity=TenantIdentity("acme", "alice", frozenset({"agent"})),
        internal_token=None,
        trace_id="trace-stream-cancel",
    )


@pytest.mark.asyncio
async def test_reflexion_disconnect_cancels_full_queue_producer_without_hanging() -> None:
    service = BlockingReflexionService()
    stream = _reflexion_events(service, ReflexionRequest(question="q"), context())  # type: ignore[arg-type]
    first = await anext(stream)
    assert b"event: answer" in first

    await asyncio.wait_for(stream.aclose(), timeout=1)

    await asyncio.wait_for(service.cancelled.wait(), timeout=1)
