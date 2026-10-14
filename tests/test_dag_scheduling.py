from agentscope_platform.application.dag import AgentDagApplicationService
from test_dag_optimization import Synthesis, request
from test_dag_service import RecordingRunner, context


async def test_ready_child_starts_before_unrelated_slow_root_finishes():
    import asyncio

    child_started = asyncio.Event()
    release_slow = asyncio.Event()

    class DependencyRunner(RecordingRunner):
        async def run(self, goal, run_context):
            if "Your sub-task [slow]" in goal:
                await release_slow.wait()
            if "Your sub-task [child]" in goal:
                child_started.set()
            return await super().run(goal, run_context)

    service = AgentDagApplicationService(
        DependencyRunner(), optimized=True, synthesizer=Synthesis()
    )
    work = asyncio.create_task(
        service.run(
            request(
                [
                    {"id": "fast", "description": "fast"},
                    {"id": "slow", "description": "slow"},
                    {"id": "child", "description": "child", "dependsOn": ["fast"]},
                ]
            ),
            context(),
        )
    )
    try:
        await asyncio.wait_for(child_started.wait(), 0.3)
    finally:
        release_slow.set()
        reply = await work
    assert [r.task_id for r in reply.task_results] == ["fast", "slow", "child"]


async def test_worker_start_is_emitted_only_after_capacity_acquired():
    import asyncio

    first_started, release = asyncio.Event(), asyncio.Event()
    events = []

    class Runner(RecordingRunner):
        async def run(self, goal, run_context):
            first_started.set()
            await release.wait()
            return await super().run(goal, run_context)

    class Sink:
        async def emit(self, name, data):
            events.append((name, data))

    service = AgentDagApplicationService(
        Runner(), optimized=True, synthesizer=Synthesis(), max_parallel_workers=1
    )
    work = asyncio.create_task(
        service.run(
            request(
                [
                    {"id": "a", "description": "a"},
                    {"id": "b", "description": "b"},
                ]
            ),
            context(),
            Sink(),
        )
    )
    await first_started.wait()
    await asyncio.sleep(0)
    starts = [data for event, data in events if event == "dag-worker-start"]
    release.set()
    await work
    assert len(starts) == 1


async def test_shared_capacity_prevents_tenant_monopoly_and_cleans_up():
    import asyncio

    from agentscope_platform.application.dag_scheduler import DagWorkerCapacity

    capacity = DagWorkerCapacity(2, 1)
    a_started, b_started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    active = {}
    high = {}

    class Runner(RecordingRunner):
        async def run(self, goal, owner):
            tenant = owner.identity.tenant_id
            active[tenant] = active.get(tenant, 0) + 1
            high[tenant] = max(high.get(tenant, 0), active[tenant])
            (a_started if tenant == "a" else b_started).set()
            try:
                await release.wait()
                return await super().run(goal, owner)
            finally:
                active[tenant] -= 1

    runner = Runner()
    first = AgentDagApplicationService(
        runner, optimized=True, synthesizer=Synthesis(), capacity=capacity
    )
    second = AgentDagApplicationService(
        runner, optimized=True, synthesizer=Synthesis(), capacity=capacity
    )
    roots = request([{"id": "x", "description": "x"}, {"id": "y", "description": "y"}])
    a = asyncio.create_task(first.run(roots, context("a")))
    await a_started.wait()
    b = asyncio.create_task(second.run(roots, context("b")))
    try:
        await asyncio.wait_for(b_started.wait(), 0.5)
        assert sum(active.values()) == 2
    finally:
        release.set()
        await asyncio.gather(a, b)
    assert high == {"a": 1, "b": 1}
    assert not capacity._tenants


async def test_cancel_drains_children_without_starting_synthesis():
    import asyncio

    from agentscope_platform.application.dag_scheduler import DagWorkerCapacity

    started, release = asyncio.Event(), asyncio.Event()
    active = 0

    class Runner(RecordingRunner):
        async def run(self, goal, owner):
            nonlocal active
            active += 1
            started.set()
            try:
                await release.wait()
                return await super().run(goal, owner)
            finally:
                active -= 1

    capacity, synthesis = DagWorkerCapacity(1, 1), Synthesis()
    service = AgentDagApplicationService(
        Runner(), optimized=True, synthesizer=synthesis, capacity=capacity
    )
    work = asyncio.create_task(service.run(request(), context()))
    await started.wait()
    work.cancel()
    import pytest

    with pytest.raises(asyncio.CancelledError):
        await work
    assert active == 0
    assert not synthesis.inputs
    assert not capacity._tenants


async def test_infrastructure_error_cancels_other_roots():
    import asyncio

    import pytest

    slow_started, slow_stopped = asyncio.Event(), asyncio.Event()

    class Runner(RecordingRunner):
        async def run(self, goal, owner):
            if "Your sub-task [fail]" in goal:
                await slow_started.wait()
                raise RuntimeError("adapter failed")
            slow_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                slow_stopped.set()

    synthesis = Synthesis()
    service = AgentDagApplicationService(Runner(), optimized=True, synthesizer=synthesis)
    with pytest.raises(RuntimeError, match="adapter failed"):
        await service.run(
            request([{"id": "fail", "description": "fail"}, {"id": "slow", "description": "slow"}]),
            context(),
        )
    assert slow_stopped.is_set()
    assert not synthesis.inputs


async def test_overloaded_tenant_is_rejected_without_blocking_other_tenant():
    import asyncio

    import pytest

    from agentscope_platform.application.dag_scheduler import DagCapacityExceeded, DagWorkerCapacity

    capacity = DagWorkerCapacity(2, 1, max_inflight=3, max_tenant_inflight=1)
    async with capacity.acquire("a"):
        with pytest.raises(DagCapacityExceeded):
            async with capacity.acquire("a"):
                raise AssertionError("overloaded tenant entered")
        async with asyncio.timeout(0.5), capacity.acquire("b"):
            pass
    assert not capacity._tenants
