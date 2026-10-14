"""诊断必须解释执行而不能改变执行结果或把未知消费当成零。"""

import asyncio
from decimal import Decimal

import pytest

from agentscope_platform.application.dag_diagnostics import (
    diagnostic_operation,
    diagnostic_scope,
)
from agentscope_platform.domain.dag_diagnostics import DagRole
from test_dag_service import context


class Observer:
    def __init__(self):
        self.events = []

    def record(self, event):
        self.events.append(event)


class Sink:
    def __init__(self):
        self.events = []

    async def emit(self, event, data):
        self.events.append((event, data))


async def test_scopes_are_isolated_and_nested_scope_does_not_duplicate_summary():
    observer = Observer()

    async def run(tenant):
        async with diagnostic_scope(context(tenant), observer, None) as session:
            async with diagnostic_scope(context(tenant), observer, None) as nested:
                assert nested is session
                async with diagnostic_operation(DagRole.WORKER, 1, "node"):
                    await asyncio.sleep(0)

    await asyncio.gather(run("a"), run("b"))
    summaries = [e for e in observer.events if e.kind == "summary"]
    assert len(summaries) == 2
    assert len({e.execution_id for e in summaries}) == 2
    assert {e.tenant_id for e in summaries} == {"a", "b"}


async def test_unknown_usage_and_unconfigured_price_are_not_zero():
    observer = Observer()
    async with diagnostic_scope(context(), observer, None):
        async with diagnostic_operation(DagRole.PLANNER) as operation:
            operation.model_finished("model", "DONE", 1, None, None, None, None)
            operation.model_finished("model", "DONE", 2, 100, 20, None, None)
    calls = [e for e in observer.events if e.kind == "model"]
    assert calls[0].input_tokens is None
    assert all(e.estimated_cost_usd is None for e in calls)
    summary = observer.events[-1]
    assert summary.unknown_usage_calls == 1
    assert summary.unpriced_calls == 2
    assert summary.estimated_cost_usd is None
    assert summary.known_input_tokens == 100


async def test_explicit_zero_price_and_decimal_cost_are_supported():
    observer = Observer()
    async with diagnostic_scope(context(), observer, None):
        async with diagnostic_operation(DagRole.WORKER, 2, "a") as operation:
            operation.model_finished("m", "DONE", 1, 100, 50, Decimal(1), Decimal(2))
            operation.model_finished("m", "DONE", 1, 100, 50, Decimal(0), Decimal(0))
    assert observer.events[-1].estimated_cost_usd == Decimal("0.0002")


async def test_observer_failure_does_not_mask_business_error_or_cancellation():
    class Broken:
        def record(self, event):
            raise RuntimeError("secret diagnostic failure")

        async def emit(self, event, data):
            raise RuntimeError("secret diagnostic failure")

    with pytest.raises(ValueError, match="business"):
        async with diagnostic_scope(context(), Broken(), Broken()):
            async with diagnostic_operation(DagRole.WORKER):
                raise ValueError("business")
    observer = Observer()
    with pytest.raises(asyncio.CancelledError):
        async with diagnostic_scope(context(), observer, None):
            async with diagnostic_operation(DagRole.WORKER):
                raise asyncio.CancelledError()
    assert observer.events[-1].status == "CANCELLED"


@pytest.mark.parametrize("streaming", [False, True])
async def test_real_model_adapter_records_terminal_usage_once(monkeypatch, streaming):
    from agentscope.message import UserMsg
    from agentscope.model import ChatResponse, ChatUsage, OpenAIChatModel

    from agentscope_platform.infrastructure.agentscope.model_factory import build_openai_chat_model
    from test_api import settings

    async def provider(self, **kwargs):
        async def chunks():
            yield ChatResponse(
                content=[],
                is_last=False,
                usage=ChatUsage(input_tokens=3, output_tokens=2, time=0.1),
            )
            yield ChatResponse(
                content=[],
                is_last=True,
                usage=ChatUsage(input_tokens=10, output_tokens=5, time=0.2),
            )

        if streaming:
            return chunks()
        return ChatResponse(
            content=[], is_last=True, usage=ChatUsage(input_tokens=10, output_tokens=5, time=0.2)
        )

    monkeypatch.setattr(OpenAIChatModel, "__call__", provider)
    model = build_openai_chat_model(
        settings(
            agent_dag_cost_rates_configured=True,
            agent_input_cost_usd_per_million_tokens=1,
            agent_output_cost_usd_per_million_tokens=2,
        ),
        temperature=0,
        stream=streaming,
    )
    observer = Observer()
    async with diagnostic_scope(context(), observer, None):
        async with diagnostic_operation(DagRole.SYNTHESIS):
            reply = await model([UserMsg(name="u", content="private prompt")])
            if streaming:
                async for _ in reply:
                    pass
    calls = [e for e in observer.events if e.kind == "model"]
    assert len(calls) == 1
    assert (calls[0].input_tokens, calls[0].output_tokens) == (10, 5)
    assert calls[0].estimated_cost_usd == Decimal("0.00002")
    assert "private prompt" not in str(observer.events)


