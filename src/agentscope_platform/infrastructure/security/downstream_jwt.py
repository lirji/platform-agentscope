from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt

from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import RunContext
from agentscope_platform.domain.security import DownstreamServiceTokenClaims


class DownstreamServiceTokenError(RuntimeError):
    """A scoped provider delegation token cannot be issued safely."""


class DownstreamServiceTokenIssuer:
    """Mint request-scoped provider credentials without forwarding the caller JWT."""

    def __init__(self, settings: Settings) -> None:
        self._secret = settings.agent_downstream_jwt_secret.get_secret_value()
        self._issuer = settings.agent_downstream_jwt_issuer
        self._subject = settings.agent_downstream_jwt_subject
        self._key_id = settings.agent_downstream_jwt_key_id
        self._ttl = timedelta(seconds=settings.agent_downstream_jwt_ttl_seconds)
        self._allowed_audiences = frozenset(
            {
                settings.agent_mcp_audience,
                settings.agent_browser_audience,
                settings.agent_code_audience,
            }
        )

    def issue(self, context: RunContext, *, audience: str, action: str) -> str:
        if len(self._secret.encode("utf-8")) < 32:
            raise DownstreamServiceTokenError("downstream service token signing key is unavailable")
        if audience not in self._allowed_audiences:
            raise DownstreamServiceTokenError("downstream service token audience is not allowed")
        if not action or len(action) > 256:
            raise DownstreamServiceTokenError("downstream service token action is invalid")

        now = datetime.now(UTC)
        try:
            claims = DownstreamServiceTokenClaims(
                iss=self._issuer,
                aud=audience,
                sub=self._subject,
                tenant=context.identity.tenant_id,
                actor_uid=context.identity.user_id,
                scopes=("agent.tool.invoke",),
                token_use="agent_downstream",
                act=action,
                jti=str(uuid4()),
                iat=int(now.timestamp()),
                exp=int((now + self._ttl).timestamp()),
            )
            return jwt.encode(
                claims.model_dump(mode="json"),
                self._secret,
                algorithm="HS256",
                headers={"kid": self._key_id, "typ": "JWT"},
            )
        except Exception as exc:
            raise DownstreamServiceTokenError("downstream service token signing failed") from exc
