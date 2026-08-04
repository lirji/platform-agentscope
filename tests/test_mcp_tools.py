import json
from typing import Any

import pytest
from agentscope.message import TextBlock, ToolResultState
from pydantic import SecretStr, ValidationError

from agentscope_platform.application.ports import McpGateway
from agentscope_platform.core.config import Settings
from agentscope_platform.core.context import bind_run_context, reset_run_context
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.domain.mcp import McpGatewayError, McpToolBinding
from agentscope_platform.infrastructure.agentscope.governed_tools import GovernedToolset
from agentscope_platform.infrastructure.agentscope.tools import GovernedFunctionTool
from agentscope_platform.infrastructure.http.platform_client import PlatformClient
from tool_confirmation_support import (
    CONFIRMATION_SECRET,
    DOWNSTREAM_SECRET,
    PassingConfirmationConsumer,
    confirmation_grant,
)


def binding_json(*, read_only: bool = True) -> str:
    metadata = {
        "name": "mcp_weather_get_weather",
        "readOnly": read_only,
        "sideEffect": "none" if read_only else "medium",
        "idempotency": "none" if read_only else "request_key",
        "requiresConfirmation": "never" if read_only else "always",
        "requiredScopes": ["agent"],
        "timeoutSeconds": 4,
        "retryPolicy": "none",
    }
    return json.dumps(
        [
            {
                "serverId": "weather",
                "remoteName": "get_weather",
                "description": "Read current weather from the approved MCP provider.",
                "metadata": metadata,
            }
        ]
    )


def settings(*, enabled: bool = True, read_only: bool = True) -> Settings:
    return Settings(
        _env_file=None,
        agent_mcp_enabled=enabled,
        agent_mcp_url="https://mcp.example.test/mcp" if enabled else "",
        agent_mcp_tools_json=binding_json(read_only=read_only) if enabled else "[]",
        agent_confirmation_secret=SecretStr(CONFIRMATION_SECRET),
        agent_downstream_jwt_secret=SecretStr(DOWNSTREAM_SECRET),
    )


def context(
    *,
    tenant: str = "acme",
    confirmed: bool = False,
    idempotency_key: str | None = None,
) -> RunContext:
    grants = (
        (
            confirmation_grant(
                "mcp_weather_get_weather",
                {"arguments": {}},
                tenant=tenant,
                idempotency_key=idempotency_key,
            ),
        )
        if confirmed and idempotency_key
        else ()
    )
    return RunContext(
        identity=TenantIdentity(tenant, "alice", frozenset({"agent"})),
        internal_token=f"token-{tenant}",
        trace_id=f"trace-{tenant}",
        confirmation_grants=grants,
        idempotency_key=idempotency_key,
    )


def text(result: object) -> str:
    block = result.content[0]
    assert isinstance(block, TextBlock)
    return block.text


class FakeMcpGateway(McpGateway):
    def __init__(self, *, result: str = "sunny", error: str | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, str, dict[str, Any], RunContext, float]] = []

    async def call(
        self,
        *,
        server_url: str,
        tool_name: str,
        arguments: dict[str, Any],
        context: RunContext,
        timeout_seconds: float,
    ) -> str:
        self.calls.append((server_url, tool_name, arguments, context, timeout_seconds))
        if self.error:
            raise McpGatewayError(self.error)
        return self.result


def test_mcp_is_default_off_and_enabled_configuration_is_fail_closed() -> None:
    assert Settings(_env_file=None).agent_mcp_tools == ()
    with pytest.raises(ValidationError, match="AGENT_MCP_URL"):
        Settings(
            _env_file=None,
            agent_mcp_enabled=True,
            agent_mcp_tools_json=binding_json(),
        )
    with pytest.raises(ValidationError, match="AGENT_MCP_TOOLS_JSON"):
        Settings(
            _env_file=None,
            agent_mcp_enabled=True,
            agent_mcp_url="https://mcp.example.test/mcp",
        )


