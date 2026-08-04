import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from agentscope_platform.api.routes import _project_task_events


@pytest.mark.asyncio
async def test_projects_lifecycle_and_preserves_progress_across_chunk_boundaries() -> None:
    now = datetime.now(UTC).isoformat()
    central = {
        "taskId": "task-1",
        "tenantId": "acme",
        "userId": "alice",
        "kind": "agent.dag",
        "status": "RUNNING",
        "input": {"goal": "中文"},
        "result": None,
        "error": None,
        "webhookUrl": None,
        "createdAt": now,
        "updatedAt": now,
        "finishedAt": None,
        "leaseOwnerId": "worker",
        "leaseExpiresAt": now,
    }
    progress = {
        "taskId": "task-1",
        "event": "dag-worker-start",
        "data": {"taskId": "t1"},
        "ts": now,
    }
    payload = (
        f"id: 1\r\nevent: RUNNING\r\ndata: {json.dumps(central, ensure_ascii=False)}\r\n\r\n"
        f"id: 2\nevent: dag-worker-start\ndata: {json.dumps(progress)}\n\n"
    ).encode()

    async def chunks() -> AsyncIterator[bytes]:
        previous = 0
        for boundary in (7, 31, 83, len(payload)):
            yield payload[previous:boundary]
            previous = boundary

    output = b"".join([part async for part in _project_task_events(chunks())]).decode()

    first, second, _ = output.split("\n\n")
    data_line = next(line for line in first.splitlines() if line.startswith("data: "))
    lifecycle = json.loads(data_line[6:])
    assert lifecycle["taskId"] == "task-1"
    assert "kind" not in lifecycle
    assert "leaseOwnerId" not in lifecycle
    assert "中文" in first
    assert "dag-worker-start" in second


@pytest.mark.asyncio
async def test_invalid_upstream_frame_is_sanitized_and_closes_source() -> None:
    secret = "provider-secret-must-not-leak"
    closed = False

    async def chunks() -> AsyncIterator[bytes]:
        nonlocal closed
        try:
            yield f"event: RUNNING\ndata: {secret}\n\n".encode()
        finally:
            closed = True

    output = b"".join([part async for part in _project_task_events(chunks())]).decode()

    assert output == (
        'event: error\ndata: {"error":"agent task stream failed",'
        '"code":"AGENT_TASK_STREAM_FAILED"}\n\n'
    )
    assert secret not in output
    assert closed is True


@pytest.mark.asyncio
async def test_consumer_disconnect_closes_upstream_generator() -> None:
    closed = False

    async def chunks() -> AsyncIterator[bytes]:
        nonlocal closed
        try:
            yield b"event: progress\ndata: {}\n\n"
            await __import__("asyncio").Event().wait()
        finally:
            closed = True

    projected = _project_task_events(chunks())
    assert await anext(projected) == b"event: progress\ndata: {}\n\n"

    await projected.aclose()

    assert closed is True
