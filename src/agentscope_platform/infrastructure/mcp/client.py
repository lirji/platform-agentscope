import json
from contextvars import ContextVar
from datetime import timedelta
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent

from agentscope_platform.core.config import Settings
from agentscope_platform.core.deadline import outbound_deadline_epoch_ms
from agentscope_platform.domain.agent import RunContext
from agentscope_platform.domain.mcp import McpGatewayError
from agentscope_platform.infrastructure.http.resilience import (
    DependencyCallRejected,
    DependencyGuardRegistry,
    httpx_limits,
)
from agentscope_platform.infrastructure.security.downstream_jwt import (
    DownstreamServiceTokenError,
    DownstreamServiceTokenIssuer,
)


class StreamableHttpMcpGateway:
    """One-shot Streamable HTTP MCP client; stdio execution is intentionally absent."""

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        token_issuer: DownstreamServiceTokenIssuer | None = None,
        guards: DependencyGuardRegistry | None = None,
    ) -> None:
        self._settings = settings
        self._token_issuer = token_issuer or DownstreamServiceTokenIssuer(settings)
        self._request_headers: ContextVar[dict[str, str] | None] = ContextVar(
            "mcp_request_headers",
            default=None,
        )
        self._client = httpx.AsyncClient(
            timeout=None,
            transport=transport,
            limits=httpx_limits(settings),
            event_hooks={"request": [self._inject_headers]},
        )
        self._guard = (guards or DependencyGuardRegistry(settings)).for_dependency("mcp-provider")

    async def close(self) -> None:
        await self._client.aclose()

    async def _inject_headers(self, request: httpx.Request) -> None:
        headers = self._request_headers.get()
        if headers is not None:
            request.headers.update(headers)

    async def call(
        self,
        *,
        server_url: str,
        tool_name: str,
        arguments: dict[str, Any],
        context: RunContext,
        timeout_seconds: float,
    ) -> str:
        try:
            provider_token = self._token_issuer.issue(
                context,
                audience=self._settings.agent_mcp_audience,
                action=f"mcp:{tool_name}",
            )
        except DownstreamServiceTokenError as exc:
            raise McpGatewayError("mcp provider authentication unavailable") from exc
        headers = {
            "X-Trace-Id": context.trace_id,
            "X-Request-Deadline-Ms": str(outbound_deadline_epoch_ms(timeout_seconds)),
            self._settings.agent_downstream_jwt_header: provider_token,
        }

        async def invoke() -> Any:
            async with streamable_http_client(
                server_url,
                http_client=self._client,
            ) as (read_stream, write_stream, _):
                async with ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=timedelta(seconds=timeout_seconds),
                ) as session:
                    await session.initialize()
                    return await session.call_tool(
                        tool_name,
                        arguments,
                        read_timeout_seconds=timedelta(seconds=timeout_seconds),
                        meta=self._call_meta(context),
                    )

        headers_token = self._request_headers.set(headers)
        try:
            result = await self._guard.execute(
                invoke,
                timeout_seconds=timeout_seconds,
            )
        except DependencyCallRejected as exc:
            raise McpGatewayError(f"mcp provider unavailable ({exc.reason})") from exc
        except Exception as exc:
            raise McpGatewayError("mcp provider unavailable") from exc
        finally:
            self._request_headers.reset(headers_token)

        if result.isError:
            raise McpGatewayError("mcp tool returned an error")
        rendered = self._render_result(result.content, result.structuredContent)
        if len(rendered) > self._settings.agent_mcp_max_result_chars:
            return rendered[: self._settings.agent_mcp_max_result_chars] + "\n[truncated]"
        return rendered

    @staticmethod
    def _call_meta(context: RunContext) -> dict[str, Any]:
        meta: dict[str, Any] = {"platform/traceId": context.trace_id}
        if context.idempotency_key:
            meta["platform/idempotencyKey"] = context.idempotency_key
        return meta

    @staticmethod
    def _render_result(content: list[Any], structured_content: dict[str, Any] | None) -> str:
        text_parts = [item.text for item in content if isinstance(item, TextContent)]
        if text_parts:
            return "\n".join(text_parts)
        if structured_content is not None:
            return json.dumps(structured_content, ensure_ascii=False, separators=(",", ":"))
        if content:
            return "(MCP tool returned non-text content; omitted)"
        return "(MCP tool returned an empty result)"
