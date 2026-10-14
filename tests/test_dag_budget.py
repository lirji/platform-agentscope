"""整次 DAG 预算必须覆盖规划与并发真实模型调用。"""

import asyncio

import pytest

from agentscope_platform.application.dag import AgentDagApplicationService
from agentscope_platform.application.planning import AgentDagPlanningService
from test_dag_optimization import Synthesis, request
from test_dag_service import RecordingRunner, context


async def test_total_deadline_includes_planner_and_does_not_fallback():
    from agentscope_platform.application.dag_budget import DagDeadlineExceeded, DagRunLimits
    from agentscope_platform.domain.dag import AgentPlanRunRequest

    class Planner:
        async def plan(self, *args):
            await asyncio.Event().wait()

    runner = RecordingRunner()
    service = AgentDagApplicationService(
        runner, optimized=True, synthesizer=Synthesis(), limits=DagRunLimits(timeout_seconds=0.02)
    )
    planning = AgentDagPlanningService(Planner(), service)
    with pytest.raises(DagDeadlineExceeded):
        await planning.plan_and_run(AgentPlanRunRequest(goal="slow plan"), context())
    assert not runner.calls


async def test_model_call_budget_denies_before_provider_and_is_shared():
    from agentscope.message import UserMsg
    from agentscope.model import ChatResponse

    from agentscope_platform.application.dag_budget import DagBudgetExceeded, DagRunLimits
    from agentscope_platform.infrastructure.agentscope.dag_budget_model import dag_budgeted_call

    calls = 0

    async def provider(*args, **kwargs):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return ChatResponse(content=[], is_last=True)

    service = AgentDagApplicationService(
        RecordingRunner(),
        optimized=True,
        synthesizer=Synthesis(),
        limits=DagRunLimits(max_model_calls=1),
    )
    with pytest.raises(DagBudgetExceeded):
        async with service.execution_scope(context()):
            result = await asyncio.gather(
                *[
                    dag_budgeted_call(
                        provider, [UserMsg(name="u", content="hello")], output_limit=10
                    )
                    for _ in range(2)
                ],
                return_exceptions=True,
            )
            assert sum(isinstance(item, DagBudgetExceeded) for item in result) == 1
    assert calls == 1


async def test_budget_is_per_request_and_retains_unknown_usage():
    from agentscope.message import UserMsg
    from agentscope.model import ChatResponse

    from agentscope_platform.application.dag_budget import DagBudgetExceeded, DagRunLimits
    from agentscope_platform.infrastructure.agentscope.dag_budget_model import dag_budgeted_call

    async def provider(*args, **kwargs):
        return ChatResponse(content=[], is_last=True)

    service = AgentDagApplicationService(
        RecordingRunner(),
        optimized=True,
        synthesizer=Synthesis(),
        limits=DagRunLimits(max_model_calls=1),
    )
    for tenant in ("a", "b"):
        async with service.execution_scope(context(tenant)):
            await dag_budgeted_call(provider, [UserMsg(name="u", content="hello")], output_limit=10)
    with pytest.raises(DagBudgetExceeded):
        async with service.execution_scope(context()):
            await dag_budgeted_call(provider, [UserMsg(name="u", content="hello")], output_limit=10)
            await dag_budgeted_call(provider, [UserMsg(name="u", content="hello")], output_limit=10)


async def test_deadline_cancels_workers_without_synthesis():
    from agentscope_platform.application.dag_budget import DagDeadlineExceeded, DagRunLimits

    stopped = asyncio.Event()

    class Runner(RecordingRunner):
        async def run(self, *args):
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

    synthesis = Synthesis()
    service = AgentDagApplicationService(
        Runner(), optimized=True, synthesizer=synthesis, limits=DagRunLimits(timeout_seconds=0.02)
    )
    with pytest.raises(DagDeadlineExceeded):
        await service.run(request(), context())
    assert stopped.is_set()
    assert not synthesis.inputs


async def test_real_model_adapters_share_dag_budget(monkeypatch):
    from agentscope.message import TextBlock
    from agentscope.model import ChatResponse, OpenAIChatModel

    from agentscope_platform.application.dag_budget import DagBudgetExceeded, DagRunLimits
    from agentscope_platform.domain.dag import DagPlanKind
    from agentscope_platform.infrastructure.agentscope.planner import AgentScopeDagPlanner
    from agentscope_platform.infrastructure.agentscope.reviewer import AgentScopeDagQualityReviewer
    from agentscope_platform.infrastructure.agentscope.text_generator import AgentScopeTextGenerator
    from test_api import settings

    calls = []

    async def provider(self, messages, **kwargs):
        calls.append(messages)
        answer = (
            '{"tasks":[{"id":"one","description":"lookup","dependsOn":[]}]}'
            if len(calls) == 1
            else "answer"
        )
        return ChatResponse(content=[TextBlock(text=answer)], is_last=True)

    monkeypatch.setattr(OpenAIChatModel, "__call__", provider)
    config = settings(agent_dag_optimization_enabled=True)
    service = AgentDagApplicationService(
        RecordingRunner(),
        optimized=True,
        synthesizer=Synthesis(),
        limits=DagRunLimits(max_model_calls=2),
    )
    with pytest.raises(DagBudgetExceeded):
        async with service.execution_scope(context()):
            await AgentScopeDagPlanner(config).plan("test", context(), DagPlanKind.GENERAL)
            await AgentScopeTextGenerator(config).generate("system", "input", context())
            await AgentScopeDagQualityReviewer(config).critique("test", "answer", context())
    assert len(calls) == 2


async def test_token_admission_rejects_before_provider():
    from agentscope.message import UserMsg

    from agentscope_platform.application.dag_budget import DagBudgetExceeded, DagRunLimits
    from agentscope_platform.infrastructure.agentscope.dag_budget_model import dag_budgeted_call

    async def provider(*args, **kwargs):
        raise AssertionError("budget must reject before provider")

    service = AgentDagApplicationService(
        RecordingRunner(),
        optimized=True,
        synthesizer=Synthesis(),
        limits=DagRunLimits(max_reserved_tokens=1),
    )
    with pytest.raises(DagBudgetExceeded):
        async with service.execution_scope(context()):
            await dag_budgeted_call(provider, [UserMsg(name="u", content="hello")], output_limit=10)


def test_api_maps_budget_to_stable_error_without_provider_detail():
    from fastapi.testclient import TestClient

    from agentscope_platform.api.app import create_app
    from agentscope_platform.application.dag_budget import DagBudgetExceeded
    from test_api import internal_token, settings

    class Runner(RecordingRunner):
        async def run(self, *args):
            raise DagBudgetExceeded("private provider detail")

    with TestClient(
        create_app(
            settings(agent_dag_optimization_enabled=True), Runner(), text_generator=Synthesis()
        )
    ) as client:
        response = client.post(
            "/agent/dag/run",
            json=request().model_dump(by_alias=True),
            headers={"X-Internal-Token": internal_token()},
        )
    assert response.status_code == 429
    assert response.json()["error"] == "AGENT_DAG_BUDGET_EXCEEDED"
    assert "private" not in response.text


def test_optimized_configuration_rejects_hidden_provider_retries():
    from pydantic import ValidationError

    from test_api import settings

    with pytest.raises(ValidationError, match="fail-once"):
        settings(agent_dag_optimization_enabled=True, agent_model_max_retries=1)
