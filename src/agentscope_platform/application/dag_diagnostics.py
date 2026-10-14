"""请求局部诊断会话; 观测失败不改变模型、预算、检查点或业务终态。"""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import (
    AbstractAsyncContextManager,
    AsyncExitStack,
    asynccontextmanager,
    contextmanager,
)
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from time import monotonic, time
from typing import Literal, Protocol, TypedDict
from uuid import uuid4

from agentscope_platform.application.ports import ProgressSink
from agentscope_platform.domain.agent import RunContext
from agentscope_platform.domain.dag_diagnostics import (
    SUCCESS_STOP_REASON,
    DagCriticalPath,
    DagDiagnosticEvent,
    DagDiagnosticReason,
    DagDiagnosticSummary,
    DagModelDiagnostic,
    DagOperationDiagnostic,
    DagRole,
)

log = logging.getLogger(__name__)
MAX_RECORDS = 256
DELIVERY_TIMEOUT_SECONDS = 0.25


class _Identity(TypedDict):
    execution_id: str
    trace_id: str
    tenant_id: str
    central_task_id: str | None
    lease_epoch: int | None


@dataclass(frozen=True)
class _TaskMetadata:
    """中央租约显式传入, v1整任务接管也不能冒充完整消费历史。"""

    task_id: str
    lease_epoch: int
    deadline: float


_task_metadata: ContextVar[_TaskMetadata | None] = ContextVar("dag_diagnostic_task", default=None)


@contextmanager
def diagnostic_task_scope(task_id: str, lease_epoch: int, deadline: float) -> Iterator[None]:
    """异步任务管理器提供权威关联信息, 模型和业务输入不能覆盖。"""
    token = _task_metadata.set(_TaskMetadata(task_id, lease_epoch, deadline))
    try:
        yield
    finally:
        _task_metadata.reset(token)


class DagDiagnosticObserver(Protocol):
    """基础设施负责日志与指标; 应用层不依赖观测 SDK。"""

    def record(self, event: DagDiagnosticEvent) -> None: ...


