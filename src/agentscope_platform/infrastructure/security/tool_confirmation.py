import asyncio
import math
import re
from datetime import UTC, datetime
from typing import Any

import jwt
from jwt import InvalidTokenError as JwtInvalidTokenError
from redis.asyncio import Redis

from agentscope_platform.application.confirmation import (
    ToolConfirmationError,
    ToolConfirmationUnavailableError,
)
from agentscope_platform.application.ports import ConfirmationReplayStore
from agentscope_platform.core.config import Settings
from agentscope_platform.domain.confirmation import ToolConfirmationGrant

_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_USE = "tool_confirmation"


class JwtToolConfirmationCodec:
    def __init__(self, settings: Settings) -> None:
        self._secret = settings.agent_confirmation_secret.get_secret_value()
        self._issuer = settings.agent_confirmation_issuer
        self._audience = settings.agent_confirmation_audience
        self._key_id = settings.agent_confirmation_key_id
        self._ttl_seconds = settings.agent_confirmation_ttl_seconds
        self._leeway_seconds = settings.agent_confirmation_clock_skew_seconds

    def encode(self, grant: ToolConfirmationGrant) -> str:
        if len(self._secret.encode("utf-8")) < 32:
            raise ToolConfirmationUnavailableError(
                "AGENT_CONFIRMATION_SECRET must contain at least 32 bytes"
            )
        return jwt.encode(
            {
                "iss": self._issuer,
                "aud": self._audience,
                "sub": grant.tenant_id,
                "uid": grant.user_id,
                "tool": grant.tool_name,
                "args_sha256": grant.arguments_sha256,
                "idem": grant.idempotency_key,
                "token_use": _TOKEN_USE,
                "jti": grant.grant_id,
                "iat": grant.issued_at,
                "exp": grant.expires_at,
            },
            self._secret,
            algorithm="HS256",
            headers={"kid": self._key_id, "typ": "JWT"},
        )

    def decode(self, token: str) -> ToolConfirmationGrant:
        if not token or len(token) > 8_192 or len(self._secret.encode("utf-8")) < 32:
            raise ToolConfirmationError("invalid tool confirmation grant")
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "HS256" or header.get("kid") != self._key_id:
                raise ToolConfirmationError("invalid tool confirmation grant header")
            claims: dict[str, Any] = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway_seconds,
                options={
                    "require": [
                        "iss",
                        "aud",
                        "sub",
                        "uid",
                        "tool",
                        "args_sha256",
                        "idem",
                        "token_use",
                        "jti",
                        "iat",
                        "exp",
                    ]
                },
            )
        except (JwtInvalidTokenError, ValueError, TypeError) as exc:
            raise ToolConfirmationError("invalid tool confirmation grant") from exc

        issued_at = self._timestamp(claims.get("iat"))
        expires_at = self._timestamp(claims.get("exp"))
        tenant_id = claims.get("sub")
        user_id = claims.get("uid")
        tool_name = claims.get("tool")
        arguments_sha256 = claims.get("args_sha256")
        idempotency_key = claims.get("idem")
        grant_id = claims.get("jti")
        if (
            claims.get("token_use") != _TOKEN_USE
            or not isinstance(tenant_id, str)
            or not isinstance(user_id, str)
            or not isinstance(tool_name, str)
            or _TOOL_NAME.fullmatch(tool_name) is None
            or not isinstance(arguments_sha256, str)
            or _SHA256.fullmatch(arguments_sha256) is None
            or not isinstance(idempotency_key, str)
            or not isinstance(grant_id, str)
            or expires_at <= issued_at
            or (expires_at - issued_at).total_seconds() > self._ttl_seconds + self._leeway_seconds
        ):
            raise ToolConfirmationError("invalid tool confirmation grant claims")
        try:
            return ToolConfirmationGrant(
                grant_id=grant_id,
                tenant_id=tenant_id,
                user_id=user_id,
                tool_name=tool_name,
                arguments_sha256=arguments_sha256,
                idempotency_key=idempotency_key,
                issued_at=issued_at,
                expires_at=expires_at,
            )
        except ValueError as exc:
            raise ToolConfirmationError("invalid tool confirmation grant claims") from exc

    @staticmethod
    def _timestamp(value: object) -> datetime:
        if not isinstance(value, (int, float)):
            raise ToolConfirmationError("invalid tool confirmation timestamp")
        return datetime.fromtimestamp(value, tz=UTC)


class InMemoryConfirmationReplayStore(ConfirmationReplayStore):
    """Single-process replay store for local development and deterministic tests."""

    def __init__(self) -> None:
        self._used: dict[str, datetime] = {}
        self._lock = asyncio.Lock()

    async def consume(self, grant: ToolConfirmationGrant) -> bool:
        now = datetime.now(UTC)
        async with self._lock:
            self._used = {
                grant_id: expires_at
                for grant_id, expires_at in self._used.items()
                if expires_at > now
            }
            if grant.grant_id in self._used:
                return False
            self._used[grant.grant_id] = grant.expires_at
            return True

    async def ready(self, timeout_seconds: float) -> bool:
        del timeout_seconds
        return True

    async def close(self) -> None:
        self._used.clear()


class RedisConfirmationReplayStore(ConfirmationReplayStore):
    def __init__(self, redis_url: str, namespace: str) -> None:
        self._client = Redis.from_url(redis_url, decode_responses=True)
        self._namespace = namespace

    async def consume(self, grant: ToolConfirmationGrant) -> bool:
        ttl = math.ceil((grant.expires_at - datetime.now(UTC)).total_seconds())
        if ttl <= 0:
            return False
        try:
            created = await self._client.set(
                f"{self._namespace}:{grant.grant_id}",
                "1",
                ex=ttl,
                nx=True,
            )
        except Exception as exc:
            raise ToolConfirmationUnavailableError(
                "confirmation replay store is unavailable"
            ) from exc
        return bool(created)

    async def ready(self, timeout_seconds: float) -> bool:
        try:
            return bool(
                await asyncio.wait_for(
                    self._client.ping(),
                    timeout=timeout_seconds,
                )
            )
        except Exception:
            return False

    async def close(self) -> None:
        await self._client.aclose()


def build_confirmation_replay_store(settings: Settings) -> ConfirmationReplayStore:
    if settings.agent_confirmation_replay_store == "redis":
        return RedisConfirmationReplayStore(
            settings.agent_confirmation_redis_url.get_secret_value(),
            settings.agent_confirmation_redis_namespace,
        )
    return InMemoryConfirmationReplayStore()