@pytest.mark.parametrize("failure", ["error", "cancel", "close"])
async def test_model_stream_failure_never_uses_partial_usage(failure):
    from agentscope.model import ChatResponse, ChatUsage

    from agentscope_platform.infrastructure.agentscope.diagnostic_model import observed_model_call

    closed = []

    async def provider():
        async def chunks():
            try:
                yield ChatResponse(
                    content=[],
                    is_last=False,
                    usage=ChatUsage(input_tokens=9, output_tokens=2, time=0),
                )
                if failure == "error":
                    raise ValueError("provider secret")
                raise asyncio.CancelledError()
            finally:
                closed.append(True)

        return chunks()

    observer = Observer()
    async with diagnostic_scope(context(), observer, None):
        async with diagnostic_operation(DagRole.WORKER):
            stream = await observed_model_call(
                provider, model="m", input_rate=None, output_rate=None
            )
            await anext(stream)
            if failure == "close":
                await stream.aclose()
            else:
                with pytest.raises(ValueError if failure == "error" else asyncio.CancelledError):
                    await anext(stream)
    calls = [e for e in observer.events if e.kind == "model"]
    assert len(calls) == 1 and closed == [True]
    assert calls[0].input_tokens is None
    assert calls[0].status == ("ERROR" if failure == "error" else "CANCELLED")


async def test_all_roles_replan_and_reuse_use_actual_model_usage(monkeypatch):
    import json

    from agentscope.message import TextBlock
    from agentscope.model import ChatResponse, ChatUsage, OpenAIChatModel

    from agentscope_platform.application.dag import AgentDagApplicationService, DagReviewPolicy
    from agentscope_platform.application.dag_diagnostics import current_operation
    from agentscope_platform.application.planning import AgentDagPlanningService
    from agentscope_platform.domain.agent import AgentExecution
    from agentscope_platform.domain.dag import AgentPlanRunRequest
    from agentscope_platform.infrastructure.agentscope.planner import AgentScopeDagPlanner
    from agentscope_platform.infrastructure.agentscope.reviewer import AgentScopeDagQualityReviewer
    from agentscope_platform.infrastructure.agentscope.text_generator import AgentScopeTextGenerator
    from test_api import settings

    plan = {"tasks": [{"id": "a", "description": "analyze", "dependsOn": []}]}

    async def provider(self, **kwargs):
        operation = current_operation()
        if operation.role in {DagRole.PLANNER, DagRole.REPLANNER}:
            answer = json.dumps(plan)
        elif operation.role is DagRole.CRITIC:
            score = 0.1 if operation.attempt == 1 else 1
            answer = json.dumps(
                dict(correctness=score, completeness=score, clarity=score, mainIssue="improve")
            )
        else:
            answer = "grounded answer"
        return ChatResponse(
            content=[TextBlock(text=answer)],
            is_last=True,
            usage=ChatUsage(input_tokens=10, output_tokens=5, time=0),
        )

    monkeypatch.setattr(OpenAIChatModel, "__call__", provider)
    config = settings(
        agent_dag_optimization_enabled=True,
        agent_dag_cost_rates_configured=True,
        agent_input_cost_usd_per_million_tokens=1,
        agent_output_cost_usd_per_million_tokens=2,
    )
    generator = AgentScopeTextGenerator(config)

    class Runner:
        async def run(self, goal, owner):
            return AgentExecution(await generator.generate("worker", goal, owner), "DONE")

    observer, sink = Observer(), Sink()
    dag = AgentDagApplicationService(
        Runner(),
        optimized=True,
        synthesizer=generator,
        reviewer=AgentScopeDagQualityReviewer(config),
        review_policy=DagReviewPolicy(enabled=True),
        diagnostics_enabled=True,
        diagnostic_observer=observer,
    )
    reply = await AgentDagPlanningService(AgentScopeDagPlanner(config), dag).plan_and_run(
        AgentPlanRunRequest(goal="private business question"), context(), progress=sink
    )
    calls = [e for e in observer.events if e.kind == "model"]
    assert reply.accepted_by_threshold
    assert {e.role for e in calls} == set(DagRole)
    assert len(calls) == 7
    assert len([e for e in calls if e.role is DagRole.WORKER]) == 1
    summary = observer.events[-1]
    assert summary.observed_model_calls == 7
    assert summary.known_input_tokens == 70
    assert summary.estimated_cost_usd == Decimal("0.00014")
    reused = [e for e in observer.events if e.kind == "operation" and e.reason == "replan_reused"]
    assert len(reused) == 1 and reused[0].observed_model_calls == 0
    assert reused[0].execution_ms == 0
    assert len([e for e in observer.events if e.kind == "summary"]) == 1
    assert all(
        "private business question" not in str(data)
        for event, data in sink.events
        if event.startswith("dag-diagnostic")
    )
    assert sink.events[-1][0] == "dag-diagnostic-summary"


