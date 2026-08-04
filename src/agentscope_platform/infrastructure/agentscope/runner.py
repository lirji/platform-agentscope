import asyncio
import logging
from dataclasses import replace
from datetime import UTC, datetime
from time import monotonic
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agentscope.agent import Agent, ReActConfig
from agentscope.event import ModelCallEndEvent, ToolCallEndEvent, ToolResultEndEvent
from agentscope.message import Msg, TextBlock, ToolResultState, UserMsg
from agentscope.state import AgentState
from agentscope.tool import ToolBase, ToolChunk, Toolkit

from agentscope_platform.application.observer import (
    NoopRunObserver,
    RunObservation,
    RunObserver,
)
from agentscope_platform.application.ports import (
    AgentRunner,
    McpGateway,
    RemoteSandboxGateway,
    SessionProgressCallback,
    ToolConfirmationConsumer,
)
from agentscope_platform.core.config import Settings
from agentscope_platform.core.context import (
    bind_run_context,
    reset_run_context,
)
from agentscope_platform.core.deadline import bind_deadline, reset_deadline
from agentscope_platform.domain.agent import AgentExecution, RunContext
from agentscope_platform.domain.session import AgentSessionCheckpoint
from agentscope_platform.domain.tool import ToolMetadata
from agentscope_platform.domain.versioning import build_execution_versions
from agentscope_platform.infrastructure.agentscope.analytics_planner import (
    AgentScopeAnalyticsSqlPlanner,
)
from agentscope_platform.infrastructure.agentscope.governed_tools import GovernedToolset
from agentscope_platform.infrastructure.agentscope.model_factory import (
    build_openai_chat_model,
)
from agentscope_platform.infrastructure.agentscope.readonly_tools import ReadonlyToolset
from agentscope_platform.infrastructure.agentscope.tools import GovernedFunctionTool
from agentscope_platform.infrastructure.agentscope.trajectory import TrajectoryCollector
from agentscope_platform.infrastructure.http.platform_client import PlatformClient
from agentscope_platform.infrastructure.sandbox.client import HttpRemoteSandboxGateway

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """
你是企业级 Agent 编排服务。必须遵守以下规则:
1. 只使用当前租户被授权的工具与数据, 绝不猜测业务事实。
2. 查询知识、订单、分析或流程状态时优先调用相应工具。
3. 工具失败时如实说明; 不要伪造成功结果。
4. 未经明确授权和幂等保护, 不执行有副作用操作。
5. 给出简洁、可核验的最终答案。
""".strip()
TOOL_IMPLEMENTATION_REVISION = "agentscope-platform-tools.v1"


class AgentNotConfiguredError(RuntimeError):
    pass


