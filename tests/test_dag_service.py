import asyncio
import re

import pytest

from agentscope_platform.application.dag import (
    AgentDagApplicationService,
    DagValidationError,
)
from agentscope_platform.domain.agent import AgentExecution, RunContext, TenantIdentity
from agentscope_platform.domain.dag import AgentDagRunRequest


def context(tenant_id: str = "acme", trace_id: str = "trace-acme") -> RunContext:
    return RunContext(
        identity=TenantIdentity(
            tenant_id=tenant_id,
            user_id=f"user-{tenant_id}",
            scopes=frozenset({"agent"}),
            department=f"{tenant_id}_rd",
        ),
        internal_token=f"token-{tenant_id}",
        trace_id=trace_id,
    )


class RecordingRunner:
    def __init__(self, *, delay: float = 0) -> None:
        self.calls: list[tuple[str, RunContext]] = []
        self.delay = delay
        self.active_workers = 0
        self.max_active_workers = 0

    async def run(self, goal: str, run_context: RunContext) -> AgentExecution:
        self.calls.append((goal, run_context))
        if goal.startswith("You are one worker"):
            self.active_workers += 1
            self.max_active_workers = max(
                self.max_active_workers,
                self.active_workers,
            )
            await asyncio.sleep(self.delay)
            self.active_workers -= 1
            task_id = re.search(r"Your sub-task \[([^]]+)]", goal)
            assert task_id is not None
            return AgentExecution(final_answer=f"result-{task_id.group(1)}")
        return AgentExecution(final_answer="synthesized")


async def test_diamond_dag_runs_by_level_and_propagates_direct_upstream() -> None:
    runner = RecordingRunner(delay=0.01)
    service = AgentDagApplicationService(runner)
    run_context = context()
    request = AgentDagRunRequest.model_validate(
        {
            "goal": " investigate ",
            "tasks": [
                {"id": "source", "description": " collect "},
                {
                    "id": "left",
                    "description": "analyze left",
                    "dependsOn": ["source"],
                },
                {
                    "id": "right",
                    "description": "analyze right",
                    "dependsOn": ["source"],
                },
                {
                    "id": "final",
                    "description": "combine",
                    "dependsOn": ["left", "right"],
                },
            ],
        }
    )

    reply = await service.run(request, run_context)

    assert reply.goal == "investigate"
    assert reply.levels == [["source"], ["left", "right"], ["final"]]
    assert [result.task_id for result in reply.task_results] == [
        "source",
        "left",
        "right",
        "final",
    ]
    assert runner.max_active_workers == 2
    worker_goals = [goal for goal, _ in runner.calls if goal.startswith("You are one worker")]
    assert "[source] collect\nresult-source" in worker_goals[1]
    assert "[source] collect\nresult-source" in worker_goals[2]
    assert "[left] analyze left\nresult-left" in worker_goals[3]
    assert "[right] analyze right\nresult-right" in worker_goals[3]
    assert all(call_context is run_context for _, call_context in runner.calls)
    assert reply.tenant_id == "acme"
    assert reply.synthesis.final_answer == "synthesized"
    assert reply.attempts == []
    assert reply.accepted_by_threshold is True


async def test_unknown_dependency_is_ignored_but_preserved_in_result() -> None:
    runner = RecordingRunner()
    service = AgentDagApplicationService(runner)
    request = AgentDagRunRequest.model_validate(
        {
            "goal": "legacy compatibility",
            "tasks": [
                {
                    "id": "only",
                    "description": "run anyway",
                    "dependsOn": ["missing"],
                }
            ],
        }
    )

    reply = await service.run(request, context())

    assert reply.levels == [["only"]]
    assert reply.task_results[0].depends_on == ["missing"]
    assert "Upstream results:\n(none)" in runner.calls[0][0]


async def test_worker_error_is_available_to_synthesis() -> None:
    class ErrorRunner(RecordingRunner):
        async def run(self, goal: str, run_context: RunContext) -> AgentExecution:
            self.calls.append((goal, run_context))
            if goal.startswith("You are one worker"):
                return AgentExecution(final_answer="downstream unavailable", stop_reason="ERROR")
            return AgentExecution(final_answer="partial synthesis")

    runner = ErrorRunner()
    service = AgentDagApplicationService(runner)

    reply = await service.run(
        AgentDagRunRequest.model_validate(
            {
                "goal": "answer safely",
                "tasks": [{"id": "t1", "description": "query dependency"}],
            }
        ),
        context(),
    )

    assert reply.task_results[0].result.stop_reason == "ERROR"
    assert "downstream unavailable" in runner.calls[-1][0]
    assert reply.synthesis.final_answer == "partial synthesis"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"goal": "  ", "tasks": []}, "goal is required"),
        ({"goal": "x", "tasks": []}, "tasks are required"),
        (
            {
                "goal": "x",
                "tasks": [
                    {"id": "a", "description": "one"},
                    {"id": "a", "description": "two"},
                ],
            },
            "duplicate task id: a",
        ),
        (
            {
                "goal": "x",
                "tasks": [
                    {"id": "a", "description": "one", "dependsOn": ["b"]},
                    {"id": "b", "description": "two", "dependsOn": ["a"]},
                ],
            },
            "task graph contains a cycle",
        ),
        (
            {"goal": "x", "tasks": [{"id": " ", "description": "one"}]},
            "task id is required",
        ),
        (
            {"goal": "x", "tasks": [{"id": "a", "description": " "}]},
            "task description is required",
        ),
    ],
)
async def test_invalid_dag_is_rejected(payload: dict[str, object], message: str) -> None:
    service = AgentDagApplicationService(RecordingRunner())

    with pytest.raises(DagValidationError, match=re.escape(message)):
        await service.run(AgentDagRunRequest.model_validate(payload), context())


async def test_task_limit_is_enforced() -> None:
    service = AgentDagApplicationService(RecordingRunner(), max_tasks=1)
    request = AgentDagRunRequest.model_validate(
        {
            "goal": "x",
            "tasks": [
                {"id": "a", "description": "one"},
                {"id": "b", "description": "two"},
            ],
        }
    )

    with pytest.raises(DagValidationError, match="too many tasks; max is 1"):
        await service.run(request, context())


async def test_parallel_tenants_never_share_context() -> None:
    runner = RecordingRunner(delay=0.01)
    service = AgentDagApplicationService(runner)

    async def execute(tenant_id: str) -> None:
        await service.run(
            AgentDagRunRequest.model_validate(
                {
                    "goal": f"goal-{tenant_id}",
                    "tasks": [
                        {"id": "a", "description": f"task-{tenant_id}-a"},
                        {"id": "b", "description": f"task-{tenant_id}-b"},
                    ],
                }
            ),
            context(tenant_id, f"trace-{tenant_id}"),
        )

    await asyncio.gather(execute("alpha"), execute("beta"))

    assert len(runner.calls) == 6
    for goal, run_context in runner.calls:
        tenant_id = run_context.identity.tenant_id
        assert tenant_id in {"alpha", "beta"}
        assert run_context.identity.user_id == f"user-{tenant_id}"
        assert run_context.identity.department == f"{tenant_id}_rd"
        assert run_context.internal_token == f"token-{tenant_id}"
        assert run_context.trace_id == f"trace-{tenant_id}"
        assert f"goal-{tenant_id}" in goal
