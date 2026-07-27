from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient
from pydantic import SecretStr

from agentscope_platform.api.app import create_app
from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import AgentExecution, RunContext

TEST_SECRET = "test-only-internal-secret-with-at-least-32-bytes"


class FakeRunner:
    def __init__(self) -> None:
        self.context: RunContext | None = None

    async def run(self, goal: str, context: RunContext) -> AgentExecution:
        self.context = context
        return AgentExecution(final_answer=f"completed: {goal}")


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "internal_auth_required": True,
        "internal_jwt_algorithm": "HS256",
        "internal_jwt_secret": SecretStr(TEST_SECRET),
        "gateway_api_key": SecretStr("test-gateway-key"),
    }
    values.update(overrides)
    return Settings(**values)


def internal_token(**overrides: object) -> str:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "sub": "acme",
        "uid": "alice",
        "scopes": ["chat", "agent"],
        "dept": "acme_rd",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, TEST_SECRET, algorithm="HS256")


def test_health_is_open_and_returns_trace_id() -> None:
    client = TestClient(create_app(settings(), FakeRunner()))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "UP"}
    assert response.headers["X-Trace-Id"]


def test_agent_run_requires_internal_token() -> None:
    client = TestClient(create_app(settings(), FakeRunner()))

    response = client.post("/agent/run", json={"goal": "test"})

    assert response.status_code == 401
    assert response.json()["detail"] == "valid internal authentication is required"


def test_agent_run_preserves_legacy_contract_and_tenant() -> None:
    runner = FakeRunner()
    client = TestClient(create_app(settings(), runner))

    response = client.post(
        "/agent/run",
        json={"goal": " search docs ", "webhookUrl": None},
        headers={
            "X-Internal-Token": internal_token(),
            "X-Trace-Id": "trace-123",
        },
    )

    assert response.status_code == 200
    assert response.headers["X-Trace-Id"] == "trace-123"
    assert response.json() == {
        "goal": "search docs",
        "steps": [],
        "finalAnswer": "completed: search docs",
        "stopReason": "DONE",
        "depth": 0,
        "tenantId": "acme",
    }
    assert runner.context is not None
    assert runner.context.identity.user_id == "alice"
    assert runner.context.identity.department == "acme_rd"
    assert runner.context.identity.scopes == frozenset({"chat", "agent"})
    assert runner.context.trace_id == "trace-123"


def test_agent_run_rejects_forged_token() -> None:
    client = TestClient(create_app(settings(), FakeRunner()))
    forged = jwt.encode(
        {
            "sub": "acme",
            "uid": "mallory",
            "scopes": ["agent"],
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        "another-test-secret-with-at-least-32-bytes",
        algorithm="HS256",
    )

    response = client.post(
        "/agent/run",
        json={"goal": "test"},
        headers={"X-Internal-Token": forged},
    )

    assert response.status_code == 401


def test_readiness_reports_missing_model_configuration() -> None:
    app_settings = settings(gateway_api_key=SecretStr(""))
    client = TestClient(create_app(app_settings, FakeRunner()))

    response = client.get("/readiness")

    assert response.status_code == 503
    assert response.json()["status"] == "DEGRADED"
    assert response.json()["checks"]["modelConfiguration"] == "MISSING_GATEWAY_API_KEY"


def test_local_auth_can_be_explicitly_disabled() -> None:
    runner = FakeRunner()
    client = TestClient(
        create_app(
            settings(internal_auth_required=False),
            runner,
        ),
    )

    response = client.post("/agent/run", json={"goal": "local test"})

    assert response.status_code == 200
    assert response.json()["tenantId"] == "anonymous"
