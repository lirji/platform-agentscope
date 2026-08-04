import asyncio
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from agentscope_platform.api.app import create_app
from agentscope_platform.application.async_task import (
    AsyncTaskManager,
    AsyncTaskRejectedError,
)
from agentscope_platform.application.ports import ProgressSink
from agentscope_platform.application.service import (
    AgentApplicationService,
    AgentExecutionFailedError,
)
from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import (
    AgentExecution,
    AgentRunRequest,
    RunContext,
    TenantIdentity,
)
from agentscope_platform.domain.async_task import (
    AsyncTaskEventAppend,
    AsyncTaskStatus,
    CentralAsyncTask,
    CentralAsyncTaskEvent,
)


class FakeAsyncTaskGateway:
    def __init__(self) -> None:
        self.tasks: dict[str, CentralAsyncTask] = {}
        self.events: list[CentralAsyncTaskEvent] = []
        self.closed = False

    async def create(
        self,
        *,
        task_id: str,
        kind: str,
        input_data: dict[str, Any],
        webhook_url: str | None,
        context: RunContext,
    ) -> CentralAsyncTask:
        now = datetime.now(UTC)
        task = CentralAsyncTask(
            taskId=task_id,
            tenantId=context.identity.tenant_id,
            userId=context.identity.user_id,
            kind=kind,
            status="PENDING",
            input=input_data,
            webhookUrl=webhook_url,
            createdAt=now,
            updatedAt=now,
        )
        self.tasks[task_id] = task
        return task

    async def get(self, task_id: str, context: RunContext) -> CentralAsyncTask | None:
        task = self.tasks.get(task_id)
        if task is None or task.tenant_id != context.identity.tenant_id:
            return None
        return task

    async def list(self, context: RunContext) -> list[CentralAsyncTask]:
        return [
            task for task in self.tasks.values() if task.tenant_id == context.identity.tenant_id
        ]

    async def lease(
        self,
        task_id: str,
        worker_id: str,
        lease_seconds: float,
        context: RunContext,
        *,
        lease_epoch: int | None = None,
    ) -> CentralAsyncTask:
        task = self.tasks[task_id]
        if task.status.terminal:
            return task
        now = datetime.now(UTC)
        if lease_epoch is None:
            if task.lease_owner_id is not None and (
                task.lease_expires_at is None or task.lease_expires_at > now
            ):
                return task
            next_epoch = task.lease_epoch + 1
        else:
            if (
                task.lease_owner_id != worker_id
                or task.lease_epoch != lease_epoch
                or task.lease_expires_at is None
                or task.lease_expires_at <= now
            ):
                return task
            next_epoch = task.lease_epoch
        updated = task.model_copy(
            update={
                "status": AsyncTaskStatus.RUNNING,
                "lease_owner_id": worker_id,
                "lease_expires_at": now + timedelta(seconds=lease_seconds),
                "lease_epoch": next_epoch,
                "updated_at": now,
            }
        )
        self.tasks[task_id] = updated
        return updated

    async def update_status(
        self,
        task_id: str,
        status: AsyncTaskStatus,
        *,
        result: Any | None,
        error: str | None,
        worker_id: str,
        lease_epoch: int,
        context: RunContext,
    ) -> CentralAsyncTask:
        task = self.tasks[task_id]
        if task.status.terminal:
            return task
        if task.lease_owner_id != worker_id or task.lease_epoch != lease_epoch:
            return task
        now = datetime.now(UTC)
        updated = task.model_copy(
            update={
                "status": status,
                "result": result,
                "error": error,
                "updated_at": now,
                "finished_at": now if status.terminal else None,
                "lease_owner_id": None if status.terminal else worker_id,
                "lease_expires_at": None if status.terminal else task.lease_expires_at,
            }
        )
        self.tasks[task_id] = updated
        return updated

    async def cancel(self, task_id: str, context: RunContext) -> bool:
        task = await self.get(task_id, context)
        if task is None or task.status.terminal:
            return False
        now = datetime.now(UTC)
        self.tasks[task_id] = task.model_copy(
            update={
                "status": AsyncTaskStatus.CANCELLED,
                "error": "cancelled by user",
                "updated_at": now,
                "finished_at": now,
                "lease_owner_id": None,
                "lease_expires_at": None,
            }
        )
        return True

    async def append_event(
        self,
        task_id: str,
        event: AsyncTaskEventAppend,
        context: RunContext,
    ) -> CentralAsyncTaskEvent:
        appended = CentralAsyncTaskEvent(
            taskId=task_id,
            sequence=len(self.events) + 1,
            eventKey=event.event_key,
            event=event.event,
            data=event.data,
            createdAt=datetime.now(UTC),
            workerId=event.worker_id,
        )
        self.events.append(appended)
        return appended

    async def stream(
        self,
        task_id: str,
        context: RunContext,
        *,
        last_event_id: str | None,
    ) -> AsyncIterator[bytes]:
        del task_id, context, last_event_id
        if False:
            yield b""

    async def close(self) -> None:
        self.closed = True


