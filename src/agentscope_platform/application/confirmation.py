from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from agentscope_platform.application.ports import (
    ConfirmationReplayStore,
    ToolConfirmationTokenCodec,
)
from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.domain.confirmation import (
    ToolConfirmationGrant,
    ToolConfirmationReply,
    canonical_tool_arguments_hash,
)
from agentscope_platform.domain.tool import (
    ConfirmationRequirement,
    IdempotencyStrategy,
    ToolMetadata,
)


class ToolConfirmationError(ValueError):
    """A malformed, forged, expired, or context-mismatched confirmation grant."""


class ToolConfirmationDeniedError(PermissionError):
    """The caller is authenticated but cannot request this tool confirmation."""


class ToolConfirmationUnavailableError(RuntimeError):
    """Confirmation signing or durable replay protection is unavailable."""


class ToolConfirmationService:
    def __init__(
        self,
        codec: ToolConfirmationTokenCodec,
        replay_store: ConfirmationReplayStore,
        settings: Settings,
    ) -> None:
        self._codec = codec
        self._replay_store = replay_store
        self._ttl = timedelta(seconds=settings.agent_confirmation_ttl_seconds)
        self._max_grants = settings.agent_confirmation_max_grants

    def issue(
        self,
        metadata: ToolMetadata,
        arguments: Mapping[str, Any],
        context: RunContext,
    ) -> ToolConfirmationReply:
        if (
            metadata.read_only
            or metadata.requires_confirmation is not ConfirmationRequirement.ALWAYS
        ):
            raise ToolConfirmationDeniedError("tool does not accept explicit confirmation grants")
        missing_scopes = set(metadata.required_scopes) - set(context.identity.scopes)
        if missing_scopes:
            raise ToolConfirmationDeniedError("required tool scope is missing")
        if metadata.idempotency is not IdempotencyStrategy.NONE and not context.idempotency_key:
            raise ToolConfirmationDeniedError("idempotency key is required")

        now = datetime.now(UTC)
        grant = ToolConfirmationGrant(
            grant_id=str(uuid4()),
            tenant_id=context.identity.tenant_id,
            user_id=context.identity.user_id,
            tool_name=metadata.name,
            arguments_sha256=canonical_tool_arguments_hash(arguments),
            idempotency_key=context.idempotency_key or "",
            issued_at=now,
            expires_at=now + self._ttl,
        )
        try:
            token = self._codec.encode(grant)
        except Exception as exc:
            if isinstance(exc, ToolConfirmationUnavailableError):
                raise
            raise ToolConfirmationUnavailableError(
                "tool confirmation signing is unavailable"
            ) from exc
        return ToolConfirmationReply(
            grant=token,
            grantId=grant.grant_id,
            toolName=grant.tool_name,
            argumentsSha256=grant.arguments_sha256,
            expiresAt=grant.expires_at,
        )

    def verify_tokens(
        self,
        tokens: Sequence[str],
        identity: TenantIdentity,
        idempotency_key: str | None,
    ) -> tuple[ToolConfirmationGrant, ...]:
        if len(tokens) > self._max_grants:
            raise ToolConfirmationError("too many tool confirmation grants")
        grants: list[ToolConfirmationGrant] = []
        try:
            for token in tokens:
                grant = self._codec.decode(token)
                if (
                    grant.tenant_id != identity.tenant_id
                    or grant.user_id != identity.user_id
                    or grant.idempotency_key != idempotency_key
                    or grant.expired
                ):
                    raise ToolConfirmationError("confirmation context does not match")
                grants.append(grant)
        except ToolConfirmationError:
            raise
        except Exception as exc:
            raise ToolConfirmationError("invalid tool confirmation grant") from exc
        if len({grant.grant_id for grant in grants}) != len(grants):
            raise ToolConfirmationError("duplicate tool confirmation grant")
        return tuple(grants)

    async def consume(self, grant: ToolConfirmationGrant) -> bool:
        if grant.expired:
            return False
        try:
            return await self._replay_store.consume(grant)
        except Exception as exc:
            if isinstance(exc, ToolConfirmationUnavailableError):
                raise
            raise ToolConfirmationUnavailableError(
                "tool confirmation replay protection is unavailable"
            ) from exc

    async def ready(self, timeout_seconds: float) -> bool:
        try:
            return await self._replay_store.ready(timeout_seconds)
        except Exception:
            return False

    async def close(self) -> None:
        await self._replay_store.close()
