from datetime import UTC, datetime

import jwt
import pytest
from pydantic import SecretStr, ValidationError

from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.infrastructure.security.async_task_worker_jwt import (
    AsyncTaskWorkerTokenError,
    AsyncTaskWorkerTokenIssuer,
)

WORKER_SECRET = "test-async-worker-secret-with-at-least-32-bytes"


def context() -> RunContext:
    return RunContext(
        identity=TenantIdentity("acme", "alice", frozenset({"agent"})),
        internal_token="raw-caller-token",
        trace_id="trace-1",
    )


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "async_task_worker_id": "agentscope-orchestrator",
        "async_task_worker_jwt_secret": SecretStr(WORKER_SECRET),
    }
    values.update(overrides)
    return Settings(**values)


def test_worker_token_is_short_lived_and_binds_operation_task_and_worker() -> None:
    configured = settings()
    token = AsyncTaskWorkerTokenIssuer(configured).issue(
        context(),
        worker_id="agentscope-orchestrator",
        action="lease",
        task_id="task-1",
    )

    header = jwt.get_unverified_header(token)
    claims = jwt.decode(
        token,
        WORKER_SECRET,
        algorithms=["HS256"],
        issuer=configured.async_task_worker_jwt_issuer,
        audience=configured.async_task_worker_jwt_audience,
    )

    assert header == {
        "alg": "HS256",
        "kid": configured.async_task_worker_jwt_key_id,
        "typ": "JWT",
    }
    assert claims["sub"] == "agentscope-orchestrator"
    assert claims["tenant"] == "acme"
    assert claims["actor_uid"] == "alice"
    assert claims["worker_id"] == "agentscope-orchestrator"
    assert claims["scopes"] == ["async.task.worker"]
    assert claims["token_use"] == "async_task_worker"
    assert claims["act"] == "lease"
    assert claims["task_id"] == "task-1"
    assert 0 < claims["exp"] - claims["iat"] <= 60
    assert datetime.fromtimestamp(claims["exp"], tz=UTC) > datetime.now(UTC)
    assert "raw-caller-token" not in token


def test_worker_token_allows_unique_instance_owner_under_service_identity() -> None:
    token = AsyncTaskWorkerTokenIssuer(settings()).issue(
        context(),
        worker_id="agentscope-orchestrator.pod-7f3a",
        action="lease",
        task_id="task-1",
    )

    claims = jwt.decode(
        token,
        WORKER_SECRET,
        algorithms=["HS256"],
        issuer="platform-services",
        audience="async-task-worker",
    )
    assert claims["sub"] == "agentscope-orchestrator"
    assert claims["worker_id"] == "agentscope-orchestrator.pod-7f3a"


@pytest.mark.parametrize("action", ["read", "cancel", "admin"])
def test_worker_token_rejects_non_worker_actions(action: str) -> None:
    with pytest.raises(AsyncTaskWorkerTokenError, match="action"):
        AsyncTaskWorkerTokenIssuer(settings()).issue(
            context(),
            worker_id="agentscope-orchestrator",
            action=action,
            task_id="task-1",
        )


def test_worker_token_rejects_worker_id_impersonation() -> None:
    with pytest.raises(AsyncTaskWorkerTokenError, match="worker identity"):
        AsyncTaskWorkerTokenIssuer(settings()).issue(
            context(),
            worker_id="other-worker",
            action="status",
            task_id="task-1",
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"async_task_worker_jwt_secret": SecretStr("")},
            "must contain at least 32 bytes",
        ),
        (
            {"async_task_worker_jwt_secret": SecretStr("too-short")},
            "must contain at least 32 bytes",
        ),
        (
            {
                "internal_jwt_secret": SecretStr(WORKER_SECRET),
                "async_task_worker_jwt_secret": SecretStr(WORKER_SECRET),
            },
            "must not reuse",
        ),
    ],
)
def test_async_worker_configuration_rejects_missing_short_or_reused_secret(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        settings(async_task_enabled=True, **overrides)
