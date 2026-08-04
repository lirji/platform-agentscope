from urllib.parse import quote

import httpx
from pydantic import BaseModel

from agentscope_platform.core.config import Settings
from agentscope_platform.core.deadline import outbound_deadline_epoch_ms
from agentscope_platform.domain.agent import RunContext
from agentscope_platform.domain.sandbox import (
    BrowserActionReply,
    BrowserActionRequest,
    CodeExecutionReply,
    CodeExecutionRequest,
    SandboxGatewayError,
    sandbox_session_id,
)
from agentscope_platform.infrastructure.http.resilience import (
    DependencyCallRejected,
    DependencyGuardRegistry,
    httpx_limits,
)
from agentscope_platform.infrastructure.security.downstream_jwt import (
    DownstreamServiceTokenError,
    DownstreamServiceTokenIssuer,
)


class HttpRemoteSandboxGateway:
    """Language-neutral HTTP client; execution always happens outside this process."""

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        token_issuer: DownstreamServiceTokenIssuer | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        guards: DependencyGuardRegistry | None = None,
    ) -> None:
        if client is not None and transport is not None:
            raise ValueError("client and transport are mutually exclusive")
        self._settings = settings
        self._token_issuer = token_issuer or DownstreamServiceTokenIssuer(settings)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            transport=transport,
            limits=httpx_limits(settings),
        )
        self._guards = guards or DependencyGuardRegistry(settings)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def browser_action(
        self,
        request: BrowserActionRequest,
        context: RunContext,
        timeout_seconds: float,
    ) -> BrowserActionReply:
        return await self._request(
            service="browser sandbox",
            method="POST",
            url=f"{self._settings.agent_browser_sandbox_url.rstrip('/')}/v1/browser/actions",
            payload=request,
            context=context,
            operation_id=request.operation_id,
            audience=self._settings.agent_browser_audience,
            action=f"browser:{request.action}:{request.operation_id}",
            timeout_seconds=timeout_seconds,
            response_type=BrowserActionReply,
        )

    async def execute_code(
        self,
        request: CodeExecutionRequest,
        context: RunContext,
        timeout_seconds: float,
    ) -> CodeExecutionReply:
        return await self._request(
            service="code sandbox",
            method="POST",
            url=f"{self._settings.agent_code_sandbox_url.rstrip('/')}/v1/code/execute",
            payload=request,
            context=context,
            operation_id=request.operation_id,
            audience=self._settings.agent_code_audience,
            action=f"code:execute:{request.operation_id}",
            timeout_seconds=timeout_seconds,
            response_type=CodeExecutionReply,
        )

    async def close_browser(self, context: RunContext) -> None:
        if not self._settings.agent_browser_enabled:
            return
        session_id = quote(sandbox_session_id(context), safe="")
        await self._request_without_reply(
            service="browser sandbox",
            method="DELETE",
            url=(
                f"{self._settings.agent_browser_sandbox_url.rstrip('/')}"
                f"/v1/browser/sessions/{session_id}"
            ),
            context=context,
            audience=self._settings.agent_browser_audience,
            action=f"browser:close:{session_id}",
            timeout_seconds=self._settings.agent_browser_timeout_seconds,
        )

    async def _request[ResponseT: BaseModel](
        self,
        *,
        service: str,
        method: str,
        url: str,
        payload: BaseModel,
        context: RunContext,
        operation_id: str,
        audience: str,
        action: str,
        timeout_seconds: float,
        response_type: type[ResponseT],
    ) -> ResponseT:
        response = await self._send(
            service=service,
            method=method,
            url=url,
            payload=payload,
            context=context,
            operation_id=operation_id,
            audience=audience,
            action=action,
            timeout_seconds=timeout_seconds,
        )
        try:
            return response_type.model_validate(response.json())
        except (TypeError, ValueError) as exc:
            raise SandboxGatewayError(f"invalid {service} response") from exc

    async def _request_without_reply(
        self,
        *,
        service: str,
        method: str,
        url: str,
        context: RunContext,
        audience: str,
        action: str,
        timeout_seconds: float,
    ) -> None:
        await self._send(
            service=service,
            method=method,
            url=url,
            payload=None,
            context=context,
            operation_id=None,
            audience=audience,
            action=action,
            timeout_seconds=timeout_seconds,
        )

    async def _send(
        self,
        *,
        service: str,
        method: str,
        url: str,
        payload: BaseModel | None,
        context: RunContext,
        operation_id: str | None,
        audience: str,
        action: str,
        timeout_seconds: float,
    ) -> httpx.Response:
        try:
            provider_token = self._token_issuer.issue(
                context,
                audience=audience,
                action=action,
            )
        except DownstreamServiceTokenError as exc:
            raise SandboxGatewayError(f"{service} authentication unavailable") from exc
        headers = {
            "X-Trace-Id": context.trace_id,
            "X-Request-Deadline-Ms": str(outbound_deadline_epoch_ms(timeout_seconds)),
            self._settings.agent_downstream_jwt_header: provider_token,
        }
        if operation_id:
            headers["Idempotency-Key"] = operation_id
        timeout = httpx.Timeout(
            connect=min(timeout_seconds, self._settings.http_connect_timeout_seconds),
            read=timeout_seconds,
            write=timeout_seconds,
            pool=self._settings.http_connect_timeout_seconds,
        )
        try:
            response = await self._guards.for_dependency(service).execute(
                lambda: self._client.request(
                    method,
                    url,
                    headers=headers,
                    json=(payload.model_dump(by_alias=True) if payload is not None else None),
                    timeout=timeout,
                ),
                timeout_seconds=timeout_seconds,
                response_failed=lambda item: item.status_code >= 500,
            )
        except DependencyCallRejected as exc:
            raise SandboxGatewayError(f"{service} unavailable ({exc.reason})") from exc
        except httpx.HTTPError as exc:
            raise SandboxGatewayError(f"{service} unavailable") from exc
        if response.is_error:
            raise SandboxGatewayError(f"{service} returned HTTP {response.status_code}")
        return response
