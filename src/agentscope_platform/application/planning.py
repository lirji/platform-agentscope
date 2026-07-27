import logging

from agentscope_platform.application.dag import (
    AgentDagApplicationService,
    DagValidationError,
)
from agentscope_platform.application.ports import DagPlanner, DagPlanningError
from agentscope_platform.domain.agent import RunContext
from agentscope_platform.domain.dag import (
    AgentDagRunReply,
    AgentDagRunRequest,
    AgentDagTask,
    AgentPlanRunRequest,
    DagPlanKind,
)

log = logging.getLogger(__name__)


class AgentDagPlanningService:
    def __init__(
        self,
        planner: DagPlanner,
        dag_service: AgentDagApplicationService,
    ) -> None:
        self._planner = planner
        self._dag_service = dag_service

    async def plan_and_run(
        self,
        request: AgentPlanRunRequest,
        context: RunContext,
        kind: DagPlanKind = DagPlanKind.GENERAL,
    ) -> AgentDagRunReply:
        goal = (request.goal or "").strip()
        if not goal:
            raise DagValidationError("goal is required")

        try:
            plan = await self._planner.plan(goal, context, kind)
            tasks = [
                AgentDagTask(
                    id=task.id,
                    description=task.description,
                    dependsOn=task.depends_on,
                )
                for task in plan.tasks
            ]
        except DagPlanningError:
            log.warning(
                "DAG planning failed; using single-task fallback",
                extra={
                    "trace_id": context.trace_id,
                    "tenant_id": context.identity.tenant_id,
                    "planner_kind": kind.value,
                },
            )
            tasks = []

        if not tasks:
            tasks = [AgentDagTask(id="t1", description=goal, dependsOn=[])]
        return await self._dag_service.run(
            AgentDagRunRequest(
                goal=goal,
                tasks=tasks,
                webhookUrl=request.webhook_url,
            ),
            context,
        )
