import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from agentscope_platform.api.app import create_app
from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import AgentExecution, RunContext
from internal_jwt_support import signed_internal_token

TEST_SECRET = "test-only-internal-secret-with-at-least-32-bytes"
SESSION_ID = "sess-55555555555555555555555555555555"


class FakeResumableRunner:
    async def run(self, goal: str, context: RunContext) -> AgentExecution:
        del goal, context
        return AgentExecution(final_answer="done")

    async def run_from_checkpoint(self, goal, checkpoint, context, progress):  # type: ignore[no-untyped-def]
        del goal, checkpoint, context
        execution = AgentExecution(final_answer="done")
        await progress(execution.steps, False)
        return execution


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "gateway_api_key": SecretStr("test-key"),
        "internal_jwt_secret": SecretStr(TEST_SECRET),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def token(tenant: str = "acme", user: str = "alice") -> str:
    return signed_internal_token(TEST_SECRET, tenant=tenant, user=user)


def test_session_api_requires_auth_and_returns_no_raw_goal_or_identity_token() -> None:
    client = TestClient(create_app(settings(), FakeResumableRunner()))
    missing = client.post(f"/agent/sessions/{SESSION_ID}/run", json={"goal": "secret goal"})
    created = client.post(
        f"/agent/sessions/{SESSION_ID}/run",
        json={"goal": "secret goal"},
        headers={"X-Internal-Token": token()},
    )
    loaded = client.get(
        f"/agent/sessions/{SESSION_ID}",
        headers={"X-Internal-Token": token()},
    )

    assert missing.status_code == 401
    assert created.status_code == 200
    assert loaded.status_code == 200
    serialized = created.text
    assert "secret goal" not in serialized
    assert "X-Internal-Token" not in serialized
    assert created.json()["status"] == "SUCCEEDED"
    assert loaded.json() == created.json()


def test_session_api_hides_cross_tenant_records_and_rejects_invalid_id() -> None:
    client = TestClient(create_app(settings(), FakeResumableRunner()))
    client.post(
        f"/agent/sessions/{SESSION_ID}/run",
        json={"goal": "goal"},
        headers={"X-Internal-Token": token()},
    )

    cross_tenant = client.get(
        f"/agent/sessions/{SESSION_ID}",
        headers={"X-Internal-Token": token(tenant="other")},
    )
    invalid = client.get(
        "/agent/sessions/..%2Ftenant-bypass",
        headers={"X-Internal-Token": token()},
    )

    assert cross_tenant.status_code == 404
    assert invalid.status_code in {404, 422}


def test_production_requires_a_durable_session_store() -> None:
    with pytest.raises(ValidationError, match="AGENT_SESSION_STORE must be redis"):
        settings(app_env="production", agent_session_store="memory")

    configured = settings(
        app_env="production",
        agent_session_store="redis",
        agent_session_redis_url=SecretStr("rediss://redis.internal/0"),
    )
    assert configured.agent_session_store == "redis"
