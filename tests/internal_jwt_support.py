from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt

INTERNAL_JWT_ISSUER = "langchain4j-platform"
INTERNAL_JWT_AUDIENCE = "platform-internal"
INTERNAL_JWT_KEY_ID = "platform-internal-v1"


def signed_internal_token(
    secret: str,
    *,
    tenant: str = "acme",
    user: str = "alice",
    scopes: tuple[str, ...] = ("agent",),
    department: str | None = None,
    signing_secret: str | None = None,
    expires_at: datetime | None = None,
) -> str:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "iss": INTERNAL_JWT_ISSUER,
        "aud": [INTERNAL_JWT_AUDIENCE],
        "sub": tenant,
        "uid": user,
        "scopes": list(scopes),
        "token_use": "internal_access",
        "jti": str(uuid4()),
        "iat": now,
        "exp": expires_at or now + timedelta(minutes=5),
    }
    if department:
        claims["dept"] = department
    return jwt.encode(
        claims,
        signing_secret or secret,
        algorithm="HS256",
        headers={"kid": INTERNAL_JWT_KEY_ID, "typ": "JWT"},
    )
