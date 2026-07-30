import httpx
from agentscope.message import TextBlock, ToolResultState

from agentscope_platform.core.config import Settings
from agentscope_platform.core.context import bind_run_context, reset_run_context
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.domain.analytics import AnalyticsSqlPlan
from agentscope_platform.infrastructure.agentscope.readonly_tools import ReadonlyToolset
from agentscope_platform.infrastructure.http.platform_client import PlatformClient


def context() -> RunContext:
    return RunContext(
        identity=TenantIdentity("acme", "alice"),
        internal_token="token",
        trace_id="trace",
    )


def text(chunk: object) -> str:
    content = chunk.content
    block = content[0]
    assert isinstance(block, TextBlock)
    return block.text


class FakeAnalyticsPlanner:
    def __init__(self, sql: str = "select count(*) from orders where tenant_id = :tenantId"):
        self.sql = sql
        self.calls: list[tuple[str, str, RunContext]] = []

    async def plan(
        self,
        question: str,
        schema: str,
        run_context: RunContext,
    ) -> AnalyticsSqlPlan:
        self.calls.append((question, schema, run_context))
        return AnalyticsSqlPlan(sql=self.sql)


async def test_rag_search_formats_sources_and_truncates() -> None:
    long_text = "x" * 601

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "query": "退款",
                "tenantId": "acme",
                "hits": [
                    {
                        "displayName": "policy.md",
                        "index": "2",
                        "text": long_text,
                        "source": "manual",
                    },
                    {"displayName": "empty", "index": "3", "text": " "},
                ],
            },
        )

    settings = Settings(agent_rag_top_k=5)
    tools = ReadonlyToolset(
        settings,
        PlatformClient(settings, httpx.MockTransport(handler)),
    )
    token = bind_run_context(context())
    try:
        result = await tools.rag_search(" 退款 ")
    finally:
        reset_run_context(token)

    assert result.state == ToolResultState.RUNNING
    assert text(result).startswith("检索到 1 条片段：\n[doc=policy.md#2] (manual) ")
    assert text(result).endswith("...")
    assert "x" * 601 not in text(result)


async def test_rag_search_rejects_mismatched_tenant() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"query": "q", "tenantId": "globex", "hits": []},
        )
    )
    settings = Settings()
    tools = ReadonlyToolset(settings, PlatformClient(settings, transport))
    token = bind_run_context(context())
    try:
        result = await tools.rag_search("q")
    finally:
        reset_run_context(token)

    assert result.state == ToolResultState.ERROR
    assert "不一致的租户" in text(result)


async def test_order_schema_and_analytics_preserve_legacy_observations() -> None:
    rows = [{"n": index, "ok": True} for index in range(11)]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/orders/101":
            return httpx.Response(
                200,
                json={
                    "orderNo": "101",
                    "customer": "张三",
                    "amount": "99.00",
                    "status": "已支付",
                    "createdAt": "2026-07-01",
                },
            )
        if request.url.path == "/analytics/schema/tables":
            return httpx.Response(200, json={"tables": ["orders", "refunds"]})
        if request.url.path == "/analytics/schema/tables/orders":
            return httpx.Response(200, json={"table": "orders", "schema": "id bigint"})
        if request.url.path == "/analytics/sql":
            return httpx.Response(
                200,
                json={
                    "question": "统计",
                    "sql": "select * from orders",
                    "rowCount": 11,
                    "rows": rows,
                    "answer": "共 11 行",
                    "guardBlocked": False,
                },
            )
        raise AssertionError(request.url.path)

    settings = Settings()
    tools = ReadonlyToolset(
        settings,
        PlatformClient(settings, httpx.MockTransport(handler)),
    )
    token = bind_run_context(context())
    try:
        order = await tools.order_query("101")
        tables = await tools.schema_explore()
        schema = await tools.schema_explore("orders")
        analytics = await tools.analytics_sql("统计")
    finally:
        reset_run_context(token)

    assert text(order) == (
        "订单号: 101\n状态: 已支付\n金额: ¥99.00\n客户: 张三\n下单日期: 2026-07-01"
    )
    assert text(tables) == "可查询的表：orders, refunds"
    assert text(schema) == "id bigint"
    assert "数据: {n=0, ok=true}; {n=1, ok=true}" in text(analytics)
    assert "...(共 11 行)" in text(analytics)
    assert text(analytics).endswith("解读: 共 11 行")


