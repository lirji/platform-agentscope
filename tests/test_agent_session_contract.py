from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from agentscope_platform.domain.agent import AgentStep
from agentscope_platform.domain.session import (
    AgentSessionCheckpoint,
    AgentSessionStatus,
    goal_sha256,
)


def checkpoint() -> AgentSessionCheckpoint:
    now = datetime.now(UTC)
    return AgentSessionCheckpoint(
        sessionId="sess-11111111111111111111111111111111",
        revision=2,
        tenantId="acme",
        userId="alice",
        goalSha256=goal_sha256("research refunds"),
        status=AgentSessionStatus.PAUSED,
        steps=[
            AgentStep(
                n=1,
                action="rag_search",
                actionInput="refund policy",
                observation="policy found",
            )
        ],
        sideEffectObserved=False,
        createdAt=now,
        updatedAt=now,
        expiresAt=now + timedelta(hours=1),
    )


def test_checkpoint_is_language_neutral_and_round_trips() -> None:
    value = checkpoint()
    payload = value.model_dump(by_alias=True, mode="json")

    assert AgentSessionCheckpoint.model_validate(payload) == value
    assert payload["schemaVersion"] == "agent-session-checkpoint.v1"
    assert {
        "internalToken",
        "confirmationGrants",
        "agentScopeState",
        "modelState",
        "rawGoal",
    }.isdisjoint(payload)


def test_checkpoint_rejects_unknown_fields_and_invalid_identifiers() -> None:
    payload = checkpoint().model_dump(by_alias=True, mode="json")
    payload["agentScopeState"] = {"context": []}

    with pytest.raises(ValidationError):
        AgentSessionCheckpoint.model_validate(payload)

    payload.pop("agentScopeState")
    payload["sessionId"] = "../../tenant-bypass"
    with pytest.raises(ValidationError):
        AgentSessionCheckpoint.model_validate(payload)


def test_checkpoint_requires_side_effect_idempotency_digest() -> None:
    payload = checkpoint().model_dump(by_alias=True, mode="json")
    payload["sideEffectObserved"] = True

    with pytest.raises(ValidationError):
        AgentSessionCheckpoint.model_validate(payload)
