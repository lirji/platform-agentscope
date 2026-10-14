import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from agentscope_platform.api.app import create_app
from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import AgentExecution, RunContext


class CapturingRunner:
    def __init__(self) -> None:
        self.context: RunContext | None = None

    async def run(self, goal: str, context: RunContext) -> AgentExecution:
        self.context = context
        return AgentExecution(final_answer=goal)


def production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "app_env": "production",
        "agent_session_store": "redis",
        "agent_session_redis_url": SecretStr("rediss://redis.internal/0"),
        "internal_jwt_secret": SecretStr("test-only-internal-secret-with-at-least-32-bytes"),
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize("app_env", ["production", "prod", " Production "])
def test_production_rejects_disabled_internal_authentication(app_env: str) -> None:
    with pytest.raises(ValidationError, match="INTERNAL_AUTH_REQUIRED must be true in production"):
        production_settings(app_env=app_env, internal_auth_required=False)


def test_production_with_internal_authentication_is_unchanged() -> None:
    configured = production_settings()

    assert configured.internal_auth_required is True


def test_non_production_may_still_disable_internal_authentication() -> None:
    runner = CapturingRunner()
    configured = Settings(_env_file=None, app_env="local", internal_auth_required=False)
    client = TestClient(create_app(configured, runner))

    response = client.post("/agent/run", json={"goal": "hello"})

    assert response.status_code == 200
    assert runner.context is not None
    assert runner.context.identity.tenant_id == "anonymous"


def test_production_rejects_unauthenticated_business_requests() -> None:
    client = TestClient(create_app(production_settings(), CapturingRunner()))

    response = client.post("/agent/run", json={"goal": "hello"})

    assert response.status_code == 401
