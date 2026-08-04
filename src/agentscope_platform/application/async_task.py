import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from agentscope_platform.application.ports import (
    AsyncTaskGateway,
    AsyncTaskMetrics,
    ProgressSink,
)
from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import RunContext
from agentscope_platform.domain.async_task import (
    AGENT_TASK_KINDS,
    AgentAsyncTask,
    AsyncTaskEventAppend,
    AsyncTaskStatus,
    CentralAsyncTask,
)


class AsyncTaskRejectedError(RuntimeError):
    """The request cannot safely be accepted for background execution."""


class AsyncTaskNotFoundError(RuntimeError):
    """The requested task is absent or outside the Agent kind boundary."""


ExecuteAsyncTask = Callable[[ProgressSink], Awaitable[Any]]


class _NoopAsyncTaskMetrics:
    def submitted(self, kind: str) -> None:
        del kind

    def completed(self, kind: str, status: str) -> None:
        del kind, status

    def heartbeat_failed(self) -> None:
        pass

    def running(self, delta: int, kind: str) -> None:
        del delta, kind

    def inflight(self, delta: int, kind: str) -> None:
        del delta, kind

    def backlog(self, delta: int, kind: str) -> None:
        del delta, kind


@dataclass(slots=True)
class ExecutionHandle:
    task_id: str
    kind: str
    context: RunContext
    lease_epoch: int
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    terminal_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    event_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    event_counter: int = 0
    work: asyncio.Task[None] | None = None


class _TaskProgressSink(ProgressSink):
    def __init__(
        self,
        gateway: AsyncTaskGateway,
        handle: ExecutionHandle,
        worker_id: str,
        enabled: bool,
    ) -> None:
        self._gateway = gateway
        self._handle = handle
        self._worker_id = worker_id
        self._enabled = enabled

    async def emit(self, event: str, data: Any) -> None:
        if not self._enabled or self._handle.stop.is_set():
            return
        async with self._handle.event_lock:
            self._handle.event_counter += 1
            key = (
                f"{self._worker_id}:{self._handle.lease_epoch}:{self._handle.event_counter}:{event}"
            )
        await self._gateway.append_event(
            self._handle.task_id,
            AsyncTaskEventAppend(
                eventKey=key,
                event=event,
                data={
                    "taskId": self._handle.task_id,
                    "event": event,
                    "data": data,
                    "ts": datetime.now(UTC).isoformat(),
                },
                workerId=self._worker_id,
                leaseEpoch=self._handle.lease_epoch,
            ),
            self._handle.context,
        )


