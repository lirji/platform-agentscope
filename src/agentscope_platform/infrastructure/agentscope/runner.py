import asyncio
import logging
from datetime import UTC, datetime
from time import monotonic
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agentscope.agent import Agent, ReActConfig
from agentscope.event import ModelCallEndEvent, ToolCallEndEvent
from agentscope.message import Msg, TextBlock, ToolResultState, UserMsg
from agentscope.tool import ToolChunk, Toolkit

from agentscope_platform.application.observer import (
    NoopRunObserver,
    RunObservation,
    RunObserver,
)
from agentscope_platform.application.ports import AgentRunner
from agentscope_platform.core.config import Settings
from agentscope_platform.core.context import (
    bind_run_context,
    reset_run_context,
)
from agentscope_platform.domain.agent import AgentExecution, RunContext
from agentscope_platform.infrastructure.agentscope.model_factory import (
    build_openai_chat_model,
)
from agentscope_platform.infrastructure.agentscope.readonly_tools import ReadonlyToolset
from agentscope_platform.infrastructure.agentscope.tools import ReadOnlyFunctionTool
from agentscope_platform.infrastructure.agentscope.trajectory import TrajectoryCollector
from agentscope_platform.infrastructure.http.platform_client import PlatformClient

log = logging.getLogger(__name__)

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
    def __init__(
        self,
        settings: Settings,
        platform_client: PlatformClient,
        observer: RunObserver | None = None,
    ) -> None:
        self._settings = settings
        self._platform_client = platform_client
        self._observer = observer or NoopRunObserver()

    async def run(self, goal: str, context: RunContext) -> AgentExecution:
        if not self._settings.agent_enabled:
            raise AgentNotConfiguredError("GATEWAY_API_KEY is not configured")

        started = monotonic()
        collector = TrajectoryCollector(loop_window=self._settings.agent_loop_window)
        execution = AgentExecution(
            final_answer="Agent execution failed.",
            stop_reason="ERROR",
        )
        context_token = bind_run_context(context)
        try:
            agent = self._build_agent()
            if self._settings.agent_timeout_seconds > 0:
                async with asyncio.timeout(self._settings.agent_timeout_seconds):
                    execution = await self._consume_reply(agent, goal, collector)
            else:
                execution = await self._consume_reply(agent, goal, collector)
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
            reset_run_context(context_token)
            self._record_observation(
                context=context,
                collector=collector,
                execution=execution,
                started=started,
            )
        return execution

    async def _consume_reply(
        self,
        agent: Agent,
        goal: str,
        collector: TrajectoryCollector,
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

    def _build_agent(self) -> Agent:
        model = build_openai_chat_model(
            self._settings,
            temperature=self._settings.gateway_temperature,
            stream=False,
            max_tokens=None,
            max_retries=3,
            parallel_tool_calls=True,
        )
        retained_tools = ReadonlyToolset(self._settings, self._platform_client).tools()
        toolkit = Toolkit(
            tools=[
                ReadOnlyFunctionTool(
                    self._current_time,
                    name="current_time",
                    description="Return the current time in an IANA timezone.",
                    is_read_only=True,
                ),
                *retained_tools,
            ]
        )
        return Agent(
            name="platform-agent",
            system_prompt=SYSTEM_PROMPT,
            model=model,
            toolkit=toolkit,
            # The legacy budget counts one decision/action as a step. AgentScope
            # counts reasoning and acting as separate iterations. ``2n - 1``
            # preserves: at most n actions, or n-1 actions plus a final answer.
            react_config=ReActConfig(
                max_iters=_agentscope_max_iters(self._settings.agent_max_steps)
            ),
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


def _agentscope_max_iters(legacy_action_steps: int) -> int:
    return legacy_action_steps * 2 - 1