@pytest.mark.parametrize("tool", [False, True])
async def test_recovery_reasons_and_incomplete_history(tool):
    from agentscope_platform.application.dag import AgentDagApplicationService
    from agentscope_platform.application.dag_recovery import DagRecovery, recovery_scope
    from agentscope_platform.domain.agent import AgentExecution, AgentStep
    from test_dag_optimization import Synthesis, request
    from test_dag_recovery import MemoryCheckpoint

    class Runner:
        crash = True

        async def run(self, goal, owner):
            if "Your sub-task [dependent]" in goal and self.crash:
                raise asyncio.CancelledError()
            return AgentExecution(
                "done",
                "DONE",
                steps=(
                    (AgentStep(n=1, action="rag_search", observation="private data"),)
                    if tool
                    else ()
                ),
            )

    observer, runner, store = Observer(), Runner(), MemoryCheckpoint()
    service = AgentDagApplicationService(
        runner,
        optimized=True,
        synthesizer=Synthesis(),
        diagnostics_enabled=True,
        diagnostic_observer=observer,
    )
    first = await DagRecovery.open(store, "a" * 64, 30)
    with pytest.raises(asyncio.CancelledError):
        async with recovery_scope(first):
            await service.run(request(), context())
    runner.crash = False
    observer.events.clear()
    second = await DagRecovery.open(store, "a" * 64, 30)
    async with recovery_scope(second):
        await service.run(request(), context())
    operations = {e.node_id: e for e in observer.events if e.kind == "operation" and e.node_id}
    assert operations["source"].reason == (
        "checkpoint_not_reusable" if tool else "checkpoint_reused"
    )
    assert operations["dependent"].reason == (
        "checkpoint_input_changed" if tool else "checkpoint_incomplete"
    )
    summary = observer.events[-1]
    assert summary.resumed and not summary.history_complete
    assert summary.estimated_cost_usd is None
    assert summary.critical_paths[0].complete


async def test_queue_timing_critical_path_failure_and_skip():
    from agentscope_platform.application.dag import AgentDagApplicationService
    from agentscope_platform.domain.agent import AgentExecution
    from test_dag_optimization import Synthesis, request

    class Runner:
        async def run(self, goal, owner):
            await asyncio.sleep(0.015)
            return AgentExecution("unavailable", "TIMEOUT")

    observer = Observer()
    service = AgentDagApplicationService(
        Runner(),
        optimized=True,
        synthesizer=Synthesis(),
        max_parallel_workers=1,
        diagnostics_enabled=True,
        diagnostic_observer=observer,
    )
    await service.run(
        request(
            [
                {"id": "a", "description": "a"},
                {"id": "b", "description": "b"},
                {"id": "c", "description": "c", "dependsOn": ["b"]},
            ]
        ),
        context(),
    )
    operations = {e.node_id: e for e in observer.events if e.kind == "operation" and e.node_id}
    assert operations["b"].queue_ms >= 10
    assert operations["a"].execution_ms >= 10
    assert operations["c"].status == "SKIPPED"
    assert operations["c"].reason == "upstream_failed"
    assert operations["c"].execution_ms == 0
    summary = observer.events[-1]
    assert summary.status == "PARTIAL"
    assert summary.critical_paths[0].execution_ms == max(
        operations["a"].execution_ms, operations["b"].execution_ms
    )


