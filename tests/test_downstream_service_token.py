import json
from datetime import UTC, datetime

import jwt
import pytest
from pydantic import SecretStr, ValidationError

from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.infrastructure.security.downstream_jwt import (
    DownstreamServiceTokenError,
    DownstreamServiceTokenIssuer,
)
from tool_confirmation_support import DOWNSTREAM_SECRET


def context() -> RunContext:
    return RunContext(
        identity=TenantIdentity("acme", "alice", frozenset({"agent", "admin"})),
        internal_token="raw-caller-token-must-not-leak",
        trace_id="trace-acme",
        idempotency_key="request-42",
    )


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "agent_downstream_jwt_secret": SecretStr(DOWNSTREAM_SECRET),
    }
    values.update(overrides)
    return Settings(**values)


def test_downstream_token_is_short_lived_audience_and_action_bound_delegation() -> None:
    configured = settings()
    token = DownstreamServiceTokenIssuer(configured).issue(
        context(),
        audience=configured.agent_mcp_audience,
        action="mcp:get_weather",
    )

    header = jwt.get_unverified_header(token)
    claims = jwt.decode(
        token,
        DOWNSTREAM_SECRET,
        algorithms=["HS256"],
        issuer=configured.agent_downstream_jwt_issuer,
        audience=configured.agent_mcp_audience,
    )

    assert header == {
        "alg": "HS256",
        "kid": configured.agent_downstream_jwt_key_id,
        "typ": "JWT",
    }
    assert claims["sub"] == configured.agent_downstream_jwt_subject
    assert claims["tenant"] == "acme"
    assert claims["actor_uid"] == "alice"
    assert claims["scopes"] == ["agent.tool.invoke"]
    assert claims["token_use"] == "agent_downstream"
    assert claims["act"] == "mcp:get_weather"
    assert isinstance(claims["jti"], str) and claims["jti"]
    assert 0 < claims["exp"] - claims["iat"] <= 60
    assert datetime.fromtimestamp(claims["exp"], tz=UTC) > datetime.now(UTC)
    assert "raw-caller-token-must-not-leak" not in token


def test_downstream_token_issuer_rejects_unknown_audience() -> None:
    with pytest.raises(DownstreamServiceTokenError, match="audience"):
        DownstreamServiceTokenIssuer(settings()).issue(
            context(),
            audience="untrusted-provider",
            action="mcp:get_weather",
        )


@pytest.mark.parametrize(
    "feature",
    [
        {
            "agent_mcp_enabled": True,
            "agent_mcp_url": "https://mcp.test/mcp",
            "agent_mcp_tools_json": json.dumps(
                [
                    {
                        "serverId": "safe",
                        "remoteName": "read",
                        "description": "read",
                        "metadata": {
                            "name": "mcp_safe_read",
                            "readOnly": True,
                            "sideEffect": "none",
                            "idempotency": "none",
                            "requiresConfirmation": "never",
                            "requiredScopes": ["agent"],
                            "timeoutSeconds": 5,
                            "retryPolicy": "none",
                        },
                    }
                ]
            ),
        },
        {
            "agent_browser_enabled": True,
            "agent_browser_sandbox_url": "https://browser.test",
            "agent_browser_allowed_hosts_json": '["example.com"]',
        },
        {
            "agent_code_exec_enabled": True,
            "agent_code_sandbox_url": "https://code.test",
        },
    ],
)
def test_external_tool_features_require_separate_downstream_signing_secret(
    feature: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="AGENT_DOWNSTREAM_JWT_SECRET"):
        Settings(
            _env_file=None,
            agent_confirmation_secret=SecretStr("test-confirmation-secret-with-at-least-32-bytes"),
            **feature,
        )


def test_downstream_secret_and_audiences_must_be_independent() -> None:
    mcp_feature = {
        "agent_mcp_enabled": True,
        "agent_mcp_url": "https://mcp.test/mcp",
        "agent_mcp_tools_json": json.dumps(
            [
                {
                    "serverId": "safe",
                    "remoteName": "read",
                    "description": "read",
                    "metadata": {
                        "name": "mcp_safe_read",
                        "readOnly": True,
                        "sideEffect": "none",
                        "idempotency": "none",
                        "requiresConfirmation": "never",
                        "requiredScopes": ["agent"],
                        "timeoutSeconds": 5,
                        "retryPolicy": "none",
                    },
                }
            ]
        ),
    }
    with pytest.raises(ValidationError, match="must not reuse"):
        Settings(
            _env_file=None,
            internal_jwt_secret=SecretStr(DOWNSTREAM_SECRET),
            agent_downstream_jwt_secret=SecretStr(DOWNSTREAM_SECRET),
            **mcp_feature,
        )
    with pytest.raises(ValidationError, match="audiences must be distinct"):
        Settings(
            _env_file=None,
            agent_downstream_jwt_secret=SecretStr(DOWNSTREAM_SECRET),
            agent_mcp_audience="same-provider",
            agent_browser_audience="same-provider",
            **mcp_feature,
        )
