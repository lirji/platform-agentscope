import json
from typing import Any

import httpx
import jwt
from mcp.server.fastmcp import FastMCP
from pydantic import SecretStr

from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.infrastructure.mcp.client import StreamableHttpMcpGateway
from tool_confirmation_support import DOWNSTREAM_SECRET


async def test_streamable_http_mcp_call_carries_trusted_headers() -> None:
    seen_headers: dict[str, str] = {}
    seen_payloads: list[dict[str, Any]] = []
    server = FastMCP("test", stateless_http=True, json_response=True)

    @server.tool()
    def get_weather(city: str) -> dict[str, Any]:
        return {"city": city, "temperature": 23}

    app = server.streamable_http_app()

    async def capture_headers(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        if request.content:
            seen_payloads.append(json.loads(request.content))
        return await httpx.ASGITransport(app=app).handle_async_request(request)

    context = RunContext(
        identity=TenantIdentity("acme", "alice", frozenset({"agent"})),
        internal_token="signed-acme-token",
        trace_id="trace-acme",
        idempotency_key="request-42",
    )
    configured = Settings(
        _env_file=None,
        agent_downstream_jwt_secret=SecretStr(DOWNSTREAM_SECRET),
    )
    gateway = StreamableHttpMcpGateway(
        configured,
        transport=httpx.MockTransport(capture_headers),
    )

    async with app.router.lifespan_context(app):
        try:
            result = await gateway.call(
                server_url="http://127.0.0.1:8000/mcp",
                tool_name="get_weather",
                arguments={"city": "Taipei"},
                context=context,
                timeout_seconds=5,
            )
        finally:
            await gateway.close()

    assert "Taipei" in result
    assert "23" in result
    assert "x-internal-token" not in seen_headers
    provider_token = seen_headers[configured.agent_downstream_jwt_header.casefold()]
    assert provider_token != "signed-acme-token"
    claims = jwt.decode(
        provider_token,
        DOWNSTREAM_SECRET,
        algorithms=["HS256"],
        issuer=configured.agent_downstream_jwt_issuer,
        audience=configured.agent_mcp_audience,
    )
    assert claims["tenant"] == "acme"
    assert claims["actor_uid"] == "alice"
    assert claims["act"] == "mcp:get_weather"
    assert seen_headers["x-trace-id"] == "trace-acme"
    assert int(seen_headers["x-request-deadline-ms"]) > 0
    assert "idempotency-key" not in seen_headers
    tool_call = next(payload for payload in seen_payloads if payload.get("method") == "tools/call")
    assert tool_call["params"]["_meta"] == {
        "platform/traceId": "trace-acme",
        "platform/idempotencyKey": "request-42",
    }
