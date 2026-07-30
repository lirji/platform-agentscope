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
