import json
import math
from typing import Any, Literal
from urllib.parse import urlsplit

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolBase, ToolChunk

from agentscope_platform.application.ports import (
    McpGateway,
    RemoteSandboxGateway,
    ToolConfirmationConsumer,
)
from agentscope_platform.core.config import Settings
from agentscope_platform.core.context import current_run_context
from agentscope_platform.domain.agent import RunContext
from agentscope_platform.domain.mcp import McpGatewayError, McpToolBinding
from agentscope_platform.domain.sandbox import (
    BrowserActionReply,
    BrowserActionRequest,
    CodeExecutionRequest,
    SandboxGatewayError,
    sandbox_operation_id,
    sandbox_session_id,
)
from agentscope_platform.domain.tool import (
    ConfirmationRequirement,
    IdempotencyStrategy,
    RetryPolicy,
    SideEffectLevel,
    ToolMetadata,
)
from agentscope_platform.infrastructure.agentscope.tools import GovernedFunctionTool
from agentscope_platform.infrastructure.http.platform_client import (
    PlatformClient,
    PlatformServiceError,
)
from agentscope_platform.infrastructure.mcp.client import StreamableHttpMcpGateway
from agentscope_platform.infrastructure.observability.governed_tool_metrics import (
    record_tool_provider_failure,
)
from agentscope_platform.infrastructure.sandbox.client import HttpRemoteSandboxGateway

MAX_REFUND_MESSAGE_CHARS = 20_000
FORBIDDEN_MCP_ARGUMENT_KEYS = frozenset(
    {
        "tenantid",
        "tenant_id",
        "userid",
        "user_id",
        "internaltoken",
        "internal_token",
        "traceid",
        "trace_id",
        "confirmedtools",
        "confirmed_tools",
        "idempotencykey",
        "idempotency_key",
    }
)


