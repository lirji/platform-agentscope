"""有界的依赖就绪调度, 不保存跨请求任务结果或框架状态。"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass


@dataclass
class _TenantSlots:
    semaphore: asyncio.Semaphore
    users: int = 0


class DagWorkerCapacity:
    """同一进程的 DAG 共享总槽位, 租户先取自身槽位以免阻塞其他租户。"""

    def __init__(self, total: int, per_tenant: int) -> None:
        self._global = asyncio.Semaphore(max(1, total))
        self._per_tenant = max(1, min(per_tenant, total))
        self._tenants: dict[str, _TenantSlots] = {}

    @asynccontextmanager
    async def acquire(self, tenant_id: str) -> AsyncIterator[None]:
        """租户槽位在最后一个持有者/等待者退出后清理, 避免身份字典持续增长。"""
        slots = self._tenants.setdefault(
            tenant_id, _TenantSlots(asyncio.Semaphore(self._per_tenant))
        )
        slots.users += 1
        try:
            async with slots.semaphore, self._global:
                yield
        finally:
            slots.users -= 1
            if slots.users == 0:
                del self._tenants[tenant_id]


async def run_ready[Result](
    dependencies: Mapping[str, frozenset[str]],
    execute: Callable[[str, Mapping[str, Result]], Awaitable[Result]],
) -> dict[str, Result]:
    """完成节点立即释放后继; 任何基础设施异常或取消都收敛所有已创建协程。"""

    async def invoke(task_id: str, upstream: Mapping[str, Result]) -> Result:
        return await execute(task_id, upstream)

    results: dict[str, Result] = {}
    submitted: set[str] = set()
    pending: dict[asyncio.Task[Result], str] = {}
    try:
        while len(results) < len(dependencies):
            for task_id, upstream in dependencies.items():
                if task_id not in submitted and upstream.issubset(results):
                    # 每个节点只获得其直接依赖的快照, 不读取同轮可变共享结果。
                    work = asyncio.create_task(invoke(task_id, {d: results[d] for d in upstream}))
                    pending[work] = task_id
                    submitted.add(task_id)
            if not pending:
                raise ValueError("task graph cannot make progress")
            done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            # 在开启下一轮前取出全部异常, 不让异常完成被当作依赖成功。
            for work in done:
                results[pending.pop(work)] = work.result()
        return results
    finally:
        for work in pending:
            work.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
