"""中央检查点恢复会话; 所有状态先确认持久化, 再推进业务操作。"""

import asyncio
import hashlib
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any, Protocol, TypeVar
from uuid import uuid4

from pydantic import BaseModel

from agentscope_platform.application.dag_budget import DagBudgetExceeded, DagDeadlineExceeded
from agentscope_platform.domain.dag_checkpoint import (
    CheckpointOperation,
    CheckpointStatus,
    DagCheckpoint,
    DagCheckpointState,
)

T = TypeVar("T", bound=BaseModel)


class DagCheckpointUnavailable(RuntimeError):
    """中央暂不可用或租约冲突, 停止本执行器并保留接管机会。"""


class CheckpointGateway(Protocol):
    """应用层只依赖版本化读取/CAS, 基础设施绑定任务身份和租约。"""

    async def read(self) -> DagCheckpoint: ...

    async def save(self, revision: int, state: DagCheckpointState) -> DagCheckpoint: ...


def fingerprint(value: Any) -> str:
    """规范JSON摘要绑定输入、权限和依赖结果版本。"""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


class DagRecovery:
    """一个租约内共享锁串行保存快照, 避免并行节点覆盖彼此进度。"""

    def __init__(self, gateway: CheckpointGateway, checkpoint: DagCheckpoint) -> None:
        if checkpoint.state is None:
            raise ValueError("checkpoint state required")
        self.gateway = gateway
        self.state = checkpoint.state
        self.revision = checkpoint.revision
        self.lock = asyncio.Lock()
        self.failed = False
        self.failure: BaseException | None = None

    @classmethod
    async def open(cls, gateway: CheckpointGateway, binding: str, seconds: float) -> "DagRecovery":
        """新任务固定期限; 恢复不得刷新期限或替换输入/身份摘要。"""
        checkpoint = await gateway.read()
        if checkpoint.state is None:
            checkpoint = await gateway.save(
                0, DagCheckpointState(binding=binding, deadline=int((time.time() + seconds) * 1000))
            )
        if checkpoint.state is None or checkpoint.state.binding != binding:
            raise ValueError("DAG checkpoint execution binding mismatch")
        recovery = cls(gateway, checkpoint)
        recovery.ensure_active()
        return recovery

    def ensure_active(self) -> None:
        """任何持久化未知结果都使当前会话失败关闭, 禁止继续调用模型。"""
        if self.failed:
            if isinstance(self.failure, DagCheckpointUnavailable):
                raise self.failure
            raise RuntimeError("DAG checkpoint session failed")
        if time.time() * 1000 >= self.state.deadline:
            raise DagDeadlineExceeded("DAG recovery deadline exceeded")

    async def _save(self) -> None:
        self.ensure_active()
        try:
            reply = await self.gateway.save(self.revision, self.state.model_copy(deep=True))
            if reply.revision != self.revision + 1 or reply.state != self.state:
                raise ValueError("DAG checkpoint acknowledgement mismatch")
            self.revision = reply.revision
        except BaseException as exc:
            self.failed = True
            self.failure = exc
            raise

    async def reserve(self, tokens: int, max_calls: int, max_tokens: int) -> None:
        """模型调用前写入累计预留; 崩溃或未知usage永不退款。"""
        async with self.lock:
            self.ensure_active()
            if (
                tokens <= 0
                or self.state.model_calls >= max_calls
                or self.state.reserved_tokens + tokens > max_tokens
            ):
                raise DagBudgetExceeded("DAG durable model budget exceeded")
            self.state.model_calls += 1
            self.state.reserved_tokens += tokens
            await self._save()

    async def run(
        self,
        key: str,
        inputs: Any,
        invoke: Callable[[], Awaitable[T]],
        result_type: type[T],
        reusable: Callable[[T], bool] = lambda result: True,
    ) -> T:
        """先写RUNNING再执行, 结果提交后才交给下游; 接管可重做未知只读操作。"""
        digest = fingerprint(inputs)
        async with self.lock:
            self.ensure_active()
            old = self.state.operations.get(key)
            if (
                old
                and old.fingerprint == digest
                and old.status is CheckpointStatus.DONE
                and old.reusable
            ):
                return result_type.model_validate(old.result)
            if key not in self.state.operations and len(self.state.operations) >= 256:
                raise DagBudgetExceeded("DAG checkpoint operation capacity exceeded")
            entry = CheckpointOperation(
                fingerprint=digest, version=str(uuid4()), status=CheckpointStatus.RUNNING
            )
            self.state.operations[key] = entry
            await self._save()
        result = await invoke()
        async with self.lock:
            entry.result = result.model_dump(by_alias=True, mode="json")
            entry.status = CheckpointStatus.DONE
            entry.reusable = reusable(result)
            await self._save()
        return result


_active: ContextVar[DagRecovery | None] = ContextVar("dag_recovery", default=None)


def current_recovery() -> DagRecovery | None:
    """只在当前任务协程树中传播恢复上下文, 不共享租户状态。"""
    return _active.get()


@asynccontextmanager
async def recovery_scope(recovery: DagRecovery) -> AsyncIterator[None]:
    """固定绝对期限覆盖规划、执行、重规划及检查点IO。"""
    token = _active.set(recovery)
    try:
        recovery.ensure_active()
        async with asyncio.timeout(max(0, recovery.state.deadline / 1000 - time.time())):
            yield
    finally:
        _active.reset(token)


async def checkpoint_step[T: BaseModel](
    key: str,
    inputs: Any,
    invoke: Callable[[], Awaitable[T]],
    result_type: type[T],
    reusable: Callable[[T], bool] = lambda result: True,
) -> T:
    """普通同步/v1调用保持原行为, v2走持久检查点。"""
    recovery = current_recovery()
    return (
        await invoke()
        if recovery is None
        else await recovery.run(key, inputs, invoke, result_type, reusable)
    )
