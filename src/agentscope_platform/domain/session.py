import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentscope_platform.domain.agent import AgentStep


class AgentSessionStatus(StrEnum):
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def terminal(self) -> bool:
        return self in {
            AgentSessionStatus.SUCCEEDED,
            AgentSessionStatus.FAILED,
            AgentSessionStatus.CANCELLED,
        }


def goal_sha256(goal: str) -> str:
    """Return the stable goal digest persisted instead of the raw prompt."""

    return hashlib.sha256(goal.encode("utf-8")).hexdigest()


class AgentSessionCheckpoint(BaseModel):
    """Language-neutral, bounded session state safe for durable persistence."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal["agent-session-checkpoint.v1"] = Field(
        default="agent-session-checkpoint.v1",
        alias="schemaVersion",
    )
    session_id: str = Field(alias="sessionId", pattern=r"^sess-[a-f0-9]{32}$")
    revision: int = Field(ge=0)
    tenant_id: str = Field(alias="tenantId", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    user_id: str = Field(alias="userId", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    goal_sha256: str = Field(alias="goalSha256", pattern=r"^[0-9a-f]{64}$")
    status: AgentSessionStatus
    steps: list[AgentStep] = Field(default_factory=list, max_length=256)
    final_answer: str | None = Field(default=None, alias="finalAnswer", max_length=100_000)
    stop_reason: str | None = Field(default=None, alias="stopReason", max_length=128)
    error: str | None = Field(default=None, max_length=2_000)
    side_effect_observed: bool = Field(default=False, alias="sideEffectObserved")
    idempotency_key_sha256: str | None = Field(
        default=None,
        alias="idempotencyKeySha256",
        pattern=r"^[0-9a-f]{64}$",
    )
    lease_owner_id: str | None = Field(
        default=None,
        alias="leaseOwnerId",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    lease_expires_at: datetime | None = Field(default=None, alias="leaseExpiresAt")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    expires_at: datetime = Field(alias="expiresAt")

    @model_validator(mode="after")
    def validate_invariants(self) -> "AgentSessionCheckpoint":
        if self.updated_at < self.created_at:
            raise ValueError("updatedAt must not precede createdAt")
        if self.expires_at <= self.updated_at:
            raise ValueError("expiresAt must be later than updatedAt")
        if self.side_effect_observed and self.idempotency_key_sha256 is None:
            raise ValueError("side-effect checkpoints require an idempotency key digest")
        if (self.lease_owner_id is None) != (self.lease_expires_at is None):
            raise ValueError("leaseOwnerId and leaseExpiresAt must be set together")
        return self


class AgentSessionRunRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    goal: str = Field(min_length=1, max_length=20_000)