class AgentScopeRunner(AgentRunner):
    def __init__(
        self,
        settings: Settings,
        platform_client: PlatformClient,
        observer: RunObserver | None = None,
        mcp_gateway: McpGateway | None = None,
        sandbox_gateway: RemoteSandboxGateway | None = None,
        confirmation_consumer: ToolConfirmationConsumer | None = None,
    ) -> None:
        self._settings = settings
        self._platform_client = platform_client
        self._observer = observer or NoopRunObserver()
        self._mcp_gateway = mcp_gateway
        self._sandbox_gateway = sandbox_gateway or HttpRemoteSandboxGateway(settings)
        self._confirmation_consumer = confirmation_consumer
        self._side_effect_tool_names = frozenset(
            GovernedToolset(
                settings,
                platform_client,
                mcp_gateway=mcp_gateway,
                sandbox_gateway=self._sandbox_gateway,
                confirmation_consumer=confirmation_consumer,
            ).confirmable_metadata()
        )
        versioned_tools = tuple(
            tool.metadata for tool in self._build_tools() if isinstance(tool, GovernedFunctionTool)
        )
        self.execution_versions = build_execution_versions(
            prompt=SYSTEM_PROMPT,
            model=settings.gateway_model,
            model_parameters={
                "gatewayEndpoint": settings.gateway_base_url,
                "temperature": settings.gateway_temperature,
                "maxOutputTokens": min(
                    settings.agent_model_max_output_tokens,
                    settings.agent_max_tokens,
                ),
                "parallelToolCalls": True,
            },
            tools=versioned_tools,
            tool_implementation_revision=TOOL_IMPLEMENTATION_REVISION,
        )

    async def run(self, goal: str, context: RunContext) -> AgentExecution:
        return await self._run(goal, context)

    async def run_from_checkpoint(
        self,
        goal: str,
        checkpoint: AgentSessionCheckpoint,
        context: RunContext,
        progress: SessionProgressCallback,
    ) -> AgentExecution:
        return await self._run(
            goal,
            context,
            checkpoint=checkpoint,
            progress=progress,
        )

    async def _run(
        self,
        goal: str,
        context: RunContext,
        *,
        checkpoint: AgentSessionCheckpoint | None = None,
        progress: SessionProgressCallback | None = None,
    ) -> AgentExecution:
        if not self._settings.agent_enabled:
            raise AgentNotConfiguredError("GATEWAY_API_KEY is not configured")

        started = monotonic()
        try:
            self._observer.started(self._settings.gateway_model)
        except Exception as exc:
            log.warning("agent run observer start failed: %s", type(exc).__name__)
        collector = TrajectoryCollector(
            loop_window=self._settings.agent_loop_window,
            initial_steps=tuple(checkpoint.steps) if checkpoint is not None else (),
            versions=self.execution_versions,
        )
        execution = AgentExecution(
            final_answer="Agent execution failed.",
            stop_reason="ERROR",
        )
        context_token = bind_run_context(context)
        deadline_token = bind_deadline(self._settings.agent_timeout_seconds)
        try:
            agent = (
                self._build_resumable_agent(checkpoint)
                if checkpoint is not None
                else self._build_agent()
            )
            async with asyncio.timeout(self._settings.agent_timeout_seconds):
                execution = await self._consume_reply(
                    agent,
                    goal,
                    collector,
                    progress=progress,
                )
        except TimeoutError:
            execution = AgentExecution(
                final_answer=collector.best_effort_text or "Agent execution timed out.",
                stop_reason="TIMEOUT",
                steps=collector.steps(),
            )
        except asyncio.CancelledError:
            execution = AgentExecution(
                final_answer=collector.best_effort_text or "Agent execution was cancelled.",
                stop_reason="CANCELLED",
                steps=collector.steps(),
            )
        except Exception as exc:
            log.warning("agent execution failed: %s", type(exc).__name__)
            execution = AgentExecution(
                final_answer=collector.best_effort_text or "Agent execution failed.",
                stop_reason="ERROR",
                steps=collector.steps(),
            )
        finally:
            reset_deadline(deadline_token)
            if self._settings.agent_browser_enabled:
                try:
                    await self._sandbox_gateway.close_browser(context)
                except Exception as exc:
                    log.warning(
                        "remote browser session cleanup failed: %s",
                        type(exc).__name__,
                    )
            reset_run_context(context_token)
            self._record_observation(
                context=context,
                collector=collector,
                execution=execution,
                started=started,
            )
        return replace(
            execution,
            trajectory=collector.trajectory(
                trace_id=context.trace_id,
                stop_reason=execution.stop_reason,
            ),
        )

    async def _consume_reply(
        self,
        agent: Agent,
        goal: str,
        collector: TrajectoryCollector,
        *,
        progress: SessionProgressCallback | None = None,
    ) -> AgentExecution:
        final_message: Msg | None = None
        stop_override: str | None = None
        stream = agent.reply_stream(
            UserMsg(name="user", content=goal),
            yield_final_msg=True,
        )
        async for item in stream:
            if isinstance(item, Msg):
                final_message = item
                continue

            collector.consume(item)
            if isinstance(item, ToolResultEndEvent) and progress is not None:
                steps = collector.steps()
                await progress(
                    steps,
                    any(step.action in self._side_effect_tool_names for step in steps),
                )
            if (
                isinstance(item, ModelCallEndEvent)
                and self._settings.agent_max_tokens > 0
                and collector.total_tokens >= self._settings.agent_max_tokens
            ):
                stop_override = "BUDGET"
                await stream.aclose()
                break
            if isinstance(item, ToolCallEndEvent) and collector.repeated_action(
                self._settings.agent_max_repeats
            ):
                collector.mark_loop()
                stop_override = "LOOP"
                await stream.aclose()
                break

        stop_reason = stop_override or collector.stop_reason()
        final_answer = (
            final_message.get_text_content()
            if final_message is not None
            else collector.best_effort_text
        )
        if not final_answer and stop_reason == "DONE":
            stop_reason = "ERROR"
            final_answer = "Agent did not produce a final message."
        elif not final_answer:
            final_answer = f"Agent stopped: {stop_reason}"

        return AgentExecution(
            final_answer=final_answer,
            stop_reason=stop_reason,
            steps=collector.steps(),
        )

    def _record_observation(
        self,
        context: RunContext,
        collector: TrajectoryCollector,
        execution: AgentExecution,
        started: float,
    ) -> None:
        observation = RunObservation(
            trace_id=context.trace_id,
            tenant_id=context.identity.tenant_id,
            user_id=context.identity.user_id,
            model=self._settings.gateway_model,
            stop_reason=execution.stop_reason,
            duration_ms=max(0, int((monotonic() - started) * 1000)),
            input_tokens=collector.input_tokens,
            output_tokens=collector.output_tokens,
            tools=collector.tool_names,
        )
        try:
            self._observer.record(observation)
        except Exception as exc:
            log.warning("agent run observer failed: %s", type(exc).__name__)

    def _build_resumable_agent(self, checkpoint: AgentSessionCheckpoint) -> Agent:
        state = AgentState(
            session_id=checkpoint.session_id,
            summary=self._checkpoint_summary(checkpoint),
        )
        return self._build_agent(state=state)

    @staticmethod
    def _checkpoint_summary(checkpoint: AgentSessionCheckpoint) -> str:
        if not checkpoint.steps:
            return ""
        lines = [
            "Durable checkpoint: the following tool steps already completed. "
            "Use their observations and do not repeat side effects."
        ]
        for step in checkpoint.steps:
            lines.append(f"{step.n}. {step.action}({step.action_input}) -> {step.observation}")
        return "\n".join(lines)

    def _build_agent(self, state: AgentState | None = None) -> Agent:
        model = build_openai_chat_model(
            self._settings,
            temperature=self._settings.gateway_temperature,
            stream=False,
            max_tokens=min(
                self._settings.agent_model_max_output_tokens,
                self._settings.agent_max_tokens,
            ),
            max_retries=self._settings.agent_model_max_retries,
            parallel_tool_calls=True,
        )
        analytics_planner = (
            AgentScopeAnalyticsSqlPlanner(self._settings)
            if self._settings.analytics_external_planner_shadow_enabled
            else None
        )
        retained_tools = ReadonlyToolset(
            self._settings,
            self._platform_client,
            analytics_planner=analytics_planner,
        ).tools()
        toolkit = Toolkit(tools=self._build_tools(retained_tools))
        return Agent(
            name="platform-agent",
            system_prompt=SYSTEM_PROMPT,
            model=model,
            toolkit=toolkit,
            state=state,
            # The legacy budget counts one decision/action as a step. AgentScope
            # counts reasoning and acting as separate iterations. ``2n - 1``
            # preserves: at most n actions, or n-1 actions plus a final answer.
            react_config=ReActConfig(
                max_iters=_agentscope_max_iters(self._settings.agent_max_steps)
            ),
        )

    def _build_tools(self, retained_tools: list[ToolBase] | None = None) -> list[ToolBase]:
        tools = retained_tools
        if tools is None:
            tools = ReadonlyToolset(self._settings, self._platform_client).tools()
        return [
            GovernedFunctionTool(
                self._current_time,
                metadata=ToolMetadata.for_read_only(
                    name="current_time",
                    required_scopes=(),
                    timeout_seconds=1,
                ),
                description="Return the current time in an IANA timezone.",
            ),
            *tools,
            *GovernedToolset(
                self._settings,
                self._platform_client,
                mcp_gateway=self._mcp_gateway,
                sandbox_gateway=self._sandbox_gateway,
                confirmation_consumer=self._confirmation_consumer,
            ).tools(),
        ]

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


def _agentscope_max_iters(legacy_action_steps: int) -> int:
    return legacy_action_steps * 2 - 1