def settings() -> Settings:
    return Settings(
        async_task_enabled=True,
        async_task_worker_id="worker-test",
        async_task_worker_jwt_secret=SecretStr("test-async-worker-secret-with-at-least-32-bytes"),
        async_task_lease_seconds=4,
        async_task_heartbeat_seconds=0.01,
        async_task_max_runtime_seconds=2,
        async_task_token_safety_seconds=2,
        async_task_request_timeout_seconds=1,
    )


def context(*, expires_in: float | None = None) -> RunContext:
    expiry = None if expires_in is None else datetime.now(UTC) + timedelta(seconds=expires_in)
    return RunContext(
        identity=TenantIdentity("acme", "alice"),
        internal_token="secret-token",
        trace_id="trace-1",
        token_expires_at=expiry,
    )


async def wait_terminal(gateway: FakeAsyncTaskGateway, task_id: str) -> CentralAsyncTask:
    for _ in range(100):
        task = gateway.tasks[task_id]
        if task.status.terminal:
            return task
        await asyncio.sleep(0.01)
    raise AssertionError("task did not reach a terminal state")


@pytest.mark.asyncio
async def test_submit_leases_executes_emits_progress_and_succeeds() -> None:
    gateway = FakeAsyncTaskGateway()
    manager = AsyncTaskManager(gateway, settings())

    async def execute(progress: ProgressSink) -> dict[str, str]:
        await progress.emit("dag-planned", {"tasks": []})
        return {"answer": "done"}

    submitted = await manager.submit(
        kind="agent.dag-plan",
        input_data={"goal": "test"},
        webhook_url="https://callback.test/task",
        context=context(),
        execute=execute,
    )
    terminal = await wait_terminal(gateway, submitted.task_id)

    assert submitted.status is AsyncTaskStatus.PENDING
    assert submitted.input["webhookUrl"] == "https://callback.test/task"
    assert terminal.status is AsyncTaskStatus.SUCCEEDED
    assert terminal.result == {"answer": "done"}
    assert gateway.events[0].data["taskId"] == submitted.task_id
    assert "secret-token" not in json.dumps(gateway.events[0].data)
    await manager.shutdown()


@pytest.mark.asyncio
async def test_cancel_wins_even_when_worker_swallows_cancellation() -> None:
    gateway = FakeAsyncTaskGateway()
    manager = AsyncTaskManager(gateway, settings())
    started = asyncio.Event()

    async def execute(progress: ProgressSink) -> dict[str, str]:
        del progress
        started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            return {"late": "success"}
        return {"late": "success"}

    submitted = await manager.submit(
        kind="agent.run",
        input_data={"goal": "test"},
        webhook_url=None,
        context=context(),
        execute=execute,
    )
    await started.wait()
    assert await manager.cancel(submitted.task_id, context())
    await asyncio.sleep(0)

    assert gateway.tasks[submitted.task_id].status is AsyncTaskStatus.CANCELLED
    await manager.shutdown()


@pytest.mark.asyncio
async def test_shutdown_drains_inflight_task_before_closing_gateway() -> None:
    gateway = FakeAsyncTaskGateway()
    manager = AsyncTaskManager(
        gateway,
        settings().model_copy(update={"async_task_drain_timeout_seconds": 0.5}),
    )
    started = asyncio.Event()
    release = asyncio.Event()

    async def execute(progress: ProgressSink) -> dict[str, str]:
        del progress
        started.set()
        await release.wait()
        return {"answer": "drained"}

    submitted = await manager.submit(
        kind="agent.run",
        input_data={"goal": "test"},
        webhook_url=None,
        context=context(),
        execute=execute,
    )
    await started.wait()
    closing = asyncio.create_task(manager.shutdown())
    await asyncio.sleep(0)

    assert not closing.done()
    assert not gateway.closed
    release.set()
    await closing

    assert gateway.tasks[submitted.task_id].status is AsyncTaskStatus.SUCCEEDED
    assert gateway.tasks[submitted.task_id].result == {"answer": "drained"}
    assert gateway.closed


@pytest.mark.asyncio
async def test_shutdown_timeout_stops_local_work_without_forging_terminal_status() -> None:
    gateway = FakeAsyncTaskGateway()
    manager = AsyncTaskManager(
        gateway,
        settings().model_copy(update={"async_task_drain_timeout_seconds": 0.01}),
    )
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def execute(progress: ProgressSink) -> dict[str, str]:
        del progress
        started.set()
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()
        return {"answer": "too late"}

    submitted = await manager.submit(
        kind="agent.run",
        input_data={"goal": "test"},
        webhook_url=None,
        context=context(),
        execute=execute,
    )
    await started.wait()

    await manager.shutdown()

    assert cancelled.is_set()
    assert gateway.tasks[submitted.task_id].status is AsyncTaskStatus.RUNNING
    assert gateway.tasks[submitted.task_id].lease_owner_id == manager.worker_id
    assert gateway.closed


