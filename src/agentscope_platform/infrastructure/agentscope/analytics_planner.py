import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any, Protocol

from agentscope.message import Msg, SystemMsg, TextBlock, UserMsg
from agentscope.model import ChatResponse, FinishedReason, OpenAIChatModel
from pydantic import ValidationError

from agentscope_platform.application.ports import AnalyticsSqlPlanner
from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import RunContext
from agentscope_platform.domain.analytics import AnalyticsSqlPlan
from agentscope_platform.infrastructure.agentscope.model_factory import (
    build_openai_chat_model,
)

log = logging.getLogger(__name__)
MAX_SCHEMA_CHARS = 32_000

SYSTEM_PROMPT = """
你是只读 SQL 规划器。只返回一个 JSON 对象, 且只能包含 sql 字段。

约束:
- 只能生成单条 SELECT 或 WITH ... SELECT。
- 只能使用提供的表和字段, 不得猜测 schema。
- 不得生成 DDL、DML、存储过程、事务控制、注释或多语句。
- 必须在 SQL 中显式使用 tenant_id = :tenantId; 不要填写真实租户值。
- 不得生成或索取数据库地址、用户名、密码或访问令牌。
- Java 执行端会再次做 allowlist、只读、租户谓词、LIMIT 和超时校验。

返回格式:
{"sql":"SELECT ... WHERE tenant_id = :tenantId"}
""".strip()


class AnalyticsPlanningError(RuntimeError):
    """Sanitized failure from the candidate SQL planner."""


class _PlannerModel(Protocol):
    async def __call__(
        self,
        messages: list[Msg],
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]: ...


class AgentScopeAnalyticsSqlPlanner(AnalyticsSqlPlanner):
    def __init__(
        self,
        settings: Settings,
        model: _PlannerModel | None = None,
    ) -> None:
        self._settings = settings
        self._model = model or self._build_model()

    async def plan(
        self,
        question: str,
        schema: str,
        context: RunContext,
    ) -> AnalyticsSqlPlan:
        if not self._settings.agent_enabled:
            raise AnalyticsPlanningError("analytics planner model is not configured")
        bounded_schema = schema[:MAX_SCHEMA_CHARS]
        try:
            response = await self._model(
                [
                    SystemMsg(name="system", content=SYSTEM_PROMPT),
                    UserMsg(
                        name="user",
                        content=f"Schema:\n{bounded_schema}\n\nQuestion:\n{question}",
                    ),
                ],
                response_format={"type": "json_object"},
            )
            if not isinstance(response, ChatResponse):
                raise AnalyticsPlanningError("streaming planner response is unsupported")
            if response.get("finished_reason") == FinishedReason.INTERRUPTED:
                raise asyncio.CancelledError
            text = "".join(
                block.text for block in response.content if isinstance(block, TextBlock)
            ).strip()
            return AnalyticsSqlPlan.model_validate_json(text)
        except asyncio.CancelledError:
            raise
        except AnalyticsPlanningError:
            raise
        except (ValidationError, ValueError, TypeError) as exc:
            raise AnalyticsPlanningError("invalid analytics SQL plan") from exc
        except Exception as exc:
            log.warning(
                "analytics SQL planner failed: %s",
                type(exc).__name__,
                extra={
                    "trace_id": context.trace_id,
                    "tenant_id": context.identity.tenant_id,
                },
            )
            raise AnalyticsPlanningError("analytics SQL planner call failed") from exc

    def _build_model(self) -> OpenAIChatModel:
        return build_openai_chat_model(
            self._settings,
            temperature=0,
            stream=False,
            max_tokens=min(self._settings.agent_planner_max_tokens, 2_048),
            max_retries=self._settings.agent_planner_max_retries,
            timeout_seconds=self._settings.agent_planner_timeout_seconds,
            parallel_tool_calls=False,
        )
