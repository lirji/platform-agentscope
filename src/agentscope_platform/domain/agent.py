import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentscope_platform.domain.confirmation import (
    ToolConfirmationGrant,
    canonical_tool_arguments_hash,
)


@dataclass(frozen=True, slots=True)
class TenantIdentity:
    tenant_id: str
    user_id: str
    scopes: frozenset[str] = field(default_factory=frozenset)
    department: str | None = None


@dataclass(frozen=True, slots=True)
class RunContext:
    identity: TenantIdentity
    internal_token: str | None
    trace_id: str
    token_expires_at: datetime | None = None
    confirmation_grants: tuple[ToolConfirmationGrant, ...] = field(default_factory=tuple)
    idempotency_key: str | None = None

    def has_confirmation_for_tool(self, tool_name: str) -> bool:
        return any(
            self._grant_is_context_bound(grant) and grant.tool_name == tool_name
            for grant in self.confirmation_grants
        )

    def confirmation_for(
        self,
        tool_name: str,
        arguments: dict[str, object],
    ) -> ToolConfirmationGrant | None:
        try:
            arguments_sha256 = canonical_tool_arguments_hash(arguments)
        except ValueError:
            return None
        return next(
            (
                grant
                for grant in self.confirmation_grants
                if self._grant_is_context_bound(grant)
                and grant.tool_name == tool_name
                and grant.arguments_sha256 == arguments_sha256
            ),
            None,
        )

    def _grant_is_context_bound(self, grant: ToolConfirmationGrant) -> bool:
        return (
            not grant.expired
            and grant.tenant_id == self.identity.tenant_id
            and grant.user_id == self.identity.user_id
            and grant.idempotency_key == self.idempotency_key
        )


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    goal: str = Field(min_length=1, max_length=20_000)
    webhook_url: str | None = Field(default=None, alias="webhookUrl")


class AgentStep(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    n: int
    thought: str = ""
    action: str = ""
    action_input: str = Field(default="", alias="actionInput")
    observation: str = ""


class ExecutionVersions(BaseModel):
    """Content-addressed runtime inputs needed to reproduce an Agent trajectory."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal["agent-execution-versions.v1"] = Field(
        default="agent-execution-versions.v1",
        alias="schemaVersion",
    )
    prompt_version: str = Field(
        alias="promptVersion",
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    model_version: str = Field(
        alias="modelVersion",
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    toolset_version: str = Field(
        alias="toolsetVersion",
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    tool_versions: dict[str, str] = Field(alias="toolVersions")

    @field_validator("tool_versions")
    @classmethod
    def validate_tool_versions(cls, value: dict[str, str]) -> dict[str, str]:
        if any(
            re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", name) is None
            or re.fullmatch(r"sha256:[0-9a-f]{64}", version) is None
            for name, version in value.items()
        ):
            raise ValueError("tool versions require stable names and SHA-256 digests")
        return value


class AgentTrajectory(BaseModel):
    """Internal language-neutral trajectory; the legacy HTTP reply remains unchanged."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal["agent-trajectory.v1"] = Field(
        default="agent-trajectory.v1",
        alias="schemaVersion",
    )
    trace_id: str = Field(alias="traceId", min_length=1, max_length=128)
    versions: ExecutionVersions
    steps: tuple[AgentStep, ...]
    stop_reason: str = Field(alias="stopReason", min_length=1, max_length=64)
    input_tokens: int = Field(default=0, alias="inputTokens", ge=0)
    output_tokens: int = Field(default=0, alias="outputTokens", ge=0)


class AgentRunReply(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    goal: str
    steps: list[AgentStep] = Field(default_factory=list)
    final_answer: str = Field(alias="finalAnswer")
    stop_reason: str = Field(alias="stopReason")
    depth: int = 0
    tenant_id: str = Field(alias="tenantId")


@dataclass(frozen=True, slots=True)
class AgentExecution:
    final_answer: str
    stop_reason: str = "DONE"
    steps: tuple[AgentStep, ...] = ()
    depth: int = 0
    trajectory: AgentTrajectory | None = None
