from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jwt
from jwt import InvalidTokenError as JwtInvalidTokenError

from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import TenantIdentity


class InternalAuthenticationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class VerifiedInternalIdentity:
    identity: TenantIdentity
    expires_at: datetime


class InternalJwtVerifier:
    def __init__(self, settings: Settings) -> None:
        self._algorithm = settings.internal_jwt_algorithm
        self._key = self._resolve_key(settings)
        self._issuer = settings.internal_jwt_issuer
        self._audience = settings.internal_jwt_audience
        self._key_id = settings.internal_jwt_key_id
        self._token_use = settings.internal_jwt_token_use
        self._leeway_seconds = settings.internal_jwt_clock_skew_seconds
        self._max_ttl_seconds = settings.internal_jwt_max_ttl_seconds

    def verify(self, token: str) -> TenantIdentity:
        return self.verify_with_expiry(token).identity

    def verify_with_expiry(self, token: str) -> VerifiedInternalIdentity:
        if not token or len(token) > 8_192:
            raise InternalAuthenticationError("internal token is required")
        if not self._key:
            raise InternalAuthenticationError("internal JWT verification key is not configured")

        try:
            header = jwt.get_unverified_header(token)
            if (
                header.get("alg") != self._algorithm
                or header.get("kid") != self._key_id
                or header.get("typ") != "JWT"
            ):
                raise InternalAuthenticationError("invalid internal token header")
            claims: dict[str, Any] = jwt.decode(
                token,
                self._key,
                algorithms=[self._algorithm],
                issuer=self._issuer,
                audience=self._audience,
                leeway=self._leeway_seconds,
                options={
                    "require": [
                        "iss",
                        "aud",
                        "sub",
                        "uid",
                        "scopes",
                        "token_use",
                        "jti",
                        "iat",
                        "exp",
                    ]
                },
            )
        except (JwtInvalidTokenError, ValueError, TypeError) as exc:
            raise InternalAuthenticationError("invalid internal token") from exc

        subject = claims.get("sub")
        user_id = claims.get("uid")
        raw_scopes = claims.get("scopes", [])
        department = claims.get("dept")
        raw_audience = claims.get("aud")
        token_use = claims.get("token_use")
        token_id = claims.get("jti")

        if not isinstance(subject, str) or not subject or len(subject) > 256:
            raise InternalAuthenticationError("internal token subject is invalid")
        if not isinstance(user_id, str) or not user_id or len(user_id) > 256:
            raise InternalAuthenticationError("internal token uid is invalid")
        valid_scopes = (
            isinstance(raw_scopes, list)
            and len(raw_scopes) <= 64
            and all(isinstance(item, str) and 0 < len(item) <= 128 for item in raw_scopes)
            and len(set(raw_scopes)) == len(raw_scopes)
        )
        if not valid_scopes:
            raise InternalAuthenticationError("internal token scopes are invalid")
        if department is not None and (
            not isinstance(department, str) or not department or len(department) > 256
        ):
            raise InternalAuthenticationError("internal token dept is invalid")
        if raw_audience not in (self._audience, [self._audience]):
            raise InternalAuthenticationError("internal token audience is invalid")
        if token_use != self._token_use:
            raise InternalAuthenticationError("internal token use is invalid")
        if not isinstance(token_id, str) or not token_id or len(token_id) > 128:
            raise InternalAuthenticationError("internal token id is invalid")

        issued_at = self._timestamp(claims.get("iat"), "iat")
        expires_at = self._timestamp(claims.get("exp"), "exp")
        if (
            expires_at <= issued_at
            or (expires_at - issued_at).total_seconds()
            > self._max_ttl_seconds + self._leeway_seconds
        ):
            raise InternalAuthenticationError("internal token lifetime is invalid")

        return VerifiedInternalIdentity(
            identity=TenantIdentity(
                tenant_id=subject,
                user_id=user_id,
                scopes=frozenset(raw_scopes),
                department=department,
            ),
            expires_at=expires_at,
        )

    @staticmethod
    def _timestamp(value: object, claim: str) -> datetime:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InternalAuthenticationError(f"internal token {claim} is invalid")
        try:
            return datetime.fromtimestamp(value, tz=UTC)
        except (OverflowError, OSError, ValueError) as exc:
            raise InternalAuthenticationError(f"internal token {claim} is invalid") from exc

    @staticmethod
    def _resolve_key(settings: Settings) -> str:
        if settings.internal_jwt_algorithm == "HS256":
            return settings.internal_jwt_secret.get_secret_value()

        inline = settings.internal_jwt_public_key.get_secret_value()
        if inline:
            return inline.replace("\\n", "\n")

        key_file: Path | None = settings.internal_jwt_public_key_file
        if key_file is not None:
            try:
                return key_file.read_text(encoding="utf-8")
            except OSError as exc:
                raise ValueError(f"cannot read internal JWT public key file: {key_file}") from exc
        return ""
