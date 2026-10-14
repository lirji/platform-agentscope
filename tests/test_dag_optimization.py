"""优化模式以业务行为验证, 不把旧模式的弱失败语义作为新模式验收。"""

import json
from dataclasses import replace

import pytest

from agentscope_platform.application.dag import AgentDagApplicationService, DagValidationError
from agentscope_platform.domain.agent import AgentExecution
from agentscope_platform.domain.dag import AgentDagRunRequest
from agentscope_platform.domain.tool import ToolMetadata, ToolPolicy
from test_dag_service import RecordingRunner, context


class Synthesis:
    def __init__(self):
        self.inputs = []

    async def generate(self, system_prompt, user_prompt, run_context, **kwargs):
        self.inputs.append((system_prompt, user_prompt, run_context))
        return "grounded synthesis"


def request(tasks=None):
    return AgentDagRunRequest.model_validate(
        {
            "goal": "investigate",
            "tasks": tasks
            or [
                {"id": "source", "description": "collect"},
                {"id": "dependent", "description": "analyze", "dependsOn": ["source"]},
            ],
        }
    )


async def test_failed_dependency_skips_descendants_and_prevents_acceptance():
    class FailedRunner(RecordingRunner):
        async def run(self, goal, run_context):
            self.calls.append((goal, run_context))
            return AgentExecution("partial data must not become evidence", "TIMEOUT")

    runner, synthesis = FailedRunner(), Synthesis()
    service = AgentDagApplicationService(runner, optimized=True, synthesizer=synthesis)
    reply = await service.run(request(), context())
    assert len(runner.calls) == 1
    assert [r.result.stop_reason for r in reply.task_results] == ["TIMEOUT", "SKIPPED"]
    assert reply.synthesis.stop_reason == "PARTIAL"
    assert not reply.accepted_by_threshold
    evidence = json.loads(synthesis.inputs[0][1])
    assert evidence["tasks"][0]["stopReason"] == "TIMEOUT"
    assert evidence["tasks"][0]["answer"] == ""


async def test_synthesis_is_tool_free_and_worker_has_server_capabilities():
    runner, synthesis = RecordingRunner(), Synthesis()
    service = AgentDagApplicationService(runner, optimized=True, synthesizer=synthesis)
    reply = await service.run(request(), context())
    assert len(runner.calls) == 2
    assert len(synthesis.inputs) == 1
    assert synthesis.inputs[0][2].allowed_tools == frozenset()
    assert all(c.allowed_tools and "refund_start" not in c.allowed_tools for _, c in runner.calls)
    assert reply.synthesis.final_answer == "grounded synthesis"


async def test_optimized_rejects_unknown_dependency_before_any_call():
    runner = RecordingRunner()
    service = AgentDagApplicationService(runner, optimized=True, synthesizer=Synthesis())
    with pytest.raises(DagValidationError, match="unknown dependency"):
        await service.run(
            request([{"id": "one", "description": "x", "dependsOn": ["absent"]}]), context()
        )
    assert not runner.calls


def test_tool_allowlist_cannot_expand_caller_authority():
    owner = replace(context(), allowed_tools=frozenset({"current_time"}))
    assert not ToolPolicy.evaluate(
        ToolMetadata.for_read_only(name="order_query", required_scopes=()), owner
    ).allowed
    assert ToolPolicy.evaluate(
        ToolMetadata.for_read_only(name="current_time", required_scopes=()), owner
    ).allowed
    assert not ToolPolicy.evaluate(
        ToolMetadata.for_read_only(name="current_time", required_scopes=("admin",)), owner
    ).allowed


async def test_parallel_tenants_keep_separate_evidence_and_capabilities():
    import asyncio

    runner, synthesis = RecordingRunner(delay=0.001), Synthesis()
    service = AgentDagApplicationService(runner, optimized=True, synthesizer=synthesis)
    a, b = await asyncio.gather(
        service.run(request(), replace(context("a"), allowed_tools=frozenset({"current_time"}))),
        service.run(request(), replace(context("b"), allowed_tools=frozenset({"rag_search"}))),
    )
    assert (a.tenant_id, b.tenant_id) == ("a", "b")
    for _, owner in runner.calls:
        expected = "current_time" if owner.identity.tenant_id == "a" else "rag_search"
        assert owner.allowed_tools == frozenset({expected})
        assert owner.internal_token == f"token-{owner.identity.tenant_id}"


def test_optimized_api_preserves_response_shape_and_blocks_invalid_graph():
    from fastapi.testclient import TestClient

    from agentscope_platform.api.app import create_app
    from test_api import FakeRunner, FakeTextGenerator, internal_token, settings

    app = create_app(
        settings(agent_dag_optimization_enabled=True),
        FakeRunner(),
        text_generator=FakeTextGenerator(["summary"]),
    )
    with TestClient(app) as client:
        reply = client.post(
            "/agent/dag/run",
            json=request().model_dump(by_alias=True),
            headers={"X-Internal-Token": internal_token()},
        )
        assert reply.status_code == 200
        assert set(reply.json()) == {
            "goal",
            "levels",
            "taskResults",
            "synthesis",
            "tenantId",
            "attempts",
            "acceptedByThreshold",
        }
        assert reply.json()["synthesis"]["finalAnswer"] == "summary"
        assert (
            client.post("/agent/dag/run", json=request().model_dump(by_alias=True)).status_code
            == 401
        )
        invalid = request([{"id": "one", "description": "x", "dependsOn": ["missing"]}])
        assert (
            client.post(
                "/agent/dag/run",
                json=invalid.model_dump(by_alias=True),
                headers={"X-Internal-Token": internal_token()},
            ).status_code
            == 400
        )


async def test_partial_dag_is_not_recorded_as_async_success():
    from agentscope_platform.application.async_task import AsyncTaskManager
    from agentscope_platform.domain.async_task import AsyncTaskStatus
    from test_async_task_manager import FakeAsyncTaskGateway, settings, wait_terminal
    from test_async_task_manager import context as async_context

    class FailedRunner(RecordingRunner):
        async def run(self, goal, run_context):
            return AgentExecution("unavailable", "ERROR")

    service = AgentDagApplicationService(FailedRunner(), optimized=True, synthesizer=Synthesis())
    gateway = FakeAsyncTaskGateway()
    manager = AsyncTaskManager(gateway, settings())
    owner = async_context()
    task = await manager.submit(
        kind="agent.dag",
        input_data={"goal": "investigate"},
        webhook_url=None,
        context=owner,
        execute=lambda sink: service.run(request(), owner, sink),
    )
    await wait_terminal(gateway, task.task_id)
    assert gateway.tasks[task.task_id].status is AsyncTaskStatus.FAILED
    assert gateway.tasks[task.task_id].result is None
    await manager.shutdown()


async def test_real_tool_adapter_rejects_outside_capability_before_invocation():
    from agentscope.message import ToolResultState

    from agentscope_platform.core.context import run_context
    from agentscope_platform.infrastructure.agentscope.tools import GovernedFunctionTool

    invoked = False

    async def tool():
        nonlocal invoked
        invoked = True
        return "data"

    adapter = GovernedFunctionTool(
        tool, metadata=ToolMetadata.for_read_only(name="order_query", required_scopes=())
    )
    with run_context(replace(context(), allowed_tools=frozenset({"rag_search"}))):
        result = await adapter.call()
    assert result.state is ToolResultState.ERROR
    assert not invoked
