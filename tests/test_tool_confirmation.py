from dataclasses import replace

import httpx
import pytest
from agentscope.message import TextBlock, ToolResultState
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from agentscope_platform.api.app import create_app
from agentscope_platform.application.confirmation import (
    ToolConfirmationService,
    ToolConfirmationUnavailableError,
)
from agentscope_platform.core.config import Settings
from agentscope_platform.core.context import bind_run_context, reset_run_context
from agentscope_platform.domain.agent import AgentExecution, RunContext, TenantIdentity
from agentscope_platform.infrastructure.agentscope.governed_tools import GovernedToolset
from agentscope_platform.infrastructure.http.platform_client import PlatformClient
from agentscope_platform.infrastructure.security.tool_confirmation import (
    InMemoryConfirmationReplayStore,
    JwtToolConfirmationCodec,
    RedisConfirmationReplayStore,
)
from internal_jwt_support import signed_internal_token
from tool_confirmation_support import confirmation_grant

INTERNAL_SECRET = "test-only-internal-secret-with-at-least-32-bytes"
CONFIRMATION_SECRET = "test-only-confirmation-secret-at-least-32-bytes"


class CapturingRunner:
    def __init__(self) -> None:
        self.context: RunContext | None = None

    async def run(self, goal: str, context: RunContext) -> AgentExecution:
        self.context = context
        return AgentExecution(final_answer=f"completed: {goal}")


def configured_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "internal_jwt_secret": SecretStr(INTERNAL_SECRET),
        "agent_refund_start_enabled": True,
        "agent_confirmation_secret": SecretStr(CONFIRMATION_SECRET),
    }
    values.update(overrides)
    return Settings(**values)


def internal_token(tenant: str = "acme", user: str = "alice") -> str:
    return signed_internal_token(
        INTERNAL_SECRET,
        tenant=tenant,
        user=user,
    )


