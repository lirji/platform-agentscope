"""请求级 DAG 执行预算; ContextVar 只传播当前调用, 不共享身份或跨请求计数。"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime

from agentscope_platform.domain.agent import RunContext


class DagBudgetExceeded(RuntimeError):
    """整次执行超出预算, 不可作为可恢复规划错误回退。"""


class DagDeadlineExceeded(RuntimeError):
    """规划、排队、执行和评审共用截止时间。"""


@dataclass(frozen=True, slots=True)
class DagRunLimits:
    """服务端执行上限, 不表示模型精确计费或性能承诺。"""

    timeout_seconds: float = 300
    max_model_calls: int = 64
    max_reserved_tokens: int = 240_000
    max_evidence_chars: int = 48_000


@dataclass
class DagRunBudget:
    """同一次运行协程共享计数, 准入不含 await 以保证单事件循环内原子性。"""

    limits: DagRunLimits
    owner: tuple[str, str, str]
    model_calls: int = 0
    reserved_tokens: int = 0
    exhausted: bool = False

    def reserve(self, tokens: int) -> None:
        """失败/未知 usage 保留预算, 禁止重试通过回收预留绕过限额。"""
        self.ensure_available()
        if (
            tokens <= 0
            or self.model_calls >= self.limits.max_model_calls
            or self.reserved_tokens + tokens > self.limits.max_reserved_tokens
        ):
            self.exhausted = True
            raise DagBudgetExceeded("DAG model budget exceeded")
        self.model_calls += 1
        self.reserved_tokens += tokens

    def ensure_available(self) -> None:
        """适配器即使把预算异常转换成业务结果, 外层仍失败关闭。"""
        if self.exhausted:
            raise DagBudgetExceeded("DAG model budget exceeded")


_active_budget: ContextVar[DagRunBudget | None] = ContextVar("dag_run_budget", default=None)


def current_dag_budget() -> DagRunBudget | None:
    """模型适配器读取当前请求的预算, 非 DAG 调用保持既有行为。"""
    return _active_budget.get()


@asynccontextmanager
async def dag_execution_scope(limits: DagRunLimits, context: RunContext) -> AsyncIterator[None]:
    """嵌套规划/执行共用一次预算和截止时间, 不因进入下一阶段重置。"""
    existing = _active_budget.get()
    owner = (context.identity.tenant_id, context.identity.user_id, context.trace_id)
    if existing is not None:
        if existing.owner != owner:
            raise DagBudgetExceeded("DAG execution scope owner mismatch")
        existing.ensure_available()
        yield
        existing.ensure_available()
        return
    budget = DagRunBudget(limits, owner)
    token = _active_budget.set(budget)
    seconds = limits.timeout_seconds
    if context.token_expires_at is not None:
        seconds = min(seconds, (context.token_expires_at - datetime.now(UTC)).total_seconds() - 2)
    timeout = asyncio.timeout(max(0, seconds))
    try:
        if seconds <= 0:
            raise DagDeadlineExceeded("DAG deadline exceeded")
        async with timeout:
            yield
            budget.ensure_available()
    except TimeoutError as exc:
        if timeout.expired():
            raise DagDeadlineExceeded("DAG deadline exceeded") from exc
        raise
    finally:
        _active_budget.reset(token)