class AsyncTaskManager:
    def __init__(
        self,
        gateway: AsyncTaskGateway,
        settings: Settings,
        metrics: AsyncTaskMetrics | None = None,
    ) -> None:
        self.gateway = gateway
        self.settings = settings
        service_id = settings.async_task_worker_id.strip() or "agentscope"
        suffix = uuid4().hex[:12]
        self.worker_id = f"{service_id[: 127 - len(suffix)]}.{suffix}"
        self._metrics = metrics or _NoopAsyncTaskMetrics()
        self._semaphore = asyncio.Semaphore(settings.async_task_max_concurrent)
        self._handles: dict[str, ExecutionHandle] = {}
        self._registry_lock = asyncio.Lock()
        self._closing = False

    async def submit(
        self,
        *,
        kind: str,
        input_data: dict[str, Any],
        webhook_url: str | None,
        context: RunContext,
        execute: ExecuteAsyncTask,
    ) -> AgentAsyncTask:
        if not self.settings.async_task_enabled or self._closing:
            raise AsyncTaskRejectedError("async task execution is disabled")
        if kind not in AGENT_TASK_KINDS:
            raise AsyncTaskRejectedError("unsupported async task kind")
        self._validate_deadline(context)
        async with self._registry_lock:
            if len(self._handles) >= self.settings.async_task_max_inflight:
                raise AsyncTaskRejectedError("async task capacity is exhausted")

        task_id = str(uuid4())
        created = await self.gateway.create(
            task_id=task_id,
            kind=kind,
            input_data=input_data,
            webhook_url=webhook_url,
            context=context,
        )
        try:
            leased = await self.gateway.lease(
                task_id,
                self.worker_id,
                self.settings.async_task_lease_seconds,
                context,
                lease_epoch=None,
            )
        except Exception:
            await self.gateway.cancel(task_id, context)
            raise
        if (
            leased.lease_owner_id != self.worker_id
            or leased.lease_epoch <= 0
            or leased.status.terminal
        ):
            await self.gateway.cancel(task_id, context)
            raise AsyncTaskRejectedError("async task lease was not acquired")

        handle = ExecutionHandle(
            task_id=task_id,
            kind=kind,
            context=context,
            lease_epoch=leased.lease_epoch,
        )
        async with self._registry_lock:
            if self._closing or len(self._handles) >= self.settings.async_task_max_inflight:
                await self.gateway.cancel(task_id, context)
                raise AsyncTaskRejectedError("async task capacity is exhausted")
            self._handles[task_id] = handle
            handle.work = asyncio.create_task(
                self._run(handle, execute),
                name=f"async-task-{task_id}",
            )
            self._metrics.submitted(kind)
            self._metrics.inflight(1, kind)
        return AgentAsyncTask.from_central(created)

    async def get(self, task_id: str, context: RunContext) -> AgentAsyncTask:
        task = await self.gateway.get(task_id, context)
        if task is None or not task.agent_kind:
            raise AsyncTaskNotFoundError(task_id)
        return AgentAsyncTask.from_central(task)

    async def list(self, context: RunContext) -> list[AgentAsyncTask]:
        tasks = await self.gateway.list(context)
        return [AgentAsyncTask.from_central(task) for task in tasks if task.agent_kind]

    async def cancel(self, task_id: str, context: RunContext) -> bool:
        task = await self.gateway.get(task_id, context)
        if task is None or not task.agent_kind or task.status.terminal:
            raise AsyncTaskNotFoundError(task_id)
        cancelled = await self.gateway.cancel(task_id, context)
        if not cancelled:
            current = await self.gateway.get(task_id, context)
            cancelled = current is not None and current.status is AsyncTaskStatus.CANCELLED
        if cancelled:
            async with self._registry_lock:
                handle = self._handles.get(task_id)
            if handle is not None:
                handle.stop.set()
                if handle.work is not None:
                    handle.work.cancel()
        return cancelled

    async def shutdown(self) -> None:
        self._closing = True
        async with self._registry_lock:
            handles = list(self._handles.values())
        work = [handle.work for handle in handles if handle.work is not None]
        if work:
            _, pending = await asyncio.wait(
                work,
                timeout=self.settings.async_task_drain_timeout_seconds,
            )
            if pending:
                by_work = {handle.work: handle for handle in handles}
                for task in pending:
                    handle = by_work[task]
                    handle.stop.set()
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
        async with self._registry_lock:
            self._handles.clear()
        await self.gateway.close()

    async def _run(self, handle: ExecutionHandle, execute: ExecuteAsyncTask) -> None:
        heartbeat: asyncio.Task[None] | None = None
        queued = True
        running = False
        sink = _TaskProgressSink(
            self.gateway,
            handle,
            self.worker_id,
            self.settings.async_task_progress_enabled,
        )
        try:
            self._metrics.backlog(1, handle.kind)
            heartbeat = asyncio.create_task(self._heartbeat(handle))
            async with asyncio.timeout(self._runtime_seconds(handle.context)):
                async with self._semaphore:
                    self._metrics.backlog(-1, handle.kind)
                    queued = False
                    self._metrics.running(1, handle.kind)
                    running = True
                    result = await execute(sink)
            if handle.stop.is_set():
                return
            terminal = await self._complete_once(
                handle,
                AsyncTaskStatus.SUCCEEDED,
                result=self._json_value(result),
                error=None,
            )
            self._metrics.completed(handle.kind, terminal.status.value)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            handle.stop.set()
            terminal = await self._complete_once(
                handle,
                AsyncTaskStatus.FAILED,
                result=None,
                error="ASYNC_TASK_DEADLINE_EXCEEDED",
            )
            self._metrics.completed(handle.kind, terminal.status.value)
        except Exception:
            terminal = await self._complete_once(
                handle,
                AsyncTaskStatus.FAILED,
                result=None,
                error="ASYNC_TASK_EXECUTION_FAILED",
            )
            self._metrics.completed(handle.kind, terminal.status.value)
        finally:
            if queued:
                self._metrics.backlog(-1, handle.kind)
            if running:
                self._metrics.running(-1, handle.kind)
            self._metrics.inflight(-1, handle.kind)
            if heartbeat is not None:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
            async with self._registry_lock:
                self._handles.pop(handle.task_id, None)

    async def _heartbeat(self, handle: ExecutionHandle) -> None:
        try:
            while not handle.stop.is_set():
                await asyncio.sleep(self.settings.async_task_heartbeat_seconds)
                task = await self.gateway.lease(
                    handle.task_id,
                    self.worker_id,
                    self.settings.async_task_lease_seconds,
                    handle.context,
                    lease_epoch=handle.lease_epoch,
                )
                if (
                    task.status.terminal
                    or task.lease_owner_id != self.worker_id
                    or task.lease_epoch != handle.lease_epoch
                ):
                    handle.stop.set()
                    if handle.work is not None:
                        handle.work.cancel()
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            self._metrics.heartbeat_failed()
            if not handle.stop.is_set():
                handle.stop.set()
                if handle.work is not None:
                    handle.work.cancel()

    async def _complete_once(
        self,
        handle: ExecutionHandle,
        status: AsyncTaskStatus,
        *,
        result: Any | None,
        error: str | None,
    ) -> CentralAsyncTask:
        async with handle.terminal_lock:
            if handle.stop.is_set() and status is AsyncTaskStatus.SUCCEEDED:
                current = await self.gateway.get(handle.task_id, handle.context)
                if current is None:
                    raise AsyncTaskNotFoundError(handle.task_id)
                return current
            updated = await self.gateway.update_status(
                handle.task_id,
                status,
                result=result,
                error=error,
                worker_id=self.worker_id,
                lease_epoch=handle.lease_epoch,
                context=handle.context,
            )
            if updated.status is not status and not updated.status.terminal:
                raise AsyncTaskRejectedError("async task terminal transition was rejected")
            return updated

    def _validate_deadline(self, context: RunContext) -> None:
        if context.token_expires_at is None:
            return
        remaining = (context.token_expires_at - datetime.now(UTC)).total_seconds()
        minimum = (
            self.settings.async_task_token_safety_seconds
            + self.settings.async_task_request_timeout_seconds
            + self.settings.async_task_heartbeat_seconds
        )
        if remaining <= minimum:
            raise AsyncTaskRejectedError("internal token lifetime is too short")

    def _runtime_seconds(self, context: RunContext) -> float:
        configured = self.settings.async_task_max_runtime_seconds
        if context.token_expires_at is None:
            return configured
        token_bound = (
            context.token_expires_at - datetime.now(UTC)
        ).total_seconds() - self.settings.async_task_token_safety_seconds
        return max(0.001, min(configured, token_bound))

    @staticmethod
    def _json_value(value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump(by_alias=True, mode="json")
        return value
