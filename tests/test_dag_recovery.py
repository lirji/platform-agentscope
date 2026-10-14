"""检查点应用语义: 通过新会话模拟进程内状态完全丢失。"""

import asyncio
import time

import pytest
from pydantic import BaseModel

from agentscope_platform.application.dag_budget import DagBudgetExceeded, DagDeadlineExceeded
from agentscope_platform.application.dag_recovery import DagRecovery, fingerprint
from agentscope_platform.domain.dag_checkpoint import DagCheckpoint, DagCheckpointState


class Result(BaseModel):
    value: int


class MemoryCheckpoint:
    def __init__(self):
        self.snapshot = DagCheckpoint(revision=0)
        self.fail = False

    async def read(self):
        return self.snapshot.model_copy(deep=True)

    async def save(self, revision: int, state: DagCheckpointState):
        if self.fail:
            raise RuntimeError("connection lost")
        assert revision == self.snapshot.revision
        self.snapshot = DagCheckpoint(revision=revision + 1, state=state.model_copy(deep=True))
        return self.snapshot.model_copy(deep=True)


@pytest.mark.asyncio
async def test_recovery_reuses_completed_and_repeats_running_with_retained_budget():
    store = MemoryCheckpoint()
    first = await DagRecovery.open(store, fingerprint("task"), 30)
    calls = []

    async def done():
        calls.append("done")
        return Result(value=1)

    async def crash():
        await first.reserve(100, 3, 300)
        raise asyncio.CancelledError()

    await first.run("a", {}, done, Result)
    with pytest.raises(asyncio.CancelledError):
        await first.run("b", {}, crash, Result)
    second = await DagRecovery.open(store, fingerprint("task"), 999)
    assert second.state.deadline == first.state.deadline
    assert second.state.model_calls == 1
    assert (await second.run("a", {}, done, Result)).value == 1
    assert calls == ["done"]
    await second.run("b", {}, done, Result)
    await second.reserve(100, 2, 300)
    with pytest.raises(DagBudgetExceeded):
        await second.reserve(100, 2, 300)


@pytest.mark.asyncio
async def test_input_changes_and_nonreusable_results_get_new_versions():
    store = MemoryCheckpoint()
    first = await DagRecovery.open(store, fingerprint("task"), 30)

    async def done():
        return Result(value=1)

    await first.run("a", {"dep": "v1"}, done, Result)
    version = first.state.operations["a"].version
    await first.run("a", {"dep": "v2"}, done, Result, lambda _: False)
    assert first.state.operations["a"].version != version
    version = first.state.operations["a"].version
    second = await DagRecovery.open(store, fingerprint("task"), 30)
    await second.run("a", {"dep": "v2"}, done, Result)
    assert second.state.operations["a"].version != version
    with pytest.raises(ValueError, match="binding"):
        await DagRecovery.open(store, fingerprint("other-tenant"), 30)


@pytest.mark.asyncio
async def test_failed_persistence_stops_model_and_expired_checkpoint_stops_recovery():
    store = MemoryCheckpoint()
    first = await DagRecovery.open(store, fingerprint("task"), 30)
    store.fail = True
    called = False

    async def invoke():
        nonlocal called
        called = True
        return Result(value=1)

    with pytest.raises(RuntimeError, match="connection lost"):
        await first.run("a", {}, invoke, Result)
    assert not called
    with pytest.raises(RuntimeError, match="session failed"):
        await first.run("b", {}, invoke, Result)
    store.fail = False
    store.snapshot.state.deadline = int(time.time() * 1000) - 1
    with pytest.raises(DagDeadlineExceeded):
        await DagRecovery.open(store, fingerprint("task"), 30)