@pytest.mark.asyncio
async def test_rejects_token_too_close_to_expiry_without_creating_task() -> None:
    gateway = FakeAsyncTaskGateway()
    manager = AsyncTaskManager(gateway, settings())

    with pytest.raises(AsyncTaskRejectedError):
        await manager.submit(
            kind="agent.run",
            input_data={"goal": "test"},
            webhook_url=None,
            context=context(expires_in=1),
            execute=lambda progress: asyncio.sleep(0),
        )

    assert gateway.tasks == {}
    await manager.shutdown()


class StubRunner:
    async def run(self, goal: str, context: RunContext) -> AgentExecution:
        del goal, context
        return AgentExecution(final_answer="done")


class ErrorStubRunner:
    async def run(self, goal: str, context: RunContext) -> AgentExecution:
        del goal, context
        return AgentExecution(
            final_answer="Agent execution failed.",
            stop_reason="ERROR",
        )


@pytest.mark.asyncio
async def test_error_reply_is_compatible_for_sync_but_rejected_for_async() -> None:
    service = AgentApplicationService(ErrorStubRunner())
    request = AgentRunRequest(goal="test")

    reply = await service.run(request, context())

    assert reply.stop_reason == "ERROR"
    assert reply.final_answer == "Agent execution failed."
    with pytest.raises(AgentExecutionFailedError):
        await service.run_for_async(request, context())


@pytest.mark.asyncio
async def test_agent_error_reply_fails_central_async_task() -> None:
    gateway = FakeAsyncTaskGateway()
    manager = AsyncTaskManager(gateway, settings())
    service = AgentApplicationService(ErrorStubRunner())
    request = AgentRunRequest(goal="test")

    submitted = await manager.submit(
        kind="agent.run",
        input_data=request.model_dump(by_alias=True),
        webhook_url=None,
        context=context(),
        execute=lambda _progress: service.run_for_async(request, context()),
    )
    terminal = await wait_terminal(gateway, submitted.task_id)

    assert terminal.status is AsyncTaskStatus.FAILED
    assert terminal.result is None
    assert terminal.error == "ASYNC_TASK_EXECUTION_FAILED"
    await manager.shutdown()


@pytest.mark.parametrize(
    ("path", "payload", "kind"),
    [
        ("/agent/run/async", {"goal": "test"}, "agent.run"),
        (
            "/agent/dag/run/async",
            {
                "goal": "test",
                "tasks": [{"id": "t1", "description": "work", "dependsOn": []}],
            },
            "agent.dag",
        ),
        ("/agent/dag/plan-run/async", {"goal": "test"}, "agent.dag-plan"),
        ("/agent/analyst/run/async", {"goal": "test"}, "agent.analyst"),
        ("/agent/process/run/async", {"goal": "查询流程状态"}, "agent.process"),
    ],
)
def test_five_async_submit_contracts(path: str, payload: dict[str, Any], kind: str) -> None:
    gateway = FakeAsyncTaskGateway()
    app = create_app(
        settings().model_copy(update={"internal_auth_required": False}),
        runner=StubRunner(),
        async_task_gateway=gateway,
    )

    with TestClient(app) as client:
        response = client.post(path, json=payload)

        assert response.status_code == 202
        assert set(response.json()) == {
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
        assert gateway.tasks[response.json()["taskId"]].kind == kind


def test_agent_async_route_maps_execution_error_to_failed_task() -> None:
    gateway = FakeAsyncTaskGateway()
    app = create_app(
        settings().model_copy(update={"internal_auth_required": False}),
        runner=ErrorStubRunner(),
        async_task_gateway=gateway,
    )

    with TestClient(app) as client:
        response = client.post("/agent/run/async", json={"goal": "test"})
        task_id = response.json()["taskId"]
        for _ in range(100):
            terminal = gateway.tasks[task_id]
            if terminal.status.terminal:
                break
            time.sleep(0.01)

        assert response.status_code == 202
        assert terminal.status is AsyncTaskStatus.FAILED
        assert terminal.result is None
        assert terminal.error == "ASYNC_TASK_EXECUTION_FAILED"


def test_task_routes_hide_non_agent_kinds() -> None:
    gateway = FakeAsyncTaskGateway()
    now = datetime.now(UTC)
    gateway.tasks["workflow-1"] = CentralAsyncTask(
        taskId="workflow-1",
        tenantId="anonymous",
        userId="anonymous",
        kind="workflow.instance",
        status="PENDING",
        input={},
        createdAt=now,
        updatedAt=now,
    )
    app = create_app(
        settings().model_copy(update={"internal_auth_required": False}),
        runner=StubRunner(),
        async_task_gateway=gateway,
    )

    with TestClient(app) as client:
        assert client.get("/agent/tasks/workflow-1").status_code == 404
        assert client.get("/agent/tasks").json() == []
