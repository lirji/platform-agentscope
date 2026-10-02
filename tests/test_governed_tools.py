import json

import httpx
from agentscope.message import TextBlock, ToolResultState
from pydantic import SecretStr

from agentscope_platform.core.config import Settings
from agentscope_platform.core.context import bind_run_context, reset_run_context
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.domain.tool import (
    ConfirmationRequirement,
    IdempotencyStrategy,
    RetryPolicy,
    SideEffectLevel,
)
from agentscope_platform.infrastructure.agentscope.governed_tools import GovernedToolset
from agentscope_platform.infrastructure.agentscope.tools import GovernedFunctionTool
from agentscope_platform.infrastructure.http.platform_client import PlatformClient
from tool_confirmation_support import CONFIRMATION_SECRET


def context(
    *,
    tenant: str = "acme",
    user: str = "alice",
    idempotency_key: str | None = "refund-request-42",
) -> RunContext:
    return RunContext(
        identity=TenantIdentity(tenant, user, frozenset({"agent"})),
        internal_token=f"token-{tenant}",
        trace_id=f"trace-{tenant}",
        idempotency_key=idempotency_key,
    )


def enabled_settings() -> Settings:
    return Settings(
        agent_refund_start_enabled=True,
        agent_confirmation_secret=SecretStr(CONFIRMATION_SECRET),
    )


def text(result: object) -> str:
    block = result.content[0]
    assert isinstance(block, TextBlock)
    return block.text


def test_refund_start_is_default_off() -> None:
    settings = Settings()
    tools = GovernedToolset(settings, PlatformClient(settings)).tools()

    assert tools == []


def test_refund_start_metadata_declares_governance_contract() -> None:
    settings = enabled_settings()
    tools = GovernedToolset(settings, PlatformClient(settings)).tools()

    assert {tool.name for tool in tools} == {"refund_start", "refund_receipt"}
    receipt = next(tool for tool in tools if tool.name == "refund_receipt")
    assert receipt.metadata.read_only is True
    assert receipt.metadata.requires_confirmation is ConfirmationRequirement.NEVER
    assert receipt.metadata.retry_policy is RetryPolicy.NONE
    tool = next(tool for tool in tools if tool.name == "refund_start")
    assert isinstance(tool, GovernedFunctionTool)
    assert tool.name == "refund_start"
    assert tool.metadata.read_only is False
    assert tool.metadata.side_effect is SideEffectLevel.MEDIUM
    assert tool.metadata.idempotency is IdempotencyStrategy.REQUEST_KEY
    assert tool.metadata.requires_confirmation is ConfirmationRequirement.ALWAYS
    assert tool.metadata.required_scopes == ("agent",)
    assert tool.metadata.retry_policy is RetryPolicy.NONE
    assert set(tool.input_schema["properties"]) == {"message"}


async def test_refund_start_forwards_trusted_context_and_formats_waiting_approval() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "instanceId": "wf-1",
                "status": "WAITING_APPROVAL",
                "reply": None,
                "taskId": "task-1",
                "priority": "HIGH",
                "deduplicated": False,
            },
        )

    settings = enabled_settings()
    toolset = GovernedToolset(
        settings,
        PlatformClient(settings, httpx.MockTransport(handler)),
    )
    run_context = context()
    token = bind_run_context(run_context)
    try:
        result = await toolset.refund_start(" 订单 101 申请退款 ")
    finally:
        reset_run_context(token)

    assert result.state == ToolResultState.RUNNING
    assert text(result) == (
        "instanceId: wf-1\n"
        "status: WAITING_APPROVAL\n"
        "priority: HIGH\n"
        "taskId: task-1\n"
        "注意：高风险，已转人工审批，尚未批准；审批须由具备审批权限的人在流程外完成。"
    )
    assert len(seen) == 1
    assert seen[0].url.path == "/workflow/refund/start"
    assert seen[0].headers["X-Internal-Token"] == "token-acme"
    assert seen[0].headers["X-Trace-Id"] == "trace-acme"
    assert json.loads(seen[0].content) == {
        "message": "订单 101 申请退款",
        "chatId": "agent:alice",
        "dedupeId": "refund-request-42",
    }


