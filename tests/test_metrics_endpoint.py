from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient
from pydantic import SecretStr

from agentscope_platform.api.app import create_app
from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import AgentExecution, RunContext
from agentscope_platform.infrastructure.observability.async_task_metrics import (
    AsyncTaskMetrics,
)

TEST_SECRET = "test-only-internal-secret-with-at-least-32-bytes"


class FakeRunner:
    async def run(self, goal: str, context: RunContext) -> AgentExecution:
        del context
        return AgentExecution(final_answer=goal)


def _settings() -> Settings:
    return Settings(
        internal_auth_required=True,
        internal_jwt_secret=SecretStr(TEST_SECRET),
        gateway_api_key=SecretStr("test-gateway-key"),
    )


def _token() -> str:
    return jwt.encode(
        {
            "sub": "acme",
            "uid": "metrics-scraper",
            "scopes": ["metrics"],
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        TEST_SECRET,
        algorithm="HS256",
    )


def test_metrics_endpoint_requires_internal_authentication() -> None:
    client = TestClient(create_app(_settings(), FakeRunner()))

    response = client.get("/metrics")

    assert response.status_code == 401


def test_metrics_endpoint_exports_low_cardinality_async_metrics() -> None:
    client = TestClient(create_app(_settings(), FakeRunner()))
    metrics = AsyncTaskMetrics()
    metrics.submitted("agent.run")
    metrics.running(1, "agent.run")
    metrics.completed("agent.run", "SUCCEEDED")
    metrics.heartbeat_failed()

    response = client.get(
        "/metrics",
        headers={"X-Internal-Token": _token()},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert 'agent_async_task_submissions_total{kind="agent.run"}' in response.text
    assert (
        'agent_async_task_completions_total{kind="agent.run",status="SUCCEEDED"}' in response.text
    )
    assert 'agent_async_task_running{kind="agent.run"}' in response.text
    assert "agent_async_task_heartbeat_failures_total" in response.text
    for forbidden_label in ("task_id=", "tenant_id=", "prompt=", "result=", "token="):
        assert forbidden_label not in response.text
