import logging
from typing import TYPE_CHECKING, Any

from agentscope_platform.application.async_task import runtime_config_digest
from agentscope_platform.application.ports import ProgressSink
from agentscope_platform.domain.agent import AgentRunRequest, RunContext
from agentscope_platform.domain.async_task import READONLY_TASK_KINDS, AsyncTaskStatus
from agentscope_platform.domain.dag import AgentDagRunRequest, AgentPlanRunRequest, DagPlanKind
from agentscope_platform.infrastructure.http.async_task_client import HttpAsyncTaskClient
from agentscope_platform.infrastructure.security.internal_jwt import InternalJwtVerifier

if TYPE_CHECKING:
    from agentscope_platform.api.app import Container

log = logging.getLogger(__name__)


class ReadOnlyTaskWorker:
    """只执行显式版本化只读kind. 持久化输入替代request闭包, 无确认grant可恢复."""

    def __init__(self, container: "Container", gateway: HttpAsyncTaskClient) -> None:
        self.container = container
        self.gateway = gateway
        self.manager = container.async_task_manager
        self.verifier = InternalJwtVerifier(container.settings)

    async def poll_once(self) -> bool:
        if not self.manager.free_slots:
            return False
        claimed = await self.gateway.claim(self.manager.worker_id)
        if claimed is None:
            return False
        task = claimed.task
        verified = self.verifier.verify_with_expiry(claimed.internal_token)
        if (
            task.kind not in READONLY_TASK_KINDS
            or verified.identity.tenant_id != task.tenant_id
            or verified.identity.user_id != task.user_id
            or verified.identity.scopes != frozenset({"agent"})
        ):
            raise ValueError("invalid durable dispatch authority")
        context = RunContext(
            verified.identity,
            claimed.internal_token,
            claimed.trace_id,
            token_expires_at=verified.expires_at,
            idempotency_key=task.task_id,
        )
        versions = task.input.get("_executionVersions")
        expected = self.container.execution_versions.model_dump(by_alias=True, mode="json")
        if (
            versions != expected
            or task.input.get("_runtimeRevision")
            != self.container.settings.async_task_runtime_revision
            or task.input.get("_runtimeConfigDigest")
            != runtime_config_digest(self.container.settings)
        ):
            await self.gateway.update_status(
                task.task_id,
                AsyncTaskStatus.FAILED,
                result=None,
                error="ASYNC_TASK_EXECUTION_VERSION_MISMATCH",
                worker_id=self.manager.worker_id,
                lease_epoch=task.lease_epoch,
                context=context,
            )
            return True
        payload = {
            key: value
            for key, value in task.input.items()
            if key not in {"_executionVersions", "_runtimeRevision", "_runtimeConfigDigest"}
        }
        kind = task.kind.removeprefix("agent.readonly.").removesuffix(".v1")

        async def execute(progress: ProgressSink) -> Any:
            if kind == "run":
                return await self.container.agent_service.run_for_async(
                    AgentRunRequest.model_validate(payload),
                    context,
                )
            if kind == "dag":
                return await self.container.dag_service.run(
                    AgentDagRunRequest.model_validate(payload),
                    context,
                    progress,
                )
            plan_kind = {
                "dag-plan": DagPlanKind.GENERAL,
                "analyst": DagPlanKind.ANALYST,
                "process": DagPlanKind.PROCESS,
            }[kind]
            service = (
                self.container.process_planning_service
                if kind == "process"
                else self.container.planning_service
            )
            return await service.plan_and_run(
                AgentPlanRunRequest.model_validate(payload),
                context,
                plan_kind,
                progress,
            )

        await self.manager.adopt(task, context, execute)
        return True
