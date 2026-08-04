import httpx
import pytest
from pydantic import SecretStr

from agentscope_platform.application.confirmation import ToolConfirmationService
from agentscope_platform.core.config import Settings
from agentscope_platform.infrastructure.http.readiness import (
    HttpDependencyReadinessProbe,
)
from agentscope_platform.infrastructure.security.tool_confirmation import (
    InMemoryConfirmationReplayStore,
    JwtToolConfirmationCodec,
)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "gateway_base_url": "http://model.internal/v1",
        "gateway_api_key": SecretStr("test-gateway-key"),
        "knowledge_base_url": "http://knowledge.internal",
        "analytics_base_url": "http://analytics.internal",
        "workflow_base_url": "http://workflow.internal",
        "order_base_url": "http://order.internal",
        "async_task_enabled": True,
        "async_task_base_url": "http://async.internal",
        "async_task_worker_id": "agentscope-platform",
        "async_task_worker_jwt_secret": SecretStr("async-worker-secret-with-at-least-32-bytes"),
    }
    values.update(overrides)
    return Settings(**values)


def _confirmation_service(settings: Settings) -> ToolConfirmationService:
    return ToolConfirmationService(
        JwtToolConfirmationCodec(settings),
        InMemoryConfirmationReplayStore(),
        settings,
    )


@pytest.mark.anyio
async def test_probe_distinguishes_required_and_optional_dependencies() -> None:
    settings = _settings()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path in {
            "/health/liveliness",
            "/actuator/health/readiness",
        }
        statuses = {
            "model.internal": 200,
            "async.internal": 503,
            "knowledge.internal": 503,
            "workflow.internal": 404,
        }
        return httpx.Response(statuses.get(request.url.host, 200))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    probe = HttpDependencyReadinessProbe(
        settings,
        _confirmation_service(settings),
        client,
    )

    checks = {check.name: check for check in await probe.check()}

    assert checks["modelGateway"].status == "UP"
    assert checks["modelGateway"].required is True
    assert checks["asyncTask"].status == "DOWN"
    assert checks["asyncTask"].required is True
    assert checks["knowledgeService"].status == "DOWN"
    assert checks["knowledgeService"].required is False
    assert checks["workflowService"].status == "DOWN"
    assert checks["confirmationReplayStore"].status == "DISABLED"
    await client.aclose()


@pytest.mark.anyio
async def test_probe_maps_transport_failures_to_sanitized_down_status() -> None:
    settings = _settings(async_task_enabled=False)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "model.internal":
            raise httpx.ConnectError("secret upstream address", request=request)
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    probe = HttpDependencyReadinessProbe(
        settings,
        _confirmation_service(settings),
        client,
    )

    checks = {check.name: check for check in await probe.check()}

    assert checks["modelGateway"].status == "DOWN"
    assert checks["asyncTask"].status == "DISABLED"
    assert {check.status for check in checks.values()} <= {"UP", "DOWN", "DISABLED"}
    await client.aclose()