def test_mcp_binding_rejects_recursive_agent_tools() -> None:
    payload = json.loads(binding_json())[0]
    payload["remoteName"] = "platform.agent.run"

    with pytest.raises(ValidationError, match="recursive Agent tools"):
        McpToolBinding.model_validate(payload)


def test_only_explicitly_bound_mcp_tools_are_registered() -> None:
    configured = settings()
    gateway = FakeMcpGateway()
    tools = GovernedToolset(
        configured,
        PlatformClient(configured),
        mcp_gateway=gateway,
    ).tools()

    assert {tool.name for tool in tools} == {"mcp_weather_get_weather"}
    tool = tools[0]
    assert isinstance(tool, GovernedFunctionTool)
    assert tool.metadata == configured.agent_mcp_tools[0].metadata
    assert set(tool.input_schema["properties"]) == {"arguments"}
    assert "mcp_call" not in {item.name for item in tools}


async def test_read_only_mcp_tool_forwards_exact_allowlisted_call_and_trusted_context() -> None:
    configured = settings()
    gateway = FakeMcpGateway(result='{"temperature":23}')
    toolset = GovernedToolset(
        configured,
        PlatformClient(configured),
        mcp_gateway=gateway,
        confirmation_consumer=PassingConfirmationConsumer(),
    )
    run_context = context(tenant="globex")
    token = bind_run_context(run_context)
    try:
        result = await toolset.call_mcp(
            configured.agent_mcp_tools[0],
            {"city": "Taipei"},
        )
    finally:
        reset_run_context(token)

    assert result.state == ToolResultState.RUNNING
    assert text(result) == '{"temperature":23}'
    assert gateway.calls == [
        (
            "https://mcp.example.test/mcp",
            "get_weather",
            {"city": "Taipei"},
            run_context,
            4.0,
        )
    ]


@pytest.mark.parametrize(
    ("confirmed", "key", "reason"),
    [
        (False, "request-42", "explicit confirmation is required"),
        (True, None, "idempotency key is required"),
    ],
)
async def test_side_effect_mcp_tool_denies_before_provider(
    confirmed: bool,
    key: str | None,
    reason: str,
) -> None:
    configured = settings(read_only=False)
    gateway = FakeMcpGateway()
    toolset = GovernedToolset(
        configured,
        PlatformClient(configured),
        mcp_gateway=gateway,
    )
    token = bind_run_context(context(confirmed=confirmed, idempotency_key=key))
    try:
        result = await toolset.tools()[0].call(arguments={})
    finally:
        reset_run_context(token)

    assert result.state == ToolResultState.ERROR
    assert reason in text(result)
    assert gateway.calls == []


async def test_mcp_rejects_identity_override_and_oversized_arguments_locally() -> None:
    configured = settings()
    gateway = FakeMcpGateway()
    toolset = GovernedToolset(
        configured,
        PlatformClient(configured),
        mcp_gateway=gateway,
    )
    token = bind_run_context(context())
    try:
        identity = await toolset.call_mcp(
            configured.agent_mcp_tools[0],
            {"tenantId": "globex"},
        )
        oversized = await toolset.call_mcp(
            configured.agent_mcp_tools[0],
            {"value": "x" * 70_000},
        )
    finally:
        reset_run_context(token)

    assert "trusted request context" in text(identity)
    assert "arguments exceed" in text(oversized)
    assert gateway.calls == []


async def test_mcp_provider_failure_is_sanitized_and_not_retried() -> None:
    configured = settings()
    gateway = FakeMcpGateway(error="mcp provider unavailable")
    toolset = GovernedToolset(
        configured,
        PlatformClient(configured),
        mcp_gateway=gateway,
    )
    token = bind_run_context(context())
    try:
        result = await toolset.call_mcp(configured.agent_mcp_tools[0], {})
    finally:
        reset_run_context(token)

    assert result.state == ToolResultState.ERROR
    assert text(result) == "MCP tool call failed: mcp provider unavailable"
    assert len(gateway.calls) == 1
