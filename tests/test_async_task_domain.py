from datetime import UTC, datetime

from agentscope_platform.domain.async_task import (
    AGENT_TASK_KINDS,
    AgentAsyncTask,
    AsyncTaskStatus,
    CentralAsyncTask,
)


def test_central_task_projects_to_exact_legacy_shape() -> None:
    now = datetime.now(UTC)
    central = CentralAsyncTask.model_validate(
        {
            "taskId": "t-1",
            "tenantId": "acme",
            "userId": "alice",
            "kind": "agent.run",
            "status": "RUNNING",
            "input": {"goal": "answer"},
            "result": None,
            "error": None,
            "webhookUrl": "https://callback.example/tasks",
            "createdAt": now.isoformat(),
            "updatedAt": now.isoformat(),
            "finishedAt": None,
            "leaseOwnerId": "worker-secret",
            "leaseExpiresAt": now.isoformat(),
        }
    )

    projected = AgentAsyncTask.from_central(central).model_dump(
        by_alias=True,
        mode="json",
    )

    assert set(projected) == {
        "taskId",
        "tenantId",
        "userId",
        "status",
        "input",
        "result",
        "error",
        "createdAt",
        "updatedAt",
        "finishedAt",
    }
    assert projected["input"] == {
        "goal": "answer",
        "webhookUrl": "https://callback.example/tasks",
    }
    assert "leaseOwnerId" not in projected
    assert "worker-secret" not in str(projected)


def test_agent_kinds_are_closed_and_terminal_state_is_explicit() -> None:
    assert AGENT_TASK_KINDS == {
        "agent.run",
        "agent.dag",
        "agent.dag-plan",
        "agent.analyst",
        "agent.process",
    }
    assert AsyncTaskStatus.SUCCEEDED.terminal
    assert AsyncTaskStatus.FAILED.terminal
    assert AsyncTaskStatus.CANCELLED.terminal
    assert not AsyncTaskStatus.PENDING.terminal
    assert not AsyncTaskStatus.RUNNING.terminal