async def test_slow_diagnostic_sink_does_not_exhaust_business_deadline():
    from agentscope_platform.application.dag import AgentDagApplicationService
    from agentscope_platform.application.dag_budget import DagRunLimits
    from test_dag_optimization import Synthesis, request
    from test_dag_service import RecordingRunner

    class SlowSink:
        active = 0

        async def emit(self, event, data):
            if event.startswith("dag-diagnostic"):
                self.active += 1
                try:
                    await asyncio.sleep(10)
                finally:
                    self.active -= 1

    sink, observer = SlowSink(), Observer()
    service = AgentDagApplicationService(
        RecordingRunner(),
        optimized=True,
        synthesizer=Synthesis(),
        diagnostics_enabled=True,
        diagnostic_observer=observer,
        limits=DagRunLimits(timeout_seconds=0.1),
    )
    async with asyncio.timeout(2):
        reply = await service.run(request(), context(), sink)
    assert reply.synthesis.stop_reason == "DONE"
    assert sink.active == 0
    assert observer.events[-1].delivery_failures > 0


def test_diagnostic_metrics_have_bounded_labels_and_no_request_data():
    from agentscope_platform.core.config import Settings
    from agentscope_platform.domain.dag_diagnostics import DagModelDiagnostic
    from agentscope_platform.infrastructure.observability.dag_diagnostics import (
        DagDiagnosticsObserver,
    )
    from agentscope_platform.infrastructure.observability.prometheus import (
        configure_metrics,
        render_prometheus_metrics,
    )

    configure_metrics(Settings(_env_file=None))
    observer = DagDiagnosticsObserver()
    observer.record(
        DagModelDiagnostic(
            execution_id="sensitive-run",
            trace_id="sensitive-trace",
            tenant_id="sensitive-tenant",
            operation_id="sensitive-op",
            call_id="sensitive-call",
            node_id="sensitive-node",
            role=DagRole.CRITIC,
            attempt=1,
            model="sensitive-model",
            status="DONE",
            duration_ms=1,
            input_tokens=10,
            output_tokens=2,
            estimated_cost_usd=Decimal("0.1"),
        )
    )
    rendered = render_prometheus_metrics()
    assert 'agent_dag_model_calls_total{role="critic",status="DONE"}' in rendered
    assert "sensitive-" not in rendered


async def test_unconsumed_stream_counts_unknown_instead_of_zero():
    from agentscope.model import ChatResponse

    from agentscope_platform.infrastructure.agentscope.diagnostic_model import observed_model_call

    async def provider():
        async def chunks():
            yield ChatResponse(content=[], is_last=True)

        return chunks()

    observer = Observer()
    async with diagnostic_scope(context(), observer, None):
        async with diagnostic_operation(DagRole.WORKER):
            stream = await observed_model_call(
                provider, model="m", input_rate=None, output_rate=None
            )
            await stream.aclose()
    summary = observer.events[-1]
    assert summary.observed_model_calls == summary.unknown_usage_calls == 1
    assert summary.estimated_cost_usd is None


async def test_recovery_near_deadline_skips_diagnostic_io():
    import time

    observer, sink = Observer(), Sink()
    async with diagnostic_scope(
        context(), observer, sink, resumed=True, deadline=time.time() + 0.025
    ):
        async with diagnostic_operation(DagRole.WORKER):
            pass
    assert not sink.events
    assert observer.events[-1].history_complete is False


async def test_bounded_event_queue_reports_drops_without_failing_work():
    observer, sink = Observer(), Sink()
    async with diagnostic_scope(context(), observer, sink):
        async with diagnostic_operation(DagRole.WORKER) as operation:
            for _ in range(300):
                operation.model_finished("m", "DONE", 0, 1, 1, Decimal(0), Decimal(0))
    assert observer.events[-1].observed_model_calls == 300
    assert observer.events[-1].dropped_records >= 44
    assert observer.events[-1].estimated_cost_usd == 0


async def test_concurrent_dag_model_costs_do_not_cross_tenants(monkeypatch):
    from agentscope.message import TextBlock
    from agentscope.model import ChatResponse, ChatUsage, OpenAIChatModel

    from agentscope_platform.application.dag import AgentDagApplicationService
    from agentscope_platform.core.context import current_run_context
    from agentscope_platform.domain.agent import AgentExecution
    from agentscope_platform.infrastructure.agentscope.text_generator import AgentScopeTextGenerator
    from test_api import settings
    from test_dag_optimization import request

    async def provider(self, **kwargs):
        await asyncio.sleep(0)
        count = 10 if current_run_context().identity.tenant_id == "a" else 20
        return ChatResponse(
            content=[TextBlock(text="result")],
            is_last=True,
            usage=ChatUsage(input_tokens=count, output_tokens=count, time=0),
        )

    monkeypatch.setattr(OpenAIChatModel, "__call__", provider)
    generator = AgentScopeTextGenerator(settings(agent_dag_optimization_enabled=True))

    class Runner:
        async def run(self, goal, owner):
            return AgentExecution(await generator.generate("worker", goal, owner), "DONE")

    observer = Observer()
    dag = AgentDagApplicationService(
        Runner(),
        optimized=True,
        synthesizer=generator,
        diagnostics_enabled=True,
        diagnostic_observer=observer,
    )
    await asyncio.gather(dag.run(request(), context("a")), dag.run(request(), context("b")))
    summaries = {e.tenant_id: e for e in observer.events if e.kind == "summary"}
    assert summaries["a"].known_input_tokens == 30
    assert summaries["b"].known_input_tokens == 60
    for event in observer.events:
        assert event.execution_id == summaries[event.tenant_id].execution_id


