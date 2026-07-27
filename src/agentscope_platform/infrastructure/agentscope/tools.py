from typing import Any

from agentscope.permission import PermissionBehavior, PermissionDecision
from agentscope.tool import FunctionTool


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