class GovernedToolset:
    """Default-off side-effect tools backed by retained platform services."""

    def __init__(
        self,
        settings: Settings,
        client: PlatformClient,
        *,
        mcp_gateway: McpGateway | None = None,
        sandbox_gateway: RemoteSandboxGateway | None = None,
        confirmation_consumer: ToolConfirmationConsumer | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._mcp_gateway = mcp_gateway or StreamableHttpMcpGateway(settings)
        self._sandbox_gateway = sandbox_gateway or HttpRemoteSandboxGateway(settings)
        self._confirmation_consumer = confirmation_consumer
        self._operation_sequence = 0
        self._refund_metadata = ToolMetadata(
            name="refund_start",
            readOnly=False,
            sideEffect=SideEffectLevel.MEDIUM,
            idempotency=IdempotencyStrategy.REQUEST_KEY,
            requiresConfirmation=ConfirmationRequirement.ALWAYS,
            requiredScopes=("agent",),
            timeoutSeconds=settings.http_read_timeout_seconds,
            retryPolicy=RetryPolicy.NONE,
        )
        self._browser_metadata = {
            "browser_open": self._write_metadata("browser_open", SideEffectLevel.LOW),
            "browser_click": self._write_metadata("browser_click", SideEffectLevel.HIGH),
            "browser_click_xy": self._write_metadata("browser_click_xy", SideEffectLevel.HIGH),
            "browser_type": self._write_metadata("browser_type", SideEffectLevel.MEDIUM),
            "browser_screenshot": ToolMetadata.for_read_only(
                name="browser_screenshot",
                required_scopes=("agent",),
                timeout_seconds=settings.agent_browser_timeout_seconds,
            ),
            "browser_see": ToolMetadata.for_read_only(
                name="browser_see",
                required_scopes=("agent",),
                timeout_seconds=settings.agent_browser_timeout_seconds,
            ),
        }
        self._code_metadata = ToolMetadata(
            name="code_exec",
            readOnly=False,
            sideEffect=SideEffectLevel.MEDIUM,
            idempotency=IdempotencyStrategy.REQUEST_KEY,
            requiresConfirmation=ConfirmationRequirement.ALWAYS,
            requiredScopes=("agent",),
            timeoutSeconds=settings.agent_code_timeout_seconds,
            retryPolicy=RetryPolicy.NONE,
        )

    def _write_metadata(
        self,
        name: str,
        side_effect: SideEffectLevel,
    ) -> ToolMetadata:
        return ToolMetadata(
            name=name,
            readOnly=False,
            sideEffect=side_effect,
            idempotency=IdempotencyStrategy.REQUEST_KEY,
            requiresConfirmation=ConfirmationRequirement.ALWAYS,
            requiredScopes=("agent",),
            timeoutSeconds=self._settings.agent_browser_timeout_seconds,
            retryPolicy=RetryPolicy.NONE,
        )

    def confirmable_metadata(self) -> dict[str, ToolMetadata]:
        metadata: list[ToolMetadata] = []
        if self._settings.agent_refund_start_enabled:
            metadata.append(self._refund_metadata)
        if self._settings.agent_mcp_enabled:
            metadata.extend(binding.metadata for binding in self._settings.agent_mcp_tools)
        if self._settings.agent_browser_enabled:
            metadata.extend(self._browser_metadata.values())
        if self._settings.agent_code_exec_enabled:
            metadata.append(self._code_metadata)
        return {
            item.name: item
            for item in metadata
            if item.requires_confirmation is ConfirmationRequirement.ALWAYS
        }

    def tools(self) -> list[ToolBase]:
        tools: list[ToolBase] = []
        if self._settings.agent_refund_start_enabled:
            tools.append(
                GovernedFunctionTool(
                    self.refund_start,
                    metadata=self._refund_metadata,
                    description=(
                        "发起当前用户的退款审批流程。仅在调用方显式确认且提供幂等键时执行；"
                        "只负责发起，绝不自动批准。message 填退款诉求原文。"
                    ),
                    confirmation_consumer=self._confirmation_consumer,
                )
            )
        if self._settings.agent_mcp_enabled:
            for binding in self._settings.agent_mcp_tools:
                tools.append(self._build_mcp_tool(binding))
        if self._settings.agent_browser_enabled:
            tools.extend(
                [
                    GovernedFunctionTool(
                        self.browser_open,
                        metadata=self._browser_metadata["browser_open"],
                        description=(
                            "Open an allowlisted HTTP(S) URL in the remote browser sandbox."
                        ),
                        confirmation_consumer=self._confirmation_consumer,
                    ),
                    GovernedFunctionTool(
                        self.browser_click,
                        metadata=self._browser_metadata["browser_click"],
                        description="Click the first remote-page link matching the supplied text.",
                        confirmation_consumer=self._confirmation_consumer,
                    ),
                    GovernedFunctionTool(
                        self.browser_click_xy,
                        metadata=self._browser_metadata["browser_click_xy"],
                        description="Click coordinates in the current remote browser session.",
                        confirmation_consumer=self._confirmation_consumer,
                    ),
                    GovernedFunctionTool(
                        self.browser_type,
                        metadata=self._browser_metadata["browser_type"],
                        description=(
                            "Type text into a selector in the current remote browser session."
                        ),
                        confirmation_consumer=self._confirmation_consumer,
                    ),
                    GovernedFunctionTool(
                        self.browser_screenshot,
                        metadata=self._browser_metadata["browser_screenshot"],
                        description="Create an artifact in the remote browser sandbox.",
                        is_concurrency_safe=False,
                        confirmation_consumer=self._confirmation_consumer,
                    ),
                    GovernedFunctionTool(
                        self.browser_see,
                        metadata=self._browser_metadata["browser_see"],
                        description=(
                            "Describe the current remote page using the sandbox vision path."
                        ),
                        is_concurrency_safe=False,
                        confirmation_consumer=self._confirmation_consumer,
                    ),
                ]
            )
        if self._settings.agent_code_exec_enabled:
            tools.append(
                GovernedFunctionTool(
                    self.code_exec,
                    metadata=self._code_metadata,
                    description=(
                        "Execute Java source for deterministic computation in a "
                        "separately deployed remote sandbox. No local fallback exists."
                    ),
                    confirmation_consumer=self._confirmation_consumer,
                )
            )
        return tools

    def _build_mcp_tool(self, binding: McpToolBinding) -> GovernedFunctionTool:
        async def call(arguments: dict[str, Any]) -> ToolChunk:
            return await self.call_mcp(binding, arguments)

        return GovernedFunctionTool(
            call,
            metadata=binding.metadata,
            description=(
                f"{binding.description} Pass only the remote tool arguments in `arguments`; "
                "trusted identity, confirmation, trace, and idempotency are injected "
                "by the platform."
            ),
            confirmation_consumer=self._confirmation_consumer,
        )

    async def call_mcp(
        self,
        binding: McpToolBinding,
        arguments: dict[str, Any],
    ) -> ToolChunk:
        """Call exactly one configured remote tool after a defense-in-depth policy check."""
        context = current_run_context()
        if _contains_forbidden_mcp_context_key(arguments):
            return self._error("MCP arguments cannot override trusted request context fields.")
        try:
            encoded = json.dumps(
                arguments,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError):
            return self._error("MCP arguments must be a JSON object.")
        if len(encoded) > self._settings.agent_mcp_max_arguments_bytes:
            return self._error("MCP arguments exceed the configured byte limit.")

        try:
            result = await self._mcp_gateway.call(
                server_url=self._settings.agent_mcp_url,
                tool_name=binding.remote_name,
                arguments=arguments,
                context=context,
                timeout_seconds=binding.metadata.timeout_seconds,
            )
        except McpGatewayError as exc:
            record_tool_provider_failure(binding.metadata.name, "mcp")
            return self._error(f"MCP tool call failed: {exc}")
        return self._success(result)

    async def browser_open(self, url: str) -> ToolChunk:
        """Open one operator-allowlisted URL in the remote browser."""
        normalized = url.strip()
        if len(normalized) > self._settings.agent_browser_max_input_chars:
            return self._error("Browser URL exceeds the configured input limit.")
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            return self._error("Browser URL must be an HTTP(S) URL without credentials.")
        if parsed.hostname.casefold() not in self._settings.agent_browser_allowed_hosts:
            return self._error("Browser host is not in the configured allowlist.")
        return await self._browser_action(
            "browser_open",
            "open",
            {"url": normalized},
        )

    async def browser_click(self, link_text: str) -> ToolChunk:
        """Click matching link text in the current remote browser session."""
        normalized = link_text.strip()
        if not normalized:
            return self._error("Browser link text must not be blank.")
        if len(normalized) > self._settings.agent_browser_max_input_chars:
            return self._error("Browser link text exceeds the configured input limit.")
        return await self._browser_action(
            "browser_click",
            "click",
            {"linkText": normalized},
        )

    async def browser_click_xy(self, x: float, y: float) -> ToolChunk:
        """Click bounded coordinates in the current remote browser session."""
        if not all(math.isfinite(value) and 0 <= value <= 10_000 for value in (x, y)):
            return self._error("Browser coordinates must be finite values from 0 to 10000.")
        return await self._browser_action(
            "browser_click_xy",
            "click_xy",
            {"x": x, "y": y},
        )

    async def browser_type(self, selector: str, text: str) -> ToolChunk:
        """Type bounded text into a selector in the remote browser."""
        normalized_selector = selector.strip()
        if not normalized_selector:
            return self._error("Browser selector must not be blank.")
        if max(len(normalized_selector), len(text)) > self._settings.agent_browser_max_input_chars:
            return self._error("Browser type input exceeds the configured limit.")
        return await self._browser_action(
            "browser_type",
            "type",
            {"selector": normalized_selector, "text": text},
        )

    async def browser_screenshot(self) -> ToolChunk:
        """Create a remote screenshot artifact for the current session."""
        return await self._browser_action(
            "browser_screenshot",
            "screenshot",
            {},
        )

    async def browser_see(self, instruction: str = "") -> ToolChunk:
        """Ask the remote browser sandbox to describe the current page."""
        normalized = instruction.strip()
        if len(normalized) > self._settings.agent_browser_max_input_chars:
            return self._error("Browser vision instruction exceeds the configured limit.")
        return await self._browser_action(
            "browser_see",
            "see",
            {"instruction": normalized},
        )

    async def _browser_action(
        self,
        tool_name: str,
        action: Literal["open", "click", "click_xy", "type", "screenshot", "see"],
        arguments: dict[str, Any],
    ) -> ToolChunk:
        context = current_run_context()
        request = BrowserActionRequest(
            sessionId=sandbox_session_id(context),
            operationId=self._next_operation_id(context, tool_name),
            action=action,
            arguments=arguments,
            allowedHosts=self._settings.agent_browser_allowed_hosts,
        )
        try:
            reply = await self._sandbox_gateway.browser_action(
                request,
                context,
                self._settings.agent_browser_timeout_seconds,
            )
        except SandboxGatewayError as exc:
            record_tool_provider_failure(tool_name, "browser_sandbox")
            return self._error(f"Browser sandbox call failed: {exc}")
        return self._browser_reply(reply)

    def _browser_reply(self, reply: BrowserActionReply) -> ToolChunk:
        if reply.current_url:
            current_host = urlsplit(reply.current_url).hostname
            if (
                current_host is None
                or current_host.casefold() not in self._settings.agent_browser_allowed_hosts
            ):
                return self._error(
                    "Browser sandbox returned a URL outside the configured allowlist."
                )
        output = reply.output[: self._settings.agent_browser_max_output_chars]
        lines = [output or "(Browser sandbox returned an empty result)"]
        if reply.current_url:
            lines.append(f"currentUrl: {reply.current_url}")
        if reply.artifact_id:
            lines.append(f"artifactId: {reply.artifact_id}")
        if reply.truncated or len(reply.output) > self._settings.agent_browser_max_output_chars:
            lines.append("[truncated]")
        return self._success("\n".join(lines))

    async def code_exec(self, source: str) -> ToolChunk:
        """Execute bounded Java source in the configured remote code sandbox."""
        context = current_run_context()
        normalized = source.strip()
        if not normalized:
            return self._error("Code source must not be blank.")
        if len(normalized) > self._settings.agent_code_max_source_chars:
            return self._error("Code source exceeds the configured character limit.")
        request = CodeExecutionRequest(
            operationId=self._next_operation_id(context, "code_exec"),
            language="java",
            source=normalized,
            timeoutMs=int(self._settings.agent_code_timeout_seconds * 1000),
            maxOutputChars=self._settings.agent_code_max_output_chars,
            networkEnabled=False,
            workspace="ephemeral",
            maxMemoryMb=self._settings.agent_code_max_memory_mb,
            maxProcesses=self._settings.agent_code_max_processes,
        )
        try:
            reply = await self._sandbox_gateway.execute_code(
                request,
                context,
                self._settings.agent_code_timeout_seconds,
            )
        except SandboxGatewayError as exc:
            record_tool_provider_failure("code_exec", "code_sandbox")
            return self._error(f"Code sandbox call failed: {exc}")

        output = (reply.output or "")[: self._settings.agent_code_max_output_chars]
        suffix = "\n[truncated]" if reply.truncated else ""
        if reply.status == "TIMED_OUT":
            detail = f"\n{output}" if output else ""
            return self._error(f"Code execution timed out.{detail}{suffix}")
        if reply.status == "FAILED":
            detail = reply.error or "remote sandbox rejected the execution"
            prefix = f"{output}\n" if output else ""
            return self._error(f"{prefix}Code execution failed: {detail}{suffix}")
        if not output:
            output = "Code execution completed without output."
        return self._success(output + suffix)

    def _next_operation_id(self, context: RunContext, tool_name: str) -> str:
        self._operation_sequence += 1
        return sandbox_operation_id(context, tool_name, self._operation_sequence)

    async def refund_start(self, message: str) -> ToolChunk:
        """Start a tenant-bound Java workflow after trusted policy checks."""
        context = current_run_context()
        normalized = message.strip()
        if not normalized:
            return self._error("诉求为空：message 请填用户明确确认的退款诉求原文。")
        if len(normalized) > MAX_REFUND_MESSAGE_CHARS:
            return self._error(f"诉求过长：message 上限 {MAX_REFUND_MESSAGE_CHARS} 字符。")

        # Policy guarantees the key is present. Keeping this check local makes
        # direct adapter calls fail closed if policy code changes later.
        dedupe_id = context.idempotency_key
        if not dedupe_id:
            return self._error("发起失败：缺少幂等键。")
        try:
            reply = await self._client.start_refund(
                message=normalized,
                chat_id=f"agent:{context.identity.user_id}",
                dedupe_id=dedupe_id,
                context=context,
            )
        except PlatformServiceError as exc:
            record_tool_provider_failure("refund_start", "workflow_service")
            return self._error(f"发起失败：{exc}")

        lines = [f"instanceId: {reply.instance_id}", f"status: {reply.status}"]
        if reply.priority and reply.priority.strip():
            lines.append(f"priority: {reply.priority}")
        if reply.task_id and reply.task_id.strip():
            lines.append(f"taskId: {reply.task_id}")
        if reply.reply and reply.reply.strip():
            lines.append(f"reply: {reply.reply}")
        if reply.status == "WAITING_APPROVAL":
            lines.append(
                "注意：高风险，已转人工审批，尚未批准；审批须由具备审批权限的人在流程外完成。"
            )
        if reply.deduplicated:
            lines.append("（该诉求此前已发起过，返回的是已存在的流程，未重复发起。）")
        return self._success("\n".join(lines))

    @staticmethod
    def _success(value: str) -> ToolChunk:
        return ToolChunk(content=[TextBlock(text=value)])

    @staticmethod
    def _error(value: str) -> ToolChunk:
        return ToolChunk(
            content=[TextBlock(text=value)],
            state=ToolResultState.ERROR,
        )


def _contains_forbidden_mcp_context_key(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in FORBIDDEN_MCP_ARGUMENT_KEYS:
                return True
            if _contains_forbidden_mcp_context_key(item):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_mcp_context_key(item) for item in value)
    return False
