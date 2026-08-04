from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr, ValidationError

from agentscope_platform.core.config import Settings
from agentscope_platform.infrastructure.security.internal_jwt import (
    InternalAuthenticationError,
    InternalJwtVerifier,
)

SECRET = "test-only-internal-secret-with-at-least-32-bytes"
ISSUER = "langchain4j-platform"
AUDIENCE = "platform-internal"
KEY_ID = "platform-internal-v1"
TOKEN_USE = "internal_access"


def verifier() -> InternalJwtVerifier:
    return InternalJwtVerifier(
        Settings(
            internal_jwt_algorithm="HS256",
            internal_jwt_secret=SecretStr(SECRET),
        ),
    )


def valid_claims(**overrides: object) -> dict[str, object]:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "iss": ISSUER,
        "aud": [AUDIENCE],
        "sub": "tenant-a",
        "uid": "user-a",
        "scopes": ["agent", "chat"],
        "token_use": TOKEN_USE,
        "jti": "request-123",
        "iat": now,
        "exp": now + timedelta(minutes=1),
    }
    claims.update(overrides)
    return claims


def encode(
    claims: dict[str, object],
    *,
    key_id: str = KEY_ID,
) -> str:
    return jwt.encode(
        claims,
        SECRET,
        algorithm="HS256",
        headers={"kid": key_id, "typ": "JWT"},
    )


def test_verifies_java_compatible_claims() -> None:
    expires_at = datetime.now(UTC) + timedelta(minutes=1)
    token = encode(valid_claims(dept="tenant-a-rd", exp=expires_at))

    identity = verifier().verify(token)

    assert identity.tenant_id == "tenant-a"
    assert identity.user_id == "user-a"
    assert identity.department == "tenant-a-rd"
    assert identity.scopes == frozenset({"agent", "chat"})

    verified = verifier().verify_with_expiry(token)
    assert verified.identity == identity
    assert abs((verified.expires_at - expires_at).total_seconds()) < 1


def test_rejects_expired_token() -> None:
    token = encode(valid_claims(scopes=[], exp=datetime.now(UTC) - timedelta(seconds=10)))

    with pytest.raises(InternalAuthenticationError):
        verifier().verify(token)


@pytest.mark.parametrize(
    ("missing", "override"),
    [
        ("sub", {}),
        ("uid", {}),
        ("iss", {}),
        ("aud", {}),
        ("token_use", {}),
        ("jti", {}),
        ("iat", {}),
        (None, {"scopes": "agent"}),
    ],
)
def test_rejects_invalid_required_claims(
    missing: str | None,
    override: dict[str, object],
) -> None:
    claims = valid_claims(**override)
    if missing:
        claims.pop(missing)
    token = encode(claims)

    with pytest.raises(InternalAuthenticationError):
        verifier().verify(token)


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "other-platform"},
        {"aud": ["workflow-service"]},
        {"aud": [AUDIENCE, "workflow-service"]},
        {"token_use": "service_callback"},
        {"jti": ""},
        {"iat": datetime.now(UTC) - timedelta(minutes=20)},
    ],
)
def test_rejects_wrong_or_unbounded_security_context(overrides: dict[str, object]) -> None:
    with pytest.raises(InternalAuthenticationError):
        verifier().verify(encode(valid_claims(**overrides)))


def test_rejects_wrong_key_id_even_with_valid_signature() -> None:
    with pytest.raises(InternalAuthenticationError, match="invalid internal token"):
        verifier().verify(encode(valid_claims(), key_id="retired-key"))


def test_rs256_verifier_enforces_the_same_strict_claim_contract() -> None:
    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    token = jwt.encode(
        valid_claims(),
        private_pem,
        algorithm="RS256",
        headers={"kid": KEY_ID, "typ": "JWT"},
    )
    strict_verifier = InternalJwtVerifier(
        Settings(
            _env_file=None,
            internal_jwt_algorithm="RS256",
            internal_jwt_public_key=SecretStr(public_pem.decode("utf-8")),
        )
    )

    assert strict_verifier.verify(token).tenant_id == "tenant-a"


def test_internal_jwt_security_identifiers_reject_whitespace_or_unsafe_key_ids() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, internal_jwt_issuer="langchain platform")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, internal_jwt_key_id="../../retired")
