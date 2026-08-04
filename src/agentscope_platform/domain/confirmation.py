import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue

MAX_CONFIRMATION_ARGUMENT_BYTES = 65_536
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def canonical_tool_arguments(arguments: Mapping[str, Any]) -> bytes:
    """Return the deterministic JSON bytes covered by a confirmation grant."""
    try:
        encoded = json.dumps(
            dict(arguments),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("tool arguments must be finite JSON values") from exc
    if len(encoded) > MAX_CONFIRMATION_ARGUMENT_BYTES:
        raise ValueError(f"canonical tool arguments exceed {MAX_CONFIRMATION_ARGUMENT_BYTES} bytes")
    return encoded


def canonical_tool_arguments_hash(arguments: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_tool_arguments(arguments)).hexdigest()


@dataclass(frozen=True, slots=True)
class ToolConfirmationGrant:
    grant_id: str
    tenant_id: str
    user_id: str
    tool_name: str
    arguments_sha256: str
    idempotency_key: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.grant_id or len(self.grant_id) > 128:
            raise ValueError("confirmation grant id is invalid")
        if not self.tenant_id or not self.user_id or not self.tool_name:
            raise ValueError("confirmation grant identity or tool is invalid")
        if _SHA256.fullmatch(self.arguments_sha256) is None:
            raise ValueError("confirmation argument digest is invalid")
        if not self.idempotency_key:
            raise ValueError("confirmation idempotency key is required")
        if self.issued_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("confirmation timestamps must be timezone-aware")
        if self.expires_at <= self.issued_at:
            raise ValueError("confirmation expiry must follow issuance")

    @property
    def expired(self) -> bool:
        return self.expires_at <= datetime.now(UTC)


class ToolConfirmationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    tool_name: str = Field(alias="toolName", pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    arguments: dict[str, JsonValue]


class ToolConfirmationReply(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    grant: str
    grant_id: str = Field(alias="grantId")
    tool_name: str = Field(alias="toolName")
    arguments_sha256: str = Field(alias="argumentsSha256", pattern=r"^[0-9a-f]{64}$")
    expires_at: datetime = Field(alias="expiresAt")