class DiagnosticSession:
    """有界片段摘要; 不保留业务输入/结果, 不跨请求共享租户数据。"""

    def __init__(
        self,
        context: RunContext,
        observer: DagDiagnosticObserver | None,
        progress: ProgressSink | None,
        resumed: bool,
        deadline: float | None = None,
    ) -> None:
        task = _task_metadata.get()
        self.identity: _Identity = {
            "execution_id": uuid4().hex,
            "trace_id": context.trace_id,
            "tenant_id": context.identity.tenant_id,
            "central_task_id": task.task_id if task else None,
            "lease_epoch": task.lease_epoch if task else None,
        }
        self.observer = observer
        self.owner = (context.identity.tenant_id, context.identity.user_id, context.trace_id)
        self.progress = progress
        self.resumed = resumed or (task is not None and task.lease_epoch > 1)
        self.deadline = (
            min(deadline, task.deadline)
            if deadline is not None and task is not None
            else task.deadline
            if task is not None
            else deadline
        )
        self.started = monotonic()
        self.status = "DONE"
        self.accepted_by_threshold: bool | None = None
        self.calls = self.input_tokens = self.output_tokens = 0
        self.unknown = self.unpriced = self.delivery_failures = self.dropped = 0
        self.known_cost = Decimal(0)
        self.operations: dict[tuple[int, str], DagOperationDiagnostic] = {}
        self.graphs: dict[int, dict[str, tuple[str, ...]]] = {}
        self.pending: asyncio.Queue[DagDiagnosticEvent] = asyncio.Queue(maxsize=MAX_RECORDS)

    def observe(self, event: DagDiagnosticEvent) -> None:
        """不记录异常正文, 避免 exporter 故障泄漏业务数据或凭据。"""
        if self.observer is not None:
            try:
                self.observer.record(event)
            except Exception:
                self.delivery_failures += 1
                log.warning("DAG diagnostic observer failed")

    async def deliver(self, events: list[DagDiagnosticEvent]) -> None:
        """整批投递共用短期限; 不让慢任务事件服务拖住 DAG。"""
        if self.progress is None or asyncio.current_task() is None:
            return
        task = asyncio.current_task()
        if (task is not None and task.cancelling()) or self.delivery_timeout() <= 0:
            # 取消中的业务仍写同步诊断日志, 不延迟取消等待网络投递。
            self.delivery_failures += len(events)
            return
        try:
            async with asyncio.timeout(self.delivery_timeout()):
                for event in events:
                    await self.progress.emit(
                        f"dag-diagnostic-{event.kind}", event.model_dump(by_alias=True, mode="json")
                    )
        except Exception:
            self.delivery_failures += 1
            log.warning("DAG diagnostic event delivery failed")

    def delivery_timeout(self) -> float:
        """持久恢复外层仍有绝对期限, 临近期限时丢弃观测而非延长业务。"""
        return (
            min(DELIVERY_TIMEOUT_SECONDS, max(0.0, self.deadline - time() - 0.05))
            if self.deadline is not None
            else DELIVERY_TIMEOUT_SECONDS
        )

    def enqueue(self, event: DagDiagnosticEvent) -> None:
        """有界后台投递, 不让诊断 IO 进入节点依赖调度或模型截止时间。"""
        if self.progress is not None:
            try:
                self.pending.put_nowait(event)
            except asyncio.QueueFull:
                self.dropped += 1

    async def publish(self) -> None:
        """单发布协程保持片段内事件顺序, 结束时由会话显式取消并回收。"""
        while True:
            event = await self.pending.get()
            try:
                await self.deliver([event])
            finally:
                self.pending.task_done()

    def register_graph(self, attempt: int, graph: Mapping[str, tuple[str, ...]]) -> None:
        """规模超限只截断诊断, 不截断业务执行。"""
        if sum(len(g) for g in self.graphs.values()) + len(graph) <= MAX_RECORDS:
            self.graphs[attempt] = dict(graph)
        else:
            self.dropped += len(graph)

    def critical_paths(self) -> list[DagCriticalPath]:
        """图由编排器按稳定拓扑顺序注册, 缺失节点时明确标记不完整。"""
        paths = []
        for attempt, graph in self.graphs.items():
            scores: dict[str, tuple[float, list[str]]] = {}
            complete = True
            for node, dependencies in graph.items():
                operation = self.operations.get((attempt, node))
                complete &= operation is not None
                base, chain = max(
                    (scores[d] for d in dependencies if d in scores),
                    default=(0.0, []),
                    key=lambda item: item[0],
                )
                scores[node] = (base + (operation.execution_ms if operation else 0), [*chain, node])
            duration, chain = max(scores.values(), default=(0.0, []), key=lambda item: item[0])
            paths.append(
                DagCriticalPath(
                    attempt=attempt, node_ids=chain, execution_ms=duration, complete=complete
                )
            )
        return paths

    def summary(self) -> DagDiagnosticSummary:
        """估算总额仅对当前完整观测片段有效; 接管历史不完整时不输出总额。"""
        return DagDiagnosticSummary(
            **self.identity,
            status=self.status,
            accepted_by_threshold=self.accepted_by_threshold,
            duration_ms=_elapsed(self.started),
            resumed=self.resumed,
            history_complete=not self.resumed,
            observed_model_calls=self.calls,
            known_input_tokens=self.input_tokens,
            known_output_tokens=self.output_tokens,
            unknown_usage_calls=self.unknown,
            unpriced_calls=self.unpriced,
            known_estimated_cost_usd=self.known_cost,
            estimated_cost_usd=(
                self.known_cost if not (self.unknown or self.unpriced or self.resumed) else None
            ),
            delivery_failures=self.delivery_failures,
            dropped_records=self.dropped,
            critical_paths=self.critical_paths(),
        )


class DiagnosticOperation:
    """单操作局部计时与模型关联; 并行兄弟节点使用不同实例。"""

    def __init__(
        self, session: DiagnosticSession | None, role: DagRole, attempt: int, node_id: str | None
    ) -> None:
        self.session = session
        self.role, self.attempt, self.node_id = role, attempt, node_id
        self.operation_id = uuid4().hex
        self.started = monotonic()
        self.status, self.reason = "DONE", "executed"
        self.queue_ms = self.execution_ms = 0.0
        self.calls = 0
        self.unfinished_calls: set[Callable[[], None]] = set()

    @contextmanager
    def waiting(self) -> Iterator[None]:
        """槽位获取成功、失败或取消均记录已经等待的时间。"""
        started = monotonic()
        try:
            yield
        finally:
            self.queue_ms += _elapsed(started)

    @contextmanager
    def executing(self) -> Iterator[None]:
        """仅计算实际 runner 执行, 不把排队/检查点/SSE 耗时算成模型执行。"""
        started = monotonic()
        try:
            yield
        finally:
            self.execution_ms += _elapsed(started)

    def model_finished(
        self,
        model: str,
        status: Literal["DONE", "ERROR", "CANCELLED"],
        duration_ms: float,
        input_tokens: int | None,
        output_tokens: int | None,
        input_rate: Decimal | None,
        output_rate: Decimal | None,
    ) -> None:
        """仅模型适配器提交终态 usage; 复用路径不调用本方法。"""
        session = self.session
        if session is None:
            return
        valid_usage = (
            type(input_tokens) is int
            and type(output_tokens) is int
            and input_tokens >= 0
            and output_tokens >= 0
        )
        if not valid_usage:
            input_tokens = output_tokens = None
        cost = (
            (Decimal(input_tokens) * input_rate + Decimal(output_tokens) * output_rate)
            / Decimal(1_000_000)
            if input_tokens is not None
            and output_tokens is not None
            and input_rate is not None
            and output_rate is not None
            else None
        )
        event = DagModelDiagnostic(
            **session.identity,
            operation_id=self.operation_id,
            role=self.role,
            attempt=self.attempt,
            node_id=self.node_id,
            call_id=uuid4().hex,
            model=model,
            status=status,
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_rate_per_million=input_rate,
            output_rate_per_million=output_rate,
            estimated_cost_usd=cost,
        )
        self.calls += 1
        session.calls += 1
        session.input_tokens += input_tokens or 0
        session.output_tokens += output_tokens or 0
        session.unknown += int(not valid_usage)
        session.unpriced += int(input_rate is None or output_rate is None)
        session.known_cost += cost or Decimal(0)
        session.observe(event)
        session.enqueue(event)