def issue_grant(client: TestClient, *, message: str = "订单 101 申请退款") -> str:
    response = client.post(
        "/agent/tool-confirmations",
        json={"toolName": "refund_start", "arguments": {"message": message}},
        headers={
            "X-Internal-Token": internal_token(),
            "Idempotency-Key": "refund-request-42",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["toolName"] == "refund_start"
    assert len(body["argumentsSha256"]) == 64
    return str(body["grant"])


def test_confirmation_grant_binds_identity_arguments_and_idempotency() -> None:
    runner = CapturingRunner()
    client = TestClient(create_app(configured_settings(), runner))
    grant = issue_grant(client)

    response = client.post(
        "/agent/run",
        json={"goal": "发起退款"},
        headers={
            "X-Internal-Token": internal_token(),
            "X-Agent-Confirmation-Grants": grant,
            "Idempotency-Key": "refund-request-42",
        },
    )

    assert response.status_code == 200
    assert runner.context is not None
    assert runner.context.has_confirmation_for_tool("refund_start")
    assert (
        runner.context.confirmation_for(
            "refund_start",
            {"message": "订单 101 申请退款"},
        )
        is not None
    )
    assert (
        runner.context.confirmation_for(
            "refund_start",
            {"message": "订单 999 申请退款"},
        )
        is None
    )


def test_confirmation_grant_rejects_tampering_cross_tenant_and_wrong_idempotency() -> None:
    client = TestClient(create_app(configured_settings(), CapturingRunner()))
    grant = issue_grant(client)
    requests = [
        (grant[:-1] + ("a" if grant[-1] != "a" else "b"), internal_token(), "refund-request-42"),
        (grant, internal_token("globex", "bob"), "refund-request-42"),
        (grant, internal_token(), "different-request"),
    ]

    for supplied_grant, token, idempotency_key in requests:
        response = client.post(
            "/agent/run",
            json={"goal": "发起退款"},
            headers={
                "X-Internal-Token": token,
                "X-Agent-Confirmation-Grants": supplied_grant,
                "Idempotency-Key": idempotency_key,
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "invalid tool confirmation grant"


def test_legacy_tool_name_confirmation_header_is_rejected() -> None:
    client = TestClient(create_app(configured_settings(), CapturingRunner()))

    response = client.post(
        "/agent/run",
        json={"goal": "发起退款"},
        headers={
            "X-Internal-Token": internal_token(),
            "X-Agent-Confirmed-Tools": "refund_start",
            "Idempotency-Key": "refund-request-42",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "legacy tool-name confirmation is not supported"


async def test_confirmation_grant_is_consumed_once_before_provider_call() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"instanceId": "wf-1", "status": "WAITING_APPROVAL", "deduplicated": False},
        )

    settings = configured_settings()
    confirmation_service = ToolConfirmationService(
        JwtToolConfirmationCodec(settings),
        InMemoryConfirmationReplayStore(),
        settings,
    )
    toolset = GovernedToolset(
        settings,
        PlatformClient(settings, httpx.MockTransport(handler)),
        confirmation_consumer=confirmation_service,
    )
    tool = toolset.tools()[0]
    base_context = RunContext(
        identity=TenantIdentity("acme", "alice", frozenset({"agent"})),
        internal_token="internal",
        trace_id="trace",
        idempotency_key="refund-request-42",
    )
    issued = confirmation_service.issue(
        tool.metadata,
        {"message": "订单 101 申请退款"},
        base_context,
    )
    grants = confirmation_service.verify_tokens(
        (issued.grant,),
        base_context.identity,
        base_context.idempotency_key,
    )
    run_context = replace(base_context, confirmation_grants=grants)
    token = bind_run_context(run_context)
    try:
        first = await tool.call(message="订单 101 申请退款")
        second = await tool.call(message="订单 101 申请退款")
    finally:
        reset_run_context(token)

    assert calls == 1
    assert first.state == ToolResultState.RUNNING
    assert second.state == ToolResultState.ERROR
    block = second.content[0]
    assert isinstance(block, TextBlock)
    assert block.text == "tool permission denied: confirmation grant was already used"


async def test_confirmation_argument_mismatch_never_calls_provider() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    settings = configured_settings()
    confirmation_service = ToolConfirmationService(
        JwtToolConfirmationCodec(settings),
        InMemoryConfirmationReplayStore(),
        settings,
    )
    toolset = GovernedToolset(
        settings,
        PlatformClient(settings, httpx.MockTransport(handler)),
        confirmation_consumer=confirmation_service,
    )
    tool = toolset.tools()[0]
    base_context = RunContext(
        identity=TenantIdentity("acme", "alice", frozenset({"agent"})),
        internal_token="internal",
        trace_id="trace",
        idempotency_key="refund-request-42",
    )
    issued = confirmation_service.issue(
        tool.metadata,
        {"message": "订单 101 申请退款"},
        base_context,
    )
    run_context = replace(
        base_context,
        confirmation_grants=confirmation_service.verify_tokens(
            (issued.grant,),
            base_context.identity,
            base_context.idempotency_key,
        ),
    )
    token = bind_run_context(run_context)
    try:
        result = await tool.call(message="订单 999 申请退款")
    finally:
        reset_run_context(token)

    assert calls == 0
    assert result.state == ToolResultState.ERROR


def test_production_write_tools_require_durable_confirmation_replay_store() -> None:
    with pytest.raises(ValidationError, match="AGENT_CONFIRMATION_REPLAY_STORE"):
        configured_settings(app_env="production", agent_confirmation_replay_store="memory")


async def test_redis_replay_store_uses_atomic_set_nx_with_expiry() -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, int, bool]] = []

        async def set(self, key: str, value: str, *, ex: int, nx: bool) -> bool:
            self.calls.append((key, value, ex, nx))
            return len(self.calls) == 1

        async def aclose(self) -> None:
            pass

    fake = FakeRedis()
    store = RedisConfirmationReplayStore("redis://localhost:6379/0", "confirm")
    store._client = fake  # type: ignore[assignment]
    grant = confirmation_grant("refund_start", {"message": "退款"})

    first = await store.consume(grant)
    replay = await store.consume(grant)
    await store.close()

    assert first is True
    assert replay is False
    assert [call[0] for call in fake.calls] == [
        f"confirm:{grant.grant_id}",
        f"confirm:{grant.grant_id}",
    ]
    assert all(call[2] > 0 and call[3] is True for call in fake.calls)


async def test_redis_replay_store_fails_closed_when_backend_is_unavailable() -> None:
    class FailedRedis:
        async def set(self, *args: object, **kwargs: object) -> bool:
            del args, kwargs
            raise ConnectionError("redis password must not leak")

        async def aclose(self) -> None:
            pass

    store = RedisConfirmationReplayStore("redis://localhost:6379/0", "confirm")
    store._client = FailedRedis()  # type: ignore[assignment]

    with pytest.raises(
        ToolConfirmationUnavailableError,
        match="confirmation replay store is unavailable",
    ):
        await store.consume(confirmation_grant("refund_start", {"message": "退款"}))


def test_confirmation_redis_url_is_redacted_from_settings_repr() -> None:
    settings = configured_settings(
        agent_confirmation_replay_store="redis",
        agent_confirmation_redis_url="redis://user:super-secret@redis:6379/0",
    )

    assert "super-secret" not in repr(settings)


@pytest.mark.parametrize(
    ("overrides", "field_name"),
    [
        ({"agent_confirmation_header": "X Agent Grant"}, "agent_confirmation_header"),
        (
            {"agent_confirmation_redis_namespace": "confirm namespace"},
            "agent_confirmation_redis_namespace",
        ),
    ],
)
def test_confirmation_configuration_rejects_unsafe_identifiers(
    overrides: dict[str, object],
    field_name: str,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        configured_settings(**overrides)

    assert field_name in str(exc_info.value)
