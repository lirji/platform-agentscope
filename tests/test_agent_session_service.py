from datetime import UTC, datetime, timedelta

import pytest

from agentscope_platform.application.session import (
    AgentSessionActiveError,
    AgentSessionGoalMismatchError,
    AgentSessionNotFoundError,
    AgentSessionResumeConfirmationRequiredError,
    AgentSessionService,
)
from agentscope_platform.domain.agent import AgentExecution, AgentStep, RunContext, TenantIdentity
from agentscope_platform.domain.confirmation import ToolConfirmationGrant
from agentscope_platform.domain.session import AgentSessionStatus
from agentscope_platform.infrastructure.persistence.agent_session import InMemoryAgentSessionStore


def context(
    *,
    tenant: str = "acme",
    user: str = "alice",
    idempotency_key: str | None = None,
    grants: tuple[ToolConfirmationGrant, ...] = (),
) -> RunContext:
    return RunContext(
        identity=TenantIdentity(tenant, user, frozenset({"agent"})),
        internal_token="must-not-be-persisted",
        trace_id="trace-123",
        confirmation_grants=grants,
        idempotency_key=idempotency_key,
    )


class FakeResumableRunner:
    def __init__(self, *executions: AgentExecution, side_effect: bool = False) -> None:
        self.executions = list(executions)
        self.checkpoints: list[tuple[AgentStep, ...]] = []
        self.side_effect = side_effect

    async def run_from_checkpoint(self, goal, checkpoint, run_context, progress):  # type: ignore[no-untyped-def]
        del goal, run_context
        self.checkpoints.append(tuple(checkpoint.steps))
        execution = self.executions.pop(0)
        await progress(execution.steps, self.side_effect)
        return execution


async def test_session_persists_redacted_progress_and_resumes_after_failure() -> None:
    runner = FakeResumableRunner(
        AgentExecution(
            final_answer="failed for alice@example.com",
            stop_reason="ERROR",
            steps=(
                AgentStep(
                    n=1,
                    action="rag_search",
                    actionInput="alice@example.com",
                    observation="call 13800138000",
                ),
            ),
        ),
        AgentExecution(final_answer="done", stop_reason="DONE"),
    )
    store = InMemoryAgentSessionStore()
    service = AgentSessionService(runner, store, ttl_seconds=3600, lease_seconds=30)

    paused = await service.run(
        "sess-11111111111111111111111111111111",
        "research refunds",
        context(),
    )
    completed = await service.run(
        paused.session_id,
        "research refunds",
        context(),
    )

    assert paused.status is AgentSessionStatus.PAUSED
    assert "alice@example.com" not in paused.model_dump_json()
    assert "13800138000" not in paused.model_dump_json()
    assert completed.status is AgentSessionStatus.SUCCEEDED
    assert runner.checkpoints[1] == tuple(paused.steps)
    assert "must-not-be-persisted" not in completed.model_dump_json()


async def test_session_read_is_owner_scoped_and_goal_is_immutable() -> None:
    runner = FakeResumableRunner(AgentExecution(final_answer="done"))
    service = AgentSessionService(runner, InMemoryAgentSessionStore())
    session_id = "sess-22222222222222222222222222222222"
    await service.run(session_id, "goal one", context())

    with pytest.raises(AgentSessionNotFoundError):
        await service.get(session_id, context(tenant="other"))
    with pytest.raises(AgentSessionGoalMismatchError):
        await service.run(session_id, "goal two", context())


async def test_session_rejects_an_unexpired_competing_lease() -> None:
    store = InMemoryAgentSessionStore()
    runner = FakeResumableRunner(AgentExecution(final_answer="unused"))
    service = AgentSessionService(runner, store, lease_owner_id="worker-b")
    now = datetime.now(UTC)
    from agentscope_platform.domain.session import AgentSessionCheckpoint, goal_sha256

    await store.compare_and_set(
        AgentSessionCheckpoint(
            sessionId="sess-33333333333333333333333333333333",
            revision=1,
            tenantId="acme",
            userId="alice",
            goalSha256=goal_sha256("goal"),
            status=AgentSessionStatus.RUNNING,
            leaseOwnerId="worker-a",
            leaseExpiresAt=now + timedelta(seconds=30),
            createdAt=now,
            updatedAt=now,
            expiresAt=now + timedelta(hours=1),
        ),
        expected_revision=None,
    )

    with pytest.raises(AgentSessionActiveError):
        await service.run(
            "sess-33333333333333333333333333333333",
            "goal",
            context(),
        )


async def test_side_effect_resume_requires_matching_key_and_fresh_confirmation() -> None:
    session_id = "sess-44444444444444444444444444444444"
    runner = FakeResumableRunner(
        AgentExecution(
            final_answer="retry",
            stop_reason="ERROR",
            steps=(AgentStep(n=1, action="refund_start"),),
        ),
        side_effect=True,
    )
    service = AgentSessionService(runner, InMemoryAgentSessionStore())
    await service.run(session_id, "refund", context(idempotency_key="idem-1"))

    with pytest.raises(AgentSessionResumeConfirmationRequiredError):
        await service.run(session_id, "refund", context(idempotency_key="idem-1"))
    with pytest.raises(AgentSessionResumeConfirmationRequiredError):
        await service.run(session_id, "refund", context(idempotency_key="different"))