_session: ContextVar[DiagnosticSession | None] = ContextVar("dag_diagnostic_session", default=None)
_operation: ContextVar[DiagnosticOperation | None] = ContextVar(
    "dag_diagnostic_operation", default=None
)


def current_diagnostics() -> DiagnosticSession | None:
    """只返回显式入口创建的当前请求会话。"""
    return _session.get()


def current_operation() -> DiagnosticOperation | None:
    """模型适配器读取当前协程的角色归属。"""
    return _operation.get()


def _elapsed(started: float) -> float:
    return max(0.0, (monotonic() - started) * 1000)


@asynccontextmanager
async def diagnostic_scope(
    context: RunContext,
    observer: DagDiagnosticObserver | None,
    progress: ProgressSink | None,
    *,
    resumed: bool = False,
    deadline: float | None = None,
) -> AsyncIterator[DiagnosticSession]:
    """规划与执行复用同一会话; finally 保证上下文不泄漏到后续请求。"""
    existing = _session.get()
    metadata = _task_metadata.get()
    if (
        existing is not None
        and existing.owner
        == (context.identity.tenant_id, context.identity.user_id, context.trace_id)
        and existing.identity["central_task_id"] == (metadata.task_id if metadata else None)
    ):
        yield existing
        return
    session = DiagnosticSession(context, observer, progress, resumed, deadline)
    token = _session.set(session)
    publisher = asyncio.create_task(session.publish()) if progress is not None else None
    try:
        yield session
    except BaseException as exc:
        session.status = "CANCELLED" if isinstance(exc, asyncio.CancelledError) else "ERROR"
        raise
    finally:
        _session.reset(token)
        duration_ms = _elapsed(session.started)
        if publisher is not None:
            try:
                task = asyncio.current_task()
                if (task is None or not task.cancelling()) and session.delivery_timeout() > 0:
                    async with asyncio.timeout(session.delivery_timeout()):
                        await session.pending.join()
            except TimeoutError:
                session.delivery_failures += 1
            finally:
                # 未完成事件不能被当成完整审计记录; 不留后台任务跨请求执行。
                session.dropped += session.pending.qsize()
                publisher.cancel()
                await asyncio.gather(publisher, return_exceptions=True)
        summary = session.summary()
        summary.duration_ms = duration_ms
        session.observe(summary)
        await session.deliver([summary])


@asynccontextmanager
async def diagnostic_operation(
    role: DagRole, attempt: int = 1, node_id: str | None = None
) -> AsyncIterator[DiagnosticOperation]:
    """所有终止路径都有操作记录, 只暴露稳定状态而非异常正文。"""
    session = _session.get()
    operation = DiagnosticOperation(session, role, attempt, node_id)
    token = _operation.set(operation)
    try:
        yield operation
    except BaseException as exc:
        operation.status = "CANCELLED" if isinstance(exc, asyncio.CancelledError) else "ERROR"
        raise
    finally:
        _operation.reset(token)
        for finalize in tuple(operation.unfinished_calls):
            finalize()
        if session is not None:
            event = DagOperationDiagnostic(
                **session.identity,
                operation_id=operation.operation_id,
                role=role,
                attempt=attempt,
                node_id=node_id,
                status=operation.status,
                reason=DagDiagnosticReason(operation.reason),
                duration_ms=_elapsed(operation.started),
                queue_ms=operation.queue_ms,
                execution_ms=operation.execution_ms,
                observed_model_calls=operation.calls,
            )
            if node_id is not None and role is DagRole.WORKER:
                if len(session.operations) < MAX_RECORDS:
                    session.operations[(attempt, node_id)] = event
                else:
                    session.dropped += 1
            if operation.status != SUCCESS_STOP_REASON:
                session.status = "PARTIAL"
            session.observe(event)
            session.enqueue(event)


@asynccontextmanager
async def diagnostic_worker_slot(slot: AbstractAsyncContextManager[None]) -> AsyncIterator[None]:
    """只测量获取容量的等待, 槽位释放仍由原容量管理器保证。"""
    async with AsyncExitStack() as stack:
        operation = current_operation()
        if operation is None:
            await stack.enter_async_context(slot)
        else:
            with operation.waiting():
                await stack.enter_async_context(slot)
        yield
