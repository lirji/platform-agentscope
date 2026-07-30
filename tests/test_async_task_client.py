import json
from datetime import UTC, datetime

import httpx
import pytest

from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.infrastructure.http.async_task_client import (
    AsyncTaskGatewayError,
    HttpAsyncTaskClient,
)


def context() -> RunContext:
    return RunContext(
        identity=TenantIdentity("acme", "alice"),
        internal_token="internal-secret",
        trace_id="trace-1",
    )


def task_json(task_id: str = "task-1") -> dict[str, object]:
    now = datetime.now(UTC).isoformat()
    return {
        "taskId": task_id,
        "tenantId": "acme",
        "userId": "alice",
        "kind": "agent.run",
        "status": "PENDING",
        "input": {"goal": "test"},
        "result": None,
        "error": None,
        "webhookUrl": None,
        "createdAt": now,
        "updatedAt": now,
        "finishedAt": None,
        "leaseOwnerId": None,
        "leaseExpiresAt": None,
    }


@pytest.mark.asyncio
async def test_create_forwards_token_only_in_header() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["header"] = request.headers["X-Internal-Token"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(202, json=task_json(captured["body"]["taskId"]))

    raw = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://tasks.test",
    )
    client = HttpAsyncTaskClient(Settings(), raw)

    task = await client.create(
        task_id="task-1",
        kind="agent.run",
        input_data={"goal": "test"},
        webhook_url=None,
        context=context(),
    )

    assert task.task_id == "task-1"
    assert captured["header"] == "internal-secret"
    assert "internal-secret" not in json.dumps(captured["body"])
    await raw.aclose()


@pytest.mark.asyncio
async def test_get_maps_not_found_without_leaking_central_body() -> None:
    raw = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(404, text="private")),
        base_url="http://tasks.test",
    )
    client = HttpAsyncTaskClient(Settings(), raw)

    assert await client.get("missing", context()) is None
    await raw.aclose()


@pytest.mark.asyncio
async def test_transport_failure_is_sanitized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret upstream detail", request=request)

    raw = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://tasks.test",
    )
    client = HttpAsyncTaskClient(Settings(), raw)

    with pytest.raises(AsyncTaskGatewayError, match="unavailable") as raised:
        await client.get("task-1", context())

    assert "secret upstream detail" not in str(raised.value)
    await raw.aclose()
