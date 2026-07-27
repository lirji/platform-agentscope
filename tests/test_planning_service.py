import re

import pytest

from agentscope_platform.application.dag import (
    AgentDagApplicationService,
    DagValidationError,
)
from agentscope_platform.application.planning import AgentDagPlanningService
from agentscope_platform.application.ports import DagPlanningError
from agentscope_platform.domain.agent import AgentExecution, RunContext, TenantIdentity
from agentscope_platform.domain.dag import (
    AgentPlanRunRequest,
    DagPlan,
    DagPlanKind,
)


def context() -> RunContext:
    return RunContext(
        identity=TenantIdentity(
            tenant_id="acme",
            user_id="alice",
            scopes=frozenset({"agent", "analytics"}),
            department="acme_rd",
        ),
        internal_token="internal-token",
        trace_id="planning-trace",
    )


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, RunContext]] = []

    async def run(self, goal: str, run_context: RunContext) -> AgentExecution:
        self.calls.append((goal, run_context))
        match = re.search(r"Your sub-task \[([^]]+)]", goal)
        return AgentExecution(final_answer=f"result-{match.group(1)}" if match else "synthesis")


class FakePlanner:
    def __init__(
        self,
        plan: DagPlan | None = None,
        error: DagPlanningError | None = None,
    ) -> None:
        self.result = plan or DagPlan()
        self.error = error
        self.calls: list[tuple[str, RunContext, DagPlanKind]] = []

    async def plan(
        self,
        goal: str,
        run_context: RunContext,
        kind: DagPlanKind,
    ) -> DagPlan:
        self.calls.append((goal, run_context, kind))
        if self.error is not None:
            raise self.error
        return self.result


async def test_general_plan_reuses_dag_engine_and_context() -> None:
    runner = FakeRunner()
    planner = FakePlanner(
        DagPlan.model_validate(
            {
                "tasks": [
                    {"id": "t1", "description": "collect", "dependsOn": []},
                    {
                        "id": "t2",
                        "description": "explain",
                        "dependsOn": ["t1"],
                    },
                ]
            }
        )
    )
    service = AgentDagPlanningService(
        planner,
        AgentDagApplicationService(runner),
    )
    run_context = context()

    reply = await service.plan_and_run(
        AgentPlanRunRequest(goal=" investigate "),
        run_context,
    )

    assert reply.goal == "investigate"
    assert reply.levels == [["t1"], ["t2"]]
    assert planner.calls == [("investigate", run_context, DagPlanKind.GENERAL)]
    assert all(call_context is run_context for _, call_context in runner.calls)
    assert "[t1] collect\nresult-t1" in runner.calls[1][0]


@pytest.mark.parametrize(
    "planner",
    [
        FakePlanner(DagPlan()),
        FakePlanner(error=DagPlanningError("provider secret must not leak")),
    ],
)
async def test_empty_or_failed_plan_falls_back_to_single_task(
    planner: FakePlanner,
) -> None:
    runner = FakeRunner()
    service = AgentDagPlanningService(
        planner,
        AgentDagApplicationService(runner),
    )

    reply = await service.plan_and_run(
        AgentPlanRunRequest(goal="single goal"),
        context(),
        DagPlanKind.ANALYST,
    )

    assert reply.levels == [["t1"]]
    assert reply.task_results[0].description == "single goal"
    assert planner.calls[0][2] is DagPlanKind.ANALYST


async def test_invalid_goal_is_rejected_before_planner_call() -> None:
    planner = FakePlanner()
    service = AgentDagPlanningService(
        planner,
        AgentDagApplicationService(FakeRunner()),
    )

    with pytest.raises(DagValidationError, match="goal is required"):
        await service.plan_and_run(AgentPlanRunRequest(goal=" "), context())

    assert planner.calls == []


@pytest.mark.parametrize(
    "plan",
    [
        DagPlan(),
        DagPlan.model_validate(
            {
                "tasks": [
                    {
                        "id": "t1",
                        "description": "用 refund_start 发起退款",
                        "dependsOn": [],
                    }
                ]
            }
        ),
    ],
)
async def test_process_fallback_never_executes_planned_write_operations(
    plan: DagPlan,
) -> None:
    runner = FakeRunner()
    service = AgentDagPlanningService(
        FakePlanner(plan),
        AgentDagApplicationService(runner),
    )

    reply = await service.plan_and_run(
        AgentPlanRunRequest(goal="帮我发起退款"),
        context(),
        DagPlanKind.PROCESS,
    )

    description = reply.task_results[0].description
    assert "严格只读" in description
    assert "不得发起、审批或修改流程" in description
    assert "refund_start" not in description


async def test_invalid_planned_graph_uses_existing_dag_validation() -> None:
    planner = FakePlanner(
        DagPlan.model_validate(
            {
                "tasks": [
                    {"id": "t1", "description": "one", "dependsOn": ["t2"]},
                    {"id": "t2", "description": "two", "dependsOn": ["t1"]},
                ]
            }
        )
    )
    service = AgentDagPlanningService(
        planner,
        AgentDagApplicationService(FakeRunner()),
    )

    with pytest.raises(DagValidationError, match="task graph contains a cycle"):
        await service.plan_and_run(
            AgentPlanRunRequest(goal="cycle"),
            context(),
        )
