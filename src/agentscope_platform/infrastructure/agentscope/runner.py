from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from agentscope.agent import Agent, ReActConfig
from agentscope.credential import OpenAICredential
from agentscope.message import TextBlock, ToolResultState, UserMsg
from agentscope.model import OpenAIChatModel
from agentscope.tool import ToolChunk, Toolkit
from pydantic import SecretStr

from agentscope_platform.application.ports import AgentRunner
from agentscope_platform.core.config import Settings
from agentscope_platform.core.context import (
    bind_run_context,
    current_run_context,
    reset_run_context,
)
from agentscope_platform.domain.agent import AgentExecution, RunContext
from agentscope_platform.infrastructure.agentscope.tools import ReadOnlyFunctionTool
from agentscope_platform.infrastructure.http.platform_client import PlatformClient

SYSTEM_PROMPT = """
你是企业级 Agent 编排服务。必须遵守以下规则:
1. 只使用当前租户被授权的工具与数据, 绝不猜测业务事实。
2. 查询知识、订单、分析或流程状态时优先调用相应工具。
3. 工具失败时如实说明; 不要伪造成功结果。
4. 未经明确授权和幂等保护, 不执行有副作用操作。
5. 给出简洁、可核验的最终答案。
""".strip()


class AgentNotConfiguredError(RuntimeError):
    pass


class AgentScopeRunner(AgentRunner):
    def __init__(self, settings: Settings, platform_client: PlatformClient) -> None:
        self._settings = settings
        self._platform_client = platform_client

    async def run(self, goal: str, context: RunContext) -> AgentExecution:
        if not self._settings.agent_enabled:
            raise AgentNotConfiguredError("GATEWAY_API_KEY is not configured")

        context_token = bind_run_context(context)
        try:
            agent = self._build_agent()
            reply = await agent.reply(UserMsg(name="user", content=goal))
            return AgentExecution(final_answer=reply.get_text_content() or "")
        finally:
            reset_run_context(context_token)

    def _build_agent(self) -> Agent:
        credential = OpenAICredential(
            api_key=SecretStr(self._settings.gateway_api_key.get_secret_value()),
            base_url=self._settings.gateway_base_url,
        )
        model = OpenAIChatModel(
            credential=credential,
            model=self._settings.gateway_model,
            parameters=OpenAIChatModel.Parameters(
                temperature=self._settings.gateway_temperature,
                parallel_tool_calls=True,
            ),
            stream=False,
        )
        toolkit = Toolkit(
            tools=[
                ReadOnlyFunctionTool(
                    self._current_time,
                    name="current_time",
                    description="Return the current time in an IANA timezone.",
                    is_read_only=True,
                ),
                ReadOnlyFunctionTool(
                    self._rag_search,
                    name="rag_search",
                    description="Search the current tenant's retained Java knowledge service.",
                    is_read_only=True,
                ),
            ],
        )
        return Agent(
            name="platform-agent",
            system_prompt=SYSTEM_PROMPT,
            model=model,
            toolkit=toolkit,
            react_config=ReActConfig(max_iters=self._settings.agent_max_steps),
        )

    async def _current_time(self, timezone: str = "UTC") -> ToolChunk:
        """Return the current ISO-8601 time for an IANA timezone."""
        try:
            zone = ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            return ToolChunk(
                content=[TextBlock(text=f"unknown timezone: {timezone}")],
                state=ToolResultState.ERROR,
            )
        value = datetime.now(zone if timezone != "UTC" else UTC).isoformat()
        return ToolChunk(content=[TextBlock(text=value)])

    async def _rag_search(self, query: str, top_k: int = 5) -> ToolChunk:
        """Search knowledge visible to the current tenant."""
        top_k = min(max(top_k, 1), 20)
        try:
            payload = await self._platform_client.query_knowledge(
                query=query,
                top_k=top_k,
                context=current_run_context(),
            )
        except (httpx.HTTPError, ValueError) as exc:
            return ToolChunk(
                content=[TextBlock(text=f"knowledge search failed: {exc}")],
                state=ToolResultState.ERROR,
            )
        return ToolChunk(
            content=[TextBlock(text=str(payload))],
            metadata={"source": "knowledge-service"},
        )