async def test_refund_start_preserves_dedupe_and_completed_reply() -> None:
    bodies: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "instanceId": "wf-existing",
                "status": "COMPLETED",
                "reply": "退款已受理",
                "taskId": None,
                "priority": "LOW",
                "deduplicated": True,
            },
        )

    settings = enabled_settings()
    toolset = GovernedToolset(
        settings,
        PlatformClient(settings, httpx.MockTransport(handler)),
    )
    token = bind_run_context(context())
    try:
        first = await toolset.refund_start("退款")
        second = await toolset.refund_start("退款")
    finally:
        reset_run_context(token)

    assert bodies[0]["dedupeId"] == bodies[1]["dedupeId"] == "refund-request-42"
    assert text(first).endswith("（该诉求此前已发起过，返回的是已存在的流程，未重复发起。）")
    assert "reply: 退款已受理" in text(second)


async def test_refund_start_provider_failure_is_sanitized_and_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, text="database password=secret")

    settings = enabled_settings()
    toolset = GovernedToolset(
        settings,
        PlatformClient(settings, httpx.MockTransport(handler)),
    )
    token = bind_run_context(context())
    try:
        result = await toolset.refund_start("退款")
    finally:
        reset_run_context(token)

    assert calls == 2
    assert result.state == ToolResultState.ERROR
    assert "退款结果未确认" in text(result)
    assert "password" not in text(result)


async def test_refund_start_rejects_blank_or_oversized_message_without_http_call() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    settings = enabled_settings()
    toolset = GovernedToolset(
        settings,
        PlatformClient(settings, httpx.MockTransport(handler)),
    )
    token = bind_run_context(context())
    try:
        blank = await toolset.refund_start("   ")
        oversized = await toolset.refund_start("x" * 20_001)
    finally:
        reset_run_context(token)

    assert calls == 0
    assert "诉求为空" in text(blank)
    assert oversized.state == ToolResultState.ERROR
    assert "上限 20000" in text(oversized)


async def test_refund_start_uses_tenant_bound_tokens_not_model_identity_fields() -> None:
    seen: list[tuple[str, str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            (
                request.headers["X-Internal-Token"],
                request.headers["X-Trace-Id"],
                json.loads(request.content),
            )
        )
        return httpx.Response(
            200,
            json={"instanceId": "wf", "status": "COMPLETED", "deduplicated": False},
        )

    settings = enabled_settings()
    toolset = GovernedToolset(
        settings,
        PlatformClient(settings, httpx.MockTransport(handler)),
    )
    for run_context in (context(tenant="acme"), context(tenant="globex")):
        token = bind_run_context(run_context)
        try:
            await toolset.refund_start("退款")
        finally:
            reset_run_context(token)

    assert [item[0] for item in seen] == ["token-acme", "token-globex"]
    assert [item[1] for item in seen] == ["trace-acme", "trace-globex"]
    assert all("tenantId" not in body and "userId" not in body for _, _, body in seen)


async def test_refund_lost_response_reads_original_receipt_without_write_retry() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/start"):
            raise httpx.ReadTimeout("response lost after commit", request=request)
        return httpx.Response(
            200,
            json={"instanceId": "committed-42", "status": "WAITING_APPROVAL", "deduplicated": True},
        )

    settings = enabled_settings()
    toolset = GovernedToolset(settings, PlatformClient(settings, httpx.MockTransport(handler)))
    token = bind_run_context(context())
    try:
        result = await toolset.refund_start("退款")
    finally:
        reset_run_context(token)
    assert [r.url.path for r in requests] == ["/workflow/refund/start", "/workflow/refund/receipt"]
    assert json.loads(requests[0].content) == json.loads(requests[1].content)
    assert "instanceId: committed-42" in text(result)
    assert "尚未批准" in text(result)
    assert result.state != ToolResultState.ERROR


async def test_missing_receipt_does_not_prove_failure_and_read_tool_never_starts() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(404)

    settings = enabled_settings()
    toolset = GovernedToolset(settings, PlatformClient(settings, httpx.MockTransport(handler)))
    token = bind_run_context(context())
    try:
        result = await toolset.refund_receipt("退款")
    finally:
        reset_run_context(token)
    assert paths == ["/workflow/refund/receipt"]
    assert "不代表请求未受理" in text(result)
    assert result.state == ToolResultState.ERROR
