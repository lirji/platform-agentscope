from datetime import UTC, datetime, timedelta

from agentscope_platform.domain.confirmation import (
    ToolConfirmationGrant,
    canonical_tool_arguments_hash,
)

CONFIRMATION_SECRET = "test-only-confirmation-secret-at-least-32-bytes"
DOWNSTREAM_SECRET = "test-only-downstream-secret-at-least-32-bytes"


def confirmation_grant(
    tool_name: str,
    arguments: dict[str, object],
    *,
    tenant: str = "acme",
    user: str = "alice",
    idempotency_key: str = "request-42",
    grant_id: str | None = None,
) -> ToolConfirmationGrant:
    now = datetime.now(UTC)
    return ToolConfirmationGrant(
        grant_id=grant_id or f"grant-{tool_name}-{canonical_tool_arguments_hash(arguments)[:12]}",
        tenant_id=tenant,
        user_id=user,
        tool_name=tool_name,
        arguments_sha256=canonical_tool_arguments_hash(arguments),
        idempotency_key=idempotency_key,
        issued_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(minutes=2),
    )


class PassingConfirmationConsumer:
    def __init__(self) -> None:
        self.consumed: list[ToolConfirmationGrant] = []

    async def consume(self, grant: ToolConfirmationGrant) -> bool:
        self.consumed.append(grant)
        return True
