from collections.abc import AsyncGenerator, Mapping
from typing import Any

from agentscope.message import TextBlock, ToolResultState
from agentscope.permission import PermissionBehavior, PermissionDecision
from agentscope.tool import FunctionTool, ToolChunk

from agentscope_platform.application.confirmation import ToolConfirmationUnavailableError
from agentscope_platform.application.ports import ToolConfirmationConsumer
from agentscope_platform.core.context import current_run_context
from agentscope_platform.domain.tool import ToolMetadata, ToolPolicy, ToolPolicyReason
from agentscope_platform.infrastructure.observability.governed_tool_metrics import (
    record_tool_policy_denied,
)


class GovernedFunctionTool(FunctionTool):
    """Translate framework-neutral tool policy into AgentScope permissions."""

    def __init__(
        self,
        func: Any,
        *,
        metadata: ToolMetadata,
        description: str | None = None,
        is_concurrency_safe: bool | None = None,
        confirmation_consumer: ToolConfirmationConsumer | None = None,
    ) -> None:
        super().__init__(
            func,
            name=metadata.name,
            description=description,
            is_concurrency_safe=(
                metadata.read_only if is_concurrency_safe is None else is_concurrency_safe
            ),
            is_read_only=metadata.read_only,
        )
        self.metadata = metadata
        self._confirmation_consumer = confirmation_consumer

    async def check_permissions(
        self,
        *_args: Any,
        **_kwargs: Any,
    ) -> PermissionDecision:
        decision = ToolPolicy.evaluate(
            self.metadata,
            current_run_context(),
            self._permission_arguments(_args, _kwargs),
        )
        if not decision.allowed:
            record_tool_policy_denied(self.metadata.name, decision.reason.value)
        return PermissionDecision(
            behavior=(PermissionBehavior.ALLOW if decision.allowed else PermissionBehavior.DENY),
            message=decision.message,
            decision_reason=decision.reason.value,
        )

    async def call(
        self,
        **kwargs: Any,
    ) -> ToolChunk | AsyncGenerator[ToolChunk, None]:
        decision = ToolPolicy.evaluate(self.metadata, current_run_context(), kwargs)
        if not decision.allowed:
            record_tool_policy_denied(self.metadata.name, decision.reason.value)
            return self._denied(decision.message)
        if decision.confirmation_grant is not None:
            if self._confirmation_consumer is None:
                record_tool_policy_denied(
                    self.metadata.name,
                    ToolPolicyReason.CONFIRMATION_INVALID.value,
                )
                return self._denied(
                    "tool permission denied: confirmation replay protection is unavailable"
                )
            try:
                consumed = await self._confirmation_consumer.consume(decision.confirmation_grant)
            except ToolConfirmationUnavailableError:
                record_tool_policy_denied(
                    self.metadata.name,
                    ToolPolicyReason.CONFIRMATION_INVALID.value,
                )
                return self._denied(
                    "tool permission denied: confirmation replay protection is unavailable"
                )
            if not consumed:
                record_tool_policy_denied(
                    self.metadata.name,
                    ToolPolicyReason.CONFIRMATION_REPLAYED.value,
                )
                return self._denied("tool permission denied: confirmation grant was already used")
        return await super().call(**kwargs)

    @staticmethod
    def _denied(message: str) -> ToolChunk:
        return ToolChunk(
            content=[TextBlock(text=message)],
            state=ToolResultState.ERROR,
        )

    @staticmethod
    def _permission_arguments(
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Mapping[str, Any] | None:
        if kwargs:
            return kwargs
        if args and isinstance(args[0], Mapping):
            return args[0]
        return None


class ReadOnlyFunctionTool(FunctionTool):
    """Allow automatic execution only for explicitly registered read-only tools."""

    async def check_permissions(
        self,
        *_args: Any,
        **_kwargs: Any,
    ) -> PermissionDecision:
        if not self.is_read_only:
            return PermissionDecision(
                behavior=PermissionBehavior.DENY,
                message="The tool is not declared read-only.",
            )
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="The tool is declared read-only.",
        )
