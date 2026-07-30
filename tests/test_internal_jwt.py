from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import SecretStr

from agentscope_platform.core.config import Settings
from agentscope_platform.infrastructure.security.internal_jwt import (
    InternalAuthenticationError,
    InternalJwtVerifier,
)

SECRET = "test-only-internal-secret-with-at-least-32-bytes"


def verifier() -> InternalJwtVerifier:
    return InternalJwtVerifier(
        Settings(
            internal_jwt_algorithm="HS256",
            internal_jwt_secret=SecretStr(SECRET),
        ),
    )


def encode(claims: dict[str, object]) -> str:
    return jwt.encode(claims, SECRET, algorithm="HS256")


def test_verifies_java_compatible_claims() -> None:
    expires_at = datetime.now(UTC) + timedelta(minutes=1)
    token = encode(
        {
            "sub": "tenant-a",
            "uid": "user-a",
            "scopes": ["agent", "chat"],
            "dept": "tenant-a-rd",
            "exp": expires_at,
        },
    )

    identity = verifier().verify(token)

    assert identity.tenant_id == "tenant-a"
    assert identity.user_id == "user-a"
    assert identity.department == "tenant-a-rd"
    assert identity.scopes == frozenset({"agent", "chat"})

    verified = verifier().verify_with_expiry(token)
    assert verified.identity == identity
    assert abs((verified.expires_at - expires_at).total_seconds()) < 1


def test_rejects_expired_token() -> None:
    token = encode(
        {
            "sub": "tenant-a",
            "uid": "user-a",
            "scopes": [],
            "exp": datetime.now(UTC) - timedelta(seconds=1),
        },
    )

    with pytest.raises(InternalAuthenticationError, match="invalid internal token"):
        verifier().verify(token)


@pytest.mark.parametrize(
    "claims",
    [
        {"uid": "user-a", "scopes": [], "exp": 4_102_444_800},
        {"sub": "tenant-a", "scopes": [], "exp": 4_102_444_800},
        {"sub": "tenant-a", "uid": "user-a", "scopes": "agent", "exp": 4_102_444_800},
    ],
)
def test_rejects_invalid_required_claims(claims: dict[str, object]) -> None:
    token = encode(claims)

    with pytest.raises(InternalAuthenticationError):
        verifier().verify(token)
