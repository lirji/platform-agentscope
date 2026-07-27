from pathlib import Path
from typing import Any

import jwt
from jwt import InvalidTokenError as JwtInvalidTokenError

from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import TenantIdentity


class InternalAuthenticationError(ValueError):
    pass


class InternalJwtVerifier:
    def __init__(self, settings: Settings) -> None:
        self._algorithm = settings.internal_jwt_algorithm
        self._key = self._resolve_key(settings)

    def verify(self, token: str) -> TenantIdentity:
        if not token:
            raise InternalAuthenticationError("internal token is required")
        if not self._key:
            raise InternalAuthenticationError("internal JWT verification key is not configured")

        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                self._key,
                algorithms=[self._algorithm],
                options={"require": ["sub", "exp"]},
            )
        except JwtInvalidTokenError as exc:
            raise InternalAuthenticationError("invalid internal token") from exc

        subject = claims.get("sub")
        user_id = claims.get("uid")
        raw_scopes = claims.get("scopes", [])
        department = claims.get("dept")

        if not isinstance(subject, str) or not subject:
            raise InternalAuthenticationError("internal token subject is invalid")
        if not isinstance(user_id, str) or not user_id:
            raise InternalAuthenticationError("internal token uid is invalid")
        valid_scopes = isinstance(raw_scopes, list) and all(
            isinstance(item, str) for item in raw_scopes
        )
        if not valid_scopes:
            raise InternalAuthenticationError("internal token scopes are invalid")
        if department is not None and not isinstance(department, str):
            raise InternalAuthenticationError("internal token dept is invalid")

        return TenantIdentity(
            tenant_id=subject,
            user_id=user_id,
            scopes=frozenset(raw_scopes),
            department=department,
        )

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