@pytest.mark.asyncio
async def test_parallel_saves_do_not_lose_nodes():
    store = MemoryCheckpoint()
    session = await DagRecovery.open(store, fingerprint("task"), 30)

    async def invoke():
        await asyncio.sleep(0)
        return Result(value=1)

    await asyncio.gather(*(session.run(str(i), {}, invoke, Result) for i in range(20)))
    assert len(store.snapshot.state.operations) == 20
    assert all(op.status == "DONE" for op in store.snapshot.state.operations.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", [False, True])
async def test_real_dag_resumes_after_node_commit_and_invalidates_tool_descendants(tool):
    from agentscope_platform.application.dag import AgentDagApplicationService
    from agentscope_platform.application.dag_recovery import recovery_scope
    from agentscope_platform.domain.agent import AgentExecution, AgentStep
    from test_dag_optimization import Synthesis, request
    from test_dag_service import context

    class Runner:
        def __init__(self):
            self.calls = []
            self.crash = True

        async def run(self, goal, ctx):
            key = "source" if "Your sub-task [source]" in goal else "dependent"
            self.calls.append(key)
            if key == "dependent" and self.crash:
                raise asyncio.CancelledError()
            steps = (
                (AgentStep(n=1, action="rag_search", observation="data"),)
                if tool and key == "source"
                else ()
            )
            return AgentExecution("answer", "DONE", steps=steps)

    store = MemoryCheckpoint()
    first = await DagRecovery.open(store, fingerprint("task"), 30)
    runner, synthesis = Runner(), Synthesis()
    service = AgentDagApplicationService(runner, optimized=True, synthesizer=synthesis)
    with pytest.raises(asyncio.CancelledError):
        async with recovery_scope(first):
            await service.run(request(), context())
    assert store.snapshot.state.operations["node:1:source"].status == "DONE"
    runner.crash = False
    second = await DagRecovery.open(store, fingerprint("task"), 30)
    async with recovery_scope(second):
        reply = await service.run(request(), context())
    assert reply.synthesis.stop_reason == "DONE"
    assert runner.calls.count("source") == (2 if tool else 1)
    assert runner.calls.count("dependent") == 2
    third = await DagRecovery.open(store, fingerprint("task"), 30)
    async with recovery_scope(third):
        await service.run(request(), context())
    assert runner.calls.count("dependent") == (3 if tool else 2)
    assert len(synthesis.inputs) == (2 if tool else 1)


@pytest.mark.asyncio
async def test_planner_review_and_replan_are_restored_without_restarting_quality_loop():
    from agentscope_platform.application.dag import AgentDagApplicationService, DagReviewPolicy
    from agentscope_platform.application.dag_recovery import recovery_scope
    from agentscope_platform.application.planning import AgentDagPlanningService
    from agentscope_platform.domain.agent import AgentExecution
    from agentscope_platform.domain.dag import (
        AgentDagCritique,
        AgentPlanRunRequest,
        DagPlan,
        DagPlanTask,
    )
    from test_dag_optimization import Synthesis
    from test_dag_service import context

    calls = {"plan": 0, "review": 0, "revise": 0, "node": 0}

    class Planner:
        async def plan(self, *args):
            calls["plan"] += 1
            return DagPlan(tasks=[DagPlanTask(id="one", description="first")])

    class Reviewer:
        async def critique(self, *args):
            calls["review"] += 1
            return AgentDagCritique(correctness=0, completeness=0, clarity=0, mainIssue="improve")

        async def revise(self, *args):
            calls["revise"] += 1
            return DagPlan(tasks=[DagPlanTask(id="two", description="second")])

    class Runner:
        async def run(self, goal, ctx):
            calls["node"] += 1
            if calls["node"] == 2:
                raise asyncio.CancelledError()
            return AgentExecution("answer", "DONE")

    service = AgentDagPlanningService(
        Planner(),
        AgentDagApplicationService(
            Runner(),
            optimized=True,
            synthesizer=Synthesis(),
            reviewer=Reviewer(),
            review_policy=DagReviewPolicy(enabled=True, max_replans=1),
        ),
    )
    store = MemoryCheckpoint()
    first = await DagRecovery.open(store, fingerprint("task"), 30)
    with pytest.raises(asyncio.CancelledError):
        async with recovery_scope(first):
            await service.plan_and_run(AgentPlanRunRequest(goal="goal"), context())
    second = await DagRecovery.open(store, fingerprint("task"), 30)
    async with recovery_scope(second):
        result = await service.plan_and_run(AgentPlanRunRequest(goal="goal"), context())
    assert len(result.attempts) == 2
    assert calls == {"plan": 1, "review": 2, "revise": 1, "node": 3}


@pytest.mark.asyncio
async def test_real_model_reservation_cannot_reset_on_new_execution_scope():
    from agentscope.message import UserMsg
    from agentscope.model import ChatResponse

    from agentscope_platform.application.dag_budget import DagRunLimits, dag_execution_scope
    from agentscope_platform.application.dag_recovery import recovery_scope
    from agentscope_platform.infrastructure.agentscope.dag_budget_model import dag_budgeted_call
    from test_dag_service import context

    store = MemoryCheckpoint()
    calls = 0

    async def provider(*args, **kwargs):
        nonlocal calls
        calls += 1
        return ChatResponse(content=[], is_last=True)

    first = await DagRecovery.open(store, fingerprint("task"), 30)
    async with (
        recovery_scope(first),
        dag_execution_scope(DagRunLimits(max_model_calls=1), context()),
    ):
        await dag_budgeted_call(provider, [UserMsg(name="u", content="hello")], output_limit=10)
    second = await DagRecovery.open(store, fingerprint("task"), 30)
    with pytest.raises(DagBudgetExceeded):
        async with (
            recovery_scope(second),
            dag_execution_scope(DagRunLimits(max_model_calls=1), context()),
        ):
            await dag_budgeted_call(provider, [UserMsg(name="u", content="hello")], output_limit=10)
    assert calls == 1


@pytest.mark.asyncio
async def test_checkpoint_outage_remains_recoverable_when_runner_catches_error():
    from agentscope_platform.application.dag_recovery import DagCheckpointUnavailable

    store = MemoryCheckpoint()
    session = await DagRecovery.open(store, fingerprint("task"), 30)

    async def outage(*args):
        raise DagCheckpointUnavailable("unavailable")

    store.save = outage
    with pytest.raises(DagCheckpointUnavailable):
        await session.reserve(1, 10, 100)
    with pytest.raises(DagCheckpointUnavailable):
        session.ensure_active()


@pytest.mark.asyncio
async def test_safe_fallback_plan_is_persisted_before_node_execution():
    from agentscope_platform.application.dag import AgentDagApplicationService
    from agentscope_platform.application.dag_recovery import recovery_scope
    from agentscope_platform.application.planning import AgentDagPlanningService
    from agentscope_platform.application.ports import DagPlanningError
    from agentscope_platform.domain.agent import AgentExecution
    from agentscope_platform.domain.dag import AgentPlanRunRequest
    from test_dag_optimization import Synthesis
    from test_dag_service import context

    calls = 0

    class Planner:
        async def plan(self, *args):
            nonlocal calls
            calls += 1
            raise DagPlanningError("unavailable")

    class Runner:
        crash = True

        async def run(self, *args):
            if self.crash:
                raise asyncio.CancelledError()
            return AgentExecution("answer", "DONE")

    runner = Runner()
    service = AgentDagPlanningService(
        Planner(), AgentDagApplicationService(runner, optimized=True, synthesizer=Synthesis())
    )
    store = MemoryCheckpoint()
    first = await DagRecovery.open(store, fingerprint("task"), 30)
    with pytest.raises(asyncio.CancelledError):
        async with recovery_scope(first):
            await service.plan_and_run(AgentPlanRunRequest(goal="goal"), context())
    runner.crash = False
    second = await DagRecovery.open(store, fingerprint("task"), 30)
    async with recovery_scope(second):
        await service.plan_and_run(AgentPlanRunRequest(goal="goal"), context())
    assert calls == 1
