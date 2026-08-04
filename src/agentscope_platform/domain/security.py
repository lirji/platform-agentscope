from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DownstreamServiceTokenClaims(BaseModel):
    """Language-neutral JWT claim contract for external tool providers."""

    model_config = ConfigDict(extra="forbid")

    iss: str = Field(pattern=r"^\S{1,128}$")
    aud: str = Field(pattern=r"^\S{1,128}$")
    sub: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    tenant: str = Field(min_length=1, max_length=256)
    actor_uid: str = Field(min_length=1, max_length=256)
    scopes: tuple[Literal["agent.tool.invoke"], ...] = Field(min_length=1, max_length=1)
    token_use: Literal["agent_downstream"]
    act: str = Field(min_length=1, max_length=256)
    jti: str = Field(
        pattern=(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{4}-[0-9a-f]{12}$"
        )
    )
    iat: int = Field(ge=0)
    exp: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_lifetime(self) -> "DownstreamServiceTokenClaims":
        if self.exp <= self.iat or self.exp - self.iat > 120:
            raise ValueError("downstream service token lifetime must be within 120 seconds")
        return self


class AsyncTaskWorkerTokenClaims(BaseModel):
    """Language-neutral, request-scoped authorization for async worker operations."""

    model_config = ConfigDict(extra="forbid")

    iss: str = Field(pattern=r"^\S{1,128}$")
    aud: str = Field(pattern=r"^\S{1,128}$")
    sub: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    tenant: str = Field(min_length=1, max_length=256)
    actor_uid: str = Field(min_length=1, max_length=256)
    worker_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    scopes: tuple[Literal["async.task.worker"], ...] = Field(min_length=1, max_length=1)
    token_use: Literal["async_task_worker"]
    act: Literal["lease", "status", "event"]
    task_id: str = Field(min_length=1, max_length=256)
    jti: str = Field(
        pattern=(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{4}-[0-9a-f]{12}$"
        )
    )
    iat: int = Field(ge=0)
    exp: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_lifetime(self) -> "AsyncTaskWorkerTokenClaims":
        if self.exp <= self.iat or self.exp - self.iat > 120:
            raise ValueError("async worker token lifetime must be within 120 seconds")
        return self
