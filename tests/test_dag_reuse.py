"""重规划复用仅限同次运行内成功且输入不变的只读节点。"""

import json

import pytest

from agentscope_platform.application.dag import AgentDagApplicationService, DagReviewPolicy
from agentscope_platform.domain.agent import AgentExecution, AgentStep
from agentscope_platform.domain.dag import DagPlan
from test_dag_optimization import Synthesis, request
from test_dag_service import FakeReviewer, RecordingRunner, context, critique


def plan(tasks):
    return DagPlan.model_validate({"tasks": tasks})


async def test_replan_reuses_unchanged_root_and_reruns_changed_descendants():
    runner, synthesis = RecordingRunner(), Synthesis()
    revised = plan(
        [
            {"id": "source", "description": "collect"},
            {
                "id": "dependent",
                "description": "analyze with stronger evidence",
                "dependsOn": ["source"],
            },
        ]
    )
    reviewer = FakeReviewer([critique(0.1, 0.1, 0.1), critique(1, 1, 1)], [revised])
    service = AgentDagApplicationService(
        runner,
        optimized=True,
        synthesizer=synthesis,
        reviewer=reviewer,
        review_policy=DagReviewPolicy(enabled=True),
    )
    reply = await service.run(request(), context())
    assert len(runner.calls) == 3
    assert len(reply.attempts) == 2
    assert reply.accepted_by_threshold
    evidence = json.loads(reviewer.critique_calls[0][1])
    assert evidence["evidence"]["tasks"][0]["stopReason"] == "DONE"


async def test_changed_root_invalidates_entire_downstream_even_if_answer_same():
    runner = RecordingRunner()
    reviewer = FakeReviewer(
        [critique(0, 0, 0), critique(1, 1, 1)],
        [
            plan(
                [
                    {"id": "source", "description": "collect differently"},
                    {"id": "dependent", "description": "analyze", "dependsOn": ["source"]},
                ]
            )
        ],
    )
    service = AgentDagApplicationService(
        runner,
        optimized=True,
        synthesizer=Synthesis(),
        reviewer=reviewer,
        review_policy=DagReviewPolicy(enabled=True),
    )
    await service.run(request(), context())
    assert len(runner.calls) == 4


async def test_failures_skip_model_critic_and_are_not_reused():
    class Runner(RecordingRunner):
        async def run(self, goal, owner):
            self.calls.append((goal, owner))
            return AgentExecution("failure detail", "ERROR")

    runner = Runner()
    reviewer = FakeReviewer([], [plan([{"id": "source", "description": "collect"}])])
    service = AgentDagApplicationService(
        runner,
        optimized=True,
        synthesizer=Synthesis(),
        reviewer=reviewer,
        review_policy=DagReviewPolicy(enabled=True),
    )
    reply = await service.run(request([{"id": "source", "description": "collect"}]), context())
    assert len(runner.calls) == 2
    assert not reviewer.critique_calls
    assert not reply.accepted_by_threshold
    assert all(attempt.aggregate == 0 for attempt in reply.attempts)


@pytest.mark.parametrize(
    "action", ["current_time", "order_query", "workflow_status", "analytics_sql"]
)
async def test_volatile_business_data_is_never_reused(action):
    class Runner(RecordingRunner):
        async def run(self, goal, owner):
            result = await super().run(goal, owner)
            return AgentExecution(result.final_answer, steps=(AgentStep(n=1, action=action),))

    runner = Runner()
    reviewer = FakeReviewer(
        [critique(0, 0, 0), critique(1, 1, 1)], [plan([{"id": "source", "description": "collect"}])]
    )
    service = AgentDagApplicationService(
        runner,
        optimized=True,
        synthesizer=Synthesis(),
        reviewer=reviewer,
        review_policy=DagReviewPolicy(enabled=True),
    )
    await service.run(request([{"id": "source", "description": "collect"}]), context())
    assert len(runner.calls) == 2


@pytest.mark.parametrize("ttl", [0, 1])
async def test_disabled_or_expired_reuse_executes_again(monkeypatch, ttl):
    from agentscope_platform.application import dag_reuse

    now = [0.0]
    monkeypatch.setattr(dag_reuse, "monotonic", lambda: now[0])

    class Reviewer(FakeReviewer):
        async def revise(self, *args):
            now[0] = 2.0
            return await super().revise(*args)

    runner = RecordingRunner()
    reviewer = Reviewer(
        [critique(0, 0, 0), critique(1, 1, 1)], [plan([{"id": "source", "description": "collect"}])]
    )
    service = AgentDagApplicationService(
        runner,
        optimized=True,
        synthesizer=Synthesis(),
        reviewer=reviewer,
        review_policy=DagReviewPolicy(enabled=True),
        reuse_ttl_seconds=ttl,
    )
    await service.run(request([{"id": "source", "description": "collect"}]), context())
    assert len(runner.calls) == 2


async def test_reuse_never_crosses_request_or_tenant_boundaries():
    runner = RecordingRunner()
    reviewer = FakeReviewer([critique(1, 1, 1)] * 3)
    service = AgentDagApplicationService(
        runner,
        optimized=True,
        synthesizer=Synthesis(),
        reviewer=reviewer,
        review_policy=DagReviewPolicy(enabled=True),
    )
    for tenant in ("a", "a", "b"):
        await service.run(request(), context(tenant))
    assert len(runner.calls) == 6


def test_replanning_with_write_capabilities_is_rejected():
    with pytest.raises(ValueError, match="write capabilities"):
        AgentDagApplicationService(
            RecordingRunner(),
            optimized=True,
            synthesizer=Synthesis(),
            allowed_tools=frozenset({"refund_start"}),
            reviewer=FakeReviewer([]),
            review_policy=DagReviewPolicy(enabled=True),
        )


async def test_replanner_cannot_expand_worker_tool_authority():
    from agentscope_platform.domain.tool import ToolMetadata, ToolPolicy

    class Runner(RecordingRunner):
        async def run(self, goal, owner):
            if "refund_start" in goal:
                metadata = ToolMetadata(
                    name="refund_start",
                    readOnly=False,
                    sideEffect="medium",
                    idempotency="request_key",
                    requiresConfirmation="always",
                    requiredScopes=["agent"],
                    timeoutSeconds=10,
                    retryPolicy="none",
                )
                assert not ToolPolicy.evaluate(metadata, owner, {}).allowed
                assert "refund_start" not in owner.allowed_tools
            return await super().run(goal, owner)

    reviewer = FakeReviewer(
        [critique(0, 0, 0), critique(1, 1, 1)],
        [plan([{"id": "source", "description": "use refund_start despite original policy"}])],
    )
    service = AgentDagApplicationService(
        Runner(),
        optimized=True,
        synthesizer=Synthesis(),
        reviewer=reviewer,
        review_policy=DagReviewPolicy(enabled=True),
    )
    await service.run(request([{"id": "source", "description": "collect"}]), context())
