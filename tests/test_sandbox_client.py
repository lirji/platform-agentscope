import json

import httpx
import jwt
from pydantic import SecretStr

from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.domain.sandbox import BrowserActionRequest, CodeExecutionRequest
from agentscope_platform.infrastructure.sandbox.client import HttpRemoteSandboxGateway
from tool_confirmation_support import CONFIRMATION_SECRET, DOWNSTREAM_SECRET


def context() -> RunContext:
    return RunContext(
        identity=TenantIdentity("acme", "alice", frozenset({"agent"})),
        internal_token="token-acme",
        trace_id="trace-acme",
        idempotency_key="request-42",
    )


async def test_remote_browser_and_code_contracts_use_exact_paths_and_headers() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/v1/browser/actions":
            return httpx.Response(
                200, json={"output": "opened", "currentUrl": "https://example.com"}
            )
        return httpx.Response(200, json={"status": "COMPLETED", "output": "4", "truncated": False})

    settings = Settings(
        _env_file=None,
        agent_browser_enabled=True,
        agent_browser_sandbox_url="https://sandbox.test",
        agent_browser_allowed_hosts_json='["example.com"]',
        agent_code_sandbox_url="https://sandbox.test",
        agent_confirmation_secret=SecretStr(CONFIRMATION_SECRET),
        agent_downstream_jwt_secret=SecretStr(DOWNSTREAM_SECRET),
    )
    client = HttpRemoteSandboxGateway(settings, httpx.MockTransport(handler))
    browser_request = BrowserActionRequest(
        sessionId="run-11111111111111111111111111111111",
        operationId="op-11111111111111111111111111111111",
        action="open",
        arguments={"url": "https://example.com"},
        allowedHosts=["example.com"],
    )
    code_request = CodeExecutionRequest(
        operationId="op-22222222222222222222222222222222",
        language="java",
        source="2+2",
        timeoutMs=3000,
        maxOutputChars=2000,
        networkEnabled=False,
        workspace="ephemeral",
        maxMemoryMb=64,
        maxProcesses=4,
    )

    browser = await client.browser_action(browser_request, context(), 5)
    code = await client.execute_code(code_request, context(), 3)
    await client.close_browser(context())
    await client.close()

    assert browser.output == "opened"
    assert code.output == "4"
    assert [request.url.path for request in seen] == [
        "/v1/browser/actions",
        "/v1/code/execute",
        "/v1/browser/sessions/run-ea6fb1bdd142d94218ef459297052e52",
    ]
    assert all("X-Internal-Token" not in request.headers for request in seen)
    provider_tokens = [request.headers[settings.agent_downstream_jwt_header] for request in seen]
    assert all(token != "token-acme" for token in provider_tokens)
    audiences = [
        settings.agent_browser_audience,
        settings.agent_code_audience,
        settings.agent_browser_audience,
    ]
    claims = [
        jwt.decode(
            token,
            DOWNSTREAM_SECRET,
            algorithms=["HS256"],
            issuer=settings.agent_downstream_jwt_issuer,
            audience=audience,
        )
        for token, audience in zip(provider_tokens, audiences, strict=True)
    ]
    assert [item["act"].split(":", maxsplit=2)[:2] for item in claims] == [
        ["browser", "open"],
        ["code", "execute"],
        ["browser", "close"],
    ]
    assert all(item["tenant"] == "acme" and item["actor_uid"] == "alice" for item in claims)
    assert all(request.headers["X-Trace-Id"] == "trace-acme" for request in seen)
    assert all(int(request.headers["X-Request-Deadline-Ms"]) > 0 for request in seen)
    assert [request.headers["Idempotency-Key"] for request in seen[:2]] == [
        "op-11111111111111111111111111111111",
        "op-22222222222222222222222222222222",
    ]
    assert "Idempotency-Key" not in seen[2].headers
    assert "tenantId" not in json.loads(seen[0].content)
    assert "userId" not in json.loads(seen[1].content)
