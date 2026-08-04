import logging

from agentscope_platform.application.dag import (
    AgentDagApplicationService,
    DagValidationError,
)
from agentscope_platform.application.ports import DagPlanner, DagPlanningError, ProgressSink
from agentscope_platform.domain.agent import RunContext
from agentscope_platform.domain.dag import (
    AgentDagRunReply,
    AgentDagRunRequest,
    AgentDagTask,
    AgentPlanRunRequest,
    DagPlanKind,
)

log = logging.getLogger(__name__)
REFUND_START_MARKERS = (
    "refund_start",
    "发起退款",
    "启动退款",
)
PROCESS_WRITE_MARKERS = (
    *REFUND_START_MARKERS,
    "workflow_complete",
    "批准退款",
    "驳回退款",
    "认领任务",
    "完成审批",
)
PROCESS_READ_MARKERS = (
    "workflow_status",
    "workflow_tasks",
    "rag_search",
    "只读",
    "不支持",
)


class AgentDagPlanningService:
    def __init__(
        self,
        planner: DagPlanner,
        dag_service: AgentDagApplicationService,
        process_write_tools: frozenset[str] = frozenset(),
    ) -> None:
        self._planner = planner
        self._dag_service = dag_service
        self._process_write_tools = process_write_tools

    async def plan_and_run(
        self,
        request: AgentPlanRunRequest,
        context: RunContext,
        kind: DagPlanKind = DagPlanKind.GENERAL,
        progress: ProgressSink | None = None,
    ) -> AgentDagRunReply:
        goal = (request.goal or "").strip()
        if not goal:
            raise DagValidationError("goal is required")

        refund_start_allowed = (
            kind is DagPlanKind.PROCESS
            and "refund_start" in self._process_write_tools
            and context.has_confirmation_for_tool("refund_start")
            and bool(context.idempotency_key)
        )
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
            allowed_markers = PROCESS_READ_MARKERS + (
                REFUND_START_MARKERS if refund_start_allowed else ()
            )
            forbidden_write_markers = tuple(
                marker
                for marker in PROCESS_WRITE_MARKERS
                if marker not in (REFUND_START_MARKERS if refund_start_allowed else ())
            )
            if kind is DagPlanKind.PROCESS and (
                len(tasks) > 4
                or any(
                    marker in (task.description or "").casefold()
                    for task in tasks
                    for marker in forbidden_write_markers
                )
                or any(
                    not any(
                        marker in (task.description or "").casefold() for marker in allowed_markers
                    )
                    for task in tasks
                )
            ):
                log.warning(
                    "Process Planner proposed a write operation; using safe fallback",
                    extra={
                        "trace_id": context.trace_id,
                        "tenant_id": context.identity.tenant_id,
                    },
                )
                tasks = []
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
            description = goal
            if kind is DagPlanKind.PROCESS:
                if refund_start_allowed:
                    description = (
                        "受治理处理以下流程诉求。可使用 workflow_status、workflow_tasks、"
                        "rag_search 或 refund_start；refund_start 仅发起用户已确认且有幂等键的"
                        "流程，不得审批、认领或删除流程，也不得声称退款已批准。"
                        f"\n用户诉求：{goal}"
                    )
                else:
                    description = (
                        "严格只读处理以下流程诉求。仅可使用 workflow_status、workflow_tasks "
                        "或 rag_search；不得发起、审批或修改流程。若诉求需要写操作，明确说明"
                        f"当前候选服务不支持并不得声称成功。\n用户诉求：{goal}"
                    )
            tasks = [AgentDagTask(id="t1", description=description, dependsOn=[])]
        if progress is not None:
            await progress.emit(
                "dag-planned",
                {
                    "goal": goal,
                    "kind": kind.value,
                    "tasks": [task.model_dump(by_alias=True, mode="json") for task in tasks],
                },
            )
        return await self._dag_service.run(
            AgentDagRunRequest(
                goal=goal,
                tasks=tasks,
                webhookUrl=request.webhook_url,
            ),
            context,
            progress,
        )
