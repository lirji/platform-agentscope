import asyncio
import json
from collections.abc import AsyncIterator

import pytest

from agentscope_platform.api.routes import _project_task_events, _reflexion_events
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.domain.sibling import ReflexionRequest


def context() -> RunContext:
    return RunContext(
        identity=TenantIdentity("acme", "alice", frozenset({"agent"})),
        internal_token=None,
        trace_id="trace-stream-privacy",
    )


@pytest.mark.asyncio
async def test_task_stream_redacts_pii_recursively() -> None:
    now = "2026-08-03T00:00:00Z"
    task = {
        "taskId": "task-1",
        "tenantId": "acme",
        "userId": "alice",
        "kind": "agent.run",
        "status": "RUNNING",
        "input": {"email": "alice@example.com", "nested": ["13812345678"]},
        "result": {"identity": "11010519491231002X"},
        "error": None,
        "webhookUrl": None,
        "createdAt": now,
        "updatedAt": now,
        "finishedAt": None,
        "leaseOwnerId": "worker",
        "leaseExpiresAt": now,
    }

    async def chunks() -> AsyncIterator[bytes]:
        yield f"event: RUNNING\ndata: {json.dumps(task)}\n\n".encode()

    output = b"".join([part async for part in _project_task_events(chunks())]).decode()

    assert "alice@example.com" not in output
    assert "13812345678" not in output
    assert "11010519491231002X" not in output
    assert "[REDACTED-email]" in output
    assert "[REDACTED-phone]" in output
    assert "[REDACTED-id-card]" in output


class PiiReflexionService:
    async def run(self, request, run_context, progress):  # type: ignore[no-untyped-def]
        del request, run_context
        await progress.emit(
            "answer",
            {"answer": "contact alice@example.com or 13812345678"},
        )
        return None


class FailingReflexionService:
    async def run(self, request, run_context, progress):  # type: ignore[no-untyped-def]
        del request, run_context, progress
        raise RuntimeError("provider-key=must-not-leak")


@pytest.mark.asyncio
async def test_reflexion_stream_redacts_pii() -> None:
    output = b"".join(
        [
            part
            async for part in _reflexion_events(
                PiiReflexionService(),  # type: ignore[arg-type]
                ReflexionRequest(question="q"),
                context(),
            )
        ]
    ).decode()

    assert "alice@example.com" not in output
    assert "13812345678" not in output
    assert "[REDACTED-email]" in output
    assert "[REDACTED-phone]" in output


@pytest.mark.asyncio
async def test_reflexion_failure_uses_stable_public_error() -> None:
    stream = _reflexion_events(
        FailingReflexionService(),  # type: ignore[arg-type]
        ReflexionRequest(question="q"),
        context(),
    )

    output = await asyncio.wait_for(anext(stream), timeout=1)
    await stream.aclose()

    assert output == (
        b'event: error\ndata: {"error":"agent reflexion failed",'
        b'"code":"AGENT_REFLEXION_STREAM_FAILED"}\n\n'
    )
    assert b"provider-key" not in output