async def test_analytics_guard_block_is_not_reported_as_tool_error() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "question": "delete",
                "sql": None,
                "rowCount": 0,
                "rows": [],
                "answer": None,
                "guardBlocked": True,
            },
        )
    )
    settings = Settings()
    tools = ReadonlyToolset(settings, PlatformClient(settings, transport))
    token = bind_run_context(context())
    try:
        result = await tools.analytics_sql("delete")
    finally:
        reset_run_context(token)

    assert result.state == ToolResultState.RUNNING
    assert "安全护栏拦截" in text(result)


async def test_analytics_external_planner_runs_only_as_shadow() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/analytics/sql":
            return httpx.Response(
                200,
                json={
                    "question": "统计订单",
                    "sql": "legacy sql",
                    "rowCount": 1,
                    "rows": [{"value": 7}],
                    "answer": "legacy answer",
                    "guardBlocked": False,
                },
            )
        if request.url.path == "/analytics/schema/tables":
            return httpx.Response(200, json={"tables": ["orders"]})
        if request.url.path == "/analytics/schema/tables/orders":
            return httpx.Response(
                200,
                json={"table": "orders", "schema": "tenant_id varchar, id bigint"},
            )
        if request.url.path == "/analytics/sql/plans/execute":
            return httpx.Response(
                200,
                json={
                    "question": "统计订单",
                    "sql": "select count(*) from orders where tenant_id = :tenantId",
                    "rowCount": 1,
                    "rows": [{"value": 7}],
                    "executed": True,
                    "rejectionReason": None,
                },
            )
        raise AssertionError(request.url.path)

    settings = Settings(analytics_external_planner_shadow_enabled=True)
    planner = FakeAnalyticsPlanner()
    tools = ReadonlyToolset(
        settings,
        PlatformClient(settings, httpx.MockTransport(handler)),
        analytics_planner=planner,
    )
    token = bind_run_context(context())
    try:
        result = await tools.analytics_sql("统计订单")
    finally:
        reset_run_context(token)

    assert text(result).endswith("解读: legacy answer")
    assert planner.calls[0][0] == "统计订单"
    assert "tenant_id varchar" in planner.calls[0][1]
    candidate_request = seen[-1]
    assert candidate_request.url.path == "/analytics/sql/plans/execute"
    assert candidate_request.headers["X-Internal-Token"] == "token"
    assert b"acme" not in candidate_request.content
    assert b"alice" not in candidate_request.content


async def test_analytics_shadow_failure_does_not_break_legacy_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/analytics/sql":
            return httpx.Response(
                200,
                json={
                    "question": "统计",
                    "sql": "legacy sql",
                    "rowCount": 0,
                    "rows": [],
                    "answer": "legacy survives",
                    "guardBlocked": False,
                },
            )
        return httpx.Response(503)

    settings = Settings(analytics_external_planner_shadow_enabled=True)
    tools = ReadonlyToolset(
        settings,
        PlatformClient(settings, httpx.MockTransport(handler)),
        analytics_planner=FakeAnalyticsPlanner(),
    )
    token = bind_run_context(context())
    try:
        result = await tools.analytics_sql("统计")
    finally:
        reset_run_context(token)

    assert text(result).endswith("解读: legacy survives")


async def test_workflow_status_and_tasks_are_read_only_and_tenant_bound() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/workflow/instances/i-1":
            return httpx.Response(
                200,
                json={
                    "instanceId": "i-1",
                    "status": "WAITING_APPROVAL",
                    "reply": None,
                },
            )
        if request.url.path == "/workflow/tasks":
            return httpx.Response(
                200,
                json=[
                    {
                        "taskId": "t-1",
                        "priority": "HIGH",
                        "summary": "refund",
                        "assignee": "alice",
                    }
                ],
            )
        raise AssertionError(request.url)

    settings = Settings()
    tools = ReadonlyToolset(
        settings,
        PlatformClient(settings, httpx.MockTransport(handler)),
    )
    token = bind_run_context(context())
    try:
        instance = await tools.workflow_status("i-1")
        tasks = await tools.workflow_tasks()
    finally:
        reset_run_context(token)

    assert "仍在等待人工审批" in text(instance)
    assert "taskId=t-1 priority=HIGH summary=refund assignee=alice" in text(tasks)
    assert all(request.method == "GET" for request in seen)
    assert all(request.headers["X-Internal-Token"] == "token" for request in seen)


async def test_workflow_tasks_translates_approve_scope_failure() -> None:
    settings = Settings()
    tools = ReadonlyToolset(
        settings,
        PlatformClient(
            settings,
            httpx.MockTransport(lambda request: httpx.Response(403)),
        ),
    )
    token = bind_run_context(context())
    try:
        result = await tools.workflow_tasks()
    finally:
        reset_run_context(token)

    assert result.state == ToolResultState.ERROR
    assert "approve scope" in text(result)
