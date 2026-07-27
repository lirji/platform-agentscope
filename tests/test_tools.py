from agentscope.agent import Agent
from agentscope.permission import PermissionBehavior
from pydantic import SecretStr

from agentscope_platform.core.config import Settings
from agentscope_platform.infrastructure.agentscope.runner import AgentScopeRunner
from agentscope_platform.infrastructure.agentscope.tools import ReadOnlyFunctionTool
from agentscope_platform.infrastructure.http.platform_client import PlatformClient


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


def test_runner_builds_agent_scope_2_agent() -> None:
    settings = Settings(
        gateway_api_key=SecretStr("test-gateway-key"),
        internal_auth_required=False,
    )
    runner = AgentScopeRunner(settings, PlatformClient(settings))

    agent = runner._build_agent()

    assert isinstance(agent, Agent)
    assert agent.name == "platform-agent"
