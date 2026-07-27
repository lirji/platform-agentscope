import asyncio
from dataclasses import dataclass

from agentscope_platform.application.ports import AgentRunner
from agentscope_platform.application.service import to_agent_reply
from agentscope_platform.domain.agent import RunContext
from agentscope_platform.domain.dag import (
    AgentDagRunReply,
    AgentDagRunRequest,
    AgentDagTask,
    AgentDagTaskResult,
)


class DagValidationError(ValueError):
    """A caller-safe DAG contract validation failure."""


@dataclass(frozen=True, slots=True)
class _NormalizedTask:
    id: str
    description: str
    depends_on: tuple[str, ...]


class AgentDagApplicationService:
    def __init__(
        self,
        runner: AgentRunner,
        *,
        max_tasks: int = 6,
        max_parallel_workers: int = 8,
    ) -> None:
        self._runner = runner
        self._max_tasks = max(1, max_tasks)
        self._worker_slots = asyncio.Semaphore(max(1, max_parallel_workers))

    async def run(
        self,
        request: AgentDagRunRequest,
        context: RunContext,
    ) -> AgentDagRunReply:
        goal = (request.goal or "").strip()
        if not goal:
            raise DagValidationError("goal is required")
        tasks = self._validate_and_normalize(request.tasks)
        levels = self._topological_levels(tasks)

        by_id: dict[str, AgentDagTaskResult] = {}
        ordered: list[AgentDagTaskResult] = []
        for level in levels:
            for result in await self._run_level(goal, level, by_id, context):
                by_id[result.task_id] = result
                ordered.append(result)

        synthesis_goal = self._synthesis_goal(goal, ordered)
        synthesis_execution = await self._runner.run(synthesis_goal, context)
        synthesis = to_agent_reply(synthesis_goal, synthesis_execution, context)
        return AgentDagRunReply(
            goal=goal,
            levels=[[task.id for task in level] for level in levels],
            taskResults=ordered,
            synthesis=synthesis,
            tenantId=context.identity.tenant_id,
            attempts=[],
            acceptedByThreshold=True,
        )

    async def _run_level(
        self,
        goal: str,
        level: list[_NormalizedTask],
        upstream_results: dict[str, AgentDagTaskResult],
        context: RunContext,
    ) -> list[AgentDagTaskResult]:
        pending = [
            asyncio.create_task(self._run_one(goal, task, upstream_results, context))
            for task in level
        ]
        try:
            return list(await asyncio.gather(*pending))
        except BaseException:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            raise

    async def _run_one(
        self,
        goal: str,
        task: _NormalizedTask,
        upstream_results: dict[str, AgentDagTaskResult],
        context: RunContext,
    ) -> AgentDagTaskResult:
        worker_goal = self._worker_goal(goal, task, upstream_results)
        async with self._worker_slots:
            execution = await self._runner.run(worker_goal, context)
        return AgentDagTaskResult(
            taskId=task.id,
            description=task.description,
            dependsOn=list(task.depends_on),
            result=to_agent_reply(worker_goal, execution, context),
        )

    def _validate_and_normalize(
        self,
        tasks: list[AgentDagTask] | None,
    ) -> list[_NormalizedTask]:
        if not tasks:
            raise DagValidationError("tasks are required")
        if len(tasks) > self._max_tasks:
            raise DagValidationError(f"too many tasks; max is {self._max_tasks}")

        ids: set[str] = set()
        normalized: list[_NormalizedTask] = []
        for task in tasks:
            task_id = (task.id or "").strip()
            description = (task.description or "").strip()
            if not task_id:
                raise DagValidationError("task id is required")
            if not description:
                raise DagValidationError("task description is required")
            if task_id in ids:
                raise DagValidationError(f"duplicate task id: {task_id}")
            ids.add(task_id)
            normalized.append(
                _NormalizedTask(
                    id=task_id,
                    description=description,
                    depends_on=tuple(task.depends_on or ()),
                )
            )
        return normalized

    def _topological_levels(
        self,
        tasks: list[_NormalizedTask],
    ) -> list[list[_NormalizedTask]]:
        by_id = {task.id: task for task in tasks}
        pending_dependencies = {
            task.id: {dependency for dependency in task.depends_on if dependency in by_id}
            for task in tasks
        }

        levels: list[list[_NormalizedTask]] = []
        processed: set[str] = set()
        while len(processed) < len(tasks):
            level = [
                task
                for task in tasks
                if task.id not in processed and pending_dependencies[task.id].issubset(processed)
            ]
            if not level:
                raise DagValidationError("task graph contains a cycle")
            levels.append(level)
            processed.update(task.id for task in level)
        return levels

    @staticmethod
    def _worker_goal(
        goal: str,
        task: _NormalizedTask,
        upstream_results: dict[str, AgentDagTaskResult],
    ) -> str:
        upstream: list[str] = []
        for dependency in task.depends_on:
            result = upstream_results.get(dependency)
            if result is not None:
                upstream.append(
                    f"[{dependency}] {result.description}\n{result.result.final_answer}"
                )
        upstream_text = "\n\n".join(upstream) or "(none)"
        return (
            "You are one worker in a multi-agent DAG.\n"
            "Execute only your assigned sub-task. Return a concise, self-contained result.\n\n"
            f"Original user goal:\n{goal}\n\n"
            f"Upstream results:\n{upstream_text}\n\n"
            f"Your sub-task [{task.id}]:\n{task.description}\n"
        )

    @staticmethod
    def _synthesis_goal(
        goal: str,
        results: list[AgentDagTaskResult],
    ) -> str:
        formatted = "\n\n".join(
            f"[{result.task_id}] {result.description}\n{result.result.final_answer}"
            for result in results
        )
        return (
            "Synthesize the final answer for the original user goal using the completed "
            "DAG task results.\n"
            "Preserve useful nuance, remove duplication, and answer directly.\n\n"
            f"Original user goal:\n{goal}\n\n"
            f"Task results:\n{formatted}\n"
        )
