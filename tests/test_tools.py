from agentscope.agent import Agent
from agentscope.permission import PermissionBehavior
from pydantic import SecretStr
from pytest import MonkeyPatch

from agentscope_platform.core.config import Settings
from agentscope_platform.core.context import bind_run_context, reset_run_context
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.domain.tool import ToolMetadata, ToolPolicyReason
from agentscope_platform.infrastructure.agentscope.runner import AgentScopeRunner
from agentscope_platform.infrastructure.agentscope.tools import (
    GovernedFunctionTool,
    ReadOnlyFunctionTool,
)
from agentscope_platform.infrastructure.http.platform_client import PlatformClient
from tool_confirmation_support import (
    CONFIRMATION_SECRET,
    confirmation_grant,
)


async def _tool() -> str:
    return "ok"


async def test_read_only_tool_is_allowed() -> None:
    tool = ReadOnlyFunctionTool(_tool, is_read_only=True)

    decision = await tool.check_permissions()

    assert decision.behavior == PermissionBehavior.ALLOW


async def test_non_read_only_tool_is_denied() -> None:
    tool = ReadOnlyFunctionTool(_tool, is_read_only=False)

    decision = await tool.check_permissions()

    assert decision.behavior == PermissionBehavior.DENY


async def test_governed_tool_translates_policy_to_agentscope_permission() -> None:
    metadata = ToolMetadata(
        name="refund_start",
        readOnly=False,
        sideEffect="medium",
        idempotency="request_key",
        requiresConfirmation="always",
        requiredScopes=["agent"],
        timeoutSeconds=10,
        retryPolicy="none",
    )
    tool = GovernedFunctionTool(_tool, metadata=metadata)

    denied_token = bind_run_context(
        RunContext(
            identity=TenantIdentity("acme", "alice", frozenset({"agent"})),
            internal_token="token",
            trace_id="trace",
            idempotency_key="refund-42",
        )
    )
    try:
        denied = await tool.check_permissions({})
    finally:
        reset_run_context(denied_token)

    allowed_token = bind_run_context(
        RunContext(
            identity=TenantIdentity("acme", "alice", frozenset({"agent"})),
            internal_token="token",
            trace_id="trace",
            confirmation_grants=(
                confirmation_grant(
                    "refund_start",
                    {},
                    idempotency_key="refund-42",
                ),
            ),
            idempotency_key="refund-42",
        )
    )
    try:
        allowed = await tool.check_permissions({})
    finally:
        reset_run_context(allowed_token)

    assert denied.behavior == PermissionBehavior.DENY
    assert denied.decision_reason == ToolPolicyReason.CONFIRMATION_REQUIRED.value
    assert allowed.behavior == PermissionBehavior.ALLOW
    assert tool.metadata == metadata


async def test_governed_tool_records_low_cardinality_denial(
    monkeypatch: MonkeyPatch,
) -> None:
    recorded: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "agentscope_platform.infrastructure.agentscope.tools.record_tool_policy_denied",
        lambda tool, reason: recorded.append((tool, reason)),
    )
    metadata = ToolMetadata(
        name="refund_start",
        readOnly=False,
        sideEffect="medium",
        idempotency="request_key",
        requiresConfirmation="always",
        requiredScopes=["agent"],
        timeoutSeconds=10,
        retryPolicy="none",
    )
    tool = GovernedFunctionTool(_tool, metadata=metadata)
    token = bind_run_context(
        RunContext(
            identity=TenantIdentity("acme", "alice", frozenset({"agent"})),
            internal_token="token",
            trace_id="trace",
            idempotency_key="refund-42",
        )
    )
    try:
        await tool.check_permissions({})
    finally:
        reset_run_context(token)

    assert recorded == [("refund_start", "confirmation_required")]


def test_runner_builds_agent_scope_2_agent() -> None:
    settings = Settings(
        gateway_api_key=SecretStr("test-gateway-key"),
        internal_auth_required=False,
    )
    runner = AgentScopeRunner(settings, PlatformClient(settings))

    agent = runner._build_agent()

    assert isinstance(agent, Agent)
    assert agent.name == "platform-agent"


def test_every_registered_tool_has_complete_governed_metadata() -> None:
    settings = Settings(
        gateway_api_key=SecretStr("test-gateway-key"),
        internal_auth_required=False,
    )
    runner = AgentScopeRunner(settings, PlatformClient(settings))

    tools = runner._build_tools()

    assert {tool.name for tool in tools} == {
        "current_time",
        "rag_search",
        "order_query",
        "schema_explore",
        "analytics_sql",
        "workflow_status",
        "workflow_tasks",
    }
    assert all(isinstance(tool, GovernedFunctionTool) for tool in tools)
    assert all(tool.metadata.read_only for tool in tools if isinstance(tool, GovernedFunctionTool))


def test_refund_start_registration_is_feature_flagged() -> None:
    disabled_settings = Settings(
        gateway_api_key=SecretStr("test-gateway-key"),
        internal_auth_required=False,
    )
    enabled_settings = Settings(
        gateway_api_key=SecretStr("test-gateway-key"),
        internal_auth_required=False,
        agent_refund_start_enabled=True,
        agent_confirmation_secret=SecretStr(CONFIRMATION_SECRET),
    )

    disabled = AgentScopeRunner(
        disabled_settings,
        PlatformClient(disabled_settings),
    )._build_tools()
    enabled = AgentScopeRunner(
        enabled_settings,
        PlatformClient(enabled_settings),
    )._build_tools()

    assert "refund_start" not in {tool.name for tool in disabled}
    assert "refund_start" in {tool.name for tool in enabled}
