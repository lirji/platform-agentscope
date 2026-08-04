from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentscope_platform.domain.agent import RunContext
from agentscope_platform.domain.confirmation import ToolConfirmationGrant


class SideEffectLevel(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class IdempotencyStrategy(StrEnum):
    NONE = "none"
    REQUEST_KEY = "request_key"
    BUSINESS_KEY = "business_key"


class ConfirmationRequirement(StrEnum):
    NEVER = "never"
    ALWAYS = "always"


class RetryPolicy(StrEnum):
    NONE = "none"
    IDEMPOTENT_TRANSIENT = "idempotent_transient"


class ToolPolicyReason(StrEnum):
    ALLOWED = "allowed"
    MISSING_SCOPE = "missing_scope"
    CONFIRMATION_REQUIRED = "confirmation_required"
    CONFIRMATION_INVALID = "confirmation_invalid"
    CONFIRMATION_REPLAYED = "confirmation_replayed"
    IDEMPOTENCY_REQUIRED = "idempotency_required"


class ToolMetadata(BaseModel):
    """Language-neutral safety contract for one Agent tool."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    read_only: bool = Field(alias="readOnly")
    side_effect: SideEffectLevel = Field(alias="sideEffect")
    idempotency: IdempotencyStrategy
    requires_confirmation: ConfirmationRequirement = Field(alias="requiresConfirmation")
    required_scopes: tuple[str, ...] = Field(alias="requiredScopes")
    timeout_seconds: float = Field(alias="timeoutSeconds", gt=0, le=300)
    retry_policy: RetryPolicy = Field(alias="retryPolicy")

    @model_validator(mode="after")
    def validate_safety_invariants(self) -> "ToolMetadata":
        if self.read_only:
            if self.side_effect is not SideEffectLevel.NONE:
                raise ValueError("read-only tools cannot declare side effects")
            if self.idempotency is not IdempotencyStrategy.NONE:
                raise ValueError("read-only tools do not require idempotency")
            if self.requires_confirmation is not ConfirmationRequirement.NEVER:
                raise ValueError("read-only tools cannot require confirmation")
        elif self.side_effect is SideEffectLevel.NONE:
            raise ValueError("write tools must declare a side-effect level")
        if (
            self.retry_policy is RetryPolicy.IDEMPOTENT_TRANSIENT
            and self.idempotency is IdempotencyStrategy.NONE
        ):
            raise ValueError("retry requires an idempotency strategy")
        return self

    @classmethod
    def for_read_only(
        cls,
        *,
        name: str,
        required_scopes: tuple[str, ...],
        timeout_seconds: float = 10,
    ) -> "ToolMetadata":
        return cls(
            name=name,
            readOnly=True,
            sideEffect=SideEffectLevel.NONE,
            idempotency=IdempotencyStrategy.NONE,
            requiresConfirmation=ConfirmationRequirement.NEVER,
            requiredScopes=required_scopes,
            timeoutSeconds=timeout_seconds,
            retryPolicy=RetryPolicy.NONE,
        )


@dataclass(frozen=True, slots=True)
class ToolPolicyDecision:
    allowed: bool
    reason: ToolPolicyReason
    message: str
    confirmation_grant: ToolConfirmationGrant | None = None


class ToolPolicy:
    """Pure policy evaluator; it never trusts model-provided tool arguments."""

    @staticmethod
    def evaluate(
        metadata: ToolMetadata,
        context: RunContext,
        arguments: Mapping[str, Any] | None = None,
    ) -> ToolPolicyDecision:
        missing_scopes = sorted(set(metadata.required_scopes) - set(context.identity.scopes))
        if missing_scopes:
            return ToolPolicyDecision(
                allowed=False,
                reason=ToolPolicyReason.MISSING_SCOPE,
                message="tool permission denied: required scope is missing",
            )
        if metadata.idempotency is not IdempotencyStrategy.NONE and not context.idempotency_key:
            return ToolPolicyDecision(
                allowed=False,
                reason=ToolPolicyReason.IDEMPOTENCY_REQUIRED,
                message="tool permission denied: idempotency key is required",
            )
        confirmation_grant: ToolConfirmationGrant | None = None
        if metadata.requires_confirmation is ConfirmationRequirement.ALWAYS:
            if arguments is None:
                return ToolPolicyDecision(
                    allowed=False,
                    reason=ToolPolicyReason.CONFIRMATION_REQUIRED,
                    message="tool permission denied: argument-bound confirmation is required",
                )
            confirmation_grant = context.confirmation_for(metadata.name, dict(arguments))
            if confirmation_grant is None:
                reason = (
                    ToolPolicyReason.CONFIRMATION_INVALID
                    if context.has_confirmation_for_tool(metadata.name)
                    else ToolPolicyReason.CONFIRMATION_REQUIRED
                )
                return ToolPolicyDecision(
                    allowed=False,
                    reason=reason,
                    message=(
                        "tool permission denied: confirmation does not match tool arguments"
                        if reason is ToolPolicyReason.CONFIRMATION_INVALID
                        else "tool permission denied: explicit confirmation is required"
                    ),
                )
        return ToolPolicyDecision(
            allowed=True,
            reason=ToolPolicyReason.ALLOWED,
            message="tool policy allows this invocation",
            confirmation_grant=confirmation_grant,
        )
