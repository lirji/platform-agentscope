import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any, Protocol

from agentscope.message import Msg, SystemMsg, TextBlock, UserMsg
from agentscope.model import ChatResponse, FinishedReason, OpenAIChatModel
from pydantic import ValidationError

from agentscope_platform.application.ports import DagPlanner, DagPlanningError
from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import RunContext
from agentscope_platform.domain.dag import DagPlan, DagPlanKind
from agentscope_platform.infrastructure.agentscope.model_factory import (
    build_openai_chat_model,
)
from agentscope_platform.infrastructure.agentscope.runner import (
    AgentNotConfiguredError,
)

log = logging.getLogger(__name__)
MAX_PLAN_RESPONSE_CHARS = 65_536

GENERAL_PLANNER_PROMPT = """
You plan a multi-agent DAG for a user goal.

Rules:
- Return one JSON object with a "tasks" array and no other fields.
- Produce 1 to 6 sub-tasks. Do not over-decompose.
- For a focused single-aspect goal, produce exactly one task.
- Split multi-aspect goals by aspect, not by entity.
- Use ids t1, t2, t3, ...
- Match the user's language.
- Each task has exactly: id, description, dependsOn.
- Dependencies are optional and should be rare.
- Add dependsOn only when a task literally needs another task's output.
- Independent tasks must use an empty dependsOn array.
- The graph must be acyclic.

JSON shape:
{"tasks":[{"id":"t1","description":"self-contained instruction","dependsOn":[]}]}
""".strip()

ANALYST_PLANNER_PROMPT = """
你为一个数据分析多 Agent DAG 规划只读子任务。

可用工具:
- schema_explore: 列出可查表, 或查看指定表的字段、类型和枚举。
- analytics_sql: 用自然语言只读查询业务库, 服务端自动按当前租户过滤。

规则:
- 只返回一个包含 "tasks" 数组的 JSON 对象, 不返回其他字段。
- 产出 1 到 6 个子任务, id 使用 t1、t2、t3……
- 每个任务仅包含 id、description、dependsOn。
- 通常先用 schema_explore 确认相关表结构与枚举, 再让取数任务依赖探表结果。
- 描述必须明确使用哪个现有只读工具以及查询什么。
- 不得规划 code_exec、写操作或任何未列出的工具。
- 单一维度不要过度拆解; 多维度按维度拆分。
- 独立取数任务使用空 dependsOn 以便并行; 图必须无环。
- 使用用户的语言。

JSON 形状:
{"tasks":[{"id":"t1","description":"用 schema_explore 查看相关表结构","dependsOn":[]}]}
""".strip()


class _PlannerModel(Protocol):
    async def __call__(
        self,
        messages: list[Msg],
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]: ...


class AgentScopeDagPlanner(DagPlanner):
    def __init__(
        self,
        settings: Settings,
        model: _PlannerModel | None = None,
    ) -> None:
        self._settings = settings
        self._model = model or self._build_model()

    async def plan(
        self,
        goal: str,
        context: RunContext,
        kind: DagPlanKind,
    ) -> DagPlan:
        if not self._settings.agent_enabled:
            raise AgentNotConfiguredError("GATEWAY_API_KEY is not configured")
        prompt = ANALYST_PLANNER_PROMPT if kind is DagPlanKind.ANALYST else GENERAL_PLANNER_PROMPT
        try:
            response = await self._model(
                [
                    SystemMsg(name="system", content=prompt),
                    UserMsg(name="user", content=f"User goal:\n{goal}"),
                ],
                response_format={"type": "json_object"},
            )
            if not isinstance(response, ChatResponse):
                raise DagPlanningError("streaming Planner response is unsupported")
            if response.get("finished_reason") == FinishedReason.INTERRUPTED:
                raise asyncio.CancelledError
            text = "".join(
                block.text for block in response.content if isinstance(block, TextBlock)
            ).strip()
            if not text or len(text) > MAX_PLAN_RESPONSE_CHARS:
                raise DagPlanningError("Planner response size is invalid")
            return DagPlan.model_validate_json(text)
        except asyncio.CancelledError:
            raise
        except DagPlanningError:
            raise
        except (ValidationError, ValueError, TypeError) as exc:
            raise DagPlanningError("Planner response contract is invalid") from exc
        except Exception as exc:
            log.warning(
                "DAG Planner model call failed: %s",
                type(exc).__name__,
                extra={
                    "trace_id": context.trace_id,
                    "tenant_id": context.identity.tenant_id,
                    "planner_kind": kind.value,
                },
            )
            raise DagPlanningError("Planner model call failed") from exc

    def _build_model(self) -> OpenAIChatModel:
        return build_openai_chat_model(
            self._settings,
            temperature=0,
            stream=False,
            max_tokens=self._settings.agent_planner_max_tokens,
            max_retries=self._settings.agent_planner_max_retries,
            timeout_seconds=self._settings.agent_planner_timeout_seconds,
            parallel_tool_calls=False,
        )