async def test_diagnostic_events_survive_existing_sse_projection():
    import json

    from agentscope_platform.api.routes import _project_task_events

    observer, sink = Observer(), Sink()
    async with diagnostic_scope(context(), observer, sink):
        async with diagnostic_operation(DagRole.WORKER) as operation:
            operation.model_finished("m", "DONE", 1, 3, 2, None, None)

    async def chunks():
        for index, (name, data) in enumerate(sink.events):
            payload = dict(taskId="central-task", event=name, data=data, ts="2026-10-14T00:00:00Z")
            yield f"id: {index}\nevent: {name}\ndata: {json.dumps(payload)}\n\n".encode()

    frames = b"".join([chunk async for chunk in _project_task_events(chunks())]).decode()
    for name, _ in sink.events:
        assert f"event: {name}\n" in frames
    assert '"schemaVersion":1' in frames.replace(" ", "")


async def test_v1_reclaimed_task_has_unknown_history_without_checkpoint():
    import time

    from agentscope_platform.application.dag_diagnostics import diagnostic_task_scope

    observer = Observer()
    with diagnostic_task_scope("central-1", 2, time.time() + 30):
        async with diagnostic_scope(context(), observer, None):
            async with diagnostic_operation(DagRole.WORKER) as operation:
                operation.model_finished("m", "DONE", 0, 10, 5, Decimal(1), Decimal(2))
    summary = observer.events[-1]
    assert summary.central_task_id == "central-1" and summary.lease_epoch == 2
    assert summary.resumed and not summary.history_complete
    assert summary.known_estimated_cost_usd == Decimal("0.00002")
    assert summary.estimated_cost_usd is None
    async with diagnostic_scope(context(), observer, None):
        pass
    assert observer.events[-1].central_task_id is None
    assert not observer.events[-1].resumed


def test_diagnostic_flags_do_not_invalidate_queued_task_execution_digest():
    from agentscope_platform.application.async_task import runtime_config_digest
    from test_api import settings

    enabled = settings(agent_dag_diagnostics_enabled=True, agent_dag_cost_rates_configured=True)
    disabled = settings(agent_dag_diagnostics_enabled=False, agent_dag_cost_rates_configured=False)
    assert runtime_config_digest(enabled) == runtime_config_digest(disabled)
    # 真正改变模型行为的配置仍必须失配, 不因排除观测配置而弱化恢复绑定。
    assert runtime_config_digest(enabled) != runtime_config_digest(
        settings(gateway_temperature=0.8)
    )


async def test_task_manager_attaches_authoritative_task_identity_to_diagnostics():
    from agentscope_platform.application.async_task import AsyncTaskManager
    from agentscope_platform.application.dag import AgentDagApplicationService
    from test_async_task_manager import FakeAsyncTaskGateway, settings, wait_terminal
    from test_async_task_manager import context as owner_context
    from test_dag_optimization import Synthesis, request
    from test_dag_service import RecordingRunner

    observer = Observer()
    service = AgentDagApplicationService(
        RecordingRunner(),
        optimized=True,
        synthesizer=Synthesis(),
        diagnostics_enabled=True,
        diagnostic_observer=observer,
    )
    gateway = FakeAsyncTaskGateway()
    manager = AsyncTaskManager(gateway, settings())
    owner = owner_context()
    task = await manager.submit(
        kind="agent.dag",
        input_data={"goal": "investigate"},
        webhook_url=None,
        context=owner,
        execute=lambda sink: service.run(request(), owner, sink),
    )
    await wait_terminal(gateway, task.task_id)
    summary = observer.events[-1]
    assert summary.central_task_id == task.task_id
    assert summary.lease_epoch == gateway.tasks[task.task_id].lease_epoch
    assert summary.history_complete
    await manager.shutdown()
