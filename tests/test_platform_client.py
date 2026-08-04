import json

import httpx
import pytest

from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.infrastructure.http.platform_client import (
    PlatformClient,
    PlatformServiceError,
)


def context() -> RunContext:
    return RunContext(
        identity=TenantIdentity("acme", "alice"),
        internal_token="signed-internal-token",
        trace_id="trace-123",
    )


async def test_retained_service_contracts_and_context_propagation() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == "/rag/query":
            return httpx.Response(
                200,
                json={"query": "refund", "tenantId": "acme", "hits": []},
            )
        if request.url.raw_path == b"/orders/10%2F1":
            return httpx.Response(
                200,
                json={
                    "orderNo": "10/1",
                    "customer": "Alice",
                    "amount": "12.30",
                    "status": "已支付",
                    "createdAt": "2026-07-01",
                },
            )
        if path == "/analytics/schema/tables":
            return httpx.Response(200, json={"tables": ["orders"]})
        if path == "/analytics/schema/tables/orders":
            return httpx.Response(200, json={"table": "orders", "schema": "id bigint"})
        if path == "/analytics/sql":
            return httpx.Response(
                200,
                json={
                    "question": "total",
                    "sql": "select 1",
                    "rowCount": 1,
                    "rows": [{"value": 1}],
                    "answer": "one",
                    "guardBlocked": False,
                },
            )
        if path == "/analytics/sql/plans/execute":
            return httpx.Response(
                200,
                json={
                    "question": "total",
                    "sql": "select 1 where tenant_id = :tenantId",
                    "rowCount": 1,
                    "rows": [{"value": 1}],
                    "executed": True,
                    "rejectionReason": None,
                },
            )
        raise AssertionError(f"unexpected path: {path}")

    client = PlatformClient(Settings(), httpx.MockTransport(handler))
    run_context = context()

    await client.query_knowledge("refund", 5, 0.5, "manual", run_context)
    order = await client.get_order("10/1", run_context)
    tables = await client.list_analytics_tables(run_context)
    schema = await client.describe_analytics_table("orders", run_context)
    analytics = await client.query_analytics("total", run_context)
    plan = await client.execute_analytics_plan(
        "total",
        "select 1 where tenant_id = :tenantId",
        run_context,
    )

    assert order is not None and order.order_no == "10/1"
    assert tables.tables == ["orders"]
    assert schema is not None and schema.schema_text == "id bigint"
    assert analytics.row_count == 1
    assert plan.executed is True
    assert len(seen) == 6
    assert all(request.headers["X-Internal-Token"] == "signed-internal-token" for request in seen)
    assert all(request.headers["X-Trace-Id"] == "trace-123" for request in seen)
    rag_body = json.loads(seen[0].content)
    assert rag_body == {
        "query": "refund",
        "topK": 5,
        "minScore": 0.5,
        "category": "manual",
    }
    assert json.loads(seen[-2].content) == {"question": "total"}
    assert json.loads(seen[-1].content) == {
        "question": "total",
        "sql": "select 1 where tenant_id = :tenantId",
    }


async def test_order_and_schema_404_are_normalized() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(404))
    client = PlatformClient(Settings(), transport)

    assert await client.get_order("missing", context()) is None
    assert await client.describe_analytics_table("missing", context()) is None


async def test_invalid_retained_service_response_is_safe_error() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="not-json"))
    client = PlatformClient(Settings(), transport)

    with pytest.raises(PlatformServiceError, match="invalid knowledge-service response"):
        await client.query_knowledge("query", 5, 0, None, context())


async def test_workflow_read_contracts_preserve_context_and_encode_instance() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.raw_path == b"/workflow/instances/i%2F1":
            return httpx.Response(
                200,
                json={
                    "instanceId": "i/1",
                    "status": "WAITING_APPROVAL",
                    "reply": None,
                },
            )
        if request.url.path == "/workflow/tasks":
            return httpx.Response(
                200,
                json=[
                    {
                        "taskId": "task-1",
                        "name": "approveRefund",
                        "instanceId": "i/1",
                        "priority": "HIGH",
                        "summary": "refund 5000",
                        "assignee": None,
                    }
                ],
            )
        raise AssertionError(request.url)

    client = PlatformClient(Settings(), httpx.MockTransport(handler))
    instance = await client.get_workflow_instance("i/1", context())
    tasks = await client.list_workflow_tasks(context())

    assert instance is not None and instance.status == "WAITING_APPROVAL"
    assert tasks[0].task_id == "task-1"
    assert all(request.headers["X-Internal-Token"] == "signed-internal-token" for request in seen)


async def test_workflow_start_contract_forwards_only_explicit_business_fields() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "instanceId": "wf-1",
                "status": "WAITING_APPROVAL",
                "taskId": "t-1",
                "priority": "HIGH",
                "deduplicated": False,
            },
        )

    client = PlatformClient(Settings(), httpx.MockTransport(handler))
    reply = await client.start_refund(
        message="refund order 101",
        chat_id="agent:alice",
        dedupe_id="refund-42",
        context=context(),
    )

    assert reply.instance_id == "wf-1"
    assert len(seen) == 1
    assert json.loads(seen[0].content) == {
        "message": "refund order 101",
        "chatId": "agent:alice",
        "dedupeId": "refund-42",
    }
    assert seen[0].headers["X-Internal-Token"] == "signed-internal-token"


async def test_workflow_instance_404_is_normalized() -> None:
    client = PlatformClient(
        Settings(),
        httpx.MockTransport(lambda request: httpx.Response(404)),
    )

    assert await client.get_workflow_instance("missing", context()) is None
