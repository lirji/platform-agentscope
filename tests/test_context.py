import pytest

from agentscope_platform.core.context import (
    bind_run_context,
    current_run_context,
    reset_run_context,
)
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.domain.tool import (
    ConfirmationRequirement,
    IdempotencyStrategy,
    RetryPolicy,
    SideEffectLevel,
    ToolMetadata,
    ToolPolicy,
    ToolPolicyReason,
)
from tool_confirmation_support import confirmation_grant


def test_context_is_bound_and_reset() -> None:
    context = RunContext(
        identity=TenantIdentity("tenant-a", "user-a"),
        internal_token="token",
        trace_id="trace",
    )

    token = bind_run_context(context)
    assert current_run_context() == context

    reset_run_context(token)
    with pytest.raises(RuntimeError, match="not bound"):
        current_run_context()


def test_tool_metadata_is_language_neutral_and_complete() -> None:
    metadata = ToolMetadata(
        name="refund_start",
        readOnly=False,
        sideEffect=SideEffectLevel.MEDIUM,
        idempotency=IdempotencyStrategy.REQUEST_KEY,
        requiresConfirmation=ConfirmationRequirement.ALWAYS,
        requiredScopes=["agent"],
        timeoutSeconds=10,
        retryPolicy=RetryPolicy.NONE,
    )

    assert metadata.model_dump(by_alias=True, mode="json") == {
        "name": "refund_start",
        "readOnly": False,
        "sideEffect": "medium",
        "idempotency": "request_key",
        "requiresConfirmation": "always",
        "requiredScopes": ["agent"],
        "timeoutSeconds": 10.0,
        "retryPolicy": "none",
    }


def test_tool_policy_requires_scope_confirmation_and_idempotency() -> None:
    metadata = ToolMetadata(
        name="refund_start",
        readOnly=False,
        sideEffect="medium",
        idempotency="request_key",
        requiresConfirmation="always",
        requiredScopes=["agent"],
        timeoutSeconds=10,
        retryPolicy="none",
    )

    missing_scope = ToolPolicy.evaluate(
        metadata,
        RunContext(
            identity=TenantIdentity("acme", "alice"),
            internal_token="token",
            trace_id="trace",
        ),
    )
    missing_confirmation = ToolPolicy.evaluate(
        metadata,
        RunContext(
            identity=TenantIdentity("acme", "alice", frozenset({"agent"})),
            internal_token="token",
            trace_id="trace",
            idempotency_key="refund-42",
        ),
        {"message": "退款"},
    )
    missing_idempotency = ToolPolicy.evaluate(
        metadata,
        RunContext(
            identity=TenantIdentity("acme", "alice", frozenset({"agent"})),
            internal_token="token",
            trace_id="trace",
        ),
        {"message": "退款"},
    )
    arguments = {"message": "退款"}
    allowed = ToolPolicy.evaluate(
        metadata,
        RunContext(
            identity=TenantIdentity("acme", "alice", frozenset({"agent"})),
            internal_token="token",
            trace_id="trace",
            confirmation_grants=(
                confirmation_grant(
                    "refund_start",
                    arguments,
                    idempotency_key="refund-42",
                ),
            ),
            idempotency_key="refund-42",
        ),
        arguments,
    )

    assert missing_scope.reason == ToolPolicyReason.MISSING_SCOPE
    assert missing_confirmation.reason == ToolPolicyReason.CONFIRMATION_REQUIRED
    assert missing_idempotency.reason == ToolPolicyReason.IDEMPOTENCY_REQUIRED
    assert allowed.allowed is True
    assert allowed.reason == ToolPolicyReason.ALLOWED


def test_read_only_policy_does_not_require_confirmation_or_idempotency() -> None:
    metadata = ToolMetadata.for_read_only(name="rag_search", required_scopes=())
    decision = ToolPolicy.evaluate(
        metadata,
        RunContext(
            identity=TenantIdentity("acme", "alice"),
            internal_token="token",
            trace_id="trace",
        ),
    )

    assert decision.allowed is True
    assert decision.reason == ToolPolicyReason.ALLOWED
